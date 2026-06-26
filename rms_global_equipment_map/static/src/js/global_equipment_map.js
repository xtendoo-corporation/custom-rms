/** @odoo-module **/

import { registry } from "@web/core/registry";
import { rpc } from "@web/core/network/rpc";
import { useService } from "@web/core/utils/hooks";
import { standardActionServiceProps } from "@web/webclient/actions/action_service";
import {
    Component,
    onMounted,
    onWillStart,
    onWillUnmount,
    useRef,
    useState,
} from "@odoo/owl";

const LEAFLET_STYLESHEET =
    "/rms_global_equipment_map/static/lib/leaflet/leaflet.css";

function loadLeafletStyles() {
    if (document.querySelector("link[data-global-equipment-map-leaflet]")) {
        return Promise.resolve();
    }
    return new Promise((resolve, reject) => {
        const link = document.createElement("link");
        link.rel = "stylesheet";
        link.dataset.globalEquipmentMapLeaflet = "1";
        link.href = LEAFLET_STYLESHEET;
        link.onload = resolve;
        link.onerror = reject;
        document.head.appendChild(link);
    });
}

export class GlobalEquipmentMap extends Component {
    static template = "rms_global_equipment_map.GlobalEquipmentMap";
    static props = { ...standardActionServiceProps };

    setup() {
        this.notification = useService("notification");
        this.mapRef = useRef("map");
        this.state = useState({
            loading: true,
            search: "",
            partners: [],
            filtersOpen: false,
            modelFilterSearch: "",
            filters: {
                equipmentModelIds: [],
                operator: "or",
            },
        });
        this.markers = new Map();

        onWillStart(async () => {
            const [partners] = await Promise.all([
                rpc("/rms_global_equipment_map/partners", {}),
                loadLeafletStyles(),
            ]);
            this.state.partners = partners;
            this.state.loading = false;
        });
        onMounted(() => this.initializeMap());
        onWillUnmount(() => {
            this.resizeObserver?.disconnect();
            this.map?.remove();
        });
    }

    get equipmentModels() {
        const equipmentModels = new Map();
        for (const partner of this.state.partners) {
            for (const model of partner.equipment_models) {
                equipmentModels.set(`${model.id}`, { ...model, id: `${model.id}` });
            }
        }
        return [...equipmentModels.values()].sort((left, right) =>
            left.name.localeCompare(right.name)
        );
    }

    get availableEquipmentModels() {
        const term = this.state.modelFilterSearch.trim().toLowerCase();
        if (!term) {
            return this.equipmentModels;
        }
        return this.equipmentModels.filter((model) =>
            model.name.toLowerCase().includes(term)
        );
    }

    get selectedEquipmentModels() {
        const modelsById = new Map(this.equipmentModels.map((model) => [model.id, model]));
        return this.state.filters.equipmentModelIds
            .map((modelId) => modelsById.get(modelId))
            .filter(Boolean);
    }

    get activeFilterCount() {
        return this.state.filters.equipmentModelIds.length;
    }

    get filteredPartners() {
        const term = this.state.search.trim().toLowerCase();
        const selectedModelIds = this.state.filters.equipmentModelIds;
        const operator = this.state.filters.operator;
        return this.state.partners.filter((partner) => {
            const partnerModelIds = partner.equipment_models.map((model) => `${model.id}`);
            if (selectedModelIds.length) {
                if (operator === "and") {
                    if (!selectedModelIds.every((modelId) => partnerModelIds.includes(modelId))) {
                        return false;
                    }
                } else {
                    if (!selectedModelIds.some((modelId) => partnerModelIds.includes(modelId))) {
                        return false;
                    }
                }
            }
            if (!term) {
                return true;
            }
            const equipmentModels = partner.equipment_models
                .map((model) => model.name)
                .join(" ");
            return [partner.name, equipmentModels]
                .join(" ")
                .toLowerCase()
                .includes(term);
        });
    }

    toggleFilters() {
        this.state.filtersOpen = !this.state.filtersOpen;
    }

