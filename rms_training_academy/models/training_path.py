# -*- coding: utf-8 -*-

from odoo import api, fields, models


class RmsTrainingPath(models.Model):
    _name = "rms.training.path"
    _description = "Ruta formativa"
    _order = "sequence, id"

    name = fields.Char(string="Ruta formativa", required=True, translate=True)
    sequence = fields.Integer(string="Secuencia", default=10)
    active = fields.Boolean(default=True)
    color = fields.Integer(string="Color")
    description = fields.Text(string="Descripción", translate=True)
    audience = fields.Char(
        string="Dirigida a",
        help="Perfiles a los que va dirigida (p. ej. Comerciales, Almacén, Administración).",
    )
    group_ids = fields.Many2many(
        "res.groups",
        string="Grupos destinatarios",
        help="Si se indica, la ruta solo se muestra como recomendada a los usuarios de estos grupos. "
        "Vacío = recomendada para todos los empleados.",
    )
    lesson_ids = fields.One2many("rms.training.lesson", "path_id", string="Lecciones")
    lesson_count = fields.Integer(string="Nº lecciones", compute="_compute_lesson_count")
    total_duration = fields.Integer(
        string="Duración estimada (min)", compute="_compute_lesson_count"
    )

    # Progreso del usuario actual (no almacenado: depende de quién mira)
    my_done_count = fields.Integer(string="Completadas", compute="_compute_my_progress")
    my_progress = fields.Float(string="Mi progreso (%)", compute="_compute_my_progress")
    is_recommended = fields.Boolean(
        string="Recomendada para mí",
        compute="_compute_is_recommended",
        search="_search_is_recommended",
    )

    @api.depends("lesson_ids", "lesson_ids.duration")
    def _compute_lesson_count(self):
        for path in self:
            path.lesson_count = len(path.lesson_ids)
            path.total_duration = sum(path.lesson_ids.mapped("duration"))

    def _compute_my_progress(self):
        done = self.env["rms.training.progress"].search(
            [("user_id", "=", self.env.uid), ("state", "=", "done"), ("path_id", "in", self.ids)]
        )
        for path in self:
            count = len(done.filtered(lambda p: p.path_id == path))
            path.my_done_count = count
            path.my_progress = (100.0 * count / path.lesson_count) if path.lesson_count else 0.0

    def _compute_is_recommended(self):
        user_groups = self.env.user.all_group_ids
        for path in self:
            path.is_recommended = not path.group_ids or bool(path.group_ids & user_groups)

    def _search_is_recommended(self, operator, value):
        if operator not in ("=", "!=") or not isinstance(value, bool):
            return NotImplemented
        domain = ["|", ("group_ids", "=", False), ("group_ids", "in", self.env.user.all_group_ids.ids)]
        positive = (operator == "=") == value
        return domain if positive else ["!"] + domain

    def action_open_lessons(self):
        self.ensure_one()
        action = self.env["ir.actions.act_window"]._for_xml_id(
            "rms_training_academy.action_rms_training_lesson"
        )
        action["name"] = self.name
        action["domain"] = [("path_id", "=", self.id)]
        action["context"] = {"default_path_id": self.id, "search_default_group_level": 1}
        return action
