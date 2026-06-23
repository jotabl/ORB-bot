"""
Grid search vectorizado — ORB BTCUSDT.P OKX.
Encuentra combinaciones con WR > 50%.
"""

import itertools
import pandas as pd
import numpy as np
import pytz
from data_fetcher import fetch_candles, to_ny_time

NY_OPEN_HOUR, NY_OPEN_MINUTE = 9, 30
NY_CLOSE_HOUR, NY_CLOSE_MINUTE = 10, 30


# ---------------------------------------------------------------------------
# Pre-procesa todos los días de una vez
# ---------------------------------------------------------------------------

def build_daily_cache(df: pd.DataFrame) -> dict:
    """Para cada día NY, precalcula ORB stats y Gann Box."""
    cache = {}
    days = sorted(df["ts_ny"].dt.date.unique())

    for day in days:
        d_mask = df["ts_ny"].dt.date == day
        before = (df["ts_ny"].dt.hour < NY_OPEN_HOUR) | (
            (df["ts_ny"].dt.hour == NY_OPEN_HOUR) & (df["ts_ny"].dt.minute < NY_OPEN_MINUTE)
        )
        after = (df["ts_ny"].dt.hour > NY_OPEN_HOUR) | (
            (df["ts_ny"].dt.hour == NY_OPEN_HOUR) & (df["ts_ny"].dt.minute >= NY_OPEN_MINUTE)
        )
        before_close = (df["ts_ny"].dt.hour < NY_CLOSE_HOUR) | (
            (df["ts_ny"].dt.hour == NY_CLOSE_HOUR) & (df["ts_ny"].dt.minute <= NY_CLOSE_MINUTE)
        )

        pre   = df[d_mask & before].reset_index(drop=True)
        sess  = df[d_mask & after & before_close].reset_index(drop=True)

        # Gann Box: pre-NY del mismo día
        gb = {}
        if len(pre) >= 10:
            gh = pre["high"].max()
            gl = pre["low"].min()
            if gh > gl:
                gb = {"high": gh, "low": gl, "range": gh - gl}

        cache[day] = {"pre": pre, "sess": sess, "gb": gb}

    return cache


def simulate_outcomes(sess_future: pd.DataFrame, direction: str, entry: float,
                       sl: float, tp: float):
    """Vectorizado: recorre velas buscando SL o TP."""
    for _, row in sess_future.iterrows():
        if direction == "LONG":
            if row["low"] <= sl:
                return "SL", -1.0
            if row["high"] >= tp:
                return "TP", round((tp - entry) / (entry - sl), 3)
        else:
            if row["high"] >= sl:
                return "SL", -1.0
            if row["low"] <= tp:
                return "TP", round((entry - tp) / (sl - entry), 3)
    return "OPEN", 0.0


def run_combo(cache, days, orb_candles, orb_min_range, skip_middle, zone_pct, tp_rr):
    results = []
    for day in days:
        c = cache[day]
        sess = c["sess"]
        gb   = c["gb"]

        if len(sess) < orb_candles + 2:
            continue

        init      = sess.iloc[:orb_candles]
        orb_h     = init["high"].max()
        orb_l     = init["low"].min()
        orb_range = orb_h - orb_l
        midpoint  = (orb_h + orb_l) / 2

        if orb_range < orb_min_range:
            continue

        # Gann filter
        if gb:
            rng = gb["range"]
            pos = (gb["high"] - midpoint) / rng  # 0=top, 1=bottom
            if pos <= zone_pct:
                allowed = ["LONG"]
            elif pos >= (1 - zone_pct):
                allowed = ["SHORT"]
            else:
                allowed = [] if skip_middle else ["LONG", "SHORT"]
        else:
            allowed = [] if skip_middle else ["LONG", "SHORT"]

        if not allowed:
            continue

        # Buscar señal
        trade = None
        pend_long = pend_short = False

        for i in range(orb_candles, len(sess)):
            row     = sess.iloc[i]
            c_range = row["high"] - row["low"]
            close   = row["close"]

            if pend_long:
                if row["low"] <= orb_h and close > orb_h:
                    sd = close - midpoint
                    if sd > 0:
                        trade = ("LONG", close, midpoint, close + sd * tp_rr, sd, i)
                        break
                if close < midpoint:
                    pend_long = False

            if pend_short:
                if row["high"] >= orb_l and close < orb_l:
                    sd = midpoint - close
                    if sd > 0:
                        trade = ("SHORT", close, midpoint, close - sd * tp_rr, sd, i)
                        break
                if close > midpoint:
                    pend_short = False

            if close > orb_h and "LONG" in allowed:
                if c_range > orb_range:
                    pend_long = True
                    continue
                sd = close - midpoint
                if sd > 0:
                    trade = ("LONG", close, midpoint, close + sd * tp_rr, sd, i)
                    break

            if close < orb_l and "SHORT" in allowed:
                if c_range > orb_range:
                    pend_short = True
                    continue
                sd = midpoint - close
                if sd > 0:
                    trade = ("SHORT", close, midpoint, close - sd * tp_rr, sd, i)
                    break

        if not trade:
            continue

        direction, entry, sl, tp, sd, idx = trade
        future = sess.iloc[idx + 1:]
        outcome, pnl_r = simulate_outcomes(future, direction, entry, sl, tp)
        results.append({"direction": direction, "result": outcome, "pnl_r": pnl_r, "date": str(day)})

    return results


