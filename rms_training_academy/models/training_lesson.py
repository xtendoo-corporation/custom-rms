# -*- coding: utf-8 -*-

from odoo import api, fields, models
from odoo.exceptions import UserError

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
        "rms.training.path", string="Ruta formativa", required=True, ondelete="cascade", index=True
    )
    path_sequence = fields.Integer(related="path_id.sequence", store=True)
    sequence = fields.Integer(string="Orden", default=10)
    active = fields.Boolean(default=True)
    level = fields.Selection(LEVELS, string="Nivel", required=True, default="1_basic")
    duration = fields.Integer(string="Duración (min)", default=10)
    module_name = fields.Char(
        string="Módulo relacionado",
        help="Nombre técnico del módulo de Odoo que aporta la funcionalidad (p. ej. stock_cession).",
    )
    menu_path = fields.Char(
        string="Dónde se hace",
        translate=True,
        help="Ruta de menú en Odoo, p. ej. Inventario > Operaciones > Cesiones.",
    )
    audience = fields.Char(string="Dirigida a")
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
    question_ids = fields.One2many(
        "rms.training.question", "lesson_id", string="Test de comprobación", copy=True
    )
    pass_percent = fields.Integer(string="Nota mínima para aprobar (%)", default=70)
    step_count = fields.Integer(compute="_compute_counts", string="Nº pasos")
    question_count = fields.Integer(compute="_compute_counts", string="Nº preguntas")

    progress_ids = fields.One2many("rms.training.progress", "lesson_id", string="Progreso")
    my_state = fields.Selection(
        PROGRESS_STATES,
        string="Mi estado",
        compute="_compute_my_progress",
        search="_search_my_state",
    )
    my_score = fields.Float(string="Mi nota (%)", compute="_compute_my_progress")
    done_user_count = fields.Integer(
        string="Empleados que la han completado", compute="_compute_done_user_count"
    )

    @api.depends("step_ids", "question_ids")
    def _compute_counts(self):
        for lesson in self:
            lesson.step_count = len(lesson.step_ids)
            lesson.question_count = len(lesson.question_ids)

    def _my_progress_records(self):
        return self.env["rms.training.progress"].search(
            [("user_id", "=", self.env.uid), ("lesson_id", "in", self.ids)]
        )

    def _compute_my_progress(self):
        by_lesson = {p.lesson_id.id: p for p in self._my_progress_records()}
        for lesson in self:
            progress = by_lesson.get(lesson.id)
            lesson.my_state = progress.state if progress else "not_started"
            lesson.my_score = progress.score if progress else 0.0

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

    # ------------------------------------------------------------------
    # Acciones del empleado
    # ------------------------------------------------------------------

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
        self.ensure_one()
        if self.question_ids:
            raise UserError(
                "Esta lección tiene un test de comprobación: apruébalo con el botón "
                "\"Hacer el test\" para marcarla como completada."
            )
        self._get_or_create_my_progress()._set_done()
        return True

    def action_reset_my_progress(self):
        self.ensure_one()
        progress = self._my_progress_records()
        progress.sudo().write({"state": "in_progress", "date_done": False})
        return True

    def action_take_quiz(self):
        self.ensure_one()
        if not self.question_ids:
            raise UserError("Esta lección no tiene test de comprobación.")
        self.action_start()
        wizard = self.env["rms.training.quiz.wizard"].create(
            {
                "lesson_id": self.id,
                "line_ids": [(0, 0, {"question_id": q.id}) for q in self.question_ids],
            }
        )
        return {
            "type": "ir.actions.act_window",
            "name": "Test: %s" % self.name,
            "res_model": "rms.training.quiz.wizard",
            "res_id": wizard.id,
            "view_mode": "form",
            "target": "new",
        }

    # ------------------------------------------------------------------
    # Texto plano para el asistente de IA (rms_ai_help_assistant)
    # ------------------------------------------------------------------

    def _to_plain_guide(self):
        """Representación en texto de la lección, pensada para que el
        asistente de IA la use como fuente oficial."""
        self.ensure_one()
        level_label = dict(LEVELS).get(self.level, "")
        lines = [
            "%s (nivel %s, ruta '%s')" % (self.name, level_label, self.path_id.name),
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
            from odoo.tools import html2plaintext

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
