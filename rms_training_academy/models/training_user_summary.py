# -*- coding: utf-8 -*-

from odoo import api, fields, models
from odoo.exceptions import AccessError


class RmsTrainingUserSummary(models.Model):
    """Foto del avance de cada empleado respecto a SUS lecciones.

    No puede ser una vista SQL: qué lecciones le tocan a cada uno depende
    de sus permisos (menús visibles, grupos), que se calculan en Python. Se
    regenera cada vez que el responsable abre "Control de formación"."""

    _name = "rms.training.user.summary"
    _description = "Resumen de formación por empleado"
    _order = "progress asc, user_id"

    user_id = fields.Many2one("res.users", string="Empleado", required=True, ondelete="cascade")
    department = fields.Char(string="Departamento")
    available_count = fields.Integer(string="Lecciones que le corresponden", aggregator="sum")
    done_count = fields.Integer(string="Completadas", aggregator="sum")
    in_progress_count = fields.Integer(string="En curso", aggregator="sum")
    pending_count = fields.Integer(string="Pendientes", aggregator="sum")
    progress = fields.Float(string="Progreso (%)", aggregator="avg")
    last_activity = fields.Datetime(string="Última actividad")

    @api.model
    def _refresh(self):
        Lesson = self.env["rms.training.lesson"]
        users = self.env["res.users"].sudo().search([("share", "=", False)])
        progress = self.env["rms.training.progress"].sudo().search([("user_id", "in", users.ids)])
        has_employee = "employee_id" in users._fields
        rows = []
        for user in users:
            available = set(Lesson._get_available_lesson_ids(user))
            mine = progress.filtered(lambda p, u=user: p.user_id == u and p.lesson_id.id in available)
            done = len(mine.filtered(lambda p: p.state == "done"))
            in_progress = len(mine.filtered(lambda p: p.state == "in_progress"))
            dates = [d for d in mine.mapped("date_done") + mine.mapped("date_start") if d]
            rows.append({
                "user_id": user.id,
                # Departamento solo si RRHH está instalado (sin dependencia).
                "department": has_employee and user.employee_id.department_id.name or False,
                "available_count": len(available),
                "done_count": done,
                "in_progress_count": in_progress,
                "pending_count": len(available) - done - in_progress,
                "progress": (100.0 * done / len(available)) if available else 0.0,
                "last_activity": max(dates) if dates else False,
            })
        self.sudo().search([]).unlink()
        self.sudo().create(rows)

    @api.model
    def action_open(self):
        if not self.env.su and (
            self.env.user.share or not self.env.user.has_group("base.group_user")
            or not self.env.user.has_group("rms_training_academy.group_training_manager")
        ):
            raise AccessError("Acceso restringido a usuarios internos con permisos para esta función.")
        self._refresh()
        return self.env["ir.actions.act_window"]._for_xml_id(
            "rms_training_academy.action_rms_training_user_summary"
        )
