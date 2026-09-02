import { registry } from "@web/core/registry";
import { listView } from "@web/views/list/list_view";
import { ProductCatalogKanbanModel } from "@product/product_catalog/kanban_model";
import { productCatalogKanbanView } from "@product/product_catalog/kanban_view";

import { ProductCatalogListController } from "./list_controller";

export const productCatalogListView = {
    ...listView,
    Controller: ProductCatalogListController,
    // The data-loading logic (fetching order-line quantities/prices for each
    // product) is view-agnostic, so the kanban catalog's model is reused as-is.
    Model: ProductCatalogKanbanModel,
    // Other modules (e.g. account, for the "sections" feature) patch
    // ProductCatalogKanbanModel.prototype and productCatalogKanbanView's
    // SearchModel/SearchPanel together (e.g. selectedSection is only set up
    // by AccountProductCatalogSearchModel). Since the Model patch applies to
    // the shared prototype regardless of view type, the matching
    // SearchModel/SearchPanel must be reused too, or code expecting them
    // breaks. Read them lazily (getters) so this stays correct regardless of
    // JS asset execution order between this module and the ones patching
    // productCatalogKanbanView.
    get SearchModel() {
        return productCatalogKanbanView.SearchModel;
    },
    get SearchPanel() {
        return productCatalogKanbanView.SearchPanel;
    },
};

registry.category("views").add("product_list_catalog", productCatalogListView);
