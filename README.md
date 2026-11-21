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

## Docs

- [`docs/data-contract.md`](docs/data-contract.md): endpoints, config, snapshot, events, results.
- [`docs/design.md`](docs/design.md): design decisions, layout, running, updating the model.
- Project spec and open questions: [`model/PROJECT_CONTEXT.md`](model/PROJECT_CONTEXT.md).
