# API design

## Scope and shape

Local, single-user backend for a class demo: one process on the developer's machine, a Unity
client on the same machine, no authentication, no persistence. The model repo
(`TC2008B.CH.model`, submodule `model/`) holds the simulation and the project spec
(`model/PROJECT_CONTEXT.md`); this repo only exposes it over HTTP. The wire format is in
`data-contract.md`.

```
Unity  --HTTP/JSON-->  Flask app (electoral_api/app.py)  -->  electoral.ElectionModel (Mesa)
```

## Decisions

- **The client owns the clock.** `POST /step` advances the simulation; the server never advances
  by itself. Unity can pace the animation however it likes (one minute per second, fast forward
  with `minutes=N`, pause by not calling), and runs are deterministic. Server-side autoplay was
  rejected as extra state with no benefit for a demo.
- **Pull with a sequenced event log.** The suggested architecture has Unity polling with GET, and
  the teacher's script asks that every event reach Unity. A snapshot alone would drop transient
  states (a voter who verifies and moves on between two polls). So every change is an event with a
  gapless `seq`; `step` returns the new ones and `events?after=` replays any gap. The snapshot
  exists for the first load and for resynchronising.
- **Seeds make runs reproducible.** The seed is accepted on create and always returned. Same seed
  and config give the same event log; the model is tested against the teacher's script to
  guarantee it.
- **Simulations by id, in memory.** Cheap to support several (tests, retries, comparing
  configs). The oldest is evicted past 50. Restarting the server clears everything; fine for a
  local demo.
- **One lock.** Flask's dev server is threaded; a single lock serialises all model access so a
  step can never interleave with a read. Simple and sufficient at this scale.
- **Strict input validation.** Unknown keys, bad ranges and wrong types give 400 with a message,
  rather than being silently ignored, so typos in a config fail loudly.
- **Ballot secrecy.** No per-voter party anywhere in the API, only totals in results.
- **Config belongs to the model.** The API passes `config` to `electoral.Config.from_dict`, which
  validates; adding a parameter to the model needs no API change.

## Layout

```
electoral_api/app.py   Flask app factory: routes, validation, simulation store
tests/test_api.py      Flask test-client tests of the contract
model/                 git submodule: the Mesa model (own tests and CI)
docs/                  this file and data-contract.md
```

## Running locally

```
git clone --recurse-submodules <repo>
uv sync
uv run flask --app electoral_api:create_app run          # http://127.0.0.1:5000
```

Binds to localhost only; do not expose it (no auth, in-memory). Unity's `UnityWebRequest` is not
subject to CORS; if a WebGL build is ever used, CORS headers would need to be added.

## Updating the model

The submodule pins an exact model commit. To take a new model version:

```
git -C model pull origin main
uv sync
uv run pytest
git add model && git commit -m "Bump model"
```

Contract changes (new event types or fields) are made in the model first, then documented in
`data-contract.md` in the same commit that bumps the submodule.

## CI

GitHub Actions on every push/PR: checkout with submodules, `uv sync --locked`, `ruff check`,
`ruff format --check`, `pytest`.

## Not done / future

Server-side autoplay, CORS, persistence, API versioning, a Unity smoke client. Open
questions that may change the contract (which agents Unity needs, required metrics) are tracked in
`model/PROJECT_CONTEXT.md`.
