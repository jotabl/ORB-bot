"""
Estrategia Opening Range Breakout (ORB) — BTCUSDT.P OKX

Reglas:
  - Rango ORB: primeras 5 velas 9:30–9:34 AM NY
  - Entry:     cierre rompe orb_high (LONG) o orb_low (SHORT)
  - SL:        midpoint del rango ORB = (orb_high + orb_low) / 2
  - TP:        RR 1:2
  - Vela grande (rango > ORB): no entrar directo, esperar retest al nivel roto
  - Filtro Gann Box (HIGH/LOW del día actual antes de la apertura NY 9:30 AM):
      precio entre 0 y 0.25 del box  → solo LONG
      precio entre 0.25 y 0.75       → LONG o SHORT
      precio entre 0.75 y 1          → solo SHORT
      (0 = HIGH del día anterior, 1 = LOW del día anterior)
"""

from dataclasses import dataclass
from typing import Optional
import pandas as pd
from config import (
    NY_OPEN_HOUR, NY_OPEN_MINUTE, NY_CLOSE_HOUR, NY_CLOSE_MINUTE,
    TP_CONSERVATIVE, ORB_MIN_RANGE, ORB_CANDLES, GANN_ZONE_PCT, GANN_SKIP_MIDDLE,
)


@dataclass
class Trade:
    date: str
    strategy: str = "ORB"
    direction: str = ""
    entry_price: float = 0.0
    sl_price: float = 0.0
    tp_price: float = 0.0
    entry_time: Optional[pd.Timestamp] = None
    exit_time: Optional[pd.Timestamp] = None
    exit_price: Optional[float] = None
    result: Optional[str] = None    # "TP" | "SL" | "OPEN"
    pnl_r: Optional[float] = None
    sl_usd: float = 0.0


# ---------------------------------------------------------------------------
# Filtro Gann Box — rango Londres/Asia (00:00 → 9:30 AM NY)
# ---------------------------------------------------------------------------

def gann_filter(df: pd.DataFrame, ny_date) -> dict:
    """
    Calcula el Gann Box usando el HIGH y LOW del día actual antes de la apertura NY (9:30 AM).
    0 = HIGH del rango, 1 = LOW del rango.
    """
    d = df["ts_ny"].dt.date == ny_date
    before_open = (df["ts_ny"].dt.hour < NY_OPEN_HOUR) | (
        (df["ts_ny"].dt.hour == NY_OPEN_HOUR) & (df["ts_ny"].dt.minute < NY_OPEN_MINUTE)
    )
    prev = df[d & before_open]
    if len(prev) < 10:
        return {}
    rh  = prev["high"].max()
    rl  = prev["low"].min()
    rng = rh - rl
    if rng == 0:
        return {}
    # Cuartiles: q25 = high - 0.25*rng (zona 0→0.25 desde el high)
    return {
        "high": rh,
        "low":  rl,
        "q25":  rh - 0.25 * rng,   # límite inferior de zona LONG-only
        "q75":  rl + 0.25 * rng,   # límite superior de zona SHORT-only
    }


def direction_allowed(orb_high: float, orb_low: float, gb: dict) -> list:
    """
    Evalúa dónde cae el rango ORB dentro del Gann Box de Londres/Asia.
    Usa el midpoint del ORB para determinar la zona.

    Gann Box: 0 = HIGH de Londres/Asia, 1 = LOW de Londres/Asia
      0 → 0.25   (top quarter)    → solo LONG
      0.25 → 0.75 (middle half)   → LONG y SHORT
      0.75 → 1   (bottom quarter) → solo SHORT
    """
    if not gb:
        return ["LONG", "SHORT"]

    orb_mid = (orb_high + orb_low) / 2
    rng     = gb["high"] - gb["low"]
    if rng == 0:
        return ["LONG", "SHORT"]

    # Posición del midpoint ORB dentro del Gann Box (0=high, 1=low)
    pos = (gb["high"] - orb_mid) / rng   # 0 cuando orb_mid == gb_high, 1 cuando == gb_low

    if pos <= GANN_ZONE_PCT:
        return ["LONG"]
    if pos >= (1 - GANN_ZONE_PCT):
        return ["SHORT"]
    if GANN_SKIP_MIDDLE:
        return []
    return ["LONG", "SHORT"]


