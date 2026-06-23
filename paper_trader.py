"""
Paper trader en vivo para ORB BTCUSDT.P.
Se ejecuta por cron cada minuto durante la ventana 9:25-10:35 AM NY.
Guarda operaciones en SQLite y loguea en paper_trader.log.
"""

import sys
import time
import logging
import sqlite3
from datetime import datetime, date
from typing import Optional
import pytz
import pandas as pd

from config import NY_OPEN_HOUR, NY_OPEN_MINUTE, NY_CLOSE_HOUR, NY_CLOSE_MINUTE, NY_TZ
from data_fetcher import fetch_candles, to_ny_time
from strategies import orb_signal
from risk import position_size, pnl_usdt

DB_PATH  = "trades.db"
LOG_PATH = "paper_trader.log"
CAPITAL  = 2300.0   # capital real en USDT (1% riesgo = ~$23 por trade)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    handlers=[
        logging.FileHandler(LOG_PATH),
        logging.StreamHandler(sys.stdout),
    ],
)
log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Base de datos SQLite
# ---------------------------------------------------------------------------

def init_db():
    con = sqlite3.connect(DB_PATH)
    con.execute("""
        CREATE TABLE IF NOT EXISTS trades (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            date        TEXT,
            direction   TEXT,
            entry_price REAL,
            sl_price    REAL,
            tp_price    REAL,
            sl_usd      REAL,
            contracts   REAL,
            entry_time  TEXT,
            exit_time   TEXT,
            exit_price  REAL,
            result      TEXT,
            pnl_r       REAL,
            pnl_usdt    REAL,
            equity      REAL,
            created_at  TEXT DEFAULT (datetime('now'))
        )
    """)
    con.commit()
    con.close()


def load_open_trade() -> Optional[dict]:
    """Retorna el trade abierto del día si existe."""
    con = sqlite3.connect(DB_PATH)
    row = con.execute(
        "SELECT * FROM trades WHERE result = 'OPEN' ORDER BY id DESC LIMIT 1"
    ).fetchone()
    con.close()
    if row:
        cols = ["id","date","direction","entry_price","sl_price","tp_price",
                "sl_usd","contracts","entry_time","exit_time","exit_price",
                "result","pnl_r","pnl_usdt","equity","created_at"]
        return dict(zip(cols, row))
    return None


def save_trade(trade_dict: dict):
    con = sqlite3.connect(DB_PATH)
    cols = ["date","direction","entry_price","sl_price","tp_price","sl_usd",
            "contracts","entry_time","exit_time","exit_price","result","pnl_r",
            "pnl_usdt","equity"]
    vals = [trade_dict.get(c) for c in cols]
    con.execute(f"INSERT INTO trades ({','.join(cols)}) VALUES ({','.join(['?']*len(cols))})", vals)
    con.commit()
    con.close()


def update_trade(trade_id: int, exit_time, exit_price, result, pnl_r, pnl_usdt_val, equity):
    con = sqlite3.connect(DB_PATH)
    con.execute("""
        UPDATE trades SET exit_time=?, exit_price=?, result=?, pnl_r=?, pnl_usdt=?, equity=?
        WHERE id=?
    """, (str(exit_time), exit_price, result, pnl_r, pnl_usdt_val, equity, trade_id))
    con.commit()
    con.close()


def get_equity() -> float:
    con = sqlite3.connect(DB_PATH)
    row = con.execute(
        "SELECT equity FROM trades WHERE result != 'OPEN' ORDER BY id DESC LIMIT 1"
    ).fetchone()
    con.close()
    return row[0] if row else CAPITAL


def today_has_signal() -> bool:
    today = date.today().isoformat()
    con   = sqlite3.connect(DB_PATH)
    row   = con.execute("SELECT 1 FROM trades WHERE date=?", (today,)).fetchone()
    con.close()
    return row is not None


