# RMS Partner Equipment Model Import

Módulo para Odoo 19 Enterprise que importa desde Excel (`.xlsx`) los Equipos del Cliente asociados a compañías existentes.

## Instalación

1. Instalar `openpyxl` en el entorno Python de Odoo.
2. Actualizar la lista de aplicaciones.
3. Instalar **RMS Partner Equipment Model Import**.

## Uso

Un administrador abre **Contactos > Configuración > Importar Equipos del Cliente** y selecciona un `.xlsx` con estas columnas exactas:

- `Account Lookup: Account Name`
- `Model: Model Name`

La compañía se localiza por nombre normalizado, sin distinguir mayúsculas y
minúsculas y compactando espacios. No se crean compañías. Si varias compañías
comparten el mismo nombre normalizado, la fila se omite y se registra como
error.

Cada ejecución queda disponible en **Contactos > Configuración > Histórico de
Equipos del Cliente importados**, donde se puede consultar y descargar el log.
