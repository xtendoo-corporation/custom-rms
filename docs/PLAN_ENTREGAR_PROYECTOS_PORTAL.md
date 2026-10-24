# Plan: Entregar Proyecto + accesos al portal (para implementar por una IA)

> Documento de trabajo para un agente de código. Describe **qué hay hoy**, **qué
> hay que cambiar** y **qué se puede romper**. Repositorio: `custom-rms`
> (Odoo 19, rama base `19.0`). Comprueba siempre el código antes de actuar: las
> referencias `archivo:línea` son orientativas.

## 0. Contexto que necesitas saber

- Módulos implicados:
  - `rms_portal_projects`: modelo `rms.installation.project`, app **"Entregar Proyecto"**,
    rutas de portal `/my/installation-projects[/<id>[/file]]`.
  - `rms_portal_profiles`: campo `res.partner.portal_profile` (`customer` / `marketing` /
    `projects`), grupos `group_portal_customer|marketing|projects`, guards de rutas de
    portal y asistente `rms.portal.invite.link` (botón **"Enlace portal"** del contacto).
  - `rms_portal_access_log`: histórico de accesos y actividad del portal
    (`rms.portal.activity.project_id` → `rms.installation.project`).
  - `rms_mail_server`: **bloquea todo email a dominios ≠ `@rmsproaudio.com`**. Las
    invitaciones y "he olvidado mi contraseña" nunca llegan al cliente; por eso existe
    "Enlace portal" (genera el enlace para enviarlo a mano).
  - `rms_training_academy`: lecciones `lesson_portal_access` (exige
    `base.group_erp_manager`) y `lesson_portal_projects` (depende del menú
    `rms_portal_projects.menu_installation_project` y tiene como prerrequisito la anterior).
- dbfilter `rms*`: hay BD `rms` y `rms-sandbox`. Probar en sandbox primero.
- **Cambios hechos a mano en la BD de producción (no están en el código):**
  - El menú raíz "Entregar Proyecto" tiene Visibilidad = `Rol / Administrador`.
  - Puede existir un grupo creado desde la interfaz llamado "Entregar Proyecto" con el
    usuario Jorge de la Casa, añadido también a la visibilidad del menú.

## 1. Objetivo

1. Que **solo un grupo concreto** (hoy: Jorge) **y los administradores** vean y usen
   "Entregar Proyecto".
2. Que ese grupo pueda, **sin ser administrador**:
   - dar acceso al portal a un contacto y obtener su enlace ("Enlace portal"),
   - dejarle el perfil de portal en **Proyectos**,
   - crear y enviar proyectos a ese contacto.
3. Hacerlo **sin abrir agujeros** en el portal (ver §4): que ese poder no sirva para
   tomar cuentas de clientes ni para exponer pedidos/facturas.
4. Hacer el flujo de entrega más fácil (§3.B).

## 2. Situación actual (problemas detectados)

### Permisos internos
- `rms_portal_projects/security/ir.model.access.csv`: **todo `base.group_user` tiene CRUD
  completo** sobre `rms.installation.project`.
- `rms_portal_projects/security/security.xml` (`rule_installation_project_internal`):
  regla `[(1,'=',1)]` para `base.group_user`. Cualquier empleado puede cambiar el
  `partner_id` de un proyecto **ya enviado** y el documento pasa a verlo otro cliente.
- Los menús (`views/installation_project_views.xml`) no tienen `groups`; la restricción
  actual es solo manual en BD y **solo oculta el menú** (los datos siguen accesibles por URL).

### Invitación / perfiles
- `rms_portal_profiles/wizard/portal_invite_link.py` `_check_manager()`: solo
  `base.group_erp_manager`. ACL del transient `rms.portal.invite.link` solo para ese grupo.
  El botón del contacto también tiene `groups="base.group_erp_manager"`.
- `rms_portal_profiles/models/res_partner.py` `_sync_portal_profile_groups()` escribe
  `group_ids` en `res.users` **sin sudo**: si un no-administrador cambia el perfil de un
  contacto que ya tiene usuario de portal → **AccessError** (bug actual).
