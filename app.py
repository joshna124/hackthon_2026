"""
=========================================================================
 Problem 81 - Restaurant Kitchen Order Scheduler
 Flask API + React SPA host
=========================================================================

 Run it:
     pip install -r requirements.txt
     python app.py
     ->  http://localhost:5000

 The React frontend is optional for the API: with no build present the app
 still serves a minimal landing page at "/" that links to the raw JSON
 endpoints, so the backend can be tested on its own.
"""

from __future__ import annotations

import os
import traceback
from typing import Any, Dict

from flask import Flask, jsonify, request, send_from_directory

from scheduler import __version__
from scheduler.engine import compare_strategies, schedule_orders
from scheduler.models import SAMPLE_ORDERS, Order, ValidationError, parse_orders
from scheduler.strategies import STRATEGIES, DEFAULT_STRATEGY

# ---------------------------------------------------------------------- #
# app setup
# ---------------------------------------------------------------------- #
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STATIC_DIR = os.path.join(BASE_DIR, "static")          # Vite build output lives here

# static_folder=None: we serve the Vite build ourselves so Flask's built-in
# `/<path:filename>` static rule cannot shadow our SPA catch-all route.
app = Flask(__name__, static_folder=None)
app.config["JSON_SORT_KEYS"] = False


def _error(message: str, status: int = 400, **extra: Any):
    payload: Dict[str, Any] = {"ok": False, "error": message}
    payload.update(extra)
    return jsonify(payload), status


# ---------------------------------------------------------------------- #
# API
# ---------------------------------------------------------------------- #
def _static_or_spa(path: str):
    """Serve a real file from ./static when it exists, else fall back to index.html."""
    candidate = os.path.normpath(os.path.join(STATIC_DIR, path))
    if candidate.startswith(STATIC_DIR) and os.path.isfile(candidate):
        return send_from_directory(STATIC_DIR, path)
    index_path = os.path.join(STATIC_DIR, "index.html")
    if os.path.isfile(index_path):
        return send_from_directory(STATIC_DIR, "index.html")
    return FALLBACK_PAGE


@app.get("/api/health")
def health():
    return jsonify({"ok": True, "service": "kitchen-scheduler", "version": __version__})


@app.get("/api/strategies")
def strategies():
    return jsonify(
        {
            "ok": True,
            "default": DEFAULT_STRATEGY,
            "strategies": [
                {
                    "key": s.key,
                    "label": s.label,
                    "blurb": s.blurb,
                    "formula": s.formula,
                    "dynamic": s.dynamic,
                }
                for s in STRATEGIES
            ],
        }
    )


@app.get("/api/sample-data")
def sample_data():
    """Default JSON list of test kitchen orders."""
    return jsonify(
        {
            "ok": True,
            "orders": [Order.from_dict(o).to_dict() for o in SAMPLE_ORDERS],
            "note": (
                "Times are minutes from kitchen t=0. promised_time is the delivery "
                "deadline, urgency is 1-5 (5 = VIP)."
            ),
        }
    )


@app.post("/api/schedule")
def schedule():
    """
    Body:  { "orders": [ {...}, ... ], "strategy": "greedy_min_delay" }
    Runs the Python optimisation pipeline and returns the timeline + audit trail.
    """
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return _error("Request body must be JSON: {'orders': [...], 'strategy': '...'}")

    try:
        orders = parse_orders(payload.get("orders"))
    except ValidationError as exc:
        return _error("Invalid order data.", errors=exc.errors)

    strategy_key = payload.get("strategy") or DEFAULT_STRATEGY

    # Optional look-ahead constant K for the ATC (greedy) rule.
    raw_k = payload.get("k")
    lookahead = None
    if raw_k is not None:
        try:
            lookahead = float(raw_k)
        except (TypeError, ValueError):
            return _error("'k' must be a number.")
        if not 0.05 <= lookahead <= 50:
            return _error("'k' must be between 0.05 and 50.")

    try:
        result = schedule_orders(orders, strategy_key, k=lookahead)
    except ValidationError as exc:
        return _error("Invalid order data.", errors=exc.errors)
    except Exception:  # pragma: no cover - unexpected
        app.logger.error(traceback.format_exc())
        return _error("Scheduling failed on the server.", status=500)

    return jsonify({"ok": True, **result.to_dict()})


@app.post("/api/compare")
def compare():
    """
    Body:  { "orders": [ ... ] }
    Runs every strategy and ranks them by cumulative urgency-weighted cost.
    """
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return _error("Request body must be JSON: {'orders': [...]}")

    try:
        orders = parse_orders(payload.get("orders"))
    except ValidationError as exc:
        return _error("Invalid order data.", errors=exc.errors)

    try:
        return jsonify({"ok": True, **compare_strategies(orders)})
    except Exception:  # pragma: no cover
        app.logger.error(traceback.format_exc())
        return _error("Comparison failed on the server.", status=500)


# ---------------------------------------------------------------------- #
# frontend hosting (React build in ./static)
# ---------------------------------------------------------------------- #
@app.get("/")
def index():
    return _static_or_spa("index.html")


@app.get("/assets/<path:filename>")
def assets(filename):
    """Vite emits hashed bundles under static/assets/."""
    return send_from_directory(os.path.join(STATIC_DIR, "assets"), filename)


@app.get("/<path:path>")
def spa_fallback(path):
    """Let React Router (or any deep link / hard refresh) resolve client-side."""
    if path.startswith("api/"):
        return _error(f"Unknown API endpoint: /{path}", status=404)
    return _static_or_spa(path)


@app.errorhandler(404)
def not_found(_e):
    return _error("Not found.", status=404)


# ---------------------------------------------------------------------- #
FALLBACK_PAGE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<title>Kitchen Scheduler API</title>
<style>
  body{font-family:ui-sans-serif,system-ui,sans-serif;background:#0b1120;color:#e2e8f0;
       margin:0;padding:48px;line-height:1.6}
  code{background:#1e293b;padding:2px 6px;border-radius:4px;color:#7dd3fc}
  a{color:#38bdf8}
  .card{background:#111827;border:1px solid #1f2937;border-radius:12px;padding:24px;max-width:760px}
</style></head><body>
<div class="card">
  <h1>&#127858; Kitchen Order Scheduler &mdash; API is running</h1>
  <p>The React build was not found in <code>./static</code>. The API works fine on its own:</p>
  <ul>
    <li><a href="/api/sample-data">GET /api/sample-data</a></li>
    <li><a href="/api/strategies">GET /api/strategies</a></li>
    <li><code>POST /api/schedule</code> &nbsp;{ orders, strategy }</li>
    <li><code>POST /api/compare</code> &nbsp;{ orders }</li>
  </ul>
  <p>To build the UI: <code>cd frontend &amp;&amp; npm install &amp;&amp; npm run build</code>,
     then reload this page.</p>
</div></body></html>"""


# ---------------------------------------------------------------------- #
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    debug = os.environ.get("FLASK_DEBUG", "1") == "1"
    print("=" * 62)
    print("  Restaurant Kitchen Order Scheduler")
    print(f"  API      ->  http://localhost:{port}/api/sample-data")
    print(f"  Frontend ->  http://localhost:{port}")
    print("=" * 62)
    app.run(host="0.0.0.0", port=port, debug=debug)
