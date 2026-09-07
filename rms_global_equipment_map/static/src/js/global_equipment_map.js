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
            exporting: false,
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
            return [
                partner.name,
                partner.contact_name,
                partner.email,
                partner.phone,
                equipmentModels,
            ]
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
            const equipmentCount = partner.equipment_models.length;
            const marker = window.L.marker(coordinates, {
                title: partner.name,
                icon: window.L.divIcon({
                    className: "o_global_equipment_map_marker",
                    html: equipmentCount ? `<span>${equipmentCount}</span>` : "",
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

        const header = document.createElement("div");
        header.className = "o_global_equipment_map_popup_header d-flex align-items-center gap-2";
        const icon = document.createElement("span");
        icon.className = "o_global_equipment_map_partner_icon";
        icon.innerHTML = '<i class="fa fa-building"></i>';
        header.appendChild(icon);
        const title = document.createElement("h5");
        title.className = "mb-0 flex-grow-1";
        title.textContent = partner.name;
        header.appendChild(title);
        container.appendChild(header);

        const metaLines = [
            { icon: "fa-user", value: partner.contact_name },
            { icon: "fa-phone", value: partner.phone },
            { icon: "fa-envelope", value: partner.email },
        ].filter((line) => line.value);
        if (metaLines.length) {
            const meta = document.createElement("div");
            meta.className = "o_global_equipment_map_popup_meta";
            for (const line of metaLines) {
                const row = document.createElement("div");
                row.className = "d-flex align-items-center gap-1";
                row.innerHTML = `<i class="fa ${line.icon}"></i>`;
                const value = document.createElement("span");
                value.textContent = line.value;
                row.appendChild(value);
                meta.appendChild(row);
            }
            container.appendChild(meta);
        }

        const modelsTitle = document.createElement("div");
        modelsTitle.className = "o_global_equipment_map_popup_subtitle";
        modelsTitle.textContent = `Equipos del Cliente (${partner.equipment_models.length})`;
        container.appendChild(modelsTitle);

        const chips = document.createElement("div");
        chips.className = "o_global_equipment_map_chips d-flex flex-wrap gap-1";
        if (partner.equipment_models.length) {
            for (const model of partner.equipment_models) {
                const chip = document.createElement("span");
                chip.className = "o_global_equipment_map_chip";
                chip.textContent = model.name;
                chips.appendChild(chip);
            }
        } else {
            const chip = document.createElement("span");
            chip.className = "o_global_equipment_map_chip o_global_equipment_map_chip_empty";
            chip.textContent = "Sin equipos asignados";
            chips.appendChild(chip);
        }
        container.appendChild(chips);

        return container;
    }

    focusPartner(partnerId) {
        const marker = this.markers.get(partnerId);
        if (marker) {
            this.map.setView(marker.getLatLng(), Math.max(this.map.getZoom(), 14));
            marker.openPopup();
        }
    }

    async exportXlsx() {
        if (this.state.exporting) {
            return;
        }
        const partnerIds = this.filteredPartners.map((partner) => partner.id);
        if (!partnerIds.length) {
            this.notification.add("No hay clientes que coincidan con los filtros activos.", {
                type: "warning",
            });
            return;
        }
        this.state.exporting = true;
        try {
            const result = await rpc("/rms_global_equipment_map/export_xlsx", {
                partner_ids: partnerIds,
            });
            const binary = atob(result.content);
            const bytes = new Uint8Array(binary.length);
            for (let index = 0; index < binary.length; index++) {
                bytes[index] = binary.charCodeAt(index);
            }
            const blob = new Blob([bytes], {
                type: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            });
            const url = URL.createObjectURL(blob);
            const link = document.createElement("a");
            link.href = url;
            link.download = result.filename || "mapa_global_equipos.xlsx";
            document.body.appendChild(link);
            link.click();
            link.remove();
            URL.revokeObjectURL(url);
        } catch (error) {
            this.notification.add(
                error.data?.message || "No se pudo generar el archivo Excel.",
                { type: "danger" }
            );
        } finally {
            this.state.exporting = false;
        }
    }
}

registry.category("actions").add(
    "rms_global_equipment_map.global_map",
    GlobalEquipmentMap
);