    onModelFilterSearchInput(event) {
        this.state.modelFilterSearch = event.target.value;
    }

    onOperatorChange(event) {
        this.state.filters.operator = event.target.value;
        this.renderMarkers();
    }

    toggleEquipmentModelFilter(modelId) {
        const id = `${modelId}`;
        if (this.state.filters.equipmentModelIds.includes(id)) {
            this.state.filters.equipmentModelIds = this.state.filters.equipmentModelIds.filter(
                (selectedId) => selectedId !== id
            );
        } else {
            this.state.filters.equipmentModelIds = [
                ...this.state.filters.equipmentModelIds,
                id,
            ];
        }
        this.renderMarkers();
    }

    removeEquipmentModelFilter(modelId) {
        const id = `${modelId}`;
        this.state.filters.equipmentModelIds = this.state.filters.equipmentModelIds.filter(
            (selectedId) => selectedId !== id
        );
        this.renderMarkers();
    }

    clearFilters() {
        this.state.filters.equipmentModelIds = [];
        this.renderMarkers();
    }

    isEquipmentModelSelected(modelId) {
        return this.state.filters.equipmentModelIds.includes(`${modelId}`);
    }

    onSearchInput(event) {
        this.state.search = event.target.value;
        this.renderMarkers();
    }

    initializeMap() {
        if (!window.L || !this.mapRef.el) {
            this.notification.add("No se pudo cargar la librería cartográfica Leaflet.", {
                type: "danger",
            });
            return;
        }
        this.map = window.L.map(this.mapRef.el, {
            center: [40.4168, -3.7038],
            zoom: 6,
        });
        window.L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
            attribution:
                '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>',
            maxZoom: 19,
        }).addTo(this.map);
        this.markerLayer = window.L.layerGroup().addTo(this.map);
        this.renderMarkers();
        this.resizeObserver = new ResizeObserver(() => this.map.invalidateSize());
        this.resizeObserver.observe(this.mapRef.el);
        requestAnimationFrame(() => this.map.invalidateSize());
    }

    renderMarkers() {
        if (!this.markerLayer) {
            return;
        }
        this.markerLayer.clearLayers();
        this.markers.clear();
        const bounds = [];
        for (const partner of this.filteredPartners) {
            const coordinates = [partner.latitude, partner.longitude];
            const marker = window.L.marker(coordinates, {
                title: partner.name,
                icon: window.L.divIcon({
                    className: "o_global_equipment_map_marker",
                    html: "",
                    iconSize: [34, 42],
                    iconAnchor: [17, 42],
                    popupAnchor: [0, -40],
                }),
            });
            marker.bindPopup(this.buildPopup(partner), { minWidth: 260 });
            marker.addTo(this.markerLayer);
            this.markers.set(partner.id, marker);
            bounds.push(coordinates);
        }
        if (bounds.length === 1) {
            this.map.setView(bounds[0], 14);
        } else if (bounds.length > 1) {
            this.map.fitBounds(bounds, { padding: [40, 40], maxZoom: 15 });
        }
    }

    buildPopup(partner) {
        const container = document.createElement("div");
        container.className = "o_global_equipment_map_popup";

        const title = document.createElement("h5");
        title.textContent = partner.name;
        container.appendChild(title);

        const modelsTitle = document.createElement("strong");
        modelsTitle.textContent = `Equipos del Cliente: ${partner.equipment_models.length}`;
        container.appendChild(modelsTitle);

        if (partner.equipment_models.length) {
            const list = document.createElement("ul");
            list.className = "mt-1 mb-0 ps-3";
            for (const model of partner.equipment_models) {
                const item = document.createElement("li");
                item.textContent = model.name;
                list.appendChild(item);
            }
            container.appendChild(list);
        }

        return container;
    }

    focusPartner(partnerId) {
        const marker = this.markers.get(partnerId);
        if (marker) {
            this.map.setView(marker.getLatLng(), Math.max(this.map.getZoom(), 14));
            marker.openPopup();
        }
    }
}

registry.category("actions").add(
    "rms_global_equipment_map.global_map",
    GlobalEquipmentMap
);
