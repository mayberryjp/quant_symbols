"""HTTP transport primitives for Massive/Polygon access."""

from __future__ import annotations

from dataclasses import dataclass
import json
import requests
from typing import Protocol
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
import socket

from quant_symbols.vendors.massive.errors import MassiveTimeoutError, MassiveTransportError


@dataclass(frozen=True)
class TransportResponse:
    status_code: int
    headers: dict[str, str]
    body: bytes


class Transport(Protocol):
    def request(self, method: str, url: str, *, headers: dict[str, str], timeout: float) -> TransportResponse:
        """Execute one HTTP request."""


class RequestsSession(Protocol):
    def request(self, method: str, url: str, *, headers: dict[str, str], timeout: float) -> requests.Response:
        """Execute one request using a requests-compatible session."""


class RequestsSessionTransport:
    """HTTP transport backed by a persistent requests session.

    A single session keeps a connection pool, so repeated REST calls to the
    same host can reuse keep-alive TCP/TLS connections.
    """

    def __init__(self, session: RequestsSession | None = None) -> None:
        self._session = session or requests.Session()

    def request(self, method: str, url: str, *, headers: dict[str, str], timeout: float) -> TransportResponse:
        try:
            response = self._session.request(method, url, headers=headers, timeout=timeout)
            return TransportResponse(
                status_code=response.status_code,
                headers=dict(response.headers.items()),
                body=response.content,
            )
        except requests.Timeout as exc:
            raise MassiveTimeoutError("Massive/Polygon request timed out") from exc
        except requests.RequestException as exc:
            raise MassiveTransportError(f"Massive/Polygon transport error: {exc}") from exc


class UrllibTransport:
    """Small stdlib HTTP transport.

    The client accepts any object matching the Transport protocol, so tests and
    later services can inject their own HTTP stack without changing retry logic.
    """

    def request(self, method: str, url: str, *, headers: dict[str, str], timeout: float) -> TransportResponse:
        request = Request(url=url, method=method, headers=headers)
        try:
            with urlopen(request, timeout=timeout) as response:
                return TransportResponse(
                    status_code=response.status,
                    headers=dict(response.headers.items()),
                    body=response.read(),
                )
        except HTTPError as exc:
            return TransportResponse(
                status_code=exc.code,
                headers=dict(exc.headers.items()),
                body=exc.read(),
            )
        except (TimeoutError, socket.timeout) as exc:
            raise MassiveTimeoutError("Massive/Polygon request timed out") from exc
        except URLError as exc:
            if isinstance(exc.reason, TimeoutError):
                raise MassiveTimeoutError("Massive/Polygon request timed out") from exc
            raise MassiveTransportError(f"Massive/Polygon transport error: {exc.reason}") from exc


def decode_json_body(response: TransportResponse) -> dict[str, object]:
    try:
        decoded = json.loads(response.body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise MassiveTransportError("Massive/Polygon response body is not valid JSON") from exc
    if not isinstance(decoded, dict):
        raise MassiveTransportError("Massive/Polygon response JSON must be an object")
    return decoded
