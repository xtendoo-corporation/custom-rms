# Incidencias de soporte resueltas

## Lista de precios vacía al crear/editar un contacto (04/11/2026)

**Síntoma:** en la ficha de contacto, pestaña *Ventas y compras*, el desplegable
**Lista de precios** aparece vacío y no deja seleccionar ninguna tarifa
(caso: Pepa Sivianes, compañía activa "Espacio Tecnológico Audiovisual S.L.").

**Causa:** el usuario no tenía seleccionadas todas las empresas en el selector
de compañías (arriba a la derecha). Odoo solo ofrece las listas de precios de
las compañías activas o sin compañía, así que las tarifas de las otras
empresas no salían. No es un fallo de los módulos custom: la restricción de
`rms_ventas_restriccion_comerciales` solo afecta al grupo COMERCIALES.

**Solución:** marcar todas las empresas en el selector de compañías. Después,
cerrar sesión y volver a entrar.

Si sigue sin salir, revisar en *Ventas → Productos → Listas de precios* el
campo **Compañía** de cada tarifa y si alguna está archivada. Comprobar también
que el usuario tiene permitida esa compañía en *Ajustes → Usuarios*.
