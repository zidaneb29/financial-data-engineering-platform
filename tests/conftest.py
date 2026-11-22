import json
import socket
from collections import deque
from types import SimpleNamespace

import pytest
import requests

from ingestion.http import JsonClient


def response(data=None, *, status=200, headers=None, body=None):
    return SimpleNamespace(
        status_code=status, headers=headers or {},
        content=body if body is not None else json.dumps(data).encode(),
    )


@pytest.fixture(autouse=True)
def protect_offline_tests(monkeypatch, request):
    if not request.node.get_closest_marker("integration"):
        def deny_network(*_args, **_kwargs):
            pytest.fail("Offline test attempted a live HTTP request")

        monkeypatch.setattr(requests.Session, "send", deny_network)
        monkeypatch.setattr(socket.socket, "connect", deny_network)


@pytest.fixture
def fake_http():
    def make(items, *, rate=2, attempts=4):
        queue = deque(items)
        calls = []
        now = 0.0

        def sleep(seconds):
            nonlocal now
            now += seconds

        def get(url, **options):
            calls.append({"url": url, "time": now, **options})
            item = queue.popleft()
            if isinstance(item, Exception):
                raise item
            return item

        client = JsonClient(
            SimpleNamespace(get=get), rate=rate, attempts=attempts, clock=lambda: now,
            wall_clock=lambda: 0, sleep=sleep, jitter=lambda: 0,
        )
        return client, calls

    return make
