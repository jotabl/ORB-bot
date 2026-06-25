"""
Backtest comparativo: filtro fijo ($) vs porcentual (%) del precio.
Corre para BTC-USDT-SWAP y HYPE-USDT-SWAP.
"""

import pandas as pd
from dataclasses import dataclass
from typing import Optional
import pytz

from data_fetcher import fetch_candles, to_ny_time
from config import (NY_OPEN_HOUR, NY_OPEN_MINUTE, NY_CLOSE_HOUR, NY_CLOSE_MINUTE,
                    TP_CONSERVATIVE, ORB_CANDLES, GANN_ZONE_PCT, GANN_SKIP_MIDDLE)

NY_TZ = pytz.timezone("America/New_York")
DAYS    = 90
CAPITAL = 2300.0


# ---------------------------------------------------------------------------
# Estrategia parametrizada (sin depender de config.ORB_MIN_RANGE)
# ---------------------------------------------------------------------------

def gann_filter(df, ny_date):
    d = df["ts_ny"].dt.date == ny_date
    before = (df["ts_ny"].dt.hour < NY_OPEN_HOUR) | (
        (df["ts_ny"].dt.hour == NY_OPEN_HOUR) & (df["ts_ny"].dt.minute < NY_OPEN_MINUTE))
    prev = df[d & before]
    if len(prev) < 10:
        return {}
    rh, rl = prev["high"].max(), prev["low"].min()
    rng = float(rh - rl)
    return {"high": float(rh), "low": float(rl), "range": rng} if rng > 0 else {}


def direction_allowed(orb_high, orb_low, gb):
    if not gb:
        return ["LONG", "SHORT"]
    mid = (orb_high + orb_low) / 2
    pos = (gb["high"] - mid) / gb["range"]
    if pos <= GANN_ZONE_PCT:
        return ["LONG"]
    if pos >= (1 - GANN_ZONE_PCT):
        return ["SHORT"]
    if GANN_SKIP_MIDDLE:
        return []
    return ["LONG", "SHORT"]


def orb_signal_param(df, ny_date, min_range_usd=None, min_range_pct=None):
    d = df["ts_ny"].dt.date == ny_date
    after = (df["ts_ny"].dt.hour > NY_OPEN_HOUR) | (
        (df["ts_ny"].dt.hour == NY_OPEN_HOUR) & (df["ts_ny"].dt.minute >= NY_OPEN_MINUTE))
    before_close = (df["ts_ny"].dt.hour < NY_CLOSE_HOUR) | (
        (df["ts_ny"].dt.hour == NY_CLOSE_HOUR) & (df["ts_ny"].dt.minute <= NY_CLOSE_MINUTE))
    sess = df[d & after & before_close].reset_index(drop=True)
    if len(sess) < ORB_CANDLES + 2:
        return None

    init      = sess.iloc[:ORB_CANDLES]
    orb_h     = init["high"].max()
    orb_l     = init["low"].min()
    orb_range = orb_h - orb_l
    midpoint  = (orb_h + orb_l) / 2

    # Filtro de rango mínimo
    threshold = min_range_usd if min_range_usd else (midpoint * min_range_pct)
    if orb_range < threshold:
        return None

    gb      = gann_filter(df, ny_date)
    allowed = direction_allowed(orb_h, orb_l, gb)
    if not allowed:
        return None

    pend_long = pend_short = False
    for i in range(ORB_CANDLES, len(sess)):
        row     = sess.iloc[i]
        c_range = row["high"] - row["low"]
        close   = row["close"]

        if pend_long:
            if row["low"] <= orb_h and close > orb_h:
                sd = close - midpoint
                if sd > 0:
                    tp = close + sd * TP_CONSERVATIVE
                    return ("LONG", close, midpoint, tp, sd, row["ts_ny"])
            if close < midpoint:
                pend_long = False

        if pend_short:
            if row["high"] >= orb_l and close < orb_l:
                sd = midpoint - close
                if sd > 0:
                    tp = close - sd * TP_CONSERVATIVE
                    return ("SHORT", close, midpoint, tp, sd, row["ts_ny"])
            if close > midpoint:
                pend_short = False

        if close > orb_h and "LONG" in allowed:
            if c_range > orb_range:
                pend_long = True; continue
            sd = close - midpoint
            if sd > 0:
                tp = close + sd * TP_CONSERVATIVE
                return ("LONG", close, midpoint, tp, sd, row["ts_ny"])

        if close < orb_l and "SHORT" in allowed:
            if c_range > orb_range:
                pend_short = True; continue
            sd = midpoint - close
            if sd > 0:
                tp = close - sd * TP_CONSERVATIVE
                return ("SHORT", close, midpoint, tp, sd, row["ts_ny"])
    return None


