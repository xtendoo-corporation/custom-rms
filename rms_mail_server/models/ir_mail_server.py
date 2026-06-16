# -*- coding: utf-8 -*-
import logging
from email.utils import getaddresses
from odoo import models

_logger = logging.getLogger(__name__)

class IrMailServer(models.Model):
    _inherit = 'ir.mail_server'

    def send_email(self, message, *args, **kwargs):
        # 1. Extraer todos los destinatarios del correo (Para, CC y CCO)
        destinatarios = []
        if message.get('To'):
            destinatarios.extend(message.get_all('to', []))
        if message.get('Cc'):
            destinatarios.extend(message.get_all('cc', []))
        if message.get('Bcc'):
            destinatarios.extend(message.get_all('bcc', []))

        # Parsear direcciones de correo de forma robusta
        # getaddresses recibe una lista de cabeceras y devuelve una lista de tuplas (nombre, email)
        direcciones_parseadas = getaddresses(destinatarios)

        # 2. Verificar si hay algún correo que NO sea de la empresa
        for nombre, correo in direcciones_parseadas:
            correo_limpio = correo.strip().lower()
            
            # Solo comprobamos direcciones no vacías (por si acaso hubiera cabeceras mal formadas)
            if correo_limpio and not correo_limpio.endswith('@rmsproaudio.com'):
                # LOG de aviso en el servidor (para control vuestro)
                _logger.warning(
                    f"🚫 CORREO BLOQUEADO: Se intentó enviar un email a '{correo_limpio}' fuera del dominio permitido."
                )
                
                # Devolvemos el ID simulado del mensaje para que Odoo crea que se envió, 
                # pero cortamos la ejecución real para que NUNCA llegue al servidor SMTP real.
                return message.get('Message-Id') or 'blocked-mail-id'

        # 3. Si todos los correos son de @rmsproaudio.com, continúa el envío normal
        return super(IrMailServer, self).send_email(message, *args, **kwargs)
