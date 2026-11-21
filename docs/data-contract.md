# Data contract

The contract between the API and its client (Unity). Everything is JSON over HTTP, UTF-8.
The source of truth is the code (`electoral_api/app.py`, `model/electoral/`); the examples
below come from a real run (`seed=1`, `n_voters=3`). The simulation and project context live in
the model repo (`model/PROJECT_CONTEXT.md`).

Conventions: field names are `snake_case`; times are integer simulated minutes since the station
opened (minute 0); ids are integers starting at 1 for voters and at 0 for slots (verifier / booth
index); errors are `{"error": "<message>"}` with status 400 (bad input) or 404 (unknown id).
Fields documented as "stable codes" (states, locations, event types) will not change without
updating this file; `message` is human-readable Spanish text and must not be parsed.

## Endpoints

| Method | Path | Body / query | Success |
|---|---|---|---|
| GET | `/health` | | 200 `{"status":"ok"}` |
| POST | `/simulations` | `{"seed"?: int 0..2^32-1, "config"?: object}` | 201 snapshot (+ `id`, `seed`, `config`) |
| GET | `/simulations/{id}` | | 200 snapshot |
| POST | `/simulations/{id}/step` | `{"minutes"?: int 1..1000}` (default 1) | 200 step result |
| GET | `/simulations/{id}/events` | `?after=<seq>` (default 0) | 200 step result (events after `seq`) |
| GET | `/simulations/{id}/results` | | 200 results |
| DELETE | `/simulations/{id}` | | 204 |

Unknown keys in the create body, an out-of-range value, or a non-integer where an integer is
expected yield 400. If the seed is omitted the server picks one and returns it, so any run can be
reproduced by creating a simulation with that seed and config.

## Config (`POST /simulations`, key `config`)

All optional; defaults reproduce the teacher's baseline script. Unknown keys are rejected.

| Key | Default | Meaning |
|---|---|---|
| `n_voters` | 200 | Voters that will arrive |
| `arrival_range` | [1, 4] | Uniform integer minutes between consecutive arrivals |
| `n_verifiers` | 3 | Nominal-list verifiers |
| `verification_range` | [2, 7] | Uniform integer service minutes |
| `n_booths` | 2 | Voting booths (*mamparas*) |
| `booth_range` | [3, 9] | Uniform integer minutes |
| `urn_range` | [4, 10] | Uniform integer minutes (single urn) |
| `p_valid_document` | 0.90 | Probability the document is valid, checked when a booth is available |
| `abandon_low_frac`, `abandon_mid_frac` | 0.20, 0.40 | Verification-queue thresholds, as a fraction of `n_voters` |
| `abandon_probs` | [0.10, 0.40, 0.80] | Abandonment probability below low / below mid / otherwise (decided on arrival) |
| `parties` | ["Rojo", "Azul"] | Parties; each vote is uniform among them |
| `p_earthquake_per_minute` | 0.0002 | Chance per minute of an earthquake (at most one per run) |
| `closure_minutes` | 20 | Minutes the station stays closed after the earthquake |
| `p_return` | 0.60 | Probability an evacuated voter comes back |
| `verifier_policy` | "first" | Which free verifier is used: `first` or `random` |

Ranges are `[low, high]`, inclusive, `1 <= low <= high`. Probabilities are in `[0, 1]`.

## Snapshot

Returned by `POST /simulations` and `GET /simulations/{id}`. Full current state, for
(re)synchronising. The create/get response also carries `id`, `seed` and `config` (the effective
config, with defaults filled in).

```json
{
  "id": "12c86c3b", "seed": 1,
  "config": { "n_voters": 3, "...": "..." },
  "time": 0, "running": true, "station_open": true, "last_seq": 0,
  "verifiers": [{"index": 0, "voter_id": null}, {"index": 1, "voter_id": null}, {"index": 2, "voter_id": null}],
  "booths":    [{"index": 0, "voter_id": null}, {"index": 1, "voter_id": null}],
  "urn": {"voter_id": null},
  "queues": {"verification": [], "booth": [], "urn": []},
  "voters": [
    {"id": 1, "state": "en_route", "location": "outside", "slot": null, "arrival": 0, "exit": null}
  ]
}
```

| Field | Meaning |
|---|---|
| `time` | Current simulated minute |
| `running` | `false` once no events remain; the simulation is over |
| `station_open` | `false` while closed by the earthquake |
| `last_seq` | `seq` of the latest event (0 if none); pass it as `after` to continue |
| `verifiers`, `booths` | One entry per slot; `voter_id` is the voter being served or `null` |
| `urn.voter_id` | Voter at the urn or `null` |
| `queues.*` | Voter ids in order, head first |
| `voters[].slot` | Verifier/booth index while being served, else `null` |
| `voters[].arrival` | Arrival minute. **0 until the voter arrives**: use `state == "en_route"` to tell |
| `voters[].exit` | Minute the voter left, `null` while still in the process (including evacuated voters waiting to return) |

