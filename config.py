import pytz

SYMBOL  = "BTC-USDT-SWAP"    # BTCUSDT.P Perpetual en OKX
SYMBOLS = [
    "BTC-USDT-SWAP",
    "HYPE-USDT-SWAP",   # Hyperliquid ~$62 en OKX
]
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

# SL: midpoint del rango ORB = (orb_high + orb_low) / 2
# Sin filtro de distancia mínima — el sizing absorbe rangos chicos

# Ratios R:B
TP_CONSERVATIVE = 1.5    # 1:1.5 — optimizado por grid search
TP_AGGRESSIVE   = 2.0    # 1:2

# Rango ORB mínimo como % del precio (aplica igual a BTC, HYPE, cualquier precio)
ORB_MIN_RANGE_PCT = 0.002   # 0.2% del precio — mejor WR+R para BTC y HYPE (backtest 90d)

# Candles para calcular el rango ORB
ORB_CANDLES = 5

# Tamaño de zonas extremas del Gann Box (25% superior/inferior)
GANN_ZONE_PCT = 0.25

# Operar zona central del Gann Box
GANN_SKIP_MIDDLE = False

OKX_BASE_URL = "https://www.okx.com"
