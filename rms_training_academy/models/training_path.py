# -*- coding: utf-8 -*-

from odoo import api, fields, models


class RmsTrainingPath(models.Model):
    """Una ruta por aplicación de Odoo (Ventas, Inventario, Gastos...).

    La formación es global: el mismo catálogo para toda la empresa. Lo que
    cambia de un empleado a otro es qué lecciones ve, según sus permisos
    reales (ver rms.training.lesson._get_available_lesson_ids)."""

    _name = "rms.training.path"
    _description = "Aplicación de formación"
    _order = "sequence, id"

    name = fields.Char(string="Aplicación", required=True, translate=True)
    sequence = fields.Integer(string="Secuencia", default=10)
    active = fields.Boolean(default=True)
    color = fields.Integer(string="Color")
    description = fields.Text(string="Descripción", translate=True)
    lesson_ids = fields.One2many("rms.training.lesson", "path_id", string="Lecciones")
    lesson_count = fields.Integer(string="Nº lecciones (total)", compute="_compute_lesson_count")

    # Calculado para el usuario que mira (depende de sus permisos)
    my_lesson_count = fields.Integer(string="Mis lecciones", compute="_compute_my_progress")
    my_duration = fields.Integer(string="Duración estimada (min)", compute="_compute_my_progress")
    my_done_count = fields.Integer(string="Completadas", compute="_compute_my_progress")
    my_progress = fields.Float(string="Mi progreso (%)", compute="_compute_my_progress")
    has_available_lessons = fields.Boolean(
        string="Tiene lecciones para mí",
        compute="_compute_my_progress",
        search="_search_has_available_lessons",
    )

    @api.depends("lesson_ids")
    def _compute_lesson_count(self):
        for path in self:
            path.lesson_count = len(path.lesson_ids)

    def _compute_my_progress(self):
        Lesson = self.env["rms.training.lesson"]
        available = Lesson.browse(Lesson._get_available_lesson_ids())
        done_lesson_ids = set(
            self.env["rms.training.progress"].search(
                [("user_id", "=", self.env.uid), ("state", "=", "done")]
            ).lesson_id.ids
        )
        for path in self:
            mine = available.filtered(lambda lesson: lesson.path_id == path)
            done = len([lid for lid in mine.ids if lid in done_lesson_ids])
            path.my_lesson_count = len(mine)
            path.my_duration = sum(mine.mapped("duration"))
            path.my_done_count = done
            path.my_progress = (100.0 * done / len(mine)) if mine else 0.0
            path.has_available_lessons = bool(mine)

    def _search_has_available_lessons(self, operator, value):
        if operator not in ("=", "!=") or not isinstance(value, bool):
            return NotImplemented
        Lesson = self.env["rms.training.lesson"]
        path_ids = Lesson.browse(Lesson._get_available_lesson_ids()).path_id.ids
        positive = (operator == "=") == value
        return [("id", "in" if positive else "not in", path_ids)]

    def action_open_lessons(self):
        self.ensure_one()
        action = self.env["ir.actions.act_window"]._for_xml_id(
            "rms_training_academy.action_rms_training_lesson"
        )
        action["name"] = self.name
        action["domain"] = [("path_id", "=", self.id)]
        action["context"] = {
            "default_path_id": self.id,
            "search_default_available": 1,
            "search_default_group_level": 1,
        }
        return action
