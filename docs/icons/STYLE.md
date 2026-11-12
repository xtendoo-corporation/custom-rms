# Sistema de iconos Odoo 19

Familia visual nativa de Odoo 19 para los módulos personalizados de RMS Pro Audio. Referencias: `los SVG de addons/*/static/description/icon.svg de Odoo 19/*.svg`.

## Construcción

- Raíz obligatoria: `<svg xmlns="http://www.w3.org/2000/svg" width="512" height="512" viewBox="0 0 50 50">`. El renderizador necesita 512 × 512; las coordenadas de dibujo usan la cuadrícula de 50 × 50 de Odoo.
- Fondo transparente, sin forma de fondo: Odoo dibuja la tarjeta blanca.
- El contenido ocupa aproximadamente x = 2…48 e y = 4…46, centrado visualmente.
- Solo formas planas rellenas: `<path>`, `<rect>` y `<circle>`. Geometría gruesa, contundente y sencilla, con esquinas redondeadas de radio aproximado 3–4. Las formas se solapan o se tocan como en las referencias.
- Sin trazos, degradados, opacidad, filtros, texto ni `<style>`.
- Usar 2–3 colores por icono, combinando un tono oscuro y uno vivo. Reservar `#fff` para pequeños detalles de recorte.
- Mantener siluetas distintas entre módulos y respecto a CRM, Ventas y Contactos de Odoo. La metáfora debe reconocerse a 44 px.

## Paleta Odoo 19

Colores permitidos exclusivamente: `#985184` (morado), `#1AD3BB` (menta), `#2EBCFA` (cielo), `#144496` (marino), `#FBB945` (amarillo), `#F86126` (naranja), `#F78613` (naranja claro), `#FC868B` (rosa), `#1A6F66` (verde azulado oscuro), `#005E7A` (petróleo), `#962B48` (vino), `#088BF5` (azul) y `#fff` (detalles pequeños).

## Módulos y metáforas

Ideas basadas en el resumen de cada `__manifest__.py`; los nombres y textos explicativos no se dibujan en los iconos.

| Módulo | Idea de pictograma |
| --- | --- |
| `product_pricelist_triple_discount` | Tres etiquetas escalonadas para los tres descuentos de tarifa. |
| `rms_comerciales_tasks_shortcut` | Portapapeles de pedido con marca de verificación y persona para «Mis pedidos de venta». |
| `rms_crm_hide_company_avatar` | Tarjeta de oportunidad con filas limpias y un espacio de avatar vacío. |
| `rms_quotation_import` | Hoja de presupuesto con flecha entrante desde una cuadrícula. |
| `rms_sale_catalog_no_variant_color` | Cuadrícula de catálogo con tarjetas de variantes de aspecto uniforme. |
| `rms_sale_category_product_manager` | Presupuesto enlazado a una persona responsable de categoría. |
| `rms_ventas_restriccion_comerciales` | Escudo con candado sobre una ficha comercial. |
| `rms_document_format` | Hoja de presupuesto con bloques de maquetación y esquina doblada. |
| `rms_partner_display_name` | Silueta de contacto con una única línea de identificación. |
| `rms_partner_multi_role` | Persona conectada a tres distintivos de rol. |
| `rms_partner_import` | Ficha de contacto con flecha entrante que atraviesa una puerta abierta. |
| `rms_product_state` | Caja con selector de estado de tres posiciones. |
| `rms_stock_barcode_scan` | Código de barras entre esquinas de encuadre de cámara. |
| `rms_stock_lot_label_print` | Impresora con etiqueta de código de barras saliente. |
| `stock_cession` | Caja entre dos flechas de ida y vuelta para la mercancía cedida. |
| `rms_product_import` | Cuadrícula con flecha hacia una caja de producto. |
| `rms_customer_equipment_map` | Marcador de ubicación con un altavoz para equipos instalados. |
| `rms_global_equipment_map` | Globo con dos marcadores de instalaciones. |
| `rms_partner_equipment_model_import` | Flecha entrante hacia un altavoz vinculado a una ficha de compañía. |
| `rms_hr_employee_certification` | Diploma con sello y flecha circular de renovación. |
| `rms_hr_expense_ai_access` | Ticket con llave de acceso y un destello de IA. |
| `rms_hr_expense_ai_email` | Sobre del que emerge un ticket con un destello de IA. |
| `rms_hr_expense_quick_capture` | Móvil con encuadre de cámara alrededor de un ticket. |
| `rms_training_academy` | Libro abierto con tres peldaños de progreso. |
| `rms_portal_access_log` | Ventana de portal con reloj de historial. |
| `rms_portal_catalog` | Ventana de portal con cuadrícula de productos. |
| `rms_portal_profiles` | Ventana de portal con personas y pequeño candado de acceso. |
| `rms_portal_projects` | Carpeta de proyecto con hoja compartida hacia un cliente. |
| `rms_web_redirect` | Ventana con flecha que sale hacia un sitio externo. |
| `rms_ai_help_assistant` | Bocadillo de ayuda con destello de IA y libro abierto. |
| `rms_ai_quote_assistant` | Presupuesto con destello de IA y burbuja de conversación. |
| `rms_support_error_report` | Triángulo de alerta enviado hacia un bocadillo de soporte. |
| `rms_custom_knowledge` | Carpeta con libro abierto y hoja convertida en líneas estructuradas. |
| `rms_chatter_hide_send_message` | Bocadillo con hoja y lápiz para las notas internas. |
| `rms_mail_server` | Sobre protegido por escudo para el correo saliente restringido. |


## Entrega y renderizado

- Cada módulo tiene `static/description/icon.svg` como fuente; el PNG de 512 × 512 es un derivado. No editar los PNG manualmente.
- Partir de `docs/icons/template.svg` y añadir únicamente las formas del pictograma, manteniendo el fondo transparente.
- SVG autónomos, sin recursos externos ni fuentes enlazadas.
- Validar cada SVG con `xmllint --noout ruta/al/icon.svg`.
- Para regenerar derivados cuando corresponda, ejecutar `bash docs/icons/build_icons.sh` o seleccionar módulos como argumentos. Requiere Chrome o Chromium (variable `CHROME`).
