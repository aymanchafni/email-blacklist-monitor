import pandas as pd
import pytest

from blacklist_monitor.matching import Blacklist, normalize


@pytest.fixture
def blacklist():
    return Blacklist(pd.DataFrame([
        {"first_name": "Jane", "last_name": "Example", "cin": "ZZ000001", "imm": "99999-A-01"},
        {"first_name": "Léa", "last_name": "Démo", "cin": None, "imm": None},     # missing IDs
    ]))


def fields(matches):
    return sorted(m.field for m in matches)


def test_normalize():
    assert normalize("  Léa   DÉMO,\n99999-a-01 ") == "LEA DEMO 99999 A 01"


def test_cin_is_case_insensitive(blacklist):
    assert fields(blacklist.find_matches("Pièce d'identité: zz000001")) == ["cin"]


def test_plate_matches_whatever_the_separators(blacklist):
    for text in ["plate 99999-A-01", "plate 99999 A 01", "PLATE 99999A01", "99999/a/01"]:
        assert fields(blacklist.find_matches(text)) == ["imm"], text


def test_ids_only_match_on_token_boundaries(blacklist):
    assert blacklist.find_matches("ref ZZ0000012 and 199999-A-01") == []


def test_names_across_spreadsheet_columns_and_accents(blacklist):
    # cells separated by " | " / padded with spaces, accents dropped by OCR
    assert fields(blacklist.find_matches("Jane    |   Example | 12")) == ["full_name"]
    assert fields(blacklist.find_matches("DEMO LEA")) == ["full_name"]


def test_missing_values_never_match_the_string_nan(blacklist):
    # Old behaviour: an empty CIN became 'nan', which matched words like "financement".
    assert blacklist.find_matches("Contrat de financement - NaN - nan") == []


def test_one_match_per_entry_and_field(blacklist):
    matches = blacklist.find_matches("Jane Example ... Example Jane ... ZZ000001 ZZ000001")
    assert fields(matches) == ["cin", "full_name"]


def test_csv_header_aliases(tmp_path):
    path = tmp_path / "bl.csv"
    path.write_text("first name,last name,cin,vehicule make,imm,color\nJane,Example,ZZ000001,Toyota,1,Blue\n")
    assert len(Blacklist.from_csv(path)) == 1
    bad = tmp_path / "bad.csv"
    bad.write_text("name,id\nx,y\n")
    with pytest.raises(ValueError, match="missing columns"):
        Blacklist.from_csv(bad)
