# Simulation Specification: INE Polling Station (single casilla)

Design spec for the Mesa + REST API + Unity simulation. It builds on the baseline `baseline.py` and on the concepts from the statistics class (see `PROJECT_CONTEXT.md`, section 2). The teacher gave the team free choice of distributions, metrics, architecture and visuals, so everything here is a team proposal. Items marked **[Baseline]** come from the provided code, **[Class]** from the statistics lecture, **[Proposed]** are design choices of this spec, and **[Placeholder]** are values to calibrate (ideally with the INEGI data if it becomes available).

## 1. Goals and scope

Model the voting process of one polling station over one election day as a stochastic multi-agent system, run it as a Mesa model exposed through a REST API, and visualize it live in a 3D Unity scene. The simulation must be statistically defensible: every random component is an explicit distribution from the class toolbox, every output has a stated estimator, and results come with replication-based uncertainty.

In scope: voter arrival, collision/priority handling, nominal-list verification, booth, urn, abandonment, invalid documents, the vote itself, metrics, API, 3D visualization.
Out of scope for the first demo (see section 11): multiple stations, ballot counting procedures, fraud or irregularity detection, per-resource staff behavior such as breaks.

## 2. How the class concepts map to the model

| Concept from class | Where it appears in the model |
|---|---|
| Voter decision as a binary random variable X_i ∈ {0,1} | Vote model (5.6); estimator p̂ and confidence interval in the metrics (6.3) |
| Inter-arrival gap Δt as random; Δt = 0 is a collision; priority criteria | Arrival process (5.1) and collision rule (5.2) |
| Density conditions: f ≥ 0 and ∫f = 1 | Unit test for every configured distribution (7.1) |
| Uniform(a, b): mean (a+b)/2, variance (b−a)²/12 | Baseline-compatible arrivals and service times; moment checks (7.1) |
| Normal(μ, σ²) | Bell-shaped arrival profile, optionally service times (both truncated at 0) |
| Gamma(α, β) | Front-loaded arrival profile: a high flow at opening that thins out smoothly (5.1) |
| Beta(α, β) on [0, 1] | Bounded arrival profile scaled to the opening window (5.1) |
| Kernel density estimate overlaid on a histogram | Validation of arrival samples against the theoretical density (7.1) and a live chart option in Unity |
| Monte Carlo, central limit theorem | Replicated runs and normal-approximation intervals for every metric (7.2) |
| Poisson/exponential and queueing theory (upcoming class) | Utilization, Little's law check (6.2, 7.3), and a ready hook for exponential arrivals and service later |

## 3. Conventions

