"""Smoke client that behaves like the Unity frontend, using only the HTTP contract.

It keeps its own picture of the station built *only* from the event stream (what a Unity state
manager would do), and after each tick compares it with the server's snapshot. Any difference
means the event stream does not carry enough information to render the scene: a contract bug.

    uv run python -m electoral_api.smoke_client --url http://127.0.0.1:5000 --seed 1
    uv run python -m electoral_api.smoke_client --quake 0.02      # force an earthquake

Exit code 0 if the client view matched the server at every check, 1 otherwise.
Stdlib only, so it can be run anywhere.
"""

import argparse
import json
import sys
import urllib.error
import urllib.request


def http(method, url, body=None):
    data = None if body is None else json.dumps(body).encode()
    req = urllib.request.Request(
        url, data=data, method=method, headers={"Content-Type": "application/json"}
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            raw = resp.read()
            return json.loads(raw) if raw else None
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"{method} {url} -> {e.code}: {e.read().decode()}") from None


class StateManager:
    """What the frontend knows: bootstrapped from a snapshot, then fed events in seq order."""

    def __init__(self, snap):
        self.seq = snap["last_seq"]
        self.open = snap["station_open"]
        self.voters = {
            v["id"]: {"location": v["location"], "slot": v["slot"]} for v in snap["voters"]
        }
        self.queues = {k: list(v) for k, v in snap["queues"].items()}
        self.verifiers = [s["voter_id"] for s in snap["verifiers"]]
        self.booths = [s["voter_id"] for s in snap["booths"]]
        self.urn = snap["urn"]["voter_id"]

    def _place(self, vid, location, slot=None):
        self.voters[vid] = {"location": location, "slot": slot}

    def apply(self, ev):
        if ev["seq"] != self.seq + 1:
            raise AssertionError(f"gap in event stream: had seq {self.seq}, got {ev['seq']}")
        self.seq = ev["seq"]
        t, vid = ev["type"], ev["voter_id"]
        if t in ("voter_turned_away", "voter_abandoned", "voter_finished", "document_invalid"):
            for q in self.queues.values():
                if vid in q:
                    q.remove(vid)
            if t == "voter_finished":
                self.urn = None
            self._place(vid, "exited")
        elif t == "queue_joined":
            self.queues[ev["queue"]].append(vid)
            self._place(vid, "queue_" + ev["queue"])
        elif t == "verification_started":
            self.queues["verification"].remove(vid)
            self.verifiers[ev["resource"]] = vid
            self._place(vid, "verifier", ev["resource"])
        elif t == "verification_finished":
            self.verifiers[ev["resource"]] = None
        elif t == "booth_started":
            self.queues["booth"].remove(vid)
            self.booths[ev["resource"]] = vid
            self._place(vid, "booth", ev["resource"])
        elif t == "booth_finished":
            self.booths[ev["resource"]] = None
        elif t == "urn_started":
            self.queues["urn"].remove(vid)
            self.urn = vid
            self._place(vid, "urn")
        elif t == "earthquake":
            self.open = False
            self.queues = {k: [] for k in self.queues}
            self.verifiers = [None] * len(self.verifiers)
            self.booths = [None] * len(self.booths)
            self.urn = None
        elif t == "voter_evacuated":
            self._place(vid, "outside" if ev["will_return"] else "exited")
        elif t == "station_reopened":
            self.open = True
        elif t != "voter_arrived":
            raise AssertionError(f"unknown event type {t!r}")

    def diff(self, snap):
        """Differences between this view and the server snapshot (empty list = in sync)."""
        out = []
        if self.seq != snap["last_seq"]:
            out.append(f"seq {self.seq} != {snap['last_seq']}")
        if self.open != snap["station_open"]:
            out.append(f"station_open {self.open} != {snap['station_open']}")
        if self.queues != snap["queues"]:
            out.append(f"queues {self.queues} != {snap['queues']}")
        for name, mine in (("verifiers", self.verifiers), ("booths", self.booths)):
            theirs = [s["voter_id"] for s in snap[name]]
            if mine != theirs:
                out.append(f"{name} {mine} != {theirs}")
        if self.urn != snap["urn"]["voter_id"]:
            out.append(f"urn {self.urn} != {snap['urn']['voter_id']}")
        for v in snap["voters"]:
            mine = self.voters[v["id"]]
            if mine != {"location": v["location"], "slot": v["slot"]}:
                out.append(f"voter {v['id']}: client {mine} != server {v['location']}/{v['slot']}")
        return out


