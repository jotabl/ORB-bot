"""
Estrategia Opening Range Breakout (ORB) para BTCUSDT.P — OKX
"""

from dataclasses import dataclass
from typing import Optional
import pandas as pd
from config import (
    NY_OPEN_HOUR, NY_OPEN_MINUTE, NY_CLOSE_HOUR, NY_CLOSE_MINUTE,
    SL_MIN_USD, SL_MAX_USD, TP_CONSERVATIVE,
)


@dataclass
class Trade:
    date: str
    strategy: str = "ORB"
    direction: str = ""       # "LONG" | "SHORT"
    entry_price: float = 0.0
    sl_price: float = 0.0
    tp_price: float = 0.0
    entry_time: Optional[pd.Timestamp] = None
    exit_time: Optional[pd.Timestamp] = None
    exit_price: Optional[float] = None
    result: Optional[str] = None    # "TP" | "SL" | "OPEN"
    pnl_r: Optional[float] = None
    sl_usd: float = 0.0             # distancia SL en USD (para sizing)


# ---------------------------------------------------------------------------
# PASO 0 — Filtro del rango previo (Asia + Londres)
# ---------------------------------------------------------------------------

def prevrange_filter(df: pd.DataFrame, ny_date) -> dict:
    """
    Rango Asia+Londres: velas del mismo día NY antes de las 9:30 AM.
    Retorna zonas de dirección permitida.
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
    return {"high": rh, "low": rl, "q75": rl + 0.75 * rng, "q25": rl + 0.25 * rng}


def direction_allowed(price: float, pr: dict) -> list:
    if not pr:
        return ["LONG", "SHORT"]
    if price >= pr["q75"]:
        return ["LONG"]
    if price <= pr["q25"]:
        return ["SHORT"]
    return ["LONG", "SHORT"]


# ---------------------------------------------------------------------------
# ESTRATEGIA — Opening Range Breakout (ORB)
# ---------------------------------------------------------------------------

def orb_signal(df: pd.DataFrame, ny_date) -> Optional[Trade]:
    """
    Señal ORB para un día dado en BTCUSDT.P 1m.

    Reglas:
    - Primeras 5 velas (9:30–9:35 AM NY) forman el rango.
    - Ruptura válida: cierre > orb_high + 0.1% (LONG) o < orb_low - 0.1% (SHORT).
    - Vela de ruptura debe ser bajista/alcista con body >= 30% del rango de la vela.
    - Vela excesiva (rango > ORB completo): no entrar directo, esperar retest.
    - SL en low/high de vela previa; debe quedar entre 150-200 USD.
    - Filtro de contexto del rango previo (Asia+Londres).
    - Ventana válida: 9:30 AM → 10:30 AM NY.
    """
    # Velas de sesión NY (9:30 → 10:30)
    d = df["ts_ny"].dt.date == ny_date
    after_open = (df["ts_ny"].dt.hour > NY_OPEN_HOUR) | (
        (df["ts_ny"].dt.hour == NY_OPEN_HOUR) & (df["ts_ny"].dt.minute >= NY_OPEN_MINUTE)
    )
    before_close = (df["ts_ny"].dt.hour < NY_CLOSE_HOUR) | (
        (df["ts_ny"].dt.hour == NY_CLOSE_HOUR) & (df["ts_ny"].dt.minute <= NY_CLOSE_MINUTE)
    )
    session = df[d & after_open & before_close].reset_index(drop=True)

    if len(session) < 7:
        return None

    init      = session.iloc[:5]
    orb_high  = init["high"].max()
    orb_low   = init["low"].min()
    orb_range = orb_high - orb_low

    if orb_range < 50:   # rango mínimo $50 para evitar consolidaciones falsas
        return None

    pr           = prevrange_filter(df, ny_date)
    breakout_ext = orb_high * 0.001   # extensión mínima: 0.1% del precio
    retest_tol   = orb_range * 0.15   # zona de retest para velas excesivas

    pending_long_retest  = False
    pending_short_retest = False

    for i in range(5, len(session)):
        candle      = session.iloc[i]
        prev_candle = session.iloc[i - 1]
        body        = abs(candle["close"] - candle["open"])
        c_range     = candle["high"] - candle["low"]

        # ── Entrada por RETEST (después de vela excesiva) ─────────────────
        if pending_long_retest:
            if candle["low"] <= orb_high + retest_tol and candle["close"] > candle["open"] and candle["close"] > orb_high:
                entry   = candle["close"]
                sl      = candle["low"] - retest_tol * 0.5
                sl_dist = entry - sl
                if SL_MIN_USD <= sl_dist <= SL_MAX_USD:
                    return Trade(date=str(ny_date), direction="LONG",
                                 entry_price=entry, sl_price=sl, sl_usd=sl_dist,
                                 tp_price=entry + sl_dist * TP_CONSERVATIVE,
                                 entry_time=candle["ts_ny"])
            if candle["close"] < orb_high - retest_tol:
                pending_long_retest = False

        if pending_short_retest:
            if candle["high"] >= orb_low - retest_tol and candle["close"] < candle["open"] and candle["close"] < orb_low:
                entry   = candle["close"]
                sl      = candle["high"] + retest_tol * 0.5
                sl_dist = sl - entry
                if SL_MIN_USD <= sl_dist <= SL_MAX_USD:
                    return Trade(date=str(ny_date), direction="SHORT",
                                 entry_price=entry, sl_price=sl, sl_usd=sl_dist,
                                 tp_price=entry - sl_dist * TP_CONSERVATIVE,
                                 entry_time=candle["ts_ny"])
            if candle["close"] > orb_low + retest_tol:
                pending_short_retest = False

        # ── LONG ruptura directa ──────────────────────────────────────────
        if candle["close"] > orb_high + breakout_ext and candle["close"] > candle["open"]:
            if "LONG" not in direction_allowed(candle["close"], pr):
                continue
            if c_range > orb_range:
                pending_long_retest = True
                continue
            if c_range > 0 and body / c_range < 0.30:
                continue

            sl      = prev_candle["low"]
            sl_dist = candle["close"] - sl
            if sl_dist < SL_MIN_USD or sl_dist > SL_MAX_USD:
                continue
            if sl_dist > 0.8 * orb_range:
                continue

            entry = candle["close"]
            return Trade(date=str(ny_date), direction="LONG",
                         entry_price=entry, sl_price=sl, sl_usd=sl_dist,
                         tp_price=entry + sl_dist * TP_CONSERVATIVE,
                         entry_time=candle["ts_ny"])

        # ── SHORT ruptura directa ─────────────────────────────────────────
        if candle["close"] < orb_low - breakout_ext and candle["close"] < candle["open"]:
            if "SHORT" not in direction_allowed(candle["close"], pr):
                continue
            if c_range > orb_range:
                pending_short_retest = True
                continue
            if c_range > 0 and body / c_range < 0.30:
                continue

            sl      = prev_candle["high"]
            sl_dist = sl - candle["close"]
            if sl_dist < SL_MIN_USD or sl_dist > SL_MAX_USD:
                continue
            if sl_dist > 0.8 * orb_range:
                continue

            entry = candle["close"]
            return Trade(date=str(ny_date), direction="SHORT",
                         entry_price=entry, sl_price=sl, sl_usd=sl_dist,
                         tp_price=entry - sl_dist * TP_CONSERVATIVE,
                         entry_time=candle["ts_ny"])

    return None