- `portal_profile` tiene `default='customer'`. Un contacto al que se da acceso al portal
  sin tocar el perfil ve **pedidos y facturas de toda su empresa** (reglas estándar por
  `commercial_partner_id`).

### Seguridad del documento servido en el portal
- `rms_portal_projects/controllers/portal.py` `portal_installation_project_file` sirve el
  HTML subido con `Content-Type: text/html` **en el mismo dominio de Odoo y con la sesión
  del cliente**. Cualquier `<script>` del HTML se ejecuta como ese cliente (XSS
  almacenado): puede llamar a `/web/dataset/call_kw`, leer sus pedidos/facturas, cambiar
  sus datos de contacto, etc. Hoy cualquier empleado puede subir ese HTML.
- `Content-Disposition` se construye con `file_name` sin escapar.
- No se valida tipo ni tamaño del fichero subido.

### Incoherencias de visibilidad en portal
- `InstallationProjectsProfileGuard` (`rms_portal_profiles/controllers/portal_guards.py`)
  solo protege el **listado**, y permite perfiles **Cliente y Proyectos**. Las rutas de
  detalle y `/file` no comprueban perfil (sí comprueban `partner_id` y estado).
- `INSTRUCCIONES_EQUIPO.txt` dice que el perfil Cliente **no** ve "Proyectos" y que el
  cliente recibe un correo de invitación: ambas cosas son falsas hoy.

## 3. Cambios a implementar

### A. Grupo propio y permisos (`rms_portal_projects`)

1. Crear grupo `rms_portal_projects.group_installation_project_manager`
   ("Entregar Proyecto: gestor"), con su `res.groups.privilege` / categoría (patrón de
   `rms_portal_profiles/security/security_groups.xml`). `implied_ids` → `base.group_user`.
2. Que los administradores lo tengan siempre: añadir el grupo a `implied_ids` de
   `base.group_system` (`<record id="base.group_system" model="res.groups">` con
   `(4, ref(...))`).
3. Menús `menu_installation_project_root` y `menu_installation_project`:
   `groups="group_installation_project_manager"`.
4. ACL: CRUD completo para el grupo nuevo. **Quitar** la línea de `base.group_user`
   (ver riesgos §4.5 antes de hacerlo). Mantener la línea de `base.group_portal` (solo lectura).
5. `ir.rule` interna: cambiar el grupo de `rule_installation_project_internal` a
   `group_installation_project_manager`.
6. Integridad: impedir cambiar `partner_id` (y `file_data`) cuando `state != 'draft'`
   (obligar a "Volver a borrador"). Opcional: regla multicompañía estándar
   (`company_id in company_ids`).

### B. Flujo de entrega más fácil (`rms_portal_projects` + `rms_portal_profiles`)

1. En el formulario del proyecto, mostrar el **estado del portal del cliente**: tiene
   usuario de portal sí/no, perfil, último acceso (computados con sudo, solo lectura).
2. Botón en el proyecto **"Dar acceso / Enlace portal"** que llame al mismo asistente
   `rms.portal.invite.link` para `partner_id`.
3. Dominio de `partner_id`: contactos persona (`is_company = False`) con email.
4. Al pulsar "Enviar al cliente", abrir un pequeño asistente con un **texto listo para
   copiar** (enlace a `/my/installation-projects/<id>` y, si el contacto aún no ha
   entrado nunca, el enlace de registro), porque Odoo no puede enviarle email.
5. Botones "Marcar aceptado" / "Marcar rechazado" (hoy los estados existen pero no hay
   botón; ver tip de `lesson_portal_projects`).
6. Validar el fichero: extensión `.html/.htm`, tamaño máximo razonable (p. ej. 20 MB).

### C. Que el gestor pueda dar acceso sin ser administrador (`rms_portal_profiles`)

`rms_portal_profiles` ya depende de `rms_portal_projects`, así que puede referenciar el grupo.

