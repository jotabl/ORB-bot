"""
Risk manager: sizing con 1% de riesgo sobre capital apalancado 100x.
"""

from config import RISK_PCT


def position_size(capital_usdt: float, sl_usd: float, leverage: int = 100) -> dict:
    """
    Calcula el tamaño de posición para riesgo fijo del 1% del capital.

    Con 100x leverage:
    - Capital real:     e.g. $1.000
    - Poder de compra:  $100.000
    - Riesgo por trade: 1% del capital real = $10
    - Contracts (BTC):  riesgo_usd / sl_usd

    Returns dict con todos los valores de sizing.
    """
    risk_usd     = capital_usdt * RISK_PCT           # $ en riesgo
    contracts    = risk_usd / sl_usd                 # BTC a operar
    notional     = contracts * leverage * sl_usd     # valor nocional aprox
    margin_req   = notional / leverage               # margen necesario

    return {
        "capital_usdt": capital_usdt,
        "risk_usd":     round(risk_usd, 2),
        "sl_usd":       round(sl_usd, 2),
        "contracts_btc": round(contracts, 6),
        "notional_usdt": round(notional, 2),
        "margin_req":    round(margin_req, 2),
        "leverage":      leverage,
    }


def pnl_usdt(capital_usdt: float, sl_usd: float, pnl_r: float) -> float:
    """P&L en USDT dado el resultado en múltiplos de R."""
    risk_usd = capital_usdt * RISK_PCT
    return round(risk_usd * pnl_r, 2)
