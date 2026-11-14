# Sage en vivo en el NAS (fase 3, NO instalado todavía)

Lee Sage con el usuario de **solo lectura** de la copia de los dashboards y lo envía a
Odoo por la API JSON-2. Un contenedor de usar y tirar (imagen `bi-dash-bi`, 512 MB, 1 CPU,
10 min máx.), una ejecución a la vez, fuera de las horas de la copia diaria.

## Instalar (con el ok del usuario)
1. `sudo mkdir /volume1/docker/sage-odoo-sync && cd` ahí; copiar `run.sh`,
   `../sage_live_sync.py` y `env.example` como `.env` (rellenar `ODOO_API_KEY`, `chmod 600 .env`).
2. Probar a mano sin enviar: `docker run --rm --network host --env-file /volume1/docker/sync-bi-staging/.env --env-file .env -v $PWD/sage_live_sync.py:/sync.py:ro bi-dash-bi python3 /sync.py --dry-run | grep -v '^JSON'`
3. Primera ejecución real a mano: `./run.sh` y revisar `logs/` y, en Odoo, Inventario Sage → Sincronizaciones de Sage.
4. Programar: `sudo cp sage-odoo-sync.cron /etc/cron.d/sage-odoo-sync`.

## Quitar (marcha atrás completa)
1. `sudo rm /etc/cron.d/sage-odoo-sync` → deja de ejecutarse en la siguiente hora.
2. `sudo rm -rf /volume1/docker/sage-odoo-sync` → no queda nada en el NAS.
3. En Odoo: borrar la clave API del usuario técnico. Los datos recibidos están solo en el sandbox
   (versiones de Sage, movimientos); volver a subir a mano una exportación de Sage deja todo como antes.
