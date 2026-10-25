from odoo.fields import Domain
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestProductSearch(TransactionCase):
    def test_search_by_reference(self):
        product = self.env['product.product'].create({
            'name': 'Producto de prueba W2H',
            'default_code': 'W2H REF 123',
        })
        # La referencia debe seguir funcionando en variantes y plantillas.
        for record in (product, product.product_tmpl_id):
            model = self.env[record._name]
            self.assertEqual(model.search([
                ('id', '=', record.id), ('default_code', 'ilike', 'W2H 123'),
            ]), record)
            self.assertFalse(model.search([
                ('id', '=', record.id), ('default_code', 'ilike', 'W2H INEXISTENTE'),
            ]))

    def test_split_words_preserves_boolean_operators(self):
        model = self.env['product.product']
        product = model.create({'name': 'Altavoz activo W2H'})
        domain = ['|', ('name', 'ilike', 'activo Altavoz'),
                  ('default_code', '=', 'W2H-OTRA-REFERENCIA')]
        self.assertEqual(model.search(Domain(domain) & Domain('id', '=', product.id)), product)
        self.assertFalse(model.search([
            ('id', '=', product.id), '!', ('name', 'ilike', 'activo Altavoz'),
        ]))

    def test_internal_operator_is_unchanged(self):
        domain = [('product_tmpl_id', 'any!', [('name', 'ilike', 'dos palabras')])]
        self.assertIs(self.env['product.product']._split_search_words(domain), domain)
