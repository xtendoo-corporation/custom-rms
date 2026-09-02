import { Component, useSubEnv } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { rpc } from "@web/core/network/rpc";
import { useDebounced } from "@web/core/utils/timing";
import { standardWidgetProps } from "@web/views/widgets/standard_widget_props";
import { ProductCatalogOrderLine } from "@product/product_catalog/order_line/order_line";

/**
 * List-row counterpart of @product/product_catalog/kanban_record.js: owns the
 * same quantity/RPC logic, but as a view widget instead of a KanbanRecord
 * subclass, so it can be dropped into any <list js_class="product_list_catalog">
 * row as a plain column.
 */
export class ProductCatalogListOrderLine extends Component {
    static template = "rms_sale_catalog_no_variant_color.ProductCatalogListOrderLine";
    static components = { ProductCatalogOrderLine };
    static props = standardWidgetProps;

    setup() {
        this.debouncedUpdateQuantity = useDebounced(this._updateQuantity, 500, {
            execBeforeUnmount: true,
        });
        this._pendingUpdate = Promise.resolve();

        useSubEnv({
            currencyId: this.props.record.context.product_catalog_currency_id,
            orderId: this.props.record.context.product_catalog_order_id,
            orderResModel: this.props.record.context.product_catalog_order_model,
            digits: this.props.record.context.product_catalog_digits,
            displayUoM: this.props.record.context.display_uom,
            precision: this.props.record.context.precision,
            productId: this.props.record.resId,
            addProduct: this.addProduct.bind(this),
            removeProduct: this.removeProduct.bind(this),
            increaseQuantity: this.increaseQuantity.bind(this),
            setQuantity: this.setQuantity.bind(this),
            decreaseQuantity: this.decreaseQuantity.bind(this),
            childField: this.props.record.context.child_field,
        });
    }

    get productCatalogData() {
        return this.props.record.productCatalogData;
    }

    //--------------------------------------------------------------------------
    // Data Exchanges
    //--------------------------------------------------------------------------

    async _updateQuantity() {
        const price = await this._updateQuantityAndGetPrice();
        this.productCatalogData.price = parseFloat(price);
    }

    _updateQuantityAndGetPrice() {
        // Chain RPC calls so each request completes before the next starts,
        // preventing race conditions on quick successive clicks.
        this._pendingUpdate = this._pendingUpdate.then(() => rpc(
            "/product/catalog/update_order_line_info",
            this._getUpdateQuantityAndGetPriceParams(),
        ));
        return this._pendingUpdate;
    }

    _getUpdateQuantityAndGetPriceParams() {
        return {
            order_id: this.env.orderId,
            product_id: this.env.productId,
            quantity: this.productCatalogData.quantity,
            res_model: this.env.orderResModel,
            child_field: this.env.childField,
        };
    }

    //--------------------------------------------------------------------------
    // Handlers
    //--------------------------------------------------------------------------

    updateQuantity(quantity) {
        if (this.productCatalogData.readOnly) {
            return;
        }
        this.productCatalogData.quantity = quantity || 0;
        this.debouncedUpdateQuantity();
    }

    addProduct(qty = 1) {
        this.updateQuantity(qty);
    }

    removeProduct() {
        this.updateQuantity(0);
    }

    increaseQuantity(qty = 1) {
        this.updateQuantity(this.productCatalogData.quantity + qty);
    }

    setQuantity(event) {
        this.updateQuantity(parseFloat(event.target.value));
    }

    decreaseQuantity() {
        this.updateQuantity(parseFloat(this.productCatalogData.quantity - 1));
    }
}

export const productCatalogListOrderLine = {
    component: ProductCatalogListOrderLine,
};

registry.category("view_widgets").add("product_catalog_list_order_line", productCatalogListOrderLine);