def run(url, seed, voters, minutes, mode, quake, resync_every, log=print):
    """Run one full simulation. Returns (ok, summary dict)."""
    config = {"n_voters": voters}
    if quake is not None:
        config["p_earthquake_per_minute"] = quake
    snap = http("POST", f"{url}/simulations", {"seed": seed, "config": config})
    sid = snap["id"]
    base = f"{url}/simulations/{sid}"
    log(f"created simulation {sid} (seed {snap['seed']}, {voters} voters, mode={mode})")

    state = StateManager(snap)
    counts, ticks, problems = {}, 0, []
    running = True
    while running:
        ticks += 1
        result = http("POST", f"{base}/step", {"minutes": minutes})
        running = result["running"]
        # "step": use the events the step returned. "poll": ignore them and GET /events?after=.
        if mode == "poll":
            result = http("GET", f"{base}/events?after={state.seq}")
        for ev in result["events"]:
            state.apply(ev)
            counts[ev["type"]] = counts.get(ev["type"], 0) + 1
            if ev["type"] == "earthquake":
                log(f"  t={ev['t']:4}  EARTHQUAKE, {len(ev['affected_voters'])} voters evacuated")
            elif ev["type"] == "station_reopened":
                log(f"  t={ev['t']:4}  station reopened")

        server = http("GET", base)
        d = state.diff(server)
        if d:
            problems.append((server["time"], d))
            log(f"  MISMATCH at t={server['time']}: {d[:3]}")
            break
        if resync_every and ticks % resync_every == 0:
            state = StateManager(server)  # a client that reconnects: bootstrap from snapshot
            counts["_resyncs"] = counts.get("_resyncs", 0) + 1
        if ticks % 50 == 0:
            q = {k: len(v) for k, v in state.queues.items()}
            log(f"  t={server['time']:4}  queues {q}  events so far {state.seq}")

    res = http("GET", f"{base}/results")
    # The event stream must also agree with the final results
    if not problems:
        terminal = {v["state"] for v in http("GET", base)["voters"]}
        if res["finished"] is not True:
            problems.append((res["time"], ["results not finished after running=false"]))
        elif any(v["location"] != "exited" for v in http("GET", base)["voters"]):
            problems.append((res["time"], [f"voters left in station: {terminal}"]))
    summary = {
        "simulation": sid,
        "ticks": ticks,
        "events": state.seq,
        "event_types": counts,
        "results": {
            k: res[k]
            for k in (
                "time",
                "votes",
                "winner",
                "voters_by_state",
                "average_minutes_all",
                "average_minutes_completed",
                "earthquake",
            )
        },
    }
    http("DELETE", base)
    return not problems, summary


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--url", default="http://127.0.0.1:5000")
    p.add_argument("--seed", type=int, default=1)
    p.add_argument("--voters", type=int, default=200)
    p.add_argument("--minutes", type=int, default=1, help="minutes advanced per step call")
    p.add_argument(
        "--mode",
        choices=["step", "poll"],
        default="step",
        help="step: use events returned by step; poll: GET /events?after=seq",
    )
    p.add_argument("--quake", type=float, default=None, help="earthquake probability per minute")
    p.add_argument(
        "--resync-every",
        type=int,
        default=0,
        help="every N ticks rebuild the client from a snapshot (reconnect test)",
    )
    a = p.parse_args(argv)
    ok, summary = run(a.url, a.seed, a.voters, a.minutes, a.mode, a.quake, a.resync_every)
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    print("RESULT:", "OK, client view matched the server at every tick" if ok else "FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
