"""Importa resultados del backtest CSV a trades.db para preview del dashboard."""
import sqlite3, pandas as pd, os, sys

CSV = "backtest_results.csv"
DB  = "trades.db"

if not os.path.exists(CSV):
    print(f"No existe {CSV}. Ejecutar primero: python3 backtest.py --days 60")
    sys.exit(1)

df = pd.read_csv(CSV)

con = sqlite3.connect(DB)
con.execute("""
    CREATE TABLE IF NOT EXISTS trades (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        date TEXT, direction TEXT,
        entry_price REAL, sl_price REAL, tp_price REAL, sl_usd REAL,
        contracts REAL, entry_time TEXT, exit_time TEXT, exit_price REAL,
        result TEXT, pnl_r REAL, pnl_usdt REAL, equity REAL,
        created_at TEXT DEFAULT (datetime('now'))
    )
""")
con.execute("DELETE FROM trades")

for _, r in df.iterrows():
    con.execute("""
        INSERT INTO trades (date,direction,entry_price,sl_price,tp_price,sl_usd,
            contracts,entry_time,exit_time,exit_price,result,pnl_r,pnl_usdt,equity)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
    """, (r.date, r.direction, r.entry_price, r.sl_price, r.tp_price,
          r.get("sl_usd", 175), r.get("contracts_btc"), str(r.get("entry_time","")),
          str(r.get("exit_time","")), r.get("exit_price"), r.result,
          r.pnl_r, r.get("pnl_usdt"), r.get("equity", 1000)))

con.commit()
print(f"✓ {len(df)} trades importados a {DB}")
con.close()
