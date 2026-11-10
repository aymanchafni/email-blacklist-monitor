"""Polling loop: new inbox messages -> attachments -> text -> blacklist matches -> alert."""

from __future__ import annotations

import logging
import time
from collections import Counter
from datetime import timedelta

from .extraction import extract_text, is_supported
from .matching import Blacklist, Match
from .state import StateStore, utcnow

logger = logging.getLogger(__name__)

# Re-read a small window before the last check: Graph indexing can lag a few seconds,
# and already-processed ids are skipped anyway, so the overlap never causes duplicates.
OVERLAP = timedelta(minutes=5)
MAX_ATTEMPTS = 3


class Monitor:
    def __init__(self, graph, blacklist: Blacklist, state: StateStore, alert_email: str,
                 tesseract_cmd: str | None = None):
        self.graph = graph
        self.blacklist = blacklist
        self.state = state
        self.alert_email = alert_email
        self.tesseract_cmd = tesseract_cmd
        self.failures: Counter[str] = Counter()

    def scan_message(self, message: dict) -> list[tuple[str, list[Match]]]:
        """Returns [(attachment name, matches)] for attachments with at least one match."""
        hits = []
        if not message.get("hasAttachments"):
            return hits
        for name, content in self.graph.file_attachments(message["id"]):
            if not is_supported(name):
                logger.info("Skipping unsupported attachment %s", name)
                continue
            matches = self.blacklist.find_matches(extract_text(content, name, self.tesseract_cmd))
            if matches:
                hits.append((name, matches))
        return hits

    def alert(self, message: dict, hits: list[tuple[str, list[Match]]]) -> None:
        lines = [
            "SECURITY ALERT: blacklist match found in an incoming email",
            f"Subject:  {message.get('subject') or '(no subject)'}",
            f"From:     {message.get('from', {}).get('emailAddress', {}).get('address', 'unknown')}",
            f"Received: {message.get('receivedDateTime')}",
            "",
        ]
        for name, matches in hits:
            lines.append(f"Attachment: {name}")
            for m in matches:
                e = m.entry
                lines.append(f"  - matched {m.field} '{m.value}': {e.get('first_name', '')} {e.get('last_name', '')}"
                             f" | CIN {e.get('cin', '')} | plate {e.get('imm', '')}"
                             f" | {e.get('vehicle_make', '')} {e.get('color', '')}".rstrip())
        n = sum(len(m) for _, m in hits)
        self.graph.send_mail(self.alert_email, f"SECURITY ALERT: {n} blacklist match(es) detected", "\n".join(lines))
        logger.warning("Alert sent for '%s' (%s matches)", message.get("subject"), n)

    def poll_once(self) -> int:
        """Process every new message once. Returns the number of messages processed."""
        started = utcnow()
        processed = 0
        for message in self.graph.messages_since(self.state.last_check - OVERLAP):
            mid = message["id"]
            if self.state.is_processed(mid):
                continue
            try:
                hits = self.scan_message(message)
                if hits:
                    self.alert(message, hits)
            except Exception:
                self.failures[mid] += 1
                logger.exception("Failed to process '%s' (attempt %s/%s)",
                                 message.get("subject"), self.failures[mid], MAX_ATTEMPTS)
                if self.failures[mid] < MAX_ATTEMPTS:
                    continue   # not marked as processed: retried at the next poll
            self.state.mark_processed(mid)
            processed += 1
        # Only advance the cursor to when this poll *started*, so mail arriving during
        # processing is picked up next time.
        self.state.last_check = started
        self.state.save()
        return processed

    def run_forever(self, interval: int) -> None:
        logger.info("Monitoring inbox every %ss (%s blacklist entries)", interval, len(self.blacklist))
        while True:
            try:
                n = self.poll_once()
                logger.info("Poll done: %s new message(s)", n)
            except Exception:
                logger.exception("Poll failed, retrying in %ss", interval)
            time.sleep(interval)
