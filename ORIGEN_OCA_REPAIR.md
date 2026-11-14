# Módulos copiados de OCA/repair

Copiados **sin modificar** (licencia AGPL-3 y autores intactos en cada `__manifest__.py`
y `README.rst`) desde https://github.com/OCA/repair, rama `19.0`,
commit `485ebb8369af52d32dc7af582e0cac157a678d54` (14-oct-2026):

| Módulo | Para qué |
|---|---|
| `base_repair_config` | Página de Ajustes de Reparaciones (ahí va el aviso de días del SAT) |
| `repair_security` | Grupos Reparaciones / Usuario y Administrador (al instalarlo, los usuarios de inventario pasan a Administrador de reparaciones) |
| `repair_service` | Servicios (horas de técnico) en la orden de reparación, que pasan al presupuesto |

Se usan desde `rms_repair_sat` (SAT de RMS). `product_warranty` (OCA/rma) ya está en el
servidor y se puede instalar aparte; no se copia aquí.

Para actualizar: volver a copiar la carpeta del módulo desde OCA y anotar el nuevo commit.
