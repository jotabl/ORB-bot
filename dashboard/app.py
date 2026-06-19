"""
Dashboard Flask — ORB Bot BTCUSDT.P
Acceso: http://localhost:5000
"""

import sqlite3, json, os
from flask import Flask, render_template, jsonify

DB_PATH = os.path.join(os.path.dirname(__file__), "..", "trades.db")

app = Flask(__name__)


def get_db():
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    return con


def query(sql, params=()):
    con = get_db()
    rows = con.execute(sql, params).fetchall()
    con.close()
    return [dict(r) for r in rows]


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/trades")
def api_trades():
    trades = query("SELECT * FROM trades ORDER BY id DESC")
    return jsonify(trades)


@app.route("/api/metrics")
def api_metrics():
    all_t  = query("SELECT * FROM trades WHERE result IN ('TP','SL') ORDER BY id")
    if not all_t:
        return jsonify({"total": 0})

    total  = len(all_t)
    wins   = sum(1 for t in all_t if t["result"] == "TP")
    losses = total - wins
    wr     = round(wins / total * 100, 1)
    total_r   = round(sum(t["pnl_r"] or 0 for t in all_t), 2)
    total_pnl = round(sum(t["pnl_usdt"] or 0 for t in all_t), 2)
    avg_r     = round(total_r / total, 3)
    ev        = round(wins / total * 2 - losses / total * 1, 3)

    # Max drawdown en R
    eq, peak, max_dd = 0.0, 0.0, 0.0
    for t in all_t:
        eq += t["pnl_r"] or 0
        peak = max(peak, eq)
        max_dd = max(max_dd, peak - eq)

    # Equity curve
    equity_curve = []
    for t in all_t:
        equity_curve.append({"date": t["date"], "equity": t["equity"]})

    # LONG vs SHORT
    longs  = [t for t in all_t if t["direction"] == "LONG"]
    shorts = [t for t in all_t if t["direction"] == "SHORT"]
    long_wr  = round(sum(1 for t in longs  if t["result"] == "TP") / len(longs)  * 100, 1) if longs  else 0
    short_wr = round(sum(1 for t in shorts if t["result"] == "TP") / len(shorts) * 100, 1) if shorts else 0

    current_equity = query(
        "SELECT equity FROM trades WHERE result != 'OPEN' ORDER BY id DESC LIMIT 1"
    )
    equity_now = current_equity[0]["equity"] if current_equity else 1000.0

    return jsonify({
        "total": total, "wins": wins, "losses": losses,
        "wr": wr, "total_r": total_r, "total_pnl": total_pnl,
        "avg_r": avg_r, "ev": ev, "max_dd_r": round(max_dd, 2),
        "long_wr": long_wr, "short_wr": short_wr,
        "equity": equity_now,
        "equity_curve": equity_curve,
    })


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
