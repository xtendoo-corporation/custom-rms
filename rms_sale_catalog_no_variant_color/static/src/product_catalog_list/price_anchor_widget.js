import { Component } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { standardWidgetProps } from "@web/views/widgets/standard_widget_props";

/**
 * Anchor cell targeted by ProductCatalogOrderLine's t-portal (see
 * @product/product_catalog/order_line/order_line.xml), mirroring the
 * `id="product-{id}-price"` div used in the kanban catalog card.
 */
export class ProductCatalogListPriceAnchor extends Component {
    static template = "rms_sale_catalog_no_variant_color.ProductCatalogListPriceAnchor";
    static props = standardWidgetProps;
}

export const productCatalogListPriceAnchor = {
    component: ProductCatalogListPriceAnchor,
};

registry.category("view_widgets").add("product_catalog_list_price_anchor", productCatalogListPriceAnchor);
