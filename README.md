# 🍳 Restaurant Kitchen Order Scheduler — Problem 81

A production-grade prototype that sequences restaurant kitchen tickets using
**priority queues (`heapq`)**, **greedy job sequencing**, and a fully transparent
**decision log**.

**Stack:** Python 3.9+ / Flask (backend algorithms) · React 18 + Vite + Tailwind CSS (dashboard)

---

## ⚡ Quick start (2 commands)

```bash
pip install -r requirements.txt
python app.py
```

Then open **<http://localhost:5000>** — the Flask server serves both the API and the React UI,
so there is only **one** process and **one** port.

> The pre-built React bundle is already committed in `static/`.
> You only need Node.js if you want to *edit* the frontend (see below).

---

## 📁 Project structure

```
.
├── app.py                    # Flask app: REST API + serves the React build
├── requirements.txt          # Flask, flask-cors   (that's it)
├── test_scheduler.py         # 24 self-tests:  python test_scheduler.py
├── run.sh / run.bat          # optional one-click launchers
│
├── scheduler/                # ← all the algorithms live here (stdlib only)
│   ├── __init__.py
│   ├── models.py             # Order dataclass + validation + sample data
│   ├── strategies.py         # the 5 scheduling rules & the ATC scoring formula
│   ├── queueing.py           # heapq priority queue with lazy deletion
│   └── engine.py             # greedy sequencer + metrics + decision-log builder
│
├── static/                   # ← React production build (served by Flask)
│   ├── index.html
│   └── assets/
│
└── frontend/                 # React + Vite + Tailwind source
    ├── package.json
    ├── vite.config.js        # build output -> ../static ; /api proxy -> :5000
    ├── tailwind.config.js
    ├── postcss.config.js
    ├── index.html
    └── src/
        ├── main.jsx
        ├── App.jsx
        ├── api.js
        ├── helpers.js
        ├── index.css
        └── components/
            ├── OrderForm.jsx         # add / edit orders
            ├── OrderTable.jsx        # list, edit, delete, load sample
            ├── StrategySelector.jsx  # strategy dropdown + K slider
            ├── MetricsBar.jsx        # KPI cards
            ├── Timeline.jsx          # Gantt chart + slot table
            ├── DecisionTrace.jsx     # expandable audit trail
            └── ComparePanel.jsx      # all-strategies cost comparison
```

---

## 🧠 The algorithms

### The model

The kitchen is a **single non-preemptive machine**:

* the clock starts at `t = 0`, every ticket is available immediately
* exactly one dish cooks at a time; once started it runs to completion

For an order `j`:

| symbol | meaning |
| --- | --- |
| `pⱼ` | `prep_time` — minutes of cooking work |
| `dⱼ` | `promised_time` — delivery deadline, minutes from `t = 0` |
| `wⱼ` | `urgency` — 1–5 (5 = VIP) |
| `Cⱼ` | completion time → `Cⱼ = start + pⱼ` |
| `Tⱼ` | tardiness → `Tⱼ = max(0, Cⱼ − dⱼ)` |

### 1. Priority Queue Engine — `scheduler/queueing.py`

`heapq` gives O(log n) push/pop but cannot **re-prioritise** an existing entry —
which the dynamic rule needs every tick, because scores change as the clock moves.
The fix is **lazy deletion with a generation counter**:

* each tick bumps `self.generation`
* every pushed entry is stamped with its birth generation
* `pop()` silently discards entries whose generation is stale

Invalidating the whole queue is therefore **O(1)** instead of rebuilding it, and every
mutation becomes auditable (the trace panel shows live vs. physical heap entries).

### 2. Greedy Job Sequencing — `scheduler/engine.py`

At each tick: pick the locally best remaining ticket → commit it to the timeline →
advance the clock by its prep time → repeat. Greedy is a heuristic (1‖ΣwT is NP-hard),
which is exactly why several rules are shipped and every choice is logged.

### 3. The strategies — `scheduler/strategies.py`

| key | rule | priority function | dynamic? |
| --- | --- | --- | --- |
| `greedy_min_delay` | **Greedy Min-Delay (ATC)** | `(urgency / prep_time) × exp(−max(0, slack) / (K × avg_prep))` | ✅ rescored every tick |
| `edf` | Earliest Deadline First | `promised_time` ascending | ❌ |
| `huf` | Highest Urgency First | `−urgency`, then deadline | ❌ |
| `spt` | Shortest Prep Time First | `prep_time` ascending | ❌ |
| `fifo` | First In First Out (baseline) | input position | ❌ |

**Greedy Min-Delay** is an **Apparent Tardiness Cost (ATC)** composite rule:

```
slack           = promised_time − prep_time − now
urgency_ratio   = urgency / prep_time            ← urgency vs. the prep-time penalty
deadline_factor = exp( −max(0, slack) / (K × avg_prep) )
score           = urgency_ratio × deadline_factor      ← higher wins
```

* `urgency / prep_time` — a 5-star dish that takes 5 min beats a 5-star dish that takes
  30 min, because it unblocks the station sooner.
