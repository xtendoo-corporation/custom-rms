/** @odoo-module **/

import { registry } from "@web/core/registry";
import { loadCSS, loadJS } from "@web/core/assets";
import { rpc } from "@web/core/network/rpc";
import { useService } from "@web/core/utils/hooks";
import { useDebounced } from "@web/core/utils/timing";
import { standardActionServiceProps } from "@web/webclient/actions/action_service";
import {
    Component,
    markRaw,
    onMounted,
    onWillStart,
    onWillUnmount,
    useRef,
    useState,
} from "@odoo/owl";

const LIB_PATH = "/rms_global_equipment_map/static/lib";
const SIDEBAR_PAGE_SIZE = 200;

/**
 * Load Leaflet and its marker cluster plugin only when a map is opened,
 * instead of shipping them in every backend page. Another map module may
 * already have loaded them: reuse its copy instead of loading a second one.
 */
async function loadLeaflet() {
    await Promise.all([
        loadCSS(`${LIB_PATH}/leaflet/leaflet.css`),
        loadCSS(`${LIB_PATH}/leaflet.markercluster/MarkerCluster.css`),
        loadCSS(`${LIB_PATH}/leaflet.markercluster/MarkerCluster.Default.css`),
    ]);
    if (!window.L) {
        await loadJS(`${LIB_PATH}/leaflet/leaflet.js`);
    }
    if (!window.L.MarkerClusterGroup) {
        await loadJS(`${LIB_PATH}/leaflet.markercluster/leaflet.markercluster.js`);
    }
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
            // Bumped whenever the (non reactive) partner list changes.
            dataVersion: 0,
            sidebarLimit: SIDEBAR_PAGE_SIZE,
            filtersOpen: false,
            modelFilterSearch: "",
            exporting: false,
            filters: {
                equipmentModelIds: [],
                operator: "or",
            },
        });
        // Partner data is kept out of the reactive state: wrapping thousands
        // of records in proxies makes every search noticeably slower.
        this.partners = [];
        this.searchIndex = new Map();
        this.markers = new Map();
        this.filterCache = null;
        this.equipmentModelsCache = null;
        this.applySearch = useDebounced(() => {
            this.state.search = this.pendingSearch;
            this.state.sidebarLimit = SIDEBAR_PAGE_SIZE;
            this.renderMarkers();
        }, 250);

        onWillStart(async () => {
            const [partners] = await Promise.all([
                rpc("/rms_global_equipment_map/partners", {}),
                loadLeaflet(),
            ]);
            this.setPartners(partners);
            this.state.loading = false;
        });
        onMounted(() => this.initializeMap());
        onWillUnmount(() => {
            this.resizeObserver?.disconnect();
            this.map?.remove();
        });
    }

    setPartners(partners) {
        this.partners = markRaw(Array.isArray(partners) ? partners : []);
        this.searchIndex = new Map(
            this.partners.map((partner) => [
                partner.id,
                [
                    partner.name,
                    partner.contact_name,
                    partner.email,
                    partner.phone,
                    ...partner.equipment_models.map((model) => model.name),
                ]
                    .join(" ")
                    .toLowerCase(),
            ])
        );
        this.markers.clear();
        this.filterCache = null;
        this.equipmentModelsCache = null;
        this.state.dataVersion++;
    }

    get equipmentModels() {
        const version = this.state.dataVersion;
        if (this.equipmentModelsCache?.version === version) {
            return this.equipmentModelsCache.result;
        }
        const equipmentModels = new Map();
        for (const partner of this.partners) {
            for (const model of partner.equipment_models) {
                equipmentModels.set(`${model.id}`, { ...model, id: `${model.id}` });
            }
        }
        const result = [...equipmentModels.values()].sort((left, right) =>
            left.name.localeCompare(right.name)
        );
        this.equipmentModelsCache = { version, result };
        return result;
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
        const version = this.state.dataVersion;
        const key = [version, term, operator, selectedModelIds.join(",")].join("|");
        if (this.filterCache?.key === key) {
            return this.filterCache.result;
        }
        const result = this.partners.filter((partner) => {
            if (selectedModelIds.length) {
                const partnerModelIds = new Set(
                    partner.equipment_models.map((model) => `${model.id}`)
                );
                const matches =
                    operator === "and"
                        ? selectedModelIds.every((modelId) => partnerModelIds.has(modelId))
                        : selectedModelIds.some((modelId) => partnerModelIds.has(modelId));
                if (!matches) {
                    return false;
                }
            }
            return !term || this.searchIndex.get(partner.id).includes(term);
        });
        this.filterCache = { key, result };
        return result;
    }

    get visiblePartners() {
        return this.filteredPartners.slice(0, this.state.sidebarLimit);
    }

    onShowMorePartners() {
        this.state.sidebarLimit += SIDEBAR_PAGE_SIZE;
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
        this.pendingSearch = event.target.value;
        this.applySearch();
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
        this.markerLayer = window.L.markerClusterGroup({
            chunkedLoading: true,
            showCoverageOnHover: false,
            maxClusterRadius: 50,
        }).addTo(this.map);
        this.renderMarkers();
        this.resizeObserver = new ResizeObserver(() => this.map.invalidateSize());
        this.resizeObserver.observe(this.mapRef.el);
        requestAnimationFrame(() => this.map.invalidateSize());
    }

    getMarker(partner) {
        let marker = this.markers.get(partner.id);
        if (!marker) {
            const equipmentCount = partner.equipment_models.length;
            marker = window.L.marker([partner.latitude, partner.longitude], {
                title: partner.name,
                icon: window.L.divIcon({
                    className: "o_global_equipment_map_marker",
                    html: equipmentCount ? `<span>${equipmentCount}</span>` : "",
                    iconSize: [34, 42],
                    iconAnchor: [17, 42],
                    popupAnchor: [0, -40],
                }),
            });
            // The popup content is only built when it is opened.
            marker.bindPopup(() => this.buildPopup(partner), { minWidth: 260 });
            this.markers.set(partner.id, marker);
        }
        return marker;
    }

    renderMarkers() {
        if (!this.markerLayer) {
            return;
        }
        const markers = this.filteredPartners.map((partner) => this.getMarker(partner));
        this.markerLayer.clearLayers();
        this.markerLayer.addLayers(markers);
        if (markers.length === 1) {
            this.map.setView(markers[0].getLatLng(), 14);
        } else if (markers.length > 1) {
            // Bounds are computed from the markers themselves: with chunked
            // loading the cluster layer may still be adding them.
            const bounds = window.L.latLngBounds(markers.map((marker) => marker.getLatLng()));
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
            // The marker may be hidden inside a cluster: zoom until it shows.
            this.markerLayer.zoomToShowLayer(marker, () => marker.openPopup());
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
