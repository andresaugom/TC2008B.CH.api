"""REST API over the polling-station model.

The client (Unity) owns the clock: it creates a simulation, then calls ``/step``. Every step
returns the events produced, and ``/events?after=<seq>`` replays anything missed, so polling
can never lose a transient state change. ``/simulations/<id>`` returns a full snapshot for
(re)synchronising.
"""

import threading
import uuid
from collections import OrderedDict
from dataclasses import asdict

from electoral import Config, ElectionModel
from flask import Flask, jsonify, request

MAX_SIMULATIONS = 50  # oldest is evicted beyond this
MAX_STEP_MINUTES = 1000


class ApiError(Exception):
    def __init__(self, message, status=400):
        self.message, self.status = message, status


def create_app() -> Flask:
    app = Flask(__name__)
    sims: OrderedDict[str, ElectionModel] = OrderedDict()
    lock = threading.Lock()

    def get_sim(sid) -> ElectionModel:
        sim = sims.get(sid)
        if sim is None:
            raise ApiError(f"simulation {sid!r} not found", 404)
        return sim

    def body() -> dict:
        data = request.get_json(silent=True)
        if data is None:
            return {}
        if not isinstance(data, dict):
            raise ApiError("body must be a JSON object")
        return data

    def int_arg(value, name, default, lo, hi=None):
        if value is None:
            return default
        try:
            n = int(value)
        except (TypeError, ValueError):
            raise ApiError(f"{name} must be an integer") from None
        if isinstance(value, bool) or n < lo or (hi is not None and n > hi):
            raise ApiError(f"{name} must be between {lo} and {hi if hi is not None else 'inf'}")
        return n

    def describe(sid, sim) -> dict:
        return {"id": sid, "seed": sim.seed, "config": asdict(sim.config), **sim.snapshot()}

    @app.errorhandler(ApiError)
    def api_error(e):
        return jsonify(error=e.message), e.status

    @app.errorhandler(404)
    def not_found(_):
        return jsonify(error="not found"), 404

    @app.errorhandler(405)
    def bad_method(_):
        return jsonify(error="method not allowed"), 405

    @app.get("/health")
    def health():
        return jsonify(status="ok")

    @app.post("/simulations")
    def create():
        data = body()
        unknown = set(data) - {"seed", "config"}
        if unknown:
            raise ApiError(f"unknown keys: {sorted(unknown)}")
        seed = int_arg(data.get("seed"), "seed", None, 0, 2**32 - 1)
        try:
            config = Config.from_dict(data.get("config") or {})
        except (ValueError, TypeError) as e:
            raise ApiError(str(e)) from None
        with lock:
            sid = uuid.uuid4().hex[:8]
            sims[sid] = ElectionModel(config, seed=seed)
            while len(sims) > MAX_SIMULATIONS:
                sims.popitem(last=False)
            return jsonify(describe(sid, sims[sid])), 201

    @app.get("/simulations/<sid>")
    def snapshot(sid):
        with lock:
            return jsonify(describe(sid, get_sim(sid)))

    @app.delete("/simulations/<sid>")
    def delete(sid):
        with lock:
            get_sim(sid)
            del sims[sid]
        return "", 204

    @app.post("/simulations/<sid>/step")
    def step(sid):
        minutes = int_arg(body().get("minutes"), "minutes", 1, 1, MAX_STEP_MINUTES)
        with lock:
            sim = get_sim(sid)
            first = sim.last_seq
            for _ in range(minutes):
                if not sim.running:
                    break
                sim.step()
            return jsonify(
                time=sim.clock,
                running=sim.running,
                last_seq=sim.last_seq,
                events=sim.events_since(first),
            )

    @app.get("/simulations/<sid>/events")
    def events(sid):
        after = int_arg(request.args.get("after"), "after", 0, 0)
        with lock:
            sim = get_sim(sid)
            return jsonify(
                time=sim.clock,
                running=sim.running,
                last_seq=sim.last_seq,
                events=sim.events_since(after),
            )

    @app.get("/simulations/<sid>/results")
    def results(sid):
        with lock:
            return jsonify(get_sim(sid).results())

    return app
