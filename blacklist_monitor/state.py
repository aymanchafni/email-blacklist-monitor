"""Persistent state: which messages were processed, and up to when the inbox was checked.

Persisting the check time means mail received while the monitor was stopped is still
scanned at the next start (previously the cursor restarted at "now").
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class StateStore:
    def __init__(self, path: str, retention_days: int = 30, initial_lookback_hours: int = 24):
        self.path = path
        self.retention = timedelta(days=retention_days)
        self.processed: dict[str, str] = {}   # message id -> processed-at (ISO, UTC)
        self.last_check = utcnow() - timedelta(hours=initial_lookback_hours)
        if os.path.exists(path):
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            self.processed = data.get("processed", {})
            if data.get("last_check"):
                self.last_check = datetime.fromisoformat(data["last_check"])

    def is_processed(self, message_id: str) -> bool:
        return message_id in self.processed

    def mark_processed(self, message_id: str) -> None:
        self.processed[message_id] = utcnow().isoformat()

    def prune(self) -> None:
        cutoff = utcnow() - self.retention
        self.processed = {k: v for k, v in self.processed.items() if datetime.fromisoformat(v) >= cutoff}

    def save(self) -> None:
        self.prune()
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump({"last_check": self.last_check.isoformat(), "processed": self.processed}, f)
        os.replace(tmp, self.path)   # atomic: a crash never leaves a truncated state file
