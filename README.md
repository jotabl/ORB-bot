# ORB Bot — BTCUSDT.P OKX

## Estructura
```
orb-bot/
├── config.py          # Parámetros globales
├── data_fetcher.py    # OKX API pública 1m candles
├── strategies.py      # Lógica ORB
├── risk.py            # Sizing 1% capital / 100x leverage
├── backtest.py        # Motor de backtest
├── paper_trader.py    # Paper trading + SQLite
├── seed_db.py         # Importar backtest CSV a DB
├── setup_vps.sh       # Setup VPS Ubuntu/Debian
├── trades.db          # Base de datos SQLite
└── dashboard/
    └── app.py         # Flask dashboard (puerto 8080)
```

## Backtest
```bash
python3 backtest.py --days 60 --capital 1000
```

## Paper Trading (local)
```bash
python3 paper_trader.py
```

## Dashboard
```bash
PORT=5001 python3 dashboard/app.py
# Abrir: http://localhost:5001
```

## VPS Deploy
```bash
rsync -avz ./ user@VPS_IP:~/orb-bot/
ssh user@VPS_IP "bash ~/orb-bot/setup_vps.sh"
```

## Resultado Backtest (60 días)
- Trades: 18 | WR: 44.4% | Total R: +6R | P&L: +$59.64
- Capital: $1.000 → $1.059,64 (+5.96%)
- EV: +0.33R/trade con ratio 1:2
- Max Drawdown: 6R
