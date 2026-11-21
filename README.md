# TC2008B.CH.api

REST API (Flask) over the polling-station model. The model is the git submodule `model/`
(repo `TC2008B.CH.model`). Unity drives the clock by calling `step` and reads the events it returns.

## Setup

```
git clone --recurse-submodules <this repo>     # or: git submodule update --init
uv sync
uv run pytest
uv run flask --app electoral_api:create_app run
```

## Smoke client

`electoral_api/smoke_client.py` plays Unity's role over HTTP: it rebuilds the station from the event
stream alone and compares it with the server snapshot after every tick (exit code 1 on any mismatch).

```
uv run flask --app electoral_api:create_app run &
uv run python -m electoral_api.smoke_client --seed 1
uv run python -m electoral_api.smoke_client --quake 0.02 --mode poll --minutes 5 --resync-every 10
```

It also runs in CI (`tests/test_smoke_client.py`) against a real server in a thread.

## Docs

- [`docs/data-contract.md`](docs/data-contract.md): endpoints, config, snapshot, events, results.
- [`docs/design.md`](docs/design.md): design decisions, layout, running, updating the model.
- Project spec and open questions: [`model/PROJECT_CONTEXT.md`](model/PROJECT_CONTEXT.md).
