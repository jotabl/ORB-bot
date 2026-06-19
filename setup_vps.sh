#!/bin/bash
# ============================================================
# Setup VPS — ORB Bot BTCUSDT.P
# Ubuntu 22.04 / Debian 11
# Ejecutar: bash setup_vps.sh
# ============================================================

set -e
BOT_DIR="$HOME/orb-bot"
PYTHON="python3"

echo "=== Instalando dependencias del sistema ==="
sudo apt-get update -qq
sudo apt-get install -y python3 python3-pip sqlite3 curl

echo "=== Creando directorio del bot ==="
mkdir -p "$BOT_DIR"
cd "$BOT_DIR"

echo "=== Instalando dependencias Python ==="
pip3 install pandas requests pytz flask --quiet

echo "=== Copiando archivos del bot ==="
# Ejecutar desde la carpeta del proyecto local:
# rsync -avz . user@vps_ip:~/orb-bot/
echo "  → Copiar manualmente con: rsync -avz ./ user@VPS_IP:~/orb-bot/"

echo "=== Configurando cron job ==="
# El paper trader corre cada minuto de lunes a viernes
# entre 9:25 AM y 10:35 AM hora de Nueva York (UTC-4 en verano / UTC-5 en invierno)
# En verano (EDT = UTC-4): 9:25 NY = 13:25 UTC
# En invierno (EST = UTC-5): 9:25 NY = 14:25 UTC

cat > /tmp/orb_cron << 'CRON'
# ORB Bot — Paper Trader (horario verano EDT = UTC-4)
# Corre cada minuto de 13:25 a 14:35 UTC (= 9:25-10:35 AM NY en verano)
# Ajustar horas en invierno: 14:25-15:35 UTC
25-59 13 * * 1-5 cd ~/orb-bot && /usr/bin/python3 paper_trader.py >> logs/cron.log 2>&1
0-35  14 * * 1-5 cd ~/orb-bot && /usr/bin/python3 paper_trader.py >> logs/cron.log 2>&1

# Dashboard Flask (arranca al reiniciar)
@reboot cd ~/orb-bot && PORT=8080 /usr/bin/python3 dashboard/app.py >> logs/dashboard.log 2>&1 &
CRON

crontab /tmp/orb_cron
echo "  → Cron instalado. Ver con: crontab -l"

echo "=== Creando directorio de logs ==="
mkdir -p "$BOT_DIR/logs"

echo "=== Iniciando dashboard en background ==="
nohup bash -c "cd $BOT_DIR && PORT=8080 python3 dashboard/app.py" > "$BOT_DIR/logs/dashboard.log" 2>&1 &
echo "  → Dashboard corriendo en http://$(curl -s ifconfig.me 2>/dev/null):8080"

echo ""
echo "=== SETUP COMPLETO ==="
echo "  Bot dir    : $BOT_DIR"
echo "  Paper log  : $BOT_DIR/paper_trader.log"
echo "  Dashboard  : http://VPS_IP:8080"
echo "  DB         : $BOT_DIR/trades.db"
echo ""
echo "  Comandos útiles:"
echo "    Ver cron        : crontab -l"
echo "    Ver log live    : tail -f ~/orb-bot/paper_trader.log"
echo "    Ver dashboard   : http://VPS_IP:8080"
echo "    Backtest manual : cd ~/orb-bot && python3 backtest.py --days 30"
