"""
Motor de backtest para ORB — BTCUSDT.P OKX
Datos: velas 1m históricas de la API pública de OKX (sin autenticación).
"""

import argparse
import pandas as pd
from data_fetcher import fetch_candles, to_ny_time
from strategies import Trade, orb_signal
from risk import position_size, pnl_usdt
from config import RISK_PCT


def simulate_trade(trade: Trade, df: pd.DataFrame) -> Trade:
    """Recorre velas 1m post-entrada para determinar TP o SL."""
    future = df[df["ts_ny"] > trade.entry_time].reset_index(drop=True)

    for _, row in future.iterrows():
        if trade.direction == "LONG":
            if row["low"] <= trade.sl_price:
                trade.exit_price = trade.sl_price
                trade.exit_time  = row["ts_ny"]
                trade.result     = "SL"
                trade.pnl_r      = -1.0
                return trade
            if row["high"] >= trade.tp_price:
                trade.exit_price = trade.tp_price
                trade.exit_time  = row["ts_ny"]
                trade.result     = "TP"
                trade.pnl_r      = (trade.tp_price - trade.entry_price) / trade.sl_usd
                return trade
        else:
            if row["high"] >= trade.sl_price:
                trade.exit_price = trade.sl_price
                trade.exit_time  = row["ts_ny"]
                trade.result     = "SL"
                trade.pnl_r      = -1.0
                return trade
            if row["low"] <= trade.tp_price:
                trade.exit_price = trade.tp_price
                trade.exit_time  = row["ts_ny"]
                trade.result     = "TP"
                trade.pnl_r      = (trade.entry_price - trade.tp_price) / trade.sl_usd
                return trade

    # Trade abierto al final del histórico
    last = future.iloc[-1] if not future.empty else None
    if last is not None:
        trade.exit_price = last["close"]
        trade.exit_time  = last["ts_ny"]
        trade.result     = "OPEN"
        if trade.direction == "LONG":
            trade.pnl_r = (last["close"] - trade.entry_price) / trade.sl_usd
        else:
            trade.pnl_r = (trade.entry_price - last["close"]) / trade.sl_usd
    return trade


def run_backtest(days: int = 30, capital: float = 1000.0) -> pd.DataFrame:
    """
    Descarga datos de OKX y simula la estrategia ORB.

    Fuente de datos: OKX API pública /api/v5/market/history-candles
    Símbolo: BTC-USDT-SWAP (perpetual inverso USDT)
    Timeframe: 1m
    Sin comisiones (paper trading). En live añadir ~0.02% taker fee.
    """
    print(f"Descargando {days} días de velas 1m BTCUSDT.P desde OKX...")
    df = fetch_candles(bar="1m", days=days)
    df = to_ny_time(df)
    print(f"  {len(df):,} velas descargadas ({df['ts_ny'].min().date()} → {df['ts_ny'].max().date()})")

    trading_days = sorted(df["ts_ny"].dt.date.unique())
    all_trades: list[Trade] = []

    for day in trading_days:
        signal = orb_signal(df, day)
        if signal:
            signal = simulate_trade(signal, df)
            all_trades.append(signal)

    if not all_trades:
        print("Sin señales en el período.")
        return pd.DataFrame()

    rows = []
    equity = capital
    for t in all_trades:
        sz  = position_size(equity, t.sl_usd)
        pnl = pnl_usdt(equity, t.sl_usd, t.pnl_r or 0)
        equity += pnl
        rows.append({
            "date":         t.date,
            "direction":    t.direction,
            "entry_price":  t.entry_price,
            "sl_price":     t.sl_price,
            "tp_price":     round(t.tp_price, 1),
            "sl_usd":       t.sl_usd,
            "entry_time":   t.entry_time,
            "exit_time":    t.exit_time,
            "exit_price":   t.exit_price,
            "result":       t.result,
            "pnl_r":        round(t.pnl_r, 3) if t.pnl_r is not None else None,
            "pnl_usdt":     pnl,
            "contracts_btc": sz["contracts_btc"],
            "equity":       round(equity, 2),
        })

    return pd.DataFrame(rows)


def print_summary(df: pd.DataFrame, capital: float):
    if df.empty:
        return

    closed = df[df["result"].isin(["TP", "SL"])].copy()
    if closed.empty:
        print("Sin trades cerrados.")
        return

    total  = len(closed)
    wins   = (closed["result"] == "TP").sum()
    losses = (closed["result"] == "SL").sum()
    wr     = wins / total * 100

    total_r   = closed["pnl_r"].sum()
    avg_r     = closed["pnl_r"].mean()
    total_pnl = closed["pnl_usdt"].sum()
    max_dd_r  = _max_drawdown(closed["pnl_r"].tolist())
    long_wr   = _wr(closed[closed["direction"] == "LONG"])
    short_wr  = _wr(closed[closed["direction"] == "SHORT"])
    ev        = wins / total * 2 - losses / total * 1   # EV con 1:2 R/B

    print("\n" + "="*58)
    print("  BACKTEST ORB — BTCUSDT.P OKX (velas 1m)")
    print("="*58)
    print(f"  Período       : {df['date'].min()} → {df['date'].max()}")
    print(f"  Capital init  : ${capital:,.2f} USDT")
    print(f"  Capital final : ${df['equity'].iloc[-1]:,.2f} USDT")
    print(f"  Total trades  : {total}")
    print(f"  Win Rate      : {wr:.1f}%  ({wins}W / {losses}L)")
    print(f"  EV / trade    : {ev:+.3f}R  (break-even: 33.3%)")
    print(f"  Total R       : {total_r:+.2f}R")
    print(f"  P&L USDT      : ${total_pnl:+.2f}")
    print(f"  Avg R/trade   : {avg_r:+.3f}R")
    print(f"  Max Drawdown  : {max_dd_r:.2f}R")
    print(f"  LONG  WR      : {long_wr:.1f}%")
    print(f"  SHORT WR      : {short_wr:.1f}%")
    print("="*58)
    print(f"\n  Datos: OKX API pública /api/v5/market/history-candles")
    print(f"  Sin comisiones (agregar ~0.04% round-trip en live)")

    print("\n--- Detalle ---")
    print(closed[["date", "direction", "entry_price", "sl_usd",
                   "result", "pnl_r", "pnl_usdt", "equity"]].to_string(index=False))


def _wr(df: pd.DataFrame) -> float:
    if df.empty:
        return 0.0
    return (df["result"] == "TP").sum() / len(df) * 100


def _max_drawdown(pnl_list: list) -> float:
    eq, peak, max_dd = 0.0, 0.0, 0.0
    for r in pnl_list:
        eq += r
        peak = max(peak, eq)
        max_dd = max(max_dd, peak - eq)
    return max_dd


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Backtest ORB BTCUSDT.P")
    parser.add_argument("--days",    type=int,   default=30,   help="Días de histórico")
    parser.add_argument("--capital", type=float, default=1000, help="Capital inicial USDT")
    args = parser.parse_args()

    df = run_backtest(days=args.days, capital=args.capital)
    if not df.empty:
        df.to_csv("backtest_results.csv", index=False)
        print_summary(df, args.capital)
        print("\nResultados guardados en backtest_results.csv")
