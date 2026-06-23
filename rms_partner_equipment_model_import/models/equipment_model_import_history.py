from odoo import fields, models


class EquipmentModelImportHistory(models.Model):
    _name = "equipment.model.import.history"
    _description = "Histórico de importación de modelos de equipo"
    _order = "import_date desc, id desc"

    name = fields.Char(string="Importación", required=True, readonly=True)
    import_date = fields.Datetime(
        string="Fecha",
        required=True,
        default=fields.Datetime.now,
        readonly=True,
    )
    user_id = fields.Many2one(
        comodel_name="res.users",
        string="Usuario",
        required=True,
        default=lambda self: self.env.user,
        readonly=True,
    )
    filename = fields.Char(string="Archivo", readonly=True)
    state = fields.Selection(
        selection=[("done", "Completada"), ("failed", "Fallida")],
        string="Estado",
        required=True,
        default="done",
        readonly=True,
    )
    company_found_count = fields.Integer(
        string="Empresas encontradas",
        readonly=True,
    )
    company_not_found_count = fields.Integer(
        string="Empresas no encontradas",
        readonly=True,
    )
    model_created_count = fields.Integer(
        string="Modelos creados",
        readonly=True,
    )
    model_existing_count = fields.Integer(
        string="Modelos ya existentes",
        readonly=True,
    )
    association_created_count = fields.Integer(
        string="Asociaciones creadas",
        readonly=True,
    )
    association_existing_count = fields.Integer(
        string="Asociaciones ya existentes",
        readonly=True,
    )
    error_count = fields.Integer(string="Errores", readonly=True)
    ignored_row_count = fields.Integer(
        string="Filas vacías ignoradas",
        readonly=True,
    )
    log_text = fields.Text(string="Log", readonly=True)
    log_file = fields.Binary(
        string="Descargar log",
        attachment=True,
        readonly=True,
    )
    log_filename = fields.Char(readonly=True)
