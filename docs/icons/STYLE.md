# Sistema de iconos «unified RMS»

Familia visual para los módulos personalizados de RMS Pro Audio. Este documento define el sistema; no incluye iconos de módulos.

## Construcción

- SVG de 512 × 512, con `viewBox="0 0 512 512"`.
- Fondo a sangre: cuadrado redondeado de 512 × 512 con `rx="96"`, sin contorno. Gradiente lineal vertical del tono superior indicado al color base del área: mezcla aproximada del 8 % de blanco arriba, misma familia de tono.
- Sin sombras proyectadas ni sombras largas. Sin texto ni letras, salvo las dos excepciones de accesos externos indicadas abajo.
- Pictograma plano blanco (`#FFFFFF`), geométrico y centrado ópticamente dentro del área segura de 288 × 288, desde `(112, 112)` hasta `(400, 400)`. Incluir el grosor completo del trazo dentro de estos límites.
- Usar trazos de unos 28 px con extremos y uniones redondos, o formas sólidas de peso visual equivalente. Mantener un lenguaje consistente dentro de cada pictograma.
- Se permite un único elemento de acento: un tinte claro del color del área o amarillo cálido `#FFD166`. No añadir otros colores decorativos.
- Priorizar una silueta sencilla y pocos detalles. Revisar a 64 × 64 px: la metáfora debe seguir siendo reconocible y los huecos no deben cerrarse.

## Paleta por área

El color base es el extremo inferior del gradiente. No usar el morado de Odoo (`#714B67`) como color principal.

| Área | Base | Superior (~8 % blanco) |
| --- | --- | --- |
| Ventas/CRM | `#2563EB` | `#3670ED` |
| Almacén/Producto | `#C86420` | `#CC7032` |
| Mapas/Equipos | `#16836B` | `#298D77` |
| RRHH/Gastos/Formación | `#BB4565` | `#C05471` |
| Portal/Web | `#087FAD` | `#1C89B4` |
| IA/Soporte | `#6554C0` | `#7162C5` |
| Sistema/Correo/Utilidades | `#526174` | `#606E7F` |

## Módulos y metáforas

Ideas basadas en el resumen de cada `__manifest__.py`; los nombres y textos explicativos no se dibujan en los iconos.