# ---------------------------------------------------------------------------
# Grid search
# ---------------------------------------------------------------------------

PARAM_GRID = {
    "orb_candles":   [3, 5, 7],
    "orb_min_range": [50, 100, 150, 200, 300],
    "skip_middle":   [True, False],
    "zone_pct":      [0.20, 0.25, 0.33],
    "tp_rr":         [1.5, 2.0, 3.0],
}


if __name__ == "__main__":
    print("Descargando datos (90 días)...")
    df = fetch_candles(bar="1m", days=90)
    df = to_ny_time(df)
    print(f"  {len(df):,} velas ({df['ts_ny'].min().date()} → {df['ts_ny'].max().date()})")

    print("Pre-procesando días...")
    cache = build_daily_cache(df)
    days  = list(cache.keys())

    keys   = list(PARAM_GRID.keys())
    combos = list(itertools.product(*PARAM_GRID.values()))
    total  = len(combos)
    print(f"Combinaciones: {total}\n")

    rows = []
    for i, combo in enumerate(combos):
        params = dict(zip(keys, combo))
        trades = run_combo(cache, days, **params)
        closed = [t for t in trades if t["result"] in ("TP", "SL")]
        if len(closed) < 8:
            continue

        wins    = sum(1 for t in closed if t["result"] == "TP")
        n       = len(closed)
        wr      = wins / n * 100
        total_r = sum(t["pnl_r"] for t in closed)
        ev      = total_r / n
        long_n  = [t for t in closed if t["direction"] == "LONG"]
        short_n = [t for t in closed if t["direction"] == "SHORT"]
        long_wr = sum(1 for t in long_n if t["result"] == "TP") / len(long_n) * 100 if long_n else 0
        short_wr= sum(1 for t in short_n if t["result"] == "TP") / len(short_n) * 100 if short_n else 0

        rows.append({
            **params,
            "trades": n,
            "wr":     round(wr, 1),
            "total_r":round(total_r, 2),
            "ev_r":   round(ev, 3),
            "long_wr":round(long_wr, 1),
            "short_wr":round(short_wr, 1),
        })

    res = pd.DataFrame(rows).sort_values(["wr", "total_r"], ascending=False)

    pd.set_option("display.max_columns", None)
    pd.set_option("display.width", 220)

    over50 = res[res["wr"] >= 50]
    print(f"\n{'='*80}")
    print(f"  Combos con WR >= 50%: {len(over50)} de {len(res)} válidos")
    print(f"{'='*80}")
    if not over50.empty:
        print(over50.head(20).to_string(index=False))
    else:
        print("Ninguna combinación superó 50%. Top 20:")
        print(res.head(20).to_string(index=False))

    res.to_csv("grid_search_results.csv", index=False)
    print(f"\nGuardado en grid_search_results.csv")