- **Clock:** integer ticks; 1 tick = 1 simulated second **[Proposed]**. The baseline uses integer minutes; durations are converted to seconds so that sub-minute events (for example depositing a ballot) are representable.
- **Arrival resolution:** arrival instants are quantized to `arrival_resolution_s` (default 60 s, matching the baseline's minute granularity) **[Proposed]**. This matters for collisions (5.2).
- **Opening window:** arrivals are generated in [0, T] with T = 600 min, i.e. a 10-hour day (assumed 08:00–18:00, to verify) **[Placeholder]**. After T no new voters arrive, but voters already inside finish.
- **Reproducibility:** one master seed per run; independent random streams (numpy `Generator`) for arrivals, service times and decisions, so changing one component does not reshuffle the others **[Proposed]**.
- **Terminology:** *urn* is the ballot box stage (the baseline code calls it "casilla"); *station* is the whole polling station.

## 4. Entities

### 4.1 Voter agent (Mesa agent) **[Baseline + Proposed]**

| Attribute | Description |
|---|---|
| `id` | 1..N |
| `arrival_tick` | scheduled arrival instant |
| `is_senior`, `mobility_limited` | priority attributes (5.2) **[Class]** |
| `doc_valid` | drawn once, Bernoulli(p_doc_valid) |
| `vote` | X_i, drawn when the voter reaches the urn; **never exposed through the API** (ballot secrecy), only aggregate tallies are |
| `state` | see 4.4 |
| timestamps | arrival, start/end of each stage, exit; used to derive every time metric |
| `outcome` | `voted`, `abandoned`, `invalid_document` |

### 4.2 Resources

| Resource | Count (baseline) | Notes |
|---|---|---|
| Verifier (nominal list) | 3 | **[Proposed]** model these as small agents (idle/busy) so they are visible and animatable in Unity, and so the multi-agent aspect is real. Open question for the teacher. |
| Booth (*mampara*) | 2 | passive resource |
| Urn | 1 | passive resource; see the saturation warning in 5.3 |

Each stage has one FIFO queue shared by its servers (as in the baseline).

### 4.3 Model

Holds the clock, configuration, queues, resources, event log, metric accumulators and the random streams.

### 4.4 Voter states

`EN_CAMINO` → `ESPERANDO_VERIFICACION` → `VERIFICANDO` → `ESPERANDO_MAMPARA` → `EN_MAMPARA` → `ESPERANDO_URNA` → `EN_URNA` → `FINALIZADO`, with two terminal side exits: `ABANDONO` (at arrival) and `DOCUMENTO_INVALIDO` (when called to a booth, as in the baseline).

## 5. Stochastic components

### 5.1 Arrival process

Two modes, selected in the configuration. In both, the station receives N voters (N = 200 in the baseline; interpreted as the expected number of voters for the day, as in the class motivation) **[Baseline + Class]**.

**Mode `interarrival`:** consecutive gaps Δt are i.i.d. from a chosen distribution and arrival instants are the cumulative sums. Baseline-compatible setting: discrete uniform {1,...,4} min. Note that this baseline setting forbids Δt = 0, so it can never produce a collision. The class example used Uniform(0, 1) min, which allows Δt ≈ 0.

**Mode `instants`:** each voter's arrival instant is drawn i.i.d. from a density over the opening window, and the instants are then sorted. This is the natural way to express the day-long profile discussed in class, where a gamma density yields a strong flow when the station opens that thins out gradually **[Class]**. A flat Uniform(0, T) here is equivalent to a homogeneous Poisson process conditioned on N arrivals, which links directly to the upcoming queueing-theory class.

| Profile | Density for the arrival instant | Illustrative parameters **[Placeholder]** | Resulting day |
|---|---|---|---|
| `uniform` | Uniform(0, T) | a = 0, b = T | flat flow ("boring" but a valid model, as the teacher noted) |
| `normal` | Normal(μ, σ²) truncated to [0, T] | μ = T/2, σ = T/6 | midday peak |
| `gamma` | Gamma(α, β) truncated to [0, T] | α = 2, scale 1/β = 120 min | rush at opening, long thinning tail |
| `beta` | T · Beta(α, β) | α = 2, β = 3 | bounded profile that peaks early; other shapes by changing α, β |

Truncation is done by rejection sampling (or `scipy.stats.truncnorm` for the normal). Truncation alters the mean and variance relative to the untruncated formulas, so the moment checks in 7.1 use the truncated values.

If the INEGI data arrives, the profile and its parameters are chosen by overlaying kernel density estimates of real arrival data on candidate densities, which is the teacher's own method, and by maximum-likelihood fits.

### 5.2 Collisions and priority

After quantization, two or more voters may share the same arrival tick. This is the "collision" from class. They are admitted in priority order **[Class]**:

1. `is_senior` before not senior.
2. Among equals, `mobility_limited` before not.
3. Among equals, uniformly random order (or lowest id; configurable).

**[Proposed]** Create 3 more conditions for the priority.

Each resolution produces a `collision_resolved` event, and the number of collisions is a reported metric. Priority applies only to simultaneous arrivals, as in the lecture. Whether priority should also apply inside the queues is a model extension, not in the first demo.

How often collisions occur depends on resolution: for 200 voters spread flat over 600 one-minute slots, the expected number of coinciding pairs is C(200,2)/600 ≈ 33, while at one-second resolution it is below 1 per day. The default resolution of 60 s keeps collisions meaningful.

Attribute probabilities: `p_senior = 0.15`, `p_mobility_limited = 0.05` **[Placeholder]**.

### 5.3 Service times

Each stage has a configurable distribution; the default reproduces the baseline.

| Stage | Baseline | Alternative worth testing |
|---|---|---|
| Verification | discrete uniform {2..7} min **[Baseline]** | Gamma (positive, right-skewed) |
| Booth | discrete uniform {3..9} min **[Baseline]** | Gamma or truncated Normal |
| Urn | discrete uniform {4..10} min **[Baseline]** | Uniform(0.25, 1.0) min **[Proposed]** (see below) |

**Urn saturation warning.** With the baseline numbers the urn receives about 0.32 voters/min and serves 1/7 per min, so its utilization is about 2.3. Eight baseline runs showed the last voter leaving between minute 1045 and 1240, although arrivals end near minute 500. Depositing a ballot is physically a matter of seconds, so the 4–10 minute urn time likely models something else (or is a placeholder). The spec therefore defines two urn settings: `baseline` (reproduces the core simulation) and `ballot_deposit` (a short uniform time). The team should decide which is the main scenario. **[Open]**

Verifier choice when several are free: `first_free` (baseline), `random_free`, or voter-chosen (the baseline comment says students may let the voter decide) **[Baseline]**.

### 5.4 Abandonment **[Baseline]**

Decided once, on arrival, using the verification queue length ℓ: probability 0.10 if ℓ < 0.20·N, 0.40 if ℓ < 0.40·N, else 0.80. Abandoned voters leave immediately with outcome `abandoned`. The thresholds scale with N in the baseline; whether to keep that or switch to absolute queue sizes is open. Re-evaluating abandonment in later queues is an extension (and would also mitigate the urn queue).

### 5.5 Document validity **[Baseline]**

`doc_valid ~ Bernoulli(0.90)`. The baseline checks it when the voter is called to a booth; an invalid voter leaves without using the booth. Moving the check to the verification stage is a candidate fix. **[Open]**

### 5.6 Vote model and estimator **[Class]**

When a voter starts at the urn, X_i ~ Bernoulli(p_A) with X_i = 1 meaning party A ("Rojo") and 0 meaning party B ("Azul"). The baseline corresponds to p_A = 0.5. The configured p_A is the ground truth that the estimator tries to recover, which makes the demo a controlled experiment: the team can check that p̂ converges to p_A as the number of voters grows.

## 6. Metrics and outputs

The set below is the team's choice. It includes the baseline outputs plus the statistical outputs from the class.

### 6.1 Per voter

Wait time and service time at each stage, total time in the station T_i = exit − arrival, and outcome.

### 6.2 Per run

| Metric | Definition |
|---|---|
| Mean, median, P90 time in station | over voters with outcome `voted` (also over all voters, to compare with the baseline's average) |
| Outcome rates | share of `voted`, `abandoned`, `invalid_document` |
| Mean and maximum wait per stage | wait before verification, booth, urn |
| Queue length | maximum and time-averaged length per stage |
| Utilization ρ per resource | busy time / (servers × observed time) |
| Throughput | voters completed per hour, and per hour of the day (a turnout profile) |
| Overrun | last exit time − T (zero when the station copes; large when saturated) |
| Collisions | number of tied arrivals and priority resolutions |
| Little's law check | L̄ ≈ λ_eff · W̄ per stage (7.3) |

### 6.3 Election result

With n = votes cast and n_A the votes for A: p̂ = n_A / n (the sample proportion estimator), standard error SE = √(p̂(1−p̂)/n), and a 95% confidence interval p̂ ± 1.96·SE (normal approximation, justified by the central limit theorem). Winner = party with more votes, with an explicit tie rule. Optional test of H0: p = 0.5 with z = (p̂ − 0.5)/√(0.25/n). Abandoned and invalid-document voters do not vote.

The tally is revealed only at station closing by default (`reveal_tally: at_close`), mimicking the real process.

### 6.4 Diagnostics (for validation and charts)

The sample of inter-arrival gaps and arrival instants, as a density-normalized histogram with the kernel density estimate and the theoretical density overlaid.

## 7. Validation and experiments

### 7.1 Distribution checks (unit tests)

For every configured density: it is non-negative and numerically integrates to 1 over its support (the two conditions from class); sample mean and variance of a large draw match the formulas (for the uniform, (a+b)/2 and (b−a)²/12) within tolerance; and the kernel density estimate of a large sample is visually and numerically close to the theoretical density (for example a Kolmogorov–Smirnov test).

### 7.2 Replication (Monte Carlo)

Run R independent replications (R between 30 and 100, to be tuned) with different seeds, and report the mean and a normal-approximation 95% interval for each metric. A single run is a demo; the replicated results are the evidence.

### 7.3 Internal consistency

Voters are conserved (arrived = voted + abandoned + invalid + inside at the check time, and zero inside at the end). Little's law holds for each stage within sampling error. Time never goes backward, and no resource serves more than its capacity.

### 7.4 Baseline regression

The scenario `S0_baseline` must reproduce the core simulation's statistics (mean time in station, abandonment and invalid rates, overrun) within the replication intervals. Exact equality is not expected because random streams differ.

### 7.5 Scenario set

| Scenario | Arrivals | Urn | Purpose |
|---|---|---|---|
| S0 baseline | `interarrival`, uniform {1..4} min | baseline 4–10 min | regression against the core code |
| S1 flat day | `instants`, uniform | ballot_deposit | reference without peaks |
| S2 midday peak | `instants`, normal | ballot_deposit | bell-shaped demand |
| S3 opening rush | `instants`, gamma | ballot_deposit | front-loaded demand; most stress on verification |
| S4 beta profile | `instants`, beta | ballot_deposit | flexible bounded profile |
| S5 capacity sweep | best of S1–S4 | ballot_deposit | vary verifiers (1–5) and booths (1–4) to find the smallest staffing without overrun, the resource-estimation question from the first lecture |

## 8. Software architecture

### 8.1 Overall flow

Adopts the course slide's suggestion. Mesa model → serializer → Flask API → (HTTP) → Unity HTTP client → state manager → GameObjects → render. Models are authored in Blender and imported into Unity as FBX/OBJ.

### 8.2 Mesa model

Mesa advances in steps, while the baseline is event-driven. This spec proposes a time-stepped model with 1 tick = 1 s, in which each voter or verifier holds a countdown and only does work when it expires or when it is being served, so the per-tick cost stays small even over 36,000 ticks. Order within a tick, fixed for determinism: (1) service completions, (2) arrivals scheduled for this tick with collision resolution and abandonment decision, (3) assignment of waiting voters to free resources, (4) event logging and metric sampling. A time-stepped design makes "two arrivals in the same tick" a natural collision. The alternative, keeping the `heapq` core and advancing it to a target clock inside each Mesa step, preserves the baseline exactly but fits Mesa less naturally. **[Open, decide before coding]** Pin the Mesa version in `requirements.txt`, since the API changed between major versions.

Suggested modules: `config.py` (dataclasses and YAML loading), `distributions.py` (a wrapper over numpy/scipy with density, sampler and moments, plus tests), `agents.py`, `model.py`, `metrics.py`, `api.py`, `experiments.py` (replications and scenarios), `tests/`.

R-to-Python equivalents for porting the lab code: `runif` → `rng.uniform`, `rnorm` → `rng.normal`, `rgamma(shape, rate)` → `rng.gamma(shape, 1/rate)` (numpy and scipy use a scale, which is 1/β), `rbeta` → `rng.beta`, `hist(freq=FALSE)` → `plt.hist(density=True)`, `density()` → `scipy.stats.gaussian_kde`.

### 8.3 Positions

Mesa reports logical locations only (which queue and slot index, or which resource id) and does not compute 3D coordinates. Unity maps those to world positions and animates the movement. This keeps the model independent of the scene layout and lets artists change the layout without touching Python.

### 8.4 REST API (Flask) **[Proposed]**

| Endpoint | Purpose |
|---|---|
| `POST /sim/reset` | body: scenario name or full config and seed; builds a new model |
| `POST /sim/step` | body: `{ticks: k}`; advances k ticks; returns the new clock |
| `GET /sim/state` | full snapshot (below) |
| `GET /sim/events?since=<seq>` | all events with sequence number greater than `since` |
| `GET /sim/metrics` | current aggregates; includes the result summary once the station has closed |
| `GET /sim/config` | active configuration |

Who drives the clock: the simplest option is Unity calling `POST /sim/step` at a rate set by the speed control, which is deterministic and single-threaded. The slide's GET-only polling is also possible if the server advances time itself with a background thread, at the cost of locking. The `events?since=` endpoint exists so that a polling client cannot miss transient changes, which satisfies the baseline requirement that every event reach Unity. **[Open, team decision]**

Snapshot shape (illustrative):

```json
{
  "clock_s": 5400, "open": true, "seq": 1432,
  "queues": {"verification": [12, 15], "booth": [9], "urn": []},
  "resources": {
    "verifiers": [{"id": 0, "state": "busy", "voter": 7}, ...],
    "booths":    [{"id": 0, "state": "busy", "voter": 3}, ...],
    "urn":       [{"id": 0, "state": "idle", "voter": null}]
  },
  "voters": [
    {"id": 7, "state": "VERIFICANDO", "location": {"zone": "verifier", "index": 0},
     "senior": false, "mobility_limited": false}
  ],
  "counters": {"arrived": 41, "voted": 22, "abandoned": 3, "invalid": 2}
}
```

Events carry `seq`, `t`, `type`, `voter_id` and the resource when relevant. Types: `arrival`, `collision_resolved`, `abandon`, `start_verification`, `end_verification`, `invalid_document`, `start_booth`, `end_booth`, `start_urn`, `end_urn`, `exit`, `close`. The API never includes an individual's vote.

### 8.5 Unity (3D) **[Proposed]**

- **Scene:** entrance, queue area, three verifier tables, booth queue area, two booths, the urn, exit. Models from Blender.
- **Voter visuals:** a capsule or simple character per voter, colored by state, with distinct markers for seniors and mobility-limited voters. Movement is interpolated between logical locations, so low API polling rates still look smooth.
- **Controls:** pause/resume, speed (simulated seconds per real second), reset with scenario and seed.
- **HUD:** simulated clock (time of day), queue lengths, running counters (arrived, voted, abandoned, invalid), resource utilization.
- **End of day panel:** tally, p̂ with its confidence interval, mean time in station, overrun. Optional chart of the arrival histogram with its kernel density estimate.
- **Failure handling:** if the API is unreachable the scene shows a banner and retries; the client never assumes state it has not received.

## 9. Default configuration (illustrative)

```yaml
seed: 12345
time:
  tick_seconds: 1
  open_duration_min: 600          # placeholder, assumed 08:00-18:00
  arrival_resolution_s: 60
voters:
  n: 200
  p_senior: 0.15                  # placeholder
  p_mobility_limited: 0.05        # placeholder
  p_doc_valid: 0.90               # baseline
  p_vote_A: 0.50                  # baseline (uniform choice)
priority_tiebreak: random         # random | id
arrivals:
  mode: instants                  # instants | interarrival
  dist: gamma                     # uniform | normal | gamma | beta
  params: {alpha: 2.0, scale_min: 120}
resources:
  verifiers: {count: 3, choice: first_free,
              service: {dist: uniform_int, min: 2, max: 7, unit: min}}
  booths:    {count: 2, service: {dist: uniform_int, min: 3, max: 9, unit: min}}
  urn:       {count: 1, service: {dist: uniform, min: 0.25, max: 1.0, unit: min}}
abandonment:
  rule: queue_fraction            # baseline thresholds as fractions of n
  thresholds: [0.20, 0.40]
  probabilities: [0.10, 0.40, 0.80]
reveal_tally: at_close
```

## 10. Minimum demo versus extensions

**Minimum demo:** voters, the three-stage flow, one arrival profile selectable among the four, priority on collisions, the baseline abandonment and document rules, metrics 6.2 and 6.3 for a single run, the API of 8.4, a Unity scene with the HUD and end-of-day panel.

**Extensions:** replication runner and scenario comparison in the UI, kernel-density chart in Unity, verifier agents with their own behavior (breaks), per-verifier queues versus a single shared queue (the classic queueing-theory comparison), abandonment in every queue, exponential/Poisson arrivals and service once the queueing lectures arrive, calibration from the INEGI data, an irregularity-detection module (first-lecture motivation), several stations.

## 11. Open decisions

1. Urn model: baseline (4–10 min, saturated) or `ballot_deposit`. This also decides whether the main demo is a saturated or a healthy station.
2. Time-stepped Mesa port or hybrid with the existing `heapq` core (8.2).
3. Which agents beyond voters (verifier agents proposed).
4. Clock driver: Unity-driven `POST /sim/step` or server-driven with GET-only polling (8.4).
5. Default arrival profile for the main demo and whether the INEGI data becomes available.
6. Placeholders to calibrate: T, `p_senior`, `p_mobility_limited`, gamma and beta parameters, abandonment thresholds.
7. Confirm with the teacher that the deliverable is a demo and whether anything beyond it is graded.
