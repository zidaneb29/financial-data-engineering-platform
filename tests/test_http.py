from datetime import datetime, timezone
from email.utils import format_datetime

import pytest
import requests

from ingestion.http import IngestionError, retry_after
from conftest import response


@pytest.mark.parametrize("status", [400, 401, 403, 404])
def test_permanent_http_errors_are_not_retried(fake_http, status):
    client, calls = fake_http([response(status=status, body=b"private body")])
    with pytest.raises(IngestionError, match=fr"HTTP {status}") as exc:
        client.get("https://example.test/api", params={"api_key": "do-not-log"})
    assert exc.value.code == f"http_{status}"
    assert len(calls) == 1
    assert calls[0]["allow_redirects"] is False
    assert calls[0]["timeout"] == (5, 30)


def test_rate_limit_and_transient_network_retry(fake_http):
    client, calls = fake_http([
        response(status=429, headers={"Retry-After": "3"}),
        requests.ConnectionError("URL with private data"),
        response(status=503), response({"value": 1}),
    ], rate=2)
    assert client.get("https://example.test/api").data == {"value": 1}
    assert [call["time"] for call in calls] == [0, 3, 5, 9]
    client.session.get = lambda *_args, **_kwargs: response({})
    client.get("https://example.test/api")
    assert client.next_request == 10


def test_retry_exhaustion_redacts_network_errors(fake_http):
    client, calls = fake_http([requests.Timeout("secret URL")] * 3, attempts=3)
    with pytest.raises(IngestionError, match="Source connection failed") as exc:
        client.get("https://example.test/api")
    assert exc.value.code == "network_error"
    assert exc.value.__context__ is None
    assert [call["time"] for call in calls] == [0, 1, 3]


def test_long_retry_after_stops_requests_during_cooldown(fake_http):
    client, calls = fake_http([response(status=429, headers={"Retry-After": "90"})])
    with pytest.raises(IngestionError, match="above 60 seconds"):
        client.get("https://example.test/api")
    with pytest.raises(IngestionError, match="cooling down"):
        client.get("https://example.test/another")
    assert len(calls) == 1


def test_retry_after_accepts_http_date():
    value = format_datetime(datetime.fromtimestamp(20, tz=timezone.utc), usegmt=True)
    assert retry_after(value, 5) == 15
    assert retry_after(value, 30) == 0


@pytest.mark.parametrize(("payload", "code"), [
    (response({"error_code": 400, "error_message": "secret"}), "fred_api_error"),
    (response(body=b"<html>bad gateway</html>"), "invalid_payload"),
    (response([]), "invalid_payload"),
])
def test_fred_api_and_json_errors_are_distinct_and_sanitized(fake_http, payload, code):
    client, calls = fake_http([payload])
    with pytest.raises(IngestionError) as exc:
        client.get("https://example.test/api", fred=True)
    assert exc.value.code == code
    assert "secret" not in str(exc.value)
    assert len(calls) == 1
