# RMS Portal Projects

Añade el modelo `rms.installation.project` (Proyecto de instalación) y una
nueva sección **"Proyectos"** en el portal de clientes (`/my/projects`).

Este modelo es **independiente de la app Proyecto nativa de Odoo**
(`project.project`, usada internamente por el equipo p. ej. para el
calendario de Marketing). Comparte el nombre de cara al usuario porque así se
llama internamente en la empresa, pero no tiene relación técnica ni de datos
con `project.project`: los clientes con acceso a esta sección del portal no
tienen ni tendrán acceso a ningún proyecto interno de Odoo.

## Funcionamiento

- El equipo interno crea proyectos desde **Proyecto > Proyectos**, asigna un
  cliente (`partner_id`) y adjunta el PDF.
- Mientras el estado es **Borrador**, el cliente no lo ve en su portal.
- Al pulsar **Enviar al cliente**, pasa a **Enviado** y aparece
  automáticamente en `/my/projects` para ese contacto exacto (no para toda su
  empresa).
- El cliente puede ver el PDF embebido y descargarlo desde el portal, pero no
  puede editar ni comentar el proyecto.

## Seguridad

- `ir.rule` restringe la lectura en portal a `partner_id == usuario.partner_id`
  y excluye los borradores.
- El PDF se sirve mediante una ruta propia (`/my/projects/<id>/pdf`) que
  repite la misma comprobación de acceso, en vez de depender de la URL directa
  del adjunto (`/web/content/...`).

## Pendiente / posibles mejoras futuras

- Notificar por email al cliente cuando se envía un proyecto.
- Permitir aceptar/rechazar el proyecto desde el propio portal.
- Extender la visibilidad a toda la empresa (`commercial_partner_id`) si en el
  futuro se necesita que varios contactos de un mismo cliente vean los mismos
  proyectos.
