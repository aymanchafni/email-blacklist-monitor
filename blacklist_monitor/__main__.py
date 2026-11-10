"""python -m blacklist_monitor [--once] [--scan FILE ...]"""

import argparse
import logging
import sys

from .config import Settings


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="blacklist_monitor", description=__doc__)
    parser.add_argument("--once", action="store_true", help="poll the inbox once and exit")
    parser.add_argument("--scan", nargs="+", metavar="FILE",
                        help="offline mode: scan local files against the blacklist (no email access)")
    parser.add_argument("--blacklist", help="blacklist CSV (default: BLACKLIST_FILE or blacklist.csv)")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s - %(message)s",
                        handlers=[logging.StreamHandler(), logging.FileHandler("email_monitor.log")])

    from .matching import Blacklist

    if args.scan:
        import os

        from .extraction import extract_text
        blacklist = Blacklist.from_csv(args.blacklist or os.getenv("BLACKLIST_FILE", "blacklist.csv"))
        found = False
        for path in args.scan:
            with open(path, "rb") as f:
                matches = blacklist.find_matches(extract_text(f.read(), path, os.getenv("TESSERACT_PATH")))
            for m in matches:
                found = True
                print(f"{path}: {m.field} match '{m.value}' -> {m.entry.get('first_name')} {m.entry.get('last_name')}")
            if not matches:
                print(f"{path}: no match")
        return 1 if found else 0

    from .graph import GraphClient, MsalTokenProvider
    from .monitor import Monitor
    from .state import StateStore

    settings = Settings.from_env()
    tokens = MsalTokenProvider(settings.client_id, settings.authority, settings.scopes, settings.token_cache_file)
    monitor = Monitor(
        graph=GraphClient(tokens),
        blacklist=Blacklist.from_csv(args.blacklist or settings.blacklist_file),
        state=StateStore(settings.state_file),
        alert_email=settings.alert_email,
        tesseract_cmd=settings.tesseract_path,
    )
    if args.once:
        monitor.poll_once()
    else:
        try:
            monitor.run_forever(settings.check_interval)
        except KeyboardInterrupt:
            logging.info("Stopped")
    return 0


if __name__ == "__main__":
    sys.exit(main())
