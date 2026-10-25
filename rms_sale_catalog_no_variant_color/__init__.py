# -*- coding: utf-8 -*-

from . import models


def post_init_hook(env):
    # Primera instalación: misma inicialización de colores que la migración.
    env['product.attribute.value'].search([])._compute_color()
    env['product.template.attribute.value'].search([])._compute_color()
