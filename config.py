import pytz

SYMBOL = "BTC-USDT-SWAP"   # BTCUSDT.P Perpetual en OKX
TIMEFRAME_1M = "1m"
TIMEFRAME_5M = "5m"
TIMEFRAME_15M = "15m"

NY_TZ = pytz.timezone("America/New_York")
NY_OPEN_HOUR = 9
NY_OPEN_MINUTE = 30
NY_CLOSE_HOUR = 10   # ventana ORB cierra 10:30 AM NY
NY_CLOSE_MINUTE = 30

# Riesgo por operación (% del capital)
RISK_PCT = 0.01          # 1% del capital por trade
SL_MIN_USD = 150
SL_MAX_USD = 200

# Ratios R:B
TP_CONSERVATIVE = 2.0    # 1:2
TP_AGGRESSIVE   = 3.0    # 1:3

OKX_BASE_URL = "https://www.okx.com"
