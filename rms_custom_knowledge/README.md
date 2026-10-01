# Módulo de Gestión de Documentos y Biblioteca de Conocimiento (Knowledge)

Este módulo añade una central de documentos (Biblioteca de Conocimiento) donde los empleados pueden consultar o subir archivos estructurados por directorios, con un sistema de permisos jerárquicos basado en **Grupos de Usuarios de Odoo**.

---

## 📋 Guía Rápida para el Administrador del Sistema

Como administrador, tienes control total para crear la estructura de carpetas, definir los grupos de usuarios y controlar quién puede leer, escribir o eliminar en cada directorio. Sigue estos pasos para configurarlo todo desde cero:

---

### Paso 1: Actualización del Módulo
Antes de empezar a configurar, asegúrate de aplicar los últimos cambios:
1. Sube los archivos actualizados al servidor de producción.
2. Actualiza el módulo `rms_custom_knowledge` desde el menú de **Aplicaciones** en Odoo (o mediante terminal/contenedor si procede).
3. Recarga la página en tu navegador.

---

### Paso 2: Crear y Organizar los Grupos de Usuarios
El sistema de permisos se gestiona a través de los **Grupos** de Odoo. 
1. Ve a **Ajustes** ➡️ **Usuarios y Compañías** ➡️ **Grupos**.
2. Haz clic en **Nuevo** para crear grupos específicos según las áreas de tu empresa, por ejemplo:
   * *Knowledge - Lectores Administración*
   * *Knowledge - Editores Ventas*
   * *Knowledge - Dirección General*
3. Añade a los empleados correspondientes en la pestaña **Usuarios** de cada grupo.

---

### Paso 3: Acceder a la Administración de Directorios (Biblioteca)
Una vez actualizado el módulo, verás un nuevo menú:
1. Ve a la aplicación **Conocimiento** (Knowledge).
2. Como administrador del sistema, en la parte superior te aparecerá una opción llamada **Biblioteca**.
3. Al entrar en **Biblioteca**, verás un listado con todos los directorios del sistema (incluyendo el directorio raíz **General**).

---

### Paso 4: Crear Nuevos Directorios y Subdirectorios
Puedes diseñar la estructura de carpetas que desees:
1. Desde **Biblioteca**, haz clic en **Nuevo** para crear una nueva carpeta raíz.
2. Si quieres crear una **subcarpeta** dentro de otra existente:
   * Indica la carpeta contenedora en el campo **Parent Directory** (Directorio Padre).
   * Odoo calculará automáticamente la ruta jerárquica (el nombre completo con la estructura del árbol de directorios).

---

### Paso 5: Configurar los Permisos de las Carpetas
En el formulario de cualquier directorio (en la pestaña **Biblioteca**), verás una pestaña inferior llamada **Permisos**:

1. Haz clic en **Agregar línea**.
2. Selecciona el **Grupo** de Odoo (creado en el Paso 2) al que quieres aplicar la regla.
3. Elige uno de los tres niveles de permisos disponibles:
   * **Lectura**: Los usuarios del grupo pueden ver el directorio y descargar los archivos.
   * **Lectura y Escritura**: Los usuarios pueden ver la carpeta, subir nuevos archivos y crear subdirectorios dentro de ella.
   * **Lectura, Escritura y Eliminación**: Los usuarios tienen acceso total sobre la carpeta y sus archivos (incluyendo borrar carpetas y documentos).

#### ⚠️ Reglas Importantes de Permisos (Herencia y Conflicto)
* **El Directorio "General"**: Por defecto, todos los usuarios internos de la base de datos tienen permisos de **Lectura** automáticos en el directorio "General" y sus hijos. No hace falta crear reglas de lectura manuales para que la gente vea esta carpeta.
* **Herencia en Cascada**: Cualquier subdirectorio hereda por defecto los permisos de su directorio padre de forma automática.
* **Restricción y Sobrescritura**: Si quieres restringir una subcarpeta específica dentro de una carpeta pública, añade una línea de permiso para esa subcarpeta específica. Los permisos definidos directamente en una carpeta hija sobrescriben las reglas heredadas de la carpeta padre.
* **Resolución de Conflictos**: Si un empleado pertenece a más de un grupo con permisos en la misma carpeta (por ejemplo, Grupo A tiene *Lectura* y Grupo B tiene *Lectura y Escritura*), Odoo le otorgará siempre **el nivel de acceso más alto** asignado a sus grupos (en este caso, *Lectura y Escritura*).

---

## 📂 Subida e Aislamiento de Documentos

Para subir un archivo a un directorio concreto:
1. Ve a **Conocimiento** ➡️ Selecciona la carpeta correspondiente en el panel Kanban/Lista.
2. Haz clic en **Subir documento** o arrastra el archivo directamente.
3. Los documentos subidos aquí quedan marcados como `is_knowledge_document = True` y vinculados únicamente a esta sección.
4. **Independencia del sistema**: Ningún adjunto del CRM, de tareas de proyectos o de correos electrónicos aparecerá en esta biblioteca, manteniendo tu centro de documentación limpio de archivos temporales del sistema.

---

## ✏️ Edición de Excel en el navegador (OnlyOffice)

Los archivos `.xlsx`/`.xls`/`.ods`/`.csv` de Knowledge se pueden editar directamente desde el navegador (fórmulas y formato incluidos) usando un servidor **OnlyOffice Document Server self-hosted** (gratuito, sin licencia Enterprise de Odoo).

### Paso 1: Desplegar OnlyOffice Document Server

Añade este servicio a tu `docker-compose.yml` de producción (junto al de Odoo, en la misma red):

```yaml
onlyoffice:
  image: onlyoffice/documentserver:latest
  restart: unless-stopped
  environment:
    JWT_ENABLED: "true"
    JWT_SECRET: "<mismo-secreto-que-pondrás-en-Ajustes>"
  volumes:
    - onlyoffice_data:/var/www/onlyoffice/Data
    - onlyoffice_logs:/var/log/onlyoffice
```

Expón ese servicio con dominio propio y HTTPS (p.ej. `office.tudominio.com`) a través de tu proxy inverso habitual (Nginx, Traefik, etc.), igual que ya haces con Odoo. Odoo y OnlyOffice deben poder alcanzarse mutuamente por HTTPS: OnlyOffice descarga el archivo desde Odoo y Odoo recibe el guardado desde OnlyOffice.

### Paso 2: Dependencia Python

El módulo necesita `PyJWT` en el contenedor de Odoo. En un despliegue Doodba, añade `PyJWT` a `custom/dependencies/pip.txt` y reconstruye la imagen.

### Paso 3: Configurar en Odoo

**Ajustes** ➡️ **General Settings** ➡️ bloque **Knowledge - OnlyOffice** (solo visible para Administradores):
* **URL del servidor OnlyOffice**: `https://office.tudominio.com`
* **Secreto JWT**: el mismo valor que `JWT_SECRET` del contenedor. Puedes dejarlo vacío mientras pruebas en local sin JWT, pero en producción con dominio público **es obligatorio** para que nadie pueda suplantar al servidor de documentos.

### Uso

En cualquier documento de hoja de cálculo dentro de Knowledge aparecerá el botón **"Editar con OnlyOffice"** (en la ficha del documento y en la tarjeta Kanban). Se abre en una pestaña nueva; los cambios se guardan automáticamente sobre el mismo adjunto. Si el usuario solo tiene permiso de lectura en esa carpeta, el editor se abre en modo solo lectura.
