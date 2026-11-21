import pytest

from electoral_api import create_app


@pytest.fixture
def client():
    return create_app().test_client()


def new_sim(client, **payload):
    r = client.post("/simulations", json=payload)
    assert r.status_code == 201, r.json
    return r.json


def test_health(client):
    assert client.get("/health").json == {"status": "ok"}


def test_create_returns_snapshot(client):
    sim = new_sim(client, seed=1)
    assert sim["seed"] == 1 and sim["time"] == 0 and sim["running"]
    assert len(sim["verifiers"]) == 3 and len(sim["booths"]) == 2
    assert len(sim["voters"]) == 200
    assert sim["config"]["n_voters"] == 200


def test_step_events_and_replay_agree(client):
    sid = new_sim(client, seed=4)["id"]
    seen = []
    while True:
        r = client.post(f"/simulations/{sid}/step", json={"minutes": 7}).json
        seen += r["events"]
        if not r["running"]:
            break
    replay = client.get(f"/simulations/{sid}/events?after=0").json
    assert seen == replay["events"]
    tail = client.get(f"/simulations/{sid}/events?after={replay['last_seq'] - 3}").json
    assert tail["events"] == seen[-3:]


def test_same_seed_same_events(client):
    runs = []
    for _ in range(2):
        sid = new_sim(client, seed=8, config={"n_voters": 30})["id"]
        client.post(f"/simulations/{sid}/step", json={"minutes": 1000})
        runs.append(client.get(f"/simulations/{sid}/events").json["events"])
    assert runs[0] == runs[1] and runs[0]


def test_results_after_finish(client):
    sid = new_sim(client, seed=2, config={"n_voters": 20})["id"]
    client.post(f"/simulations/{sid}/step", json={"minutes": 1000})
    r = client.get(f"/simulations/{sid}/results").json
    assert r["finished"] and sum(r["voters_by_state"].values()) == 20


@pytest.mark.parametrize(
    "payload",
    [
        {"config": {"bogus": 1}},
        {"config": {"p_return": 5}},
        {"seed": -1},
        {"seed": "x"},
        {"extra": 1},
        {"config": {"verifier_policy": "x"}},
    ],
)
def test_create_validation(client, payload):
    r = client.post("/simulations", json=payload)
    assert r.status_code == 400 and "error" in r.json


@pytest.mark.parametrize("minutes", [0, -1, 100000, "a", True])
def test_step_validation(client, minutes):
    sid = new_sim(client)["id"]
    assert client.post(f"/simulations/{sid}/step", json={"minutes": minutes}).status_code == 400


def test_unknown_simulation_and_delete(client):
    assert client.get("/simulations/nope").status_code == 404
    sid = new_sim(client)["id"]
    assert client.delete(f"/simulations/{sid}").status_code == 204
    assert client.get(f"/simulations/{sid}").status_code == 404
