import base64
from datetime import timedelta

import pandas as pd

from blacklist_monitor.graph import GraphClient
from blacklist_monitor.matching import Blacklist
from blacklist_monitor.monitor import MAX_ATTEMPTS, Monitor
from blacklist_monitor.state import StateStore, utcnow

BL = Blacklist(pd.DataFrame([{"first_name": "Jane", "last_name": "Example", "cin": "ZZ000001", "imm": "1"}]))


class FakeGraph:
    def __init__(self, messages, attachments):
        self.messages, self.attachments, self.sent, self.since = messages, attachments, [], None

    def messages_since(self, since):
        self.since = since
        return iter(self.messages)

    def file_attachments(self, message_id):
        att = self.attachments[message_id]
        if isinstance(att, Exception):
            raise att
        return iter(att)

    def send_mail(self, to, subject, body):
        self.sent.append((to, subject, body))


def msg(mid, attachments=True):
    return {"id": mid, "subject": f"subject {mid}", "hasAttachments": attachments,
            "receivedDateTime": "2026-01-01T10:00:00Z", "from": {"emailAddress": {"address": "x@y.z"}}}


def make(tmp_path, messages, attachments):
    graph = FakeGraph(messages, attachments)
    return graph, Monitor(graph, BL, StateStore(str(tmp_path / "state.json")), "alerts@example.com")


def test_alert_sent_once_and_state_persisted(tmp_path):
    graph, monitor = make(tmp_path, [msg("a"), msg("b"), msg("c", attachments=False)], {
        "a": [("list.csv", b"name,cin\nJane Example,ZZ000001\n")],
        "b": [("clean.csv", b"name\nNobody\n")],
    })
    assert monitor.poll_once() == 3
    assert len(graph.sent) == 1 and "ZZ000001" in graph.sent[0][2]

    # restart: state is reloaded, nothing is processed or alerted twice
    graph2 = FakeGraph(graph.messages, graph.attachments)
    monitor2 = Monitor(graph2, BL, StateStore(str(tmp_path / "state.json")), "alerts@example.com")
    assert monitor2.poll_once() == 0 and graph2.sent == []


def test_cursor_only_advances_to_poll_start(tmp_path):
    graph, monitor = make(tmp_path, [], {})
    before = utcnow()
    monitor.poll_once()
    assert before <= monitor.state.last_check <= utcnow()
    monitor.poll_once()
    assert graph.since < monitor.state.last_check - timedelta(minutes=4)   # overlap window


def test_failed_message_is_retried_then_given_up(tmp_path):
    graph, monitor = make(tmp_path, [msg("a")], {"a": RuntimeError("Graph 503")})
    for attempt in range(1, MAX_ATTEMPTS):
        monitor.poll_once()
        assert not monitor.state.is_processed("a"), attempt
    monitor.poll_once()
    assert monitor.state.is_processed("a")


class FakeResponse:
    def __init__(self, status, payload=None):
        self.status_code, self.payload = status, payload or {}

    def json(self):
        return self.payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(self.status_code)


class FakeSession:
    def __init__(self, responses):
        self.responses, self.calls = list(responses), []

    def request(self, method, url, headers, timeout, **kw):
        self.calls.append((url, headers["Authorization"]))
        return self.responses.pop(0)


class FakeTokens:
    def __init__(self):
        self.n = 0

    def token(self, force_refresh=False):
        self.n += 1
        return f"token-{self.n}"


def test_graph_follows_pagination_and_refreshes_expired_token():
    session = FakeSession([
        FakeResponse(401),                                                          # expired token
        FakeResponse(200, {"value": [{"id": "1"}], "@odata.nextLink": "https://next"}),
        FakeResponse(200, {"value": [{"id": "2"}]}),
    ])
    client = GraphClient(FakeTokens(), session=session)
    assert [m["id"] for m in client.messages_since(utcnow())] == ["1", "2"]
    assert session.calls[1][1] == "Bearer token-2"          # retried with a fresh token
    assert session.calls[2][0] == "https://next"


def test_graph_decodes_file_attachments_and_skips_others():
    content = base64.b64encode(b"hello").decode()
    session = FakeSession([FakeResponse(200, {"value": [
        {"@odata.type": "#microsoft.graph.fileAttachment", "id": "a1", "name": "x.csv", "contentBytes": content},
        {"@odata.type": "#microsoft.graph.itemAttachment", "id": "a2", "name": "fwd"},
    ]})])
    assert list(GraphClient(FakeTokens(), session=session).file_attachments("m")) == [("x.csv", b"hello")]
