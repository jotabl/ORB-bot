"""
Escanea pares OKX SWAP buscando los que tienen mejor ORB performance.
Criterio: WR >= 50% y TotalR >= +15R en 90 días con filtro Pct 0.2%.
"""

import sys
import pandas as pd
from data_fetcher import fetch_candles, to_ny_time
from config import (NY_OPEN_HOUR, NY_OPEN_MINUTE, NY_CLOSE_HOUR, NY_CLOSE_MINUTE,
                    TP_CONSERVATIVE, ORB_CANDLES, GANN_ZONE_PCT, GANN_SKIP_MIDDLE)

DAYS = 90
MIN_RANGE_PCT = 0.002
MIN_TRADES = 20
MIN_WR = 50.0
MIN_TOTAL_R = 10.0

CANDIDATES = [
    "BTC-USDT-SWAP",
    "XRP-USDT-SWAP",
    "DOGE-USDT-SWAP",
    "LTC-USDT-SWAP",
    "LINK-USDT-SWAP",
    "AVAX-USDT-SWAP",
    "DOT-USDT-SWAP",
    "ADA-USDT-SWAP",
    "SUI-USDT-SWAP",
    "TON-USDT-SWAP",
    "APT-USDT-SWAP",
    "OP-USDT-SWAP",
    "ARB-USDT-SWAP",
    "TRX-USDT-SWAP",
    "NEAR-USDT-SWAP",
    "BCH-USDT-SWAP",
    "ICP-USDT-SWAP",
    "FIL-USDT-SWAP",
    "ATOM-USDT-SWAP",
    "UNI-USDT-SWAP",
]


def gann_filter(df, ny_date):
    d      = df["ts_ny"].dt.date == ny_date
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


def orb_signal(df, ny_date):
    d      = df["ts_ny"].dt.date == ny_date
    after  = (df["ts_ny"].dt.hour > NY_OPEN_HOUR) | (
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

    if orb_range < midpoint * MIN_RANGE_PCT:
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
                    return ("LONG", close, midpoint, close + sd * TP_CONSERVATIVE, sd, row["ts_ny"])
            if close < midpoint:
                pend_long = False

        if pend_short:
            if row["high"] >= orb_l and close < orb_l:
                sd = midpoint - close
                if sd > 0:
                    return ("SHORT", close, midpoint, close - sd * TP_CONSERVATIVE, sd, row["ts_ny"])
            if close > midpoint:
                pend_short = False

        if close > orb_h and "LONG" in allowed:
            if c_range > orb_range:
                pend_long = True; continue
            sd = close - midpoint
            if sd > 0:
                return ("LONG", close, midpoint, close + sd * TP_CONSERVATIVE, sd, row["ts_ny"])

        if close < orb_l and "SHORT" in allowed:
            if c_range > orb_range:
                pend_short = True; continue
            sd = midpoint - close
            if sd > 0:
                return ("SHORT", close, midpoint, close - sd * TP_CONSERVATIVE, sd, row["ts_ny"])
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


def scan_symbol(symbol):
    for attempt in range(3):
        try:
            df = fetch_candles(bar="1m", days=DAYS, symbol=symbol)
            df = to_ny_time(df)
            break
        except Exception as e:
            if attempt == 2:
                return None, f"Error: {e}"
            import time; time.sleep(5)

    days_list = sorted(df["ts_ny"].dt.date.unique())
    trades = []
    for day in days_list:
        t = orb_signal(df, day)
        if t:
            r, pnl = simulate(t, df)
            if r in ("TP", "SL"):
                trades.append({"result": r, "pnl_r": pnl, "dir": t[0]})

    if len(trades) < MIN_TRADES:
        return None, f"Solo {len(trades)} trades (mín {MIN_TRADES})"

    wins    = sum(1 for t in trades if t["result"] == "TP")
    n       = len(trades)
    wr      = wins / n * 100
    total_r = sum(t["pnl_r"] for t in trades)
    long_wr = sum(1 for t in trades if t["result"]=="TP" and t["dir"]=="LONG") / max(1, sum(1 for t in trades if t["dir"]=="LONG")) * 100
    short_wr= sum(1 for t in trades if t["result"]=="TP" and t["dir"]=="SHORT") / max(1, sum(1 for t in trades if t["dir"]=="SHORT")) * 100

    return {
        "symbol":   symbol,
        "trades":   n,
        "wr":       round(wr, 1),
        "total_r":  round(total_r, 2),
        "ev":       round(total_r / n, 3),
        "long_wr":  round(long_wr, 1),
        "short_wr": round(short_wr, 1),
    }, None


if __name__ == "__main__":
    print(f"\nEscaneando {len(CANDIDATES)} pares — ORB 90d, filtro Pct {MIN_RANGE_PCT*100:.1f}%")
    print(f"Criterio: WR >= {MIN_WR}% y TotalR >= {MIN_TOTAL_R}R\n")
    print(f"  {'Símbolo':<22} {'Trades':>7} {'WR':>7} {'TotalR':>8} {'EV/t':>7} {'LONG%':>7} {'SHORT%':>7}")
    print(f"  {'-'*68}")

    winners = []
    for symbol in CANDIDATES:
        sys.stdout.write(f"  {symbol:<22} ")
        sys.stdout.flush()
        result, err = scan_symbol(symbol)
        if err:
            print(f"— {err}")
            continue
        r = result
        ok = r["wr"] >= MIN_WR and r["total_r"] >= MIN_TOTAL_R
        tag = " ✅" if ok else ""
        print(f"{r['trades']:>7} {r['wr']:>6.1f}% {r['total_r']:>+8.2f}R {r['ev']:>+7.3f} {r['long_wr']:>6.1f}% {r['short_wr']:>6.1f}%{tag}")
        if ok:
            winners.append(r)

    print(f"\n{'='*72}")
    print(f"  PARES APTOS PARA CARTERA (WR≥{MIN_WR}%, TotalR≥{MIN_TOTAL_R}R):")
    print(f"{'='*72}")
    if winners:
        winners.sort(key=lambda x: x["total_r"], reverse=True)
        for r in winners:
            print(f"  {r['symbol']:<22}  WR={r['wr']}%  TotalR={r['total_r']:+.1f}R  EV={r['ev']:+.3f}")
    else:
        print("  Ningún par cumple los criterios.")
