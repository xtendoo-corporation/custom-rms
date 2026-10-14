# RMS Notificar Errores a Soporte (IA)

Añade un botón **"Notificar a soporte"** a las ventanas de error de Odoo 19
(tanto el "Oops! Something went wrong" de los fallos de código como los
avisos de validación tipo *"Error de validación: …"*). Con un clic, soporte
recibe un aviso en Conversaciones con un **informe de la IA (Claude)**:
qué falla, por qué falla, qué módulo lo provoca, gravedad y posibles
soluciones (con parche propuesto cuando aplica).

## Cómo funciona

1. El usuario pulsa **Notificar a soporte**, escribe opcionalmente qué
   estaba haciendo y pulsa **Enviar a soporte**.
2. Se crea una **Incidencia de soporte** (`rms.support.ticket`) con el tipo
   de error, el mensaje, el traceback técnico que Odoo ya manda al
   navegador, la URL y el modelo/registro de la pantalla.
   - Si el mismo error ya está abierto (misma excepción y misma pila de
     llamadas, aunque cambie el documento) **no se duplica**: se suma una
     ocurrencia y el usuario se añade a "Usuarios afectados".
   - Máximo 20 avisos por usuario y hora.
3. Un cron (que se lanza al instante) manda a Claude:
   - el error y el traceback,
   - el **código fuente** de las funciones implicadas, leído del propio
     servidor: la función completa en los módulos propios de este
     repositorio y unas líneas alrededor en el código estándar de Odoo,
   - si el error ocurre dentro de una **acción de servidor o automatización**
     creada desde la interfaz de Odoo, su código (que vive en la base de
     datos, no en ningún fichero),
   - los ficheros de módulos propios que **extienden el modelo afectado**
     (p. ej. todos los que heredan `sale.order`), que es donde suelen estar
     las inconsistencias entre módulos,
   - la lista de módulos propios instalados con su versión.
4. El informe se guarda en la incidencia y se publica un resumen con enlace
   en el canal de Conversaciones **"Soporte Odoo"**.

La IA **solo diagnostica**: no modifica código ni datos. Revisa siempre el
informe antes de aplicar cambios.

## Quién recibe los avisos

El canal **Soporte Odoo** (app Conversaciones) es privado para el grupo
**"Recibe incidencias de soporte"**, y todos los usuarios del grupo quedan
suscritos automáticamente. Para que alguien reciba los avisos:

Ajustes → Usuarios → (usuario) → permiso *Soporte (RMS) / Incidencias de soporte*.

Al instalar se añade el usuario administrador. Los usuarios del grupo ven
también el menú **Incidencias de soporte**, donde pueden:
- leer el informe completo, el traceback y el contexto,
- **Reanalizar con IA** (p. ej. tras configurar la clave o si el análisis
  falló),
- marcar como **Resuelta** o **Descartada**. Si un error resuelto vuelve a
  aparecer, se abre una incidencia nueva.

## Configuración

Ajustes → Técnico → Parámetros del sistema:

| Parámetro | Valor |
|---|---|
| `rms_support_error_report.anthropic_api_key` | API key de Anthropic. Si no se pone, usa la de `rms_ai_help_assistant` o `rms_ai_quote_assistant`. |
| `rms_support_error_report.anthropic_model` | Modelo. Por defecto `claude-sonnet-5-5`. |
| `rms_support_error_report.anthropic_workspace_id` | Solo para claves vinculadas a un workspace (igual que en los otros asistentes). |

Coste orientativo: cada informe nuevo son unas decenas de miles de tokens
de entrada (sobre todo código), del orden de 0,08–0,15 € por incidencia.
Los errores repetidos no se vuelven a analizar.

## Seguridad y privacidad

- Los usuarios normales no tienen acceso al modelo: la incidencia se crea
  con `sudo()` desde `report_error`, que solo acepta campos de texto
  (recortados) y fija el usuario en el servidor. Solo usuarios internos.
- Las rutas del traceback las manda el navegador, así que no se confía en
  ellas: solo se leen ficheros `.py` dentro de las carpetas de addons de
  Odoo y de este repositorio.
- Se envía a Anthropic el mensaje de error, el traceback, el comentario del
  usuario y código fuente (incluido el de las acciones de servidor
  implicadas); **no** se envían los valores de los registros.
  Ten en cuenta que el mensaje de error puede incluir nombres de documentos
  o clientes.
