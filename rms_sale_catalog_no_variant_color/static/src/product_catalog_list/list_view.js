import { registry } from "@web/core/registry";
import { listView } from "@web/views/list/list_view";
import { ProductCatalogKanbanModel } from "@product/product_catalog/kanban_model";

import { ProductCatalogListController } from "./list_controller";

export const productCatalogListView = {
    ...listView,
    Controller: ProductCatalogListController,
    // The data-loading logic (fetching order-line quantities/prices for each
    // product) is view-agnostic, so the kanban catalog's model is reused as-is.
    Model: ProductCatalogKanbanModel,
};

registry.category("views").add("product_list_catalog", productCatalogListView);
