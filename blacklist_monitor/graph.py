"""Microsoft Graph access: authentication (MSAL device flow, persistent cache) and the
few mail endpoints the monitor needs."""

from __future__ import annotations

import base64
import logging
import os
from datetime import datetime, timezone
from typing import Iterator

import requests

logger = logging.getLogger(__name__)

GRAPH = "https://graph.microsoft.com/v1.0"


class MsalTokenProvider:
    """Returns a valid access token on every call.

    MSAL's `acquire_token_silent` serves the cached token and transparently refreshes it
    when it is about to expire. (The previous version fetched a token once and reused it
    forever: after ~1 hour every Graph call failed with 401.)
    """

    def __init__(self, client_id: str, authority: str, scopes: list[str], cache_file: str = "token_cache.json"):
        import msal

        self.scopes = scopes
        self.cache_file = cache_file
        self.cache = msal.SerializableTokenCache()
        if os.path.exists(cache_file):
            with open(cache_file, encoding="utf-8") as f:
                self.cache.deserialize(f.read())
        self.app = msal.PublicClientApplication(client_id, authority=authority, token_cache=self.cache)

    def _persist(self) -> None:
        if self.cache.has_state_changed:
            with open(self.cache_file, "w", encoding="utf-8") as f:
                f.write(self.cache.serialize())

    def token(self, force_refresh: bool = False) -> str:
        accounts = self.app.get_accounts()
        result = None
        if accounts:
            result = self.app.acquire_token_silent(self.scopes, account=accounts[0], force_refresh=force_refresh)
        if not result or "access_token" not in result:
            flow = self.app.initiate_device_flow(scopes=self.scopes)
            if "user_code" not in flow:
                raise RuntimeError(f"Could not start device flow: {flow}")
            print(f"\n{'=' * 60}\nAUTHENTICATION REQUIRED\n{flow['message']}\n{'=' * 60}\n", flush=True)
            result = self.app.acquire_token_by_device_flow(flow)
        if "access_token" not in result:
            raise RuntimeError(f"Authentication failed: {result.get('error_description', result)}")
        self._persist()
        return result["access_token"]


class GraphClient:
    def __init__(self, tokens, session: requests.Session | None = None, timeout: int = 30):
        self.tokens = tokens
        self.session = session or requests.Session()
        self.timeout = timeout

    def _request(self, method: str, url: str, **kwargs) -> requests.Response:
        for attempt in (1, 2):
            headers = {"Authorization": f"Bearer {self.tokens.token(force_refresh=attempt == 2)}"}
            resp = self.session.request(method, url, headers=headers, timeout=self.timeout, **kwargs)
            if resp.status_code != 401:
                break
            logger.warning("Graph returned 401, refreshing the token and retrying once")
        resp.raise_for_status()
        return resp

    def messages_since(self, since: datetime) -> Iterator[dict]:
        """Inbox messages received at or after `since` (UTC), oldest first, all pages."""
        since_utc = since.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        url = f"{GRAPH}/me/mailFolders/inbox/messages"
        params = {
            "$filter": f"receivedDateTime ge {since_utc}",
            "$orderby": "receivedDateTime asc",
            "$select": "id,subject,receivedDateTime,hasAttachments,from",
            "$top": "50",
        }
        while url:
            data = self._request("GET", url, params=params).json()
            yield from data.get("value", [])
            url, params = data.get("@odata.nextLink"), None   # nextLink already carries the query

    def file_attachments(self, message_id: str) -> Iterator[tuple[str, bytes]]:
        """(filename, content) for each file attachment of a message."""
        data = self._request("GET", f"{GRAPH}/me/messages/{message_id}/attachments").json()
        for att in data.get("value", []):
            if att.get("@odata.type") != "#microsoft.graph.fileAttachment":
                continue   # item/reference attachments (forwarded mails, OneDrive links)
            content = att.get("contentBytes")
            if content is None:
                content = self._request(
                    "GET", f"{GRAPH}/me/messages/{message_id}/attachments/{att['id']}"
                ).json()["contentBytes"]
            yield att["name"], base64.b64decode(content)

    def send_mail(self, to: str, subject: str, body: str) -> None:
        message = {
            "message": {
                "subject": subject,
                "body": {"contentType": "Text", "content": body},
                "toRecipients": [{"emailAddress": {"address": to}}],
            }
        }
        self._request("POST", f"{GRAPH}/me/sendMail", json=message)
