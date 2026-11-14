#!/bin/bash
# Sage en vivo: lee Sage (SOLO LECTURA) y lo envía a Odoo. Lo lanza cron cada hora.
# Carpeta propuesta en el NAS: /volume1/docker/sage-odoo-sync/
#   run.sh  sage_live_sync.py  .env (ODOO_URL, ODOO_DB, ODOO_API_KEY)  logs/
# No toca ningún otro contenedor ni archivo del NAS.
set -uo pipefail
DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$DIR"
mkdir -p logs
LOG="logs/sync_$(date +%Y%m%d).log"

# Una sola ejecución a la vez.
exec 9>"$DIR/.lock"
if ! flock -n 9; then
  echo "$(date '+%F %T') ya hay una ejecución en marcha: salgo" >> "$LOG"
  exit 0
fi
# No coincidir con la copia diaria de los dashboards (03:00 y 14:30).
if pgrep -f sincronizar_2026.py > /dev/null; then
  echo "$(date '+%F %T') la copia de los dashboards está en marcha: salgo" >> "$LOG"
  exit 0
fi

echo "=== Inicio $(date '+%F %T') ===" >> "$LOG"
# Contenedor de usar y tirar: 512 MB y 1 CPU como máximo, 10 minutos como máximo.
timeout 600 docker run --rm --network host --memory 512m --cpus 1 \
  --env-file /volume1/docker/sync-bi-staging/.env \
  --env-file "$DIR/.env" \
  -v "$DIR/sage_live_sync.py:/sync.py:ro" \
  bi-dash-bi python3 /sync.py >> "$LOG" 2>&1
CODE=$?
echo "=== Fin $(date '+%F %T') (código $CODE) ===" >> "$LOG"
# Logs de más de 30 días fuera.
find "$DIR/logs" -name 'sync_*.log' -mtime +30 -delete
exit $CODE
