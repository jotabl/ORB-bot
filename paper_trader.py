"""
Paper trader en vivo para ORB — múltiples símbolos.
Se ejecuta en loop cada minuto durante la ventana 9:30-10:35 AM NY.
Guarda operaciones en SQLite y loguea en paper_trader.log.
"""

import sys
import json
import logging
import sqlite3
from datetime import datetime, date
from typing import Optional
import pandas as pd

from config import NY_OPEN_HOUR, NY_OPEN_MINUTE, NY_CLOSE_HOUR, NY_CLOSE_MINUTE, NY_TZ, SYMBOLS
from data_fetcher import fetch_candles, to_ny_time
from strategies import orb_signal
from risk import position_size, pnl_usdt

try:
    from notify import send as tg
except ImportError:
    def tg(msg): pass

try:
    from okx_client import place_order, get_balance, get_positions, close_position
    OKX_LIVE = True
except ImportError:
    OKX_LIVE = False

DB_PATH  = "trades.db"
LOG_PATH = "paper_trader.log"
CAPITAL  = 2300.0   # capital real en USDT — 1% riesgo por trade por símbolo

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
            symbol      TEXT,
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
    # migración: agregar columna symbol si no existe
    try:
        con.execute("ALTER TABLE trades ADD COLUMN symbol TEXT")
        con.commit()
    except Exception:
        pass
    con.commit()
    con.close()


def load_open_trade(symbol: str) -> Optional[dict]:
    con = sqlite3.connect(DB_PATH)
    row = con.execute(
        "SELECT * FROM trades WHERE result='OPEN' AND symbol=? ORDER BY id DESC LIMIT 1",
        (symbol,)
    ).fetchone()
    con.close()
    if row:
        cols = ["id","symbol","date","direction","entry_price","sl_price","tp_price",
                "sl_usd","contracts","entry_time","exit_time","exit_price",
                "result","pnl_r","pnl_usdt","equity","created_at"]
        return dict(zip(cols, row))
    return None


def save_trade(trade_dict: dict):
    con = sqlite3.connect(DB_PATH)
    cols = ["symbol","date","direction","entry_price","sl_price","tp_price","sl_usd",
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


def get_equity(symbol: str) -> float:
    con = sqlite3.connect(DB_PATH)
    row = con.execute(
        "SELECT equity FROM trades WHERE result != 'OPEN' AND symbol=? ORDER BY id DESC LIMIT 1",
        (symbol,)
    ).fetchone()
    con.close()
    return row[0] if row else CAPITAL


def today_has_signal(symbol: str) -> bool:
    today = date.today().isoformat()
    con   = sqlite3.connect(DB_PATH)
    row   = con.execute("SELECT 1 FROM trades WHERE date=? AND symbol=?", (today, symbol)).fetchone()
    con.close()
    return row is not None


# ---------------------------------------------------------------------------
# Lógica por símbolo
# ---------------------------------------------------------------------------

def check_open_trade(open_trade: dict, df: pd.DataFrame, symbol: str):
    last = df.iloc[-1]
    tid  = open_trade["id"]
    ep   = open_trade["entry_price"]
    sl   = open_trade["sl_price"]
    tp   = open_trade["tp_price"]
    sl_u = open_trade["sl_usd"]
    dir_ = open_trade["direction"]
    cap  = get_equity(symbol)

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
        emoji = "✅" if result == "TP" else "❌"
        log.info(f"[{symbol}] TRADE CERRADO {result} | dir={dir_} entry={ep} exit={exit_p} "
                 f"pnl={pnl:+.2f} USDT ({pnl_r:+.2f}R) equity=${new_equity}")
        tg(f"{emoji} <b>{symbol} — {result}</b>\n"
           f"Dir: {dir_} | Entry: {ep}\n"
           f"Exit: {exit_p}\n"
           f"P&L: {pnl:+.2f} USDT ({pnl_r:+.2f}R)\n"
           f"Equity: ${new_equity}")


def run_symbol(symbol: str, ny_today, df: pd.DataFrame):
    open_trade = load_open_trade(symbol)
    if open_trade and open_trade["date"] == str(ny_today):
        check_open_trade(open_trade, df, symbol)
        return

    if today_has_signal(symbol):
        return

    signal = orb_signal(df, ny_today)
    if not signal:
        log.info(f"[{symbol}] Sin señal ORB todavía.")
        return

    capital = get_equity(symbol)
    sz      = position_size(capital, signal.sl_usd)
    dir_emoji = "🟢 LONG" if signal.direction == "LONG" else "🔴 SHORT"
    side      = "buy" if signal.direction == "LONG" else "sell"
    log.info(
        f"[{symbol}] SEÑAL ORB {signal.direction} | entry={signal.entry_price} "
        f"SL={signal.sl_price} TP={signal.tp_price} "
        f"SL_dist={signal.sl_usd:.0f} USD | "
        f"Contracts={sz['contracts_btc']} | Risk=${sz['risk_usd']}"
    )

    # Ejecutar orden real en OKX Demo
    okx_result = ""
    if OKX_LIVE:
        resp = place_order(
            inst_id   = symbol,
            side      = side,
            sz        = sz["contracts_btc"],
            sl_price  = signal.sl_price,
            tp_price  = signal.tp_price,
        )
        if resp.get("code") == "0":
            ord_id = resp["data"][0]["ordId"]
            okx_result = f"✅ OKX orderId: {ord_id}"
            log.info(f"[{symbol}] OKX Demo orden colocada: {ord_id}")
        else:
            okx_result = f"⚠️ OKX error: {resp.get('msg')}"
            log.error(f"[{symbol}] OKX Demo error: {resp}")

    tg(f"🚨 <b>{symbol} — ORDEN EJECUTADA</b>\n"
       f"{dir_emoji}\n"
       f"Entry: <b>{signal.entry_price}</b>\n"
       f"SL: {signal.sl_price}\n"
       f"TP: {signal.tp_price}\n"
       f"Riesgo: ${sz['risk_usd']} USDT\n"
       f"{okx_result}")

    save_trade({
        "symbol":       symbol,
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

    # Escribe señal para notificación push
    signals_file = "last_signal.json"
    try:
        existing = json.load(open(signals_file)) if __import__("os").path.exists(signals_file) else {}
    except Exception:
        existing = {}
    existing[symbol] = {
        "date":      str(ny_today),
        "direction": signal.direction,
        "entry":     signal.entry_price,
        "sl":        signal.sl_price,
        "tp":        signal.tp_price,
    }
    with open(signals_file, "w") as f:
        json.dump(existing, f)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def run():
    init_db()
    now_ny = datetime.now(NY_TZ)
    log.info(f"Paper trader ejecutado — {now_ny.strftime('%Y-%m-%d %H:%M NY')}")

    h, m = now_ny.hour, now_ny.minute
    in_window = (
        (h == NY_OPEN_HOUR and m >= NY_OPEN_MINUTE) or
        (h > NY_OPEN_HOUR and h < NY_CLOSE_HOUR) or
        (h == NY_CLOSE_HOUR and m <= NY_CLOSE_MINUTE + 5)
    )
    if not in_window:
        log.info("Fuera de ventana ORB (9:30-10:35 AM NY). Nada que hacer.")
        return

    ny_today = now_ny.date()

    for symbol in SYMBOLS:
        try:
            df = fetch_candles(bar="1m", days=2, symbol=symbol)
            df = to_ny_time(df)
            run_symbol(symbol, ny_today, df)
        except Exception as e:
            log.error(f"[{symbol}] Error: {e}")


if __name__ == "__main__":
    run()