| Módulo | Área | Idea de pictograma |
| --- | --- | --- |
| `product_pricelist_triple_discount` | Ventas/CRM | Tres etiquetas escalonadas para los tres descuentos de tarifa. |
| `rms_comerciales_tasks_shortcut` | Ventas/CRM | Lista de tareas con una flecha de acceso directo. |
| `rms_crm_hide_company_avatar` | Ventas/CRM | Tarjeta de oportunidad con filas limpias y un espacio de avatar vacío. |
| `rms_quotation_import` | Ventas/CRM | Hoja de presupuesto con flecha entrante desde una cuadrícula. |
| `rms_sale_catalog_no_variant_color` | Ventas/CRM | Cuadrícula de catálogo con tarjetas de variantes de aspecto uniforme. |
| `rms_sale_category_product_manager` | Ventas/CRM | Presupuesto enlazado a una persona responsable de categoría. |
| `rms_ventas_restriccion_comerciales` | Ventas/CRM | Escudo con candado sobre una ficha comercial. |
| `rms_document_format` | Ventas/CRM | Hoja de presupuesto con bloques de maquetación y esquina doblada. |
| `rms_partner_display_name` | Ventas/CRM | Silueta de contacto con una única línea de identificación. |
| `rms_partner_multi_role` | Ventas/CRM | Persona conectada a tres distintivos de rol. |
| `rms_partner_import` | Ventas/CRM | Ficha de contacto con flecha entrante que atraviesa una puerta abierta. |
| `rms_product_state` | Almacén/Producto | Caja con selector de estado de tres posiciones. |
| `rms_stock_barcode_scan` | Almacén/Producto | Código de barras entre esquinas de encuadre de cámara. |
| `rms_stock_lot_label_print` | Almacén/Producto | Impresora con etiqueta de código de barras saliente. |
| `stock_cession` | Almacén/Producto | Caja entre dos flechas de ida y vuelta para la mercancía cedida. |
| `rms_product_import` | Almacén/Producto | Cuadrícula con flecha hacia una caja de producto. |
| `rms_customer_equipment_map` | Mapas/Equipos | Marcador de ubicación con un altavoz para equipos instalados. |
| `rms_global_equipment_map` | Mapas/Equipos | Globo con dos marcadores de instalaciones. |
| `rms_partner_equipment_model_import` | Mapas/Equipos | Flecha entrante hacia un altavoz vinculado a una ficha de compañía. |
| `rms_hr_employee_certification` | RRHH/Gastos/Formación | Diploma con sello y flecha circular de renovación. |
| `rms_hr_expense_ai_access` | RRHH/Gastos/Formación | Ticket con llave de acceso y un destello de IA. |
| `rms_hr_expense_ai_email` | RRHH/Gastos/Formación | Sobre del que emerge un ticket con un destello de IA. |
| `rms_hr_expense_quick_capture` | RRHH/Gastos/Formación | Móvil con encuadre de cámara alrededor de un ticket. |
| `rms_training_academy` | RRHH/Gastos/Formación | Libro abierto con tres peldaños de progreso. |
| `rms_portal_access_log` | Portal/Web | Ventana de portal con reloj de historial. |
| `rms_portal_catalog` | Portal/Web | Ventana de portal con cuadrícula de productos. |
| `rms_portal_profiles` | Portal/Web | Ventana de portal con personas y pequeño candado de acceso. |
| `rms_portal_projects` | Portal/Web | Carpeta de proyecto con hoja compartida hacia un cliente. |
| `rms_web_redirect` | Portal/Web | Ventana con flecha que sale hacia un sitio externo. |
| `rms_ai_help_assistant` | IA/Soporte | Bocadillo de ayuda con destello de IA y libro abierto. |
| `rms_ai_quote_assistant` | IA/Soporte | Presupuesto con destello de IA y burbuja de conversación. |
| `rms_support_error_report` | IA/Soporte | Triángulo de alerta enviado hacia un bocadillo de soporte. |
| `rms_custom_knowledge` | IA/Soporte | Carpeta con libro abierto y hoja convertida en líneas estructuradas. |
| `rms_chatter_hide_send_message` | Sistema/Correo/Utilidades | Bocadillo con hoja y lápiz para las notas internas. |
| `rms_mail_server` | Sistema/Correo/Utilidades | Sobre protegido por escudo para el correo saliente restringido. |

## Entrega y renderizado

- Cada módulo tendrá `static/description/icon.svg` como fuente y `static/description/icon.png` como derivado de 512 × 512 px. No editar el PNG manualmente.
- `rms_web_redirect` tendrá además `static/img/sala_in.svg` y `static/img/club.svg`, con sus derivados `sala_in.png` y `club.png` de 256 × 256 px. Aplicar Portal/Web y las mismas proporciones; solo estos dos pictogramas pueden conservar los textos cortos «IN» y «CLUB».
- SVG autónomos: sin recursos externos ni fuentes enlazadas. Para las excepciones de texto, preferir convertir a trazados; si se mantiene texto, usar `font-family="sans-serif"` y `font-weight="bold"`.
- Partir de `docs/icons/template.svg`, sustituir su gradiente por el del área y añadir el pictograma. La guía comentada no se exporta.
- Ejecutar `bash docs/icons/build_icons.sh` para todos los SVG, o `bash docs/icons/build_icons.sh modulo_a modulo_b` para una selección. Requiere Chrome o Chromium (variable `CHROME` para otra ruta); el renderizador interno de ImageMagick pinta los degradados en negro; sobrescribe únicamente los PNG correspondientes a SVG existentes. No crea pictogramas ni fuentes SVG.
