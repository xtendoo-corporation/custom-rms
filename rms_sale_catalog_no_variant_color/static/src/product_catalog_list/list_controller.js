import { ListController } from "@web/views/list/list_controller";
import { onWillStart } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";
import { useDebounced } from "@web/core/utils/timing";
import { _t } from "@web/core/l10n/translation";

/**
 * List variant of the "Add from catalog" picker opened from a quotation.
 * Mirrors @product/product_catalog/kanban_controller.js so the "Back to
 * Quotation" button and order state behave the same way in list mode.
 */
export class ProductCatalogListController extends ListController {
    static template = "rms_sale_catalog_no_variant_color.ProductCatalogListController";

    setup() {
        super.setup();
        this.orm = useService("orm");
        this.orderId = this.props.context.order_id;
        this.orderResModel = this.props.context.product_catalog_order_model;
        this.backToQuotationDebounced = useDebounced(this.backToQuotation, 500);

        onWillStart(() => this.onWillStart());
    }

    async onWillStart() {
        await this.setOrderStateInfo();
        this._defineButtonContent();
    }

    get stateFiels() {
        return ["state"];
    }

    async setOrderStateInfo() {
        const orderData = await this.orm.searchRead(
            this.orderResModel, [["id", "=", this.orderId]], this.stateFiels
        );
        this.orderStateInfo = orderData[0] || {};
    }

    _defineButtonContent() {
        const orderIsQuotation = ["draft", "sent"].includes(this.orderStateInfo.state);
        this.buttonString = orderIsQuotation ? _t("Back to Quotation") : _t("Back to Order");
    }

    async backToQuotation() {
        if (this.env.config.breadcrumbs.length > 1) {
            await this.actionService.restore();
        } else {
            await this.actionService.doAction({
                type: "ir.actions.act_window",
                res_model: this.orderResModel,
                views: [[false, "form"]],
                view_mode: "form",
                res_id: this.orderId,
            });
        }
    }
}