* the exponential term — tickets with lots of slack are exponentially deprioritised.
  Once `slack ≤ 0` (the ticket is already at risk) it saturates at `1.0` and only the
  raw urgency ratio matters.
* `K` (default **1.5**) is the look-ahead constant, tunable with a slider in the UI.
  Low `K` → aggressive / ratio-dominated. High `K` → gentler discount, closer to EDF.

All ties break deterministically by `(promised_time, prep_time, id)`, so identical input
always yields byte-identical output.

### 4. Cost function (what "minimise" means)

```
cost = Σ ( delayⱼ × urgencyⱼ )  +  10 × (number of late orders)
```

Urgency-weighted minutes late, plus a flat penalty per missed promise so the optimiser
can't buy a 30-second win by sacrificing a VIP table.

### 5. Explainability — the `decision_log`

Every step returns: queue mutation (build / reuse / recompute + generation), a ranked
candidate table with the full arithmetic per ticket, the chosen order, the runner-up,
a plain-English rationale, and the running metrics. Example:

> *Picked #2 Butter Chicken: urgency ratio 5/18 = 0.278 × deadline factor 1.000 =
> score 0.278; already at risk (slack ≤ 0). Its urgency ratio outperformed its
> prep-time penalty versus runner-up #5 Garlic Bread.*

---

## 🌐 REST API

| Method | Endpoint | Body | Returns |
| --- | --- | --- | --- |
| `GET` | `/api/health` | – | service status |
| `GET` | `/api/strategies` | – | strategy list + priority formulas |
| `GET` | `/api/sample-data` | – | default list of test kitchen orders |
| `POST` | `/api/schedule` | `{ "orders": [...], "strategy": "...", "k": 1.5 }` | timeline + metrics + `decision_log` |
| `POST` | `/api/compare` | `{ "orders": [...] }` | every strategy ranked by cumulative cost |

### Order schema

```json
{ "id": 1, "name": "Butter Chicken", "prep_time": 18, "urgency": 5, "promised_time": 53 }
```

* `prep_time` — integer, `> 0`
* `urgency` — integer `1`–`5`
* `promised_time` — integer `≥ 0`, minutes from kitchen `t = 0`

Invalid input returns `HTTP 400` with a precise `errors[]` list.

### curl examples

```bash
curl http://localhost:5000/api/sample-data

curl -X POST http://localhost:5000/api/schedule \
     -H "Content-Type: application/json" \
     -d '{"strategy":"greedy_min_delay",
          "orders":[{"id":1,"name":"Pizza","prep_time":12,"urgency":3,"promised_time":40},
                    {"id":2,"name":"Biryani","prep_time":22,"urgency":5,"promised_time":43}]}'

curl -X POST http://localhost:5000/api/compare \
     -H "Content-Type: application/json" \
     -d '{"orders":[{"id":1,"name":"Pizza","prep_time":12,"urgency":3,"promised_time":40}]}'
```

---

## 💻 Working on the frontend (optional)

You only need Node.js ≥ 18 to **modify** the UI. For a live-reloading dev server
run **both** processes:

```bash
# terminal 1 — API on :5000
python app.py

# terminal 2 — Vite dev server on :5173 (proxies /api -> :5000)
cd frontend
npm install
npm run dev
```

Open **<http://localhost:5173>**.

After editing, refresh the production bundle:

```bash
cd frontend && npm run build     # writes into ../static
```

---

## ✅ Running the tests

```bash
python test_scheduler.py
```

24 tests covering the `Order` model & validation, heapq lazy deletion, ATC scoring,
timeline contiguity, delay arithmetic, determinism, decision-log shape, and metric math.

---

## 🔧 Troubleshooting

| Problem | Fix |
| --- | --- |
| `ModuleNotFoundError: flask` | `pip install -r requirements.txt` (use `python3`/`pip3` on macOS/Linux) |
| Port 5000 already in use | `PORT=5050 python app.py` (`set PORT=5050 && python app.py` on Windows) |
| UI shows the plain API page | The React build is missing → `cd frontend && npm install && npm run build` |
| `Cannot reach the Flask server` | Start the backend, or run `npm run dev` **and** `python app.py` together |
| Auto-reload bothering you | `FLASK_DEBUG=0 python app.py` |

---

## 📊 Sample result (8 tickets, 87 min of work)

| strategy | total delay | on-time | late | **cost** |
| --- | --- | --- | --- | --- |
| ★ Greedy Min-Delay (ATC, K=1.5) | 69 m | **75.0 %** | 2 | **315** |
| Shortest Prep Time First | 65 m | 62.5 % | 3 | 346 |
| Earliest Deadline First | 67 m | 62.5 % | 3 | 351 |
| First In First Out | 240 m | 25.0 % | 6 | 625 |
| Highest Urgency First | 300 m | 25.0 % | 6 | 626 |

The greedy rule trades 2 minutes of raw delay for 12.5 percentage points more on-time
deliveries and the lowest urgency-weighted cost — exactly the behaviour the ATC formula
is designed to produce.