### Voter `state` and `location` (stable codes)

| `state` | `location` | Meaning |
|---|---|---|
| `en_route` | `outside` | Not arrived yet |
| `waiting_verification` | `queue_verification` | In the verification queue |
| `verifying` | `verifier` | At verifier `slot` |
| `waiting_booth` | `queue_booth` | In the booth queue |
| `in_booth` | `booth` | At booth `slot` |
| `waiting_urn` | `queue_urn` | In the urn queue |
| `at_urn` | `urn` | Casting the vote |
| `finished` | `exited` | Voted (terminal) |
| `abandoned` | `exited` | Left on arrival, or found the station closed (terminal) |
| `invalid_document` | `exited` | Document rejected at the booth stage (terminal) |
| `evacuated` | `outside` | Evacuated by the earthquake, will return |
| `abandoned_earthquake` | `exited` | Evacuated and left for good, or returned and decided not to queue (terminal) |

Voter flow: `en_route` → `waiting_verification` → `verifying` → `waiting_booth` → `in_booth` →
`waiting_urn` → `at_urn` → `finished`, with the exits above.

## Step result

Returned by `POST .../step` and `GET .../events`.

```json
{ "time": 4, "running": true, "last_seq": 5, "events": [ ... ] }
```

`step` advances up to `minutes` minutes (stopping early when the simulation ends) and returns the
events produced **by that call**. `events` returns every event with `seq > after`. Both use the
same shape. Stepping a finished simulation is a no-op returning an empty `events`.

## Events

Append-only log. `seq` starts at 1 and increases by 1 with no gaps, so a client that remembers the
last `seq` it processed can always catch up with `GET .../events?after=<seq>`. Events are ordered
by `t`, then by the order in which they happened inside the minute (apply them in `seq` order).

Common fields: `seq`, `t` (minute), `type`, `voter_id` (`null` for station events), `message`.

```json
{"seq": 3, "t": 2, "type": "verification_started", "voter_id": 1, "resource": 0,
 "message": "Votante 01 inicia verificación 1"}
```

| `type` | Extra fields | When |
|---|---|---|
| `voter_arrived` | | Voter reaches the station |
| `voter_turned_away` | | Arrived while closed; voter leaves (`abandoned`) |
| `voter_abandoned` | | Decided not to queue, on arrival or on return (`abandoned` / `abandoned_earthquake`) |
| `queue_joined` | `queue`: `verification` \| `booth` \| `urn` | Voter enters a queue |
| `verification_started` | `resource`: verifier index | Voter starts verification |
| `verification_finished` | `resource` | Verifier freed, voter moves to the booth queue |
| `document_invalid` | | Document rejected when a booth became available (`invalid_document`) |
| `booth_started` | `resource`: booth index | Voter enters a booth |
| `booth_finished` | `resource` | Booth freed, voter moves to the urn queue |
| `urn_started` | | Voter starts casting the vote |
| `voter_finished` | | Vote cast, voter leaves (`finished`) |
| `earthquake` | `affected_voters`: [ids] | Station evacuated: queues, slots and urn emptied, any vote being cast is voided; `voter_id` is `null` |
| `voter_evacuated` | `will_return`: bool | One per affected voter, right after `earthquake` |
| `station_reopened` | | Closure over; `voter_id` is `null` |

A voter who returns after an earthquake and queues emits `queue_joined` (queue `verification`)
again. The party a voter chose is intentionally absent from events and the snapshot (ballot
secrecy); it only appears as totals in the results.

## Results

`GET /simulations/{id}/results`. Valid at any time; final once `finished` is `true`.

```json
{
  "finished": true, "time": 24,
  "per_voter": [{"id": 1, "state": "finished", "minutes": 22}],
  "average_minutes_all": 7.33, "average_minutes_completed": 22.0,
  "voters_by_state": {"abandoned": 2, "finished": 1},
  "votes": {"Azul": 1, "Rojo": 0}, "winner": "Azul", "tie": false,
  "earthquake": {"occurred": false, "evacuated": 0, "voted_afterwards": 0}
}
```

- `minutes` = exit minute minus arrival minute (abandoned and invalid-document voters included).
- `average_minutes_all` is the baseline definition (over all voters). `average_minutes_completed`
  covers only voters in state `finished`, `null` if none.
- `winner` is the party with most votes; on a tie it is the first of those in `parties` order and
  `tie` is `true`. With zero votes `winner` is the first party and `tie` is `true`.
- `voted_afterwards` counts evacuated voters who ended `finished`.