1. `_check_manager()`: permitir `base.group_erp_manager` **o**
   `rms_portal_projects.group_installation_project_manager`. Añadir ACL del transient
   `rms.portal.invite.link` para el grupo y poner el grupo en el `groups` del botón.
2. **Restricciones para quien no sea `group_erp_manager`** (imprescindibles, §4):
   - Contacto **sin usuario de portal**: antes de conceder el acceso, fijar
     `portal_profile = 'projects'` (con sudo), y después conceder. Así nunca nace un
     usuario con perfil Cliente desde este camino.
   - Contacto **con usuario de portal** y perfil ≠ `projects`: **rechazar** (UserError
     "Este contacto es un cliente con acceso completo; pídeselo a un administrador").
   - Contacto con usuario interno: ya se rechaza; mantenerlo.
   - Registrar en el chatter del contacto quién generó el enlace y de qué tipo
     (`signup`/`reset`), para auditoría.
3. `portal_profile`:
   - `_sync_portal_profile_groups()` debe escribir en `res.users` con `sudo()` **después**
     de comprobar permisos en `res.partner.write`.
   - En `write`, si cambia `portal_profile` y el usuario no es `group_erp_manager`:
     solo permitir el valor `'projects'` y solo si el contacto no tiene usuario de portal
     o ya era `'projects'`. En cualquier otro caso, AccessError.
4. `rms_training_academy`: en `lesson_portal_access` cambiar `group_xmlids` a
   `base.group_erp_manager,rms_portal_projects.group_installation_project_manager`
   (si no, `lesson_portal_projects` queda bloqueada por su prerrequisito para Jorge).
   Revisar que el `depends` del módulo de formación no cree un ciclo; si lo crea, dejar
   el xmlid como texto (el campo es Char y `env.ref(..., raise_if_not_found=False)`).

### D. Endurecer el portal

1. En `portal_installation_project_file` añadir cabeceras:
   - `Content-Security-Policy: sandbox allow-scripts allow-popups allow-popups-to-escape-sandbox allow-downloads`
     (**sin** `allow-same-origin`: el documento corre en origen opaco y no puede usar la
     sesión del cliente).
   - `X-Content-Type-Options: nosniff`, `Referrer-Policy: no-referrer`,
     `Cache-Control: private, no-store`.
   - `Content-Disposition` con `odoo.http.content_disposition(file_name)`.
   - Comprobar que el botón inyectado "Volver al portal" (`href="/my"`) sigue funcionando
     dentro del sandbox (navegación del propio documento de nivel superior: sí debería).
2. Unificar guards: detalle y `/file` deben aplicar el mismo criterio de perfil que el
   listado. Decidir con el usuario si el perfil **Cliente** debe ver "Proyectos" (hoy sí
   lo ve; la documentación dice que no) y alinear código, plantilla y documentación.
3. Actualizar `INSTRUCCIONES_EQUIPO.txt` y `README.md` de `rms_portal_projects` (sin
   email de invitación; "Enlace portal"; perfil Proyectos; grupo nuevo).

## 4. Qué se puede romper / riesgos de dar este poder a un no-administrador

1. **Toma de cuentas de clientes.** "Enlace portal" sobre un usuario que ya entró genera
   un enlace de *restablecer contraseña*. Si el gestor pudiera hacerlo con cualquier
   contacto, podría poner la contraseña de un cliente y entrar como él (ver sus
   facturas, pedidos, presupuestos). Lo mismo cambiando antes el email del contacto.
   → Mitigación §3.C.2: solo contactos con perfil `projects` + auditoría en chatter.
2. **Exposición de pedidos y facturas.** Con `default='customer'`, un acceso concedido a
   un contacto de una empresa ve todo lo de esa empresa. → Forzar `projects` (§3.C.2).
3. **Quitar acceso a clientes reales.** Cambiar el perfil de un contacto con perfil
   Cliente a Proyectos le oculta pedidos y facturas. → Restricción de §3.C.3.
