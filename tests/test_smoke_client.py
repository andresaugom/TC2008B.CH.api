"""Runs the Unity-like smoke client against a real HTTP server (in a thread)."""

import threading

import pytest
from werkzeug.serving import make_server

from electoral_api import create_app
from electoral_api.smoke_client import StateManager, http, run


@pytest.fixture(scope="module")
def url():
    server = make_server("127.0.0.1", 0, create_app())
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_port}"
    server.shutdown()


@pytest.mark.parametrize(
    "kwargs",
    [
        {"seed": 1, "mode": "step", "minutes": 1, "quake": None, "resync_every": 0},
        {"seed": 2, "mode": "poll", "minutes": 5, "quake": 0.01, "resync_every": 0},
        {"seed": 1, "mode": "step", "minutes": 1, "quake": 0.01, "resync_every": 7},
    ],
)
def test_client_view_matches_server(url, kwargs):
    ok, summary = run(url, voters=60, log=lambda *_: None, **kwargs)
    assert ok
    assert summary["events"] > 0
    if kwargs["quake"]:
        assert summary["event_types"].get("earthquake") == 1  # the earthquake path was exercised


def test_diff_detects_a_wrong_view(url):
    snap = http("POST", f"{url}/simulations", {"seed": 1, "config": {"n_voters": 20}})
    base = f"{url}/simulations/{snap['id']}"
    state = StateManager(snap)
    events = http("POST", f"{base}/step", {"minutes": 30})["events"]
    assert any(e["type"] == "queue_joined" for e in events)
    for ev in events:
        state.apply(ev)
    assert state.diff(http("GET", base)) == []
    state.queues["verification"].append(999)  # corrupt the client's view
    assert state.diff(http("GET", base))


def test_gap_in_events_is_rejected(url):
    snap = http("POST", f"{url}/simulations", {"seed": 1, "config": {"n_voters": 20}})
    state = StateManager(snap)
    events = http("POST", f"{url}/simulations/{snap['id']}/step", {"minutes": 30})["events"]
    with pytest.raises(AssertionError, match="gap"):
        state.apply(events[1])  # skipped events[0]