# ---------------------------------------------------------------------------
# ESTRATEGIA — Opening Range Breakout
# ---------------------------------------------------------------------------

def orb_signal(df: pd.DataFrame, ny_date) -> Optional[Trade]:
    # Sesión NY: 9:30 → 10:30 AM
    d = df["ts_ny"].dt.date == ny_date
    after_open = (df["ts_ny"].dt.hour > NY_OPEN_HOUR) | (
        (df["ts_ny"].dt.hour == NY_OPEN_HOUR) & (df["ts_ny"].dt.minute >= NY_OPEN_MINUTE)
    )
    before_close = (df["ts_ny"].dt.hour < NY_CLOSE_HOUR) | (
        (df["ts_ny"].dt.hour == NY_CLOSE_HOUR) & (df["ts_ny"].dt.minute <= NY_CLOSE_MINUTE)
    )
    session = df[d & after_open & before_close].reset_index(drop=True)

    if len(session) < ORB_CANDLES + 2:
        return None

    # Rango ORB: primeras ORB_CANDLES velas desde 9:30
    init      = session.iloc[:ORB_CANDLES]
    orb_high  = init["high"].max()
    orb_low   = init["low"].min()
    orb_range = orb_high - orb_low
    midpoint  = (orb_high + orb_low) / 2

    if orb_range < ORB_MIN_RANGE:
        return None

    gb      = gann_filter(df, ny_date)
    allowed = direction_allowed(orb_high, orb_low, gb)

    pending_long_retest  = False
    pending_short_retest = False

    for i in range(ORB_CANDLES, len(session)):
        candle  = session.iloc[i]
        c_range = candle["high"] - candle["low"]
        close   = candle["close"]

        # ── Retest LONG: precio vuelve a orb_high tras vela excesiva ─────
        if pending_long_retest:
            if candle["low"] <= orb_high and close > orb_high:
                entry   = close
                sl_dist = entry - midpoint
                if sl_dist > 0:
                    return _make_trade(ny_date, "LONG", entry, midpoint, sl_dist, candle["ts_ny"])
            if close < midpoint:
                pending_long_retest = False

        # ── Retest SHORT: precio vuelve a orb_low tras vela excesiva ─────
        if pending_short_retest:
            if candle["high"] >= orb_low and close < orb_low:
                entry   = close
                sl_dist = midpoint - entry
                if sl_dist > 0:
                    return _make_trade(ny_date, "SHORT", entry, midpoint, sl_dist, candle["ts_ny"])
            if close > midpoint:
                pending_short_retest = False

        # ── Ruptura LONG ─────────────────────────────────────────────────
        if close > orb_high and "LONG" in allowed:
            if c_range > orb_range:
                pending_long_retest = True
                continue
            entry   = close
            sl_dist = entry - midpoint
            if sl_dist > 0:
                return _make_trade(ny_date, "LONG", entry, midpoint, sl_dist, candle["ts_ny"])

        # ── Ruptura SHORT ─────────────────────────────────────────────────
        if close < orb_low and "SHORT" in allowed:
            if c_range > orb_range:
                pending_short_retest = True
                continue
            entry   = close
            sl_dist = midpoint - entry
            if sl_dist > 0:
                return _make_trade(ny_date, "SHORT", entry, midpoint, sl_dist, candle["ts_ny"])

    return None


def _make_trade(ny_date, direction, entry, midpoint, sl_dist, ts):
    sl_dist = round(sl_dist, 2)
    tp = round(entry + sl_dist * TP_CONSERVATIVE, 1) if direction == "LONG" \
         else round(entry - sl_dist * TP_CONSERVATIVE, 1)
    return Trade(
        date=str(ny_date),
        direction=direction,
        entry_price=entry,
        sl_price=round(midpoint, 1),
        sl_usd=sl_dist,
        tp_price=tp,
        entry_time=ts,
    )
