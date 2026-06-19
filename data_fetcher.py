"""Descarga velas históricas de OKX (API pública, sin autenticación)."""

import time
import requests
import pandas as pd
import pytz
from datetime import datetime, timedelta
from config import OKX_BASE_URL, SYMBOL, NY_TZ


def _bar_to_millis(bar: str) -> int:
    units = {"m": 60, "H": 3600, "D": 86400}
    n, u = int(bar[:-1]), bar[-1]
    return n * units[u] * 1000


def fetch_candles(bar: str = "1m", days: int = 30, symbol: str = SYMBOL) -> pd.DataFrame:
    """
    Descarga hasta `days` días de velas OHLCV desde OKX.
    Retorna DataFrame con columnas: ts, open, high, low, close, vol
    """
    endpoint = f"{OKX_BASE_URL}/api/v5/market/history-candles"
    limit = 300
    bar_ms = _bar_to_millis(bar)
    end_ms = int(time.time() * 1000)
    start_ms = end_ms - days * 86400 * 1000

    all_candles: list[list] = []
    after = None  # OKX: "after" devuelve datos más antiguos que ese ts

    while True:
        params: dict = {"instId": symbol, "bar": bar, "limit": limit}
        if after:
            params["after"] = after

        resp = requests.get(endpoint, params=params, timeout=15)
        resp.raise_for_status()
        data = resp.json()

        if data.get("code") != "0" or not data.get("data"):
            break

        candles = data["data"]  # newest first
        all_candles.extend(candles)

        oldest_ts = int(candles[-1][0])
        if oldest_ts <= start_ms or len(candles) < limit:
            break

        after = str(oldest_ts)
        time.sleep(0.25)

    if not all_candles:
        raise RuntimeError("No se obtuvieron datos de OKX")

    df = pd.DataFrame(all_candles, columns=["ts", "open", "high", "low", "close", "vol", "volCcy", "volCcyQuote", "confirm"])
    df = df[df["confirm"] == "1"].copy()      # solo velas cerradas
    df["ts"] = pd.to_datetime(df["ts"].astype(int), unit="ms", utc=True)
    for col in ["open", "high", "low", "close", "vol"]:
        df[col] = df[col].astype(float)
    df.sort_values("ts", inplace=True)
    df.reset_index(drop=True, inplace=True)
    df = df[df["ts"] >= pd.Timestamp(start_ms, unit="ms", tz="UTC")]
    return df[["ts", "open", "high", "low", "close", "vol"]]


def to_ny_time(df: pd.DataFrame) -> pd.DataFrame:
    """Agrega columna 'ts_ny' con el timestamp en hora de Nueva York."""
    df = df.copy()
    df["ts_ny"] = df["ts"].dt.tz_convert(NY_TZ)
    return df


if __name__ == "__main__":
    print("Descargando 7 días de velas 1m...")
    df = fetch_candles(bar="1m", days=7)
    df = to_ny_time(df)
    print(f"Total velas: {len(df)}")
    print(df.tail())
