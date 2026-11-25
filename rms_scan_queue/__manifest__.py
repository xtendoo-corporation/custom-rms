{
    'name': 'RMS Cola de lecturas (técnico)',
    'version': '19.0.1.0.0',
    'category': 'Inventory/Inventory',
    'summary': 'Librería común de las pantallas de pistola: una lectura nunca se pierde en silencio.',
    'description': """
Cola de lecturas para las pantallas de pistola
==============================================

Módulo técnico, sin menús ni modelos. Reúne lo que comparten las pantallas de
lectura (recepción de proveedor, checklist de salida y depósitos):

* Cola local persistente por operario y dispositivo: cada lectura se guarda en
  el aparato hasta que el servidor la confirma. Se envía en orden.
* Envío propio con límite de 25 s, reintentos a 2/4/8/16/30 s, al volver la
  red, el foco o la pestaña, y botón «Reintentar ahora».
* Error de red o del servidor: se reintenta. Error de validación: la lectura
  se aparta en «Lecturas con error: revisar» con Reintentar / Descartar.
* Sesión caducada: aviso y enlace para volver a entrar en la misma base.
* Indicador permanente: Todo guardado / N pendientes / Sin conexión / Sesión
  caducada. Aviso al cerrar con lecturas sin enviar.
* Corte de ráfagas de la pistola sin Enter (aguanta 100 ms entre lecturas) y
  aviso «Lectura sin procesar». Aviso de sonido bloqueado.

El servidor de cada pantalla debe aceptar un ``client_uid`` por lectura y no
duplicarla si se reenvía.
    """,
    'author': 'Custom RMS',
    'license': 'LGPL-3',
    'depends': ['web'],
    'data': [],
    'assets': {
        'web.assets_backend': [
            'rms_scan_queue/static/src/**/*',
        ],
    },
    'installable': True,
    'application': False,
}
