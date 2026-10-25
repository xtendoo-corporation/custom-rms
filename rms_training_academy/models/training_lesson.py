# -*- coding: utf-8 -*-

from odoo import api, fields, models
from odoo.tools import html2plaintext
from odoo.exceptions import AccessError

LEVELS = [
    ("1_basic", "Básico"),
    ("2_intermediate", "Intermedio"),
    ("3_advanced", "Avanzado"),
]

PROGRESS_STATES = [
    ("not_started", "Pendiente"),
    ("in_progress", "En curso"),
    ("done", "Completada"),
]


class RmsTrainingLesson(models.Model):
    _name = "rms.training.lesson"
    _description = "Lección de formación"
    _order = "path_sequence, level, sequence, id"

    name = fields.Char(string="Lección", required=True, translate=True)
    path_id = fields.Many2one(
        "rms.training.path", string="Aplicación", required=True, ondelete="cascade", index=True
    )
    path_sequence = fields.Integer(related="path_id.sequence", store=True)
    sequence = fields.Integer(string="Orden", default=10)
    active = fields.Boolean(default=True)
    level = fields.Selection(LEVELS, string="Nivel", required=True, default="1_basic")
    duration = fields.Integer(string="Duración (min)", default=10)
    menu_path = fields.Char(
        string="Dónde se hace",
        translate=True,
        help="Ruta de menú en Odoo, p. ej. Inventario > Operaciones > Cesiones.",
    )
    keywords = fields.Char(
        string="Palabras clave",
        help="Términos con los que un empleado podría preguntar por esta lección (los usa también el asistente de IA).",
    )
    objective = fields.Text(string="Qué aprenderás", translate=True)
    prerequisite_ids = fields.Many2many(
        "rms.training.lesson",
        "rms_training_lesson_prereq_rel",
        "lesson_id",
        "prereq_id",
        string="Lecciones previas recomendadas",
    )
    step_ids = fields.One2many("rms.training.step", "lesson_id", string="Paso a paso", copy=True)
    tips = fields.Html(string="Consejos y errores frecuentes", translate=True)
    step_count = fields.Integer(compute="_compute_step_count", string="Nº pasos")

    # --- A quién se le muestra -------------------------------------------
    # No hay rutas "por departamento": cada lección declara qué permiso
    # real de Odoo hace falta para poder hacer lo que explica, y cada
    # empleado ve solo las lecciones que puede poner en práctica. Así la
    # formación sigue automáticamente los cambios de permisos de cada
    # usuario, sin mantener listas aparte.
    module_name = fields.Char(
        string="Módulo necesario",
        help="Nombre técnico del módulo que aporta la funcionalidad. Si no está instalado, la lección no se muestra a nadie.",
    )
    menu_xmlid = fields.Char(
        string="Menú necesario",
        help="ID externo del menú de Odoo (p. ej. stock_cession.menu_stock_cession). La lección solo se muestra "
        "a quien puede ver ese menú. Vacío = no depende de ningún menú.",
    )
    group_xmlids = fields.Char(
        string="Grupos necesarios",
        help="IDs externos de grupos separados por comas (p. ej. base.group_system). La lección solo se muestra a "
        "quien pertenezca al menos a uno de ellos. Vacío = cualquier empleado.",
    )
    access_summary = fields.Char(
        string="Quién la ve", compute="_compute_access_summary",
        help="Resumen de los requisitos de acceso de la lección.",
    )
    is_available = fields.Boolean(
        string="Disponible para mí",
        compute="_compute_is_available",
        search="_search_is_available",
    )

    # --- Progreso del usuario actual ------------------------------------
    progress_ids = fields.One2many("rms.training.progress", "lesson_id", string="Progreso")
    my_state = fields.Selection(
        PROGRESS_STATES,
        string="Mi estado",
        compute="_compute_my_progress",
        search="_search_my_state",
    )
    done_user_count = fields.Integer(
        string="Empleados que la han completado", compute="_compute_done_user_count"
    )

    @api.depends("step_ids")
    def _compute_step_count(self):
        for lesson in self:
            lesson.step_count = len(lesson.step_ids)

    @api.depends("module_name", "menu_xmlid", "group_xmlids")
    def _compute_access_summary(self):
        for lesson in self:
            parts = []
            if lesson.menu_xmlid:
                menu = self.env.ref(lesson.menu_xmlid, raise_if_not_found=False)
                parts.append("menú %s" % (menu.complete_name if menu else lesson.menu_xmlid))
            if lesson.group_xmlids:
                names = []
                for xmlid in lesson._split_xmlids(lesson.group_xmlids):
                    group = self.env.ref(xmlid, raise_if_not_found=False)
                    names.append(group.display_name if group else xmlid)
                parts.append("grupo " + " o ".join(names))
            lesson.access_summary = ("Quien tenga " + " y ".join(parts)) if parts else "Todos los empleados"

    # ------------------------------------------------------------------
    # Disponibilidad según los permisos reales del usuario
    # ------------------------------------------------------------------

    @staticmethod
    def _split_xmlids(value):
        return [x.strip() for x in (value or "").split(",") if x.strip()]

    @api.model
    def _get_available_lesson_ids(self, user=None):
        """IDs de las lecciones activas que ``user`` puede poner en práctica:
        módulo instalado, menú visible para él (mismo cálculo que hace Odoo
        para pintar sus menús) y pertenencia a alguno de los grupos pedidos."""
        user = user or self.env.user
        lessons = self.sudo().search([])
        modules = {name for name in lessons.mapped("module_name") if name}
        installed = set(
            self.env["ir.module.module"].sudo().search(
                [("name", "in", list(modules)), ("state", "=", "installed")]
            ).mapped("name")
        )
        visible_menu_ids = self.env["ir.ui.menu"].with_user(user)._visible_menu_ids()
        user_group_ids = set(user.all_group_ids.ids)
        available = []
        for lesson in lessons:
            if lesson.module_name and lesson.module_name not in installed:
                continue
            if lesson.menu_xmlid:
                menu = self.env.ref(lesson.menu_xmlid, raise_if_not_found=False)
                if not menu or menu._name != "ir.ui.menu":
                    continue
                # _visible_menu_ids puede incluir un submenú sin grupos aunque
                # su aplicación no sea visible; en la interfaz solo se llega a
                # él si toda la cadena de menús padre es visible.
                chain = menu.sudo()
                while chain and chain.id in visible_menu_ids:
                    chain = chain.parent_id
                if chain:
                    continue
            if lesson.group_xmlids:
                group_ids = {
                    group.id
                    for group in (
                        self.env.ref(xmlid, raise_if_not_found=False)
                        for xmlid in self._split_xmlids(lesson.group_xmlids)
                    )
                    if group and group._name == "res.groups"
                }
                if not group_ids & user_group_ids:
                    continue
            available.append(lesson.id)
        return available

    def _compute_is_available(self):
        available = set(self._get_available_lesson_ids())
        for lesson in self:
            lesson.is_available = lesson.id in available

    def _search_is_available(self, operator, value):
        if operator not in ("=", "!=") or not isinstance(value, bool):
            return NotImplemented
        positive = (operator == "=") == value
        return [("id", "in" if positive else "not in", self._get_available_lesson_ids())]

    # ------------------------------------------------------------------
    # Progreso
    # ------------------------------------------------------------------

    def _my_progress_records(self):
        return self.env["rms.training.progress"].search(
            [("user_id", "=", self.env.uid), ("lesson_id", "in", self.ids)]
        )

    def _compute_my_progress(self):
        by_lesson = {p.lesson_id.id: p for p in self._my_progress_records()}
        for lesson in self:
            progress = by_lesson.get(lesson.id)
            lesson.my_state = progress.state if progress else "not_started"

    def _search_my_state(self, operator, value):
        if operator not in ("=", "!=", "in", "not in"):
            return NotImplemented
        values = [value] if isinstance(value, str) else list(value)
        if operator in ("!=", "not in"):
            values = [s for s, _label in PROGRESS_STATES if s not in values]
        progress = self.env["rms.training.progress"].search([("user_id", "=", self.env.uid)])
        started_ids = progress.filtered(lambda p: p.state != "not_started").lesson_id.ids
        matching_ids = progress.filtered(lambda p: p.state in values).lesson_id.ids
        domain = [("id", "in", matching_ids)]
        if "not_started" in values:
            domain = ["|", ("id", "not in", started_ids)] + domain
        return domain

    def _compute_done_user_count(self):
        data = self.env["rms.training.progress"].sudo()._read_group(
            [("lesson_id", "in", self.ids), ("state", "=", "done")], ["lesson_id"], ["__count"]
        )
        counts = {lesson.id: count for lesson, count in data}
        for lesson in self:
            lesson.done_user_count = counts.get(lesson.id, 0)

    def _get_or_create_my_progress(self):
        self.ensure_one()
        Progress = self.env["rms.training.progress"]
        progress = Progress.search(
            [("user_id", "=", self.env.uid), ("lesson_id", "=", self.id)], limit=1
        )
        if not progress:
            # sudo: el empleado no tiene permiso de creación genérico sobre el
            # progreso; solo puede generar SU propio registro desde aquí.
            progress = Progress.sudo().create({"user_id": self.env.uid, "lesson_id": self.id})
        return progress.sudo()

    def action_start(self):
        for lesson in self:
            progress = lesson._get_or_create_my_progress()
            if progress.state == "not_started":
                progress.write({"state": "in_progress", "date_start": fields.Datetime.now()})
        return True

    def action_mark_done(self):
        available = set(self._get_available_lesson_ids())
        if any(lesson.id not in available for lesson in self):
            raise AccessError("No puedes completar una lección que no está disponible para ti.")
        for lesson in self:
            lesson._get_or_create_my_progress()._set_done()
        return True

    def action_reset_my_progress(self):
        self._my_progress_records().sudo().write({"state": "in_progress", "date_done": False})
        return True

    # ------------------------------------------------------------------
    # Texto plano para el asistente de IA (rms_ai_help_assistant)
    # ------------------------------------------------------------------

    def _to_plain_guide(self):
        """Representación en texto de la lección, pensada para que el
        asistente de IA la use como fuente oficial."""
        self.ensure_one()
        level_label = dict(LEVELS).get(self.level, "")
        lines = [
            "%s (nivel %s, aplicación '%s')" % (self.name, level_label, self.path_id.name),
        ]
        if self.menu_path:
            lines.append("Dónde: %s" % self.menu_path)
        if self.objective:
            lines.append("Objetivo: %s" % self.objective)
        for index, step in enumerate(self.step_ids, start=1):
            text = "%d. %s" % (index, step.name)
            if step.description:
                text += " — %s" % step.description
            if step.expected_result:
                text += " (Resultado: %s)" % step.expected_result
            lines.append(text)
        if self.tips:
            lines.append("Consejos: %s" % html2plaintext(self.tips))
        return "\n".join(lines)


class RmsTrainingStep(models.Model):
    _name = "rms.training.step"
    _description = "Paso de una lección"
    _order = "lesson_id, sequence, id"

    lesson_id = fields.Many2one(
        "rms.training.lesson", string="Lección", required=True, ondelete="cascade", index=True
    )
    sequence = fields.Integer(string="Orden", default=10)
    # Text (no Char) para que los pasos largos se lean enteros en la lista.
    name = fields.Text(string="Paso", required=True, translate=True)
    description = fields.Text(string="Detalle", translate=True)
    expected_result = fields.Char(string="Resultado esperado", translate=True)
