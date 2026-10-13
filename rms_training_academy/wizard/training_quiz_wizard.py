# -*- coding: utf-8 -*-

from odoo import fields, models
from odoo.exceptions import UserError


class RmsTrainingQuizWizard(models.TransientModel):
    _name = "rms.training.quiz.wizard"
    _description = "Test de comprobación de una lección"

    lesson_id = fields.Many2one("rms.training.lesson", string="Lección", required=True, readonly=True)
    line_ids = fields.One2many("rms.training.quiz.wizard.line", "wizard_id", string="Preguntas")
    state = fields.Selection([("answering", "Respondiendo"), ("result", "Resultado")], default="answering")
    score = fields.Float(string="Nota (%)", readonly=True)
    passed = fields.Boolean(string="Aprobado", readonly=True)
    result_message = fields.Text(string="Resultado", readonly=True)

    def action_submit(self):
        self.ensure_one()
        if any(not line.answer_id for line in self.line_ids):
            raise UserError("Responde a todas las preguntas antes de corregir el test.")
        correct = len(self.line_ids.filtered(lambda l: l.answer_id.is_correct))
        total = len(self.line_ids) or 1
        score = round(100.0 * correct / total, 2)
        passed = score >= self.lesson_id.pass_percent

        progress = self.lesson_id._get_or_create_my_progress()
        progress.write({"attempt_count": progress.attempt_count + 1})
        if passed:
            progress._set_done(score=score)
        elif progress.state != "done":
            progress.write({"score": score})

        feedback = []
        for line in self.line_ids:
            ok = line.answer_id.is_correct
            right = line.question_id.answer_ids.filtered("is_correct")[:1]
            text = "%s %s" % ("✔" if ok else "✘", line.question_id.name)
            if not ok:
                text += "\n   Respuesta correcta: %s" % right.name
            if line.question_id.explanation:
                text += "\n   %s" % line.question_id.explanation
            feedback.append(text)
        header = (
            "¡Aprobado! Has acertado %d de %d (%.0f%%). La lección queda completada."
            if passed
            else "No aprobado: has acertado %d de %d (%.0f%%). Necesitas un %d%%. Repasa los pasos y vuelve a intentarlo."
        )
        params = (correct, total, score) if passed else (correct, total, score, self.lesson_id.pass_percent)
        self.write(
            {
                "state": "result",
                "score": score,
                "passed": passed,
                "result_message": (header % params) + "\n\n" + "\n\n".join(feedback),
            }
        )
        return {
            "type": "ir.actions.act_window",
            "res_model": self._name,
            "res_id": self.id,
            "view_mode": "form",
            "target": "new",
            "name": "Resultado del test",
        }

    def action_retry(self):
        self.ensure_one()
        return self.lesson_id.action_take_quiz()


class RmsTrainingQuizWizardLine(models.TransientModel):
    _name = "rms.training.quiz.wizard.line"
    _description = "Pregunta del test de comprobación"

    wizard_id = fields.Many2one("rms.training.quiz.wizard", required=True, ondelete="cascade")
    question_id = fields.Many2one("rms.training.question", string="Pregunta", required=True, readonly=True)
    answer_id = fields.Many2one(
        "rms.training.answer",
        string="Tu respuesta",
        domain="[('question_id', '=', question_id)]",
    )