4. **Escalada a usuario interno.** El asistente usa `portal.wizard` con sudo; asegurarse
   de que solo se crean usuarios `share=True` con `base.group_portal` y nunca se toca un
   usuario interno (ya se comprueba; añadir test).
5. **Otros empleados pierden acceso a datos de proyectos** al quitar la ACL de
   `base.group_user`:
   - `rms_portal_access_log`: `rms.portal.activity.project_id` es Many2one a
     `rms.installation.project` y **todos** los internos pueden leer la actividad
     (menús "Actividad", "Intereses por cliente", botón en el contacto, informe semanal).
     Mostrar ese campo a un usuario sin acceso puede dar AccessError o "sin acceso" en
     listas/formularios/pivot. Probarlo. Alternativas: guardar el nombre en un Char
     (`name` ya lo guarda) y poner `groups=` en el campo `project_id` de las vistas, o
     mantener solo lectura para `base.group_user` (pero entonces el objetivo 1 queda en
     "solo oculta el menú").
   - Informe semanal (`portal_weekly_report.py`): se ejecuta por cron como superusuario;
     verificar que no lee proyectos con el usuario destinatario.
   - `rms_training_academy`: `lesson_portal_projects` desaparecerá para quien no vea el
     menú (es lo deseado); revisar prerrequisito (§3.C.4).
6. **Cambios manuales en BD.** Al actualizar, Odoo *añade* los grupos del `menuitem`
   pero no quita los puestos a mano: el menú seguirá teniendo `Rol / Administrador` (no
   molesta) y el grupo creado a mano (sobra). Tras desplegar: pasar a Jorge al grupo
   nuevo y borrar el grupo manual.
7. **CSP sandbox puede romper documentos HTML** que usen `localStorage`/`sessionStorage`,
   cookies, `fetch` al mismo dominio o formularios. Probar con documentos reales antes
   de desplegar; si alguno lo necesita, ampliar `sandbox` con cuidado (nunca
   `allow-same-origin` junto a `allow-scripts`).
8. **Emails duplicados.** `portal.wizard` falla si ya hay un usuario con ese login/email.
   El error debe llegar claro al gestor.
9. **Enlaces existentes** `/my/installation-projects/<id>/file` deben seguir funcionando.
10. **Orden de actualización**: actualizar `rms_portal_projects`, `rms_portal_profiles`,
    `rms_portal_access_log` y `rms_training_academy` juntos (`-u` de los cuatro).

## 5. Tests mínimos (TransactionCase / HttpCase)

- Usuario interno sin grupo: no ve el menú; no puede leer/crear `rms.installation.project`.
- Gestor (no admin):
  - crea proyecto, lo envía; no puede cambiar `partner_id` estando enviado;
  - genera enlace para contacto nuevo → usuario portal creado con perfil `projects` y
    grupo `group_portal_projects`, nunca `group_portal_customer`;
  - **no** puede generar enlace para contacto con perfil `customer` con usuario existente;
  - **no** puede poner `portal_profile` distinto de `projects`; cambiarlo no da AccessError
    por `res.users` en los casos permitidos;
  - no puede generar enlace para un contacto con usuario interno.
- Admin: sigue pudiendo todo como hoy.
- Portal: el cliente solo ve sus proyectos no-borrador; la respuesta `/file` lleva la
  cabecera CSP `sandbox`; otro cliente recibe redirección a `/my`.
- Vistas de `rms.portal.activity` abiertas por un interno sin el grupo no fallan.

## 6. Pasos manuales tras desplegar

1. Actualizar los 4 módulos (primero en `rms-sandbox`).
2. Ajustes > Usuarios > Jorge de la Casa > marcar "Entregar Proyecto: gestor".
3. Borrar el grupo "Entregar Proyecto" creado a mano y quitarlo de la visibilidad del menú.
4. Revisar contactos que ya tienen proyectos enviados: que su perfil sea `projects` (o
   `customer` si de verdad son clientes con pedidos).
