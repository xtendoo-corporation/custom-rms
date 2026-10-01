from odoo import http
from odoo.http import request

from odoo.addons.auth_signup.controllers.main import AuthSignupHome
from odoo.addons.web.controllers.utils import ensure_db

# Rutas a las que se permite saltar desde /web/login sin estar logueado.
SIGNUP_REDIRECT_PREFIXES = ('/web/signup?', '/web/reset_password?')


class SignupDbRedirect(AuthSignupHome):
    """El dbfilter ``rms*`` casa con ``rms`` y ``rms-sandbox``, así que un
    visitante sin sesión no tiene base de datos y ``/web/signup`` da 404
    (el ``?db=`` solo lo aplican las rutas que llaman a ``ensure_db``).

    Los enlaces de invitación pasan por ``/web/login?db=rms&redirect=...``:
    ``ensure_db`` fija la BD en la sesión y aquí saltamos al registro."""

    @http.route()
    def web_login(self, *args, **kw):
        redirect = request.params.get('redirect') or ''
        if (
            request.httprequest.method == 'GET'
            and not request.session.uid
            and redirect.startswith(SIGNUP_REDIRECT_PREFIXES)
        ):
            # Cambia de BD si la cookie apuntaba a otra (p. ej. rms-sandbox).
            ensure_db()
            return request.redirect(redirect)
        return super().web_login(*args, **kw)
