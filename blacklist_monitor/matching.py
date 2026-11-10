"""Blacklist matching on free text extracted from attachments.

Text from PDFs, spreadsheets and OCR is messy: mixed case, accents, irregular spacing,
separators inside plate numbers ("12345-A-72"), and columns padded with spaces. Everything
is normalised first, then matched on token boundaries so that "AB12345" does not match
inside "AB123456".
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

# canonical column -> accepted spellings in the CSV header (case/spacing-insensitive)
COLUMN_ALIASES = {
    "first_name": {"first_name", "firstname", "first name", "prenom", "prénom"},
    "last_name": {"last_name", "lastname", "last name", "nom"},
    "cin": {"cin", "id", "national_id"},
    "vehicle_make": {"vehicle_make", "vehicule make", "vehicle make", "vehicule_make", "make"},
    "imm": {"imm", "plate", "registration", "immatriculation"},
    "color": {"color", "colour", "couleur"},
}
REQUIRED = ["first_name", "last_name", "cin", "imm"]


def normalize(text: str) -> str:
    """Uppercase, strip accents, turn every non-alphanumeric run into a single space."""
    text = unicodedata.normalize("NFKD", text)
    text = "".join(c for c in text if not unicodedata.combining(c))
    return re.sub(r"[^A-Z0-9]+", " ", text.upper()).strip()


def _clean(value) -> str:
    """Missing cells become '' (never the string 'nan')."""
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return ""
    return normalize(str(value))


def _id_pattern(identifier: str) -> re.Pattern:
    """Match an ID whatever the separators between its characters ('12345A72' ~ '12345-A-72')."""
    chars = identifier.replace(" ", "")
    return re.compile(r"(?<![A-Z0-9])" + r" ?".join(map(re.escape, chars)) + r"(?![A-Z0-9])")


def _phrase_pattern(*words: str) -> re.Pattern:
    return re.compile(r"(?<![A-Z0-9])" + r" ".join(map(re.escape, words)) + r"(?![A-Z0-9])")


@dataclass(frozen=True)
class Match:
    entry: dict          # the blacklist row (original values)
    field: str           # "cin", "imm" or "full_name"
    value: str           # what matched, normalised


class Blacklist:
    def __init__(self, entries: pd.DataFrame):
        self.entries = entries.reset_index(drop=True)
        self._patterns: list[tuple[int, str, str, re.Pattern]] = []
        for i, row in self.entries.iterrows():
            for field in ("cin", "imm"):
                value = _clean(row[field])
                if len(value.replace(" ", "")) >= 3:   # ignore empty / absurdly short IDs
                    self._patterns.append((i, field, value, _id_pattern(value)))
            first, last = _clean(row["first_name"]), _clean(row["last_name"])
            if first and last:
                self._patterns.append((i, "full_name", f"{first} {last}", _phrase_pattern(first, last)))
                self._patterns.append((i, "full_name", f"{last} {first}", _phrase_pattern(last, first)))

    @classmethod
    def from_csv(cls, path: str | Path) -> "Blacklist":
        df = pd.read_csv(path, dtype=str)
        rename = {}
        for col in df.columns:
            key = col.strip().lower()
            for canonical, aliases in COLUMN_ALIASES.items():
                if key in aliases:
                    rename[col] = canonical
        df = df.rename(columns=rename)
        missing = [c for c in REQUIRED if c not in df.columns]
        if missing:
            raise ValueError(f"Blacklist {path} is missing columns {missing}; found {list(df.columns)}")
        return cls(df)

    def __len__(self) -> int:
        return len(self.entries)

    def find_matches(self, text: str) -> list[Match]:
        haystack = normalize(text)
        seen, matches = set(), []
        for i, field, value, pattern in self._patterns:
            if (i, field) not in seen and pattern.search(haystack):
                seen.add((i, field))
                entry = {k: ("" if pd.isna(v) else v) for k, v in self.entries.loc[i].items()}
                matches.append(Match(entry, field, value))
        return matches
