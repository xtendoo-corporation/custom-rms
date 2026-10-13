# -*- coding: utf-8 -*-

from odoo import api, fields, models

from .training_lesson import PROGRESS_STATES


class RmsTrainingProgress(models.Model):
    _name = "rms.training.progress"
    _description = "Progreso de formación por empleado"
    _order = "date_done desc, id desc"
    _rec_name = "lesson_id"

    user_id = fields.Many2one(
        "res.users", string="Empleado", required=True, ondelete="cascade", index=True,
        default=lambda self: self.env.user,
    )
    lesson_id = fields.Many2one(
        "rms.training.lesson", string="Lección", required=True, ondelete="cascade", index=True
    )
    path_id = fields.Many2one(related="lesson_id.path_id", store=True, string="Ruta formativa")
    level = fields.Selection(related="lesson_id.level", store=True, string="Nivel")
    state = fields.Selection(PROGRESS_STATES, string="Estado", default="not_started", required=True)
    date_start = fields.Datetime(string="Empezada el")
    date_done = fields.Datetime(string="Completada el")
    score = fields.Float(string="Nota del test (%)")
    attempt_count = fields.Integer(string="Intentos del test")
    done_count = fields.Integer(
        string="Completadas",
        compute="_compute_done_count",
        store=True,
        aggregator="sum",
        help="1 si la lección está completada (para sumar en informes).",
    )

    _user_lesson_unique = models.Constraint(
        "UNIQUE(user_id, lesson_id)",
        "Ya existe un registro de progreso para este empleado y esta lección.",
    )

    @api.depends("state")
    def _compute_done_count(self):
        for progress in self:
            progress.done_count = 1 if progress.state == "done" else 0

    def _set_done(self, score=None):
        vals = {"state": "done", "date_done": fields.Datetime.now()}
        if score is not None:
            vals["score"] = score
        for progress in self:
            if not progress.date_start:
                vals["date_start"] = vals["date_done"]
            progress.write(vals)
