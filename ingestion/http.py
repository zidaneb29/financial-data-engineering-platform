"""Paced JSON requests with bounded retries and sanitized failures."""

import json
import random
import time
from dataclasses import dataclass
from decimal import Decimal
from email.utils import parsedate_to_datetime
from typing import Any

import requests


class IngestionError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


class PayloadError(IngestionError):
    def __init__(self, message: str):
        super().__init__("invalid_payload", message)


@dataclass(frozen=True)
class JsonResponse:
    body: bytes
    data: dict[str, Any]


def retry_after(value: str | None, now: float) -> float:
    if value is None:
        return 0
    if value.isascii() and value.isdigit():
        digits = value.lstrip("0")
        return float(digits or "0") if len(digits) < 12 else float("inf")
    try:
        return max(0, parsedate_to_datetime(value).timestamp() - now)
    except (ValueError, TypeError, OverflowError, OSError):
        return 0


class JsonClient:
    def __init__(
        self, session: requests.Session, *, rate: float, attempts: int = 4,
        clock=time.monotonic, wall_clock=time.time, sleep=time.sleep,
        jitter=lambda: random.uniform(0, 0.25),
    ):
        if rate <= 0 or attempts < 1:
            raise ValueError("Request rate and attempt count must be positive")
        self.session = session
        self.interval = 1 / rate
        self.attempts = attempts
        self.clock = clock
        self.wall_clock = wall_clock
        self.sleep = sleep
        self.jitter = jitter
        self.next_request = 0.0
        self.cooldown_until = 0.0

    def get(
        self, url: str, *, params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None, fred: bool = False,
    ) -> JsonResponse:
        if self.clock() < self.cooldown_until:
            raise IngestionError("source_cooldown", "Source is cooling down after a rate-limit response")
        for attempt in range(self.attempts):
            self.sleep(max(0, self.next_request - self.clock()))
            self.next_request = self.clock() + self.interval
            wait = 0.0
            try:
                response = self.session.get(
                    url, params=params, headers=headers, timeout=(5, 30),
                    allow_redirects=False,
                )
            except requests.exceptions.SSLError:
                raise IngestionError("tls_error", "TLS verification failed") from None
            except (
                requests.exceptions.Timeout, requests.exceptions.ConnectionError,
                requests.exceptions.ChunkedEncodingError,
            ):
                error = IngestionError("network_error", "Source connection failed")
            except requests.exceptions.RequestException:
                raise IngestionError("http_client_error", "Source request failed") from None
            else:
                status = response.status_code
                if 200 <= status < 300:
                    return decode_json(response.content, fred=fred)
                error = IngestionError(f"http_{status}", f"Source returned HTTP {status}")
                if status not in {408, 429, 500, 502, 503, 504}:
                    raise error
                wait = retry_after(response.headers.get("Retry-After"), self.wall_clock())
            if wait > 60:
                self.cooldown_until = self.clock() + wait
                raise IngestionError(error.code, "Source requested a cooldown above 60 seconds")
            if attempt == self.attempts - 1:
                self.next_request = max(self.next_request, self.clock() + wait)
                raise error
            self.next_request = max(self.next_request, self.clock() + max(wait, 2**attempt + self.jitter()))
        raise AssertionError("Request attempts exhausted")


def decode_json(body: bytes, *, fred: bool = False) -> JsonResponse:
    try:
        data = json.loads(body, parse_float=Decimal, parse_constant=_invalid_json_constant)
    except ValueError:
        raise PayloadError("Source response is not valid JSON") from None
    if not isinstance(data, dict):
        raise PayloadError("Source response must be a JSON object")
    if fred and ("error_code" in data or "error_message" in data):
        raise IngestionError("fred_api_error", "FRED returned an API error payload")
    return JsonResponse(body, data)


def _invalid_json_constant(_value: str) -> None:
    raise ValueError("Invalid non-finite JSON constant")
