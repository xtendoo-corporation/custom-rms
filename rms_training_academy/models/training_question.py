# -*- coding: utf-8 -*-

from odoo import api, fields, models
from odoo.exceptions import ValidationError


class RmsTrainingQuestion(models.Model):
    _name = "rms.training.question"
    _description = "Pregunta de test de formación"
    _order = "lesson_id, sequence, id"

    lesson_id = fields.Many2one(
        "rms.training.lesson", string="Lección", required=True, ondelete="cascade", index=True
    )
    sequence = fields.Integer(string="Orden", default=10)
    name = fields.Char(string="Pregunta", required=True, translate=True)
    answer_ids = fields.One2many(
        "rms.training.answer", "question_id", string="Respuestas", copy=True
    )
    explanation = fields.Text(
        string="Explicación",
        translate=True,
        help="Se muestra al empleado tras corregir el test.",
    )

    @api.constrains("answer_ids")
    def _check_one_correct_answer(self):
        for question in self:
            if question.answer_ids and len(question.answer_ids.filtered("is_correct")) != 1:
                raise ValidationError(
                    "La pregunta \"%s\" debe tener exactamente una respuesta correcta." % question.name
                )


class RmsTrainingAnswer(models.Model):
    _name = "rms.training.answer"
    _description = "Respuesta de una pregunta de formación"
    _order = "question_id, sequence, id"

    question_id = fields.Many2one(
        "rms.training.question", string="Pregunta", required=True, ondelete="cascade", index=True
    )
    sequence = fields.Integer(string="Orden", default=10)
    name = fields.Char(string="Respuesta", required=True, translate=True)
    is_correct = fields.Boolean(string="Correcta")
