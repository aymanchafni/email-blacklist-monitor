from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import load_dotenv


@dataclass(frozen=True)
class Settings:
    client_id: str
    authority: str
    scopes: list[str]
    alert_email: str
    blacklist_file: str = "blacklist.csv"
    check_interval: int = 60
    tesseract_path: str | None = None
    state_file: str = "monitor_state.json"
    token_cache_file: str = "token_cache.json"

    @classmethod
    def from_env(cls) -> "Settings":
        load_dotenv()
        missing = [k for k in ("CLIENT_ID", "ALERT_EMAIL") if not os.getenv(k)]
        if missing:
            raise SystemExit(f"Missing required settings in .env: {', '.join(missing)} (see .env.example)")
        tenant = os.getenv("TENANT_ID", "common")
        return cls(
            client_id=os.environ["CLIENT_ID"],
            authority=os.getenv("AUTHORITY") or f"https://login.microsoftonline.com/{tenant}",
            scopes=os.getenv("SCOPE", "Mail.Read Mail.Send").split(),
            alert_email=os.environ["ALERT_EMAIL"],
            blacklist_file=os.getenv("BLACKLIST_FILE", "blacklist.csv"),
            check_interval=int(os.getenv("CHECK_INTERVAL", "60")),
            tesseract_path=os.getenv("TESSERACT_PATH") or None,
        )
