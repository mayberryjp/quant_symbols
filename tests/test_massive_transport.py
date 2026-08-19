from __future__ import annotations

import requests
import pytest

from quant_symbols.vendors.massive.errors import MassiveTimeoutError, MassiveTransportError
from quant_symbols.vendors.massive.transport import RequestsSessionTransport


class FakeResponse:
    status_code = 200
    headers = {"Content-Type": "application/json"}
    content = b'{"status":"OK"}'


class FakeSession:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def request(self, method: str, url: str, *, headers: dict[str, str], timeout: float) -> FakeResponse:
        self.calls.append({"method": method, "url": url, "headers": headers, "timeout": timeout})
        return FakeResponse()


def test_requests_session_transport_reuses_injected_session() -> None:
    session = FakeSession()
    transport = RequestsSessionTransport(session=session)

    first = transport.request("GET", "https://api.polygon.io/a", headers={"Accept": "application/json"}, timeout=1.0)
    second = transport.request("GET", "https://api.polygon.io/b", headers={"Accept": "application/json"}, timeout=2.0)

    assert first.status_code == 200
    assert second.body == b'{"status":"OK"}'
    assert [call["url"] for call in session.calls] == ["https://api.polygon.io/a", "https://api.polygon.io/b"]
    assert session.calls[1]["timeout"] == 2.0


def test_requests_session_transport_maps_timeout() -> None:
    class TimeoutSession:
        def request(self, method: str, url: str, *, headers: dict[str, str], timeout: float) -> FakeResponse:
            raise requests.Timeout("too slow")

    transport = RequestsSessionTransport(session=TimeoutSession())

    with pytest.raises(MassiveTimeoutError):
        transport.request("GET", "https://api.polygon.io/a", headers={}, timeout=1.0)


def test_requests_session_transport_maps_transport_error() -> None:
    class FailingSession:
        def request(self, method: str, url: str, *, headers: dict[str, str], timeout: float) -> FakeResponse:
            raise requests.ConnectionError("closed")

    transport = RequestsSessionTransport(session=FailingSession())

    with pytest.raises(MassiveTransportError):
        transport.request("GET", "https://api.polygon.io/a", headers={}, timeout=1.0)