def simulate(trade, df):
    direction, entry, sl, tp, sd, ts = trade
    future = df[df["ts_ny"] > ts].reset_index(drop=True)
    for _, row in future.iterrows():
        if direction == "LONG":
            if row["low"] <= sl:  return "SL", -1.0
            if row["high"] >= tp: return "TP", TP_CONSERVATIVE
        else:
            if row["high"] >= sl: return "SL", -1.0
            if row["low"] <= tp:  return "TP", TP_CONSERVATIVE
    return "OPEN", 0.0


def run(df, days_list, label, **kwargs):
    trades = []
    for day in days_list:
        t = orb_signal_param(df, day, **kwargs)
        if t:
            r, pnl = simulate(t, df)
            if r in ("TP", "SL"):
                trades.append({"result": r, "pnl_r": pnl, "dir": t[0]})

    if len(trades) < 5:
        return {"label": label, "n": len(trades), "wr": 0, "total_r": 0, "ev": 0}

    wins    = sum(1 for t in trades if t["result"] == "TP")
    n       = len(trades)
    total_r = sum(t["pnl_r"] for t in trades)
    long_wr = sum(1 for t in trades if t["result"]=="TP" and t["dir"]=="LONG") / max(1, sum(1 for t in trades if t["dir"]=="LONG")) * 100
    short_wr= sum(1 for t in trades if t["result"]=="TP" and t["dir"]=="SHORT") / max(1, sum(1 for t in trades if t["dir"]=="SHORT")) * 100
    return {"label": label, "n": n, "wr": round(wins/n*100,1),
            "total_r": round(total_r,2), "ev": round(total_r/n,3),
            "long_wr": round(long_wr,1), "short_wr": round(short_wr,1)}


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

CONFIGS = [
    ("Fijo  $50",   dict(min_range_usd=50)),
    ("Fijo $100",   dict(min_range_usd=100)),
    ("Fijo $200",   dict(min_range_usd=200)),
    ("Pct  0.2%",   dict(min_range_pct=0.002)),
    ("Pct  0.3%",   dict(min_range_pct=0.003)),
    ("Pct  0.5%",   dict(min_range_pct=0.005)),
]

if __name__ == "__main__":
    for symbol in ["BTC-USDT-SWAP", "HYPE-USDT-SWAP"]:
        print(f"\n{'='*62}")
        print(f"  {symbol}  ({DAYS} días)")
        print(f"{'='*62}")
        print(f"  {'Filtro':<12} {'Trades':>7} {'WR':>7} {'TotalR':>8} {'EV/t':>7} {'LONG%':>7} {'SHORT%':>7}")
        print(f"  {'-'*58}")

        df = fetch_candles(bar="1m", days=DAYS, symbol=symbol)
        df = to_ny_time(df)
        days_list = sorted(df["ts_ny"].dt.date.unique())

        best = None
        for label, kwargs in CONFIGS:
            r = run(df, days_list, label, **kwargs)
            marker = ""
            if r["n"] >= 5 and r["wr"] >= 50 and (best is None or r["total_r"] > best["total_r"]):
                best = r
                marker = " ◀"
            print(f"  {r['label']:<12} {r['n']:>7} {r['wr']:>6.1f}% {r['total_r']:>+8.2f}R {r['ev']:>+7.3f} {r.get('long_wr',0):>6.1f}% {r.get('short_wr',0):>6.1f}%{marker}")

        if best:
            print(f"\n  ✅ Mejor: {best['label']}  WR={best['wr']}%  TotalR={best['total_r']:+.2f}R")