# ---------------------------------------------------------------------------
# Lógica principal
# ---------------------------------------------------------------------------

def check_open_trade(open_trade: dict, df: pd.DataFrame):
    """Verifica si el trade abierto tocó SL o TP."""
    last = df.iloc[-1]
    tid  = open_trade["id"]
    ep   = open_trade["entry_price"]
    sl   = open_trade["sl_price"]
    tp   = open_trade["tp_price"]
    sl_u = open_trade["sl_usd"]
    dir_ = open_trade["direction"]
    cap  = get_equity()

    result = exit_p = pnl_r = None

    if dir_ == "LONG":
        if last["low"] <= sl:
            result, exit_p, pnl_r = "SL", sl, -1.0
        elif last["high"] >= tp:
            result, exit_p, pnl_r = "TP", tp, (tp - ep) / sl_u
    else:
        if last["high"] >= sl:
            result, exit_p, pnl_r = "SL", sl, -1.0
        elif last["low"] <= tp:
            result, exit_p, pnl_r = "TP", tp, (ep - tp) / sl_u

    if result:
        pnl = pnl_usdt(cap, sl_u, pnl_r)
        new_equity = round(cap + pnl, 2)
        update_trade(tid, last["ts_ny"], exit_p, result, pnl_r, pnl, new_equity)
        log.info(f"TRADE CERRADO {result} | dir={dir_} entry={ep} exit={exit_p} "
                 f"pnl={pnl:+.2f} USDT ({pnl_r:+.2f}R) equity=${new_equity}")


def run():
    init_db()
    now_ny = datetime.now(NY_TZ)
    log.info(f"Paper trader ejecutado — {now_ny.strftime('%Y-%m-%d %H:%M NY')}")

    # ¿Estamos en ventana de trading?
    h, m = now_ny.hour, now_ny.minute
    in_window = (
        (h == NY_OPEN_HOUR and m >= NY_OPEN_MINUTE) or
        (h > NY_OPEN_HOUR and h < NY_CLOSE_HOUR) or
        (h == NY_CLOSE_HOUR and m <= NY_CLOSE_MINUTE + 5)
    )
    if not in_window:
        log.info("Fuera de ventana ORB (9:30-10:35 AM NY). Nada que hacer.")
        return

    # Descargar últimas velas (2 días bastan para contexto del rango previo)
    df = fetch_candles(bar="1m", days=2)
    df = to_ny_time(df)
    ny_today = now_ny.date()

    # 1. Revisar trade abierto
    open_trade = load_open_trade()
    if open_trade and open_trade["date"] == str(ny_today):
        check_open_trade(open_trade, df)
        return   # un trade por día

    # 2. Buscar señal ORB (solo si no operamos hoy)
    if today_has_signal():
        log.info("Ya hay un trade registrado para hoy.")
        return

    signal = orb_signal(df, ny_today)
    if not signal:
        log.info("Sin señal ORB todavía.")
        return

    capital = get_equity()
    sz      = position_size(capital, signal.sl_usd)
    log.info(
        f"SEÑAL ORB {signal.direction} | entry={signal.entry_price} "
        f"SL={signal.sl_price} TP={signal.tp_price} "
        f"SL_dist={signal.sl_usd:.0f} USD | "
        f"Contracts={sz['contracts_btc']} BTC | Risk=${sz['risk_usd']}"
    )

    save_trade({
        "date":         str(ny_today),
        "direction":    signal.direction,
        "entry_price":  signal.entry_price,
        "sl_price":     signal.sl_price,
        "tp_price":     signal.tp_price,
        "sl_usd":       signal.sl_usd,
        "contracts":    sz["contracts_btc"],
        "entry_time":   str(signal.entry_time),
        "exit_time":    None,
        "exit_price":   None,
        "result":       "OPEN",
        "pnl_r":        None,
        "pnl_usdt":     None,
        "equity":       capital,
    })


if __name__ == "__main__":
    run()
