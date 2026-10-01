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
  cliente (`partner_id`) y adjunta el documento HTML (`file_data`/`file_name`).
- Mientras el estado es **Borrador**, el cliente no lo ve en su portal.
- Al pulsar **Enviar al cliente**, pasa a **Enviado** y aparece
  automáticamente en `/my/projects` para ese contacto exacto (no para toda su
  empresa).
- El cliente abre el documento a pantalla completa en una pestaña nueva
  (se sirve como página web real, no como PDF), pero no puede editar ni
  comentar el proyecto.

## Seguridad

- `ir.rule` restringe la lectura en portal a `partner_id == usuario.partner_id`
  y excluye los borradores.
- El documento se sirve mediante una ruta propia (`/my/projects/<id>/file`,
  con `Content-Type: text/html`) que repite la misma comprobación de acceso,
  en vez de depender de la URL directa del adjunto (`/web/content/...`).

## Pendiente / posibles mejoras futuras

- Notificar por email al cliente cuando se envía un proyecto.
- Permitir aceptar/rechazar el proyecto desde el propio portal.
- Extender la visibilidad a toda la empresa (`commercial_partner_id`) si en el
  futuro se necesita que varios contactos de un mismo cliente vean los mismos
  proyectos.
