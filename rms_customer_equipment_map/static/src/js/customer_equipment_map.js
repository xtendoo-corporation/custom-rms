/** @odoo-module **/

import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { standardActionServiceProps } from "@web/webclient/actions/action_service";
import { ConfirmationDialog } from "@web/core/confirmation_dialog/confirmation_dialog";

const LEAFLET_STYLESHEET =
    "/rms_customer_equipment_map/static/lib/leaflet/leaflet.css";

function loadLeafletStyles() {
    if (document.querySelector("link[data-customer-equipment-map-leaflet]")) {
        return Promise.resolve();
    }
    return new Promise((resolve, reject) => {
        const link = document.createElement("link");
        link.rel = "stylesheet";
        link.dataset.customerEquipmentMapLeaflet = "1";
        link.href = LEAFLET_STYLESHEET;
        link.onload = resolve;
        link.onerror = reject;
        document.head.appendChild(link);
    });
}
import {
    Component,
    onMounted,
    onWillStart,
    onWillUnmount,
    useRef,
    useState,
} from "@odoo/owl";

export class CustomerEquipmentMap extends Component {
    static template = "rms_customer_equipment_map.CustomerEquipmentMap";
    static props = { ...standardActionServiceProps };

    setup() {
        this.orm = useService("orm");
        this.actionService = useService("action");
        this.notification = useService("notification");
        this.dialog = useService("dialog");
        this.mapRef = useRef("map");
        this.state = useState({
            loading: true,
            search: "",
            partners: [],
            geolocating: false,
            geolocationDone: 0,
            geolocationTotal: 0,
            filtersOpen: false,
            filters: {
                tagId: "",
            },
        });
        this.markers = new Map();

        onWillStart(async () => {
            const [partners] = await Promise.all([
                this.orm.call(
                    "res.partner",
                    "get_customer_equipment_map_data",
                    []
                ),
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

    get filterOptions() {
        const tags = new Map();
        for (const partner of this.state.partners) {
            for (const tag of partner.tags) {
                tags.set(tag.id, tag);
            }
        }
        const sortedValues = (values) =>
            [...values.values()].sort((left, right) =>
                left.name.localeCompare(right.name)
            );
        return {
            tags: sortedValues(tags),
        };
    }

    get activeFilterCount() {
        return Object.values(this.state.filters).filter(Boolean).length;
    }

    get filteredPartners() {
        const term = this.state.search.trim().toLowerCase();
        const filters = this.state.filters;
        return this.state.partners.filter((partner) => {
            if (
                filters.tagId &&
                !partner.tags.some((tag) => String(tag.id) === filters.tagId)
            ) {
                return false;
            }
            if (!term) {
                return true;
            }
            const equipment = partner.equipment
                .map((item) => item.name + " " + item.serial_no + " " + item.category)
                .join(" ");
            const tags = partner.tags.map((tag) => tag.name).join(" ");
            return [
                partner.name,
                partner.address,
                partner.phone,
                partner.email,
                partner.salesperson?.name || "",
                partner.country?.name || "",
                partner.industry?.name || "",
                tags,
                equipment,
            ]
                .join(" ")
                .toLowerCase()
                .includes(term);
        });
    }

    toggleFilters() {
        this.state.filtersOpen = !this.state.filtersOpen;
    }

    onFilterChange(event) {
        this.state.filters[event.target.name] = event.target.value;
        this.renderMarkers();
    }

    clearFilters() {
        for (const key of Object.keys(this.state.filters)) {
            this.state.filters[key] = "";
        }
        this.renderMarkers();
    }

    initializeMap() {
        if (!window.L || !this.mapRef.el) {
            this.notification.add("No se pudo cargar la librería cartográfica Leaflet.", {
                type: "danger",
            });
            return;
        }
        this.map = window.L.map(this.mapRef.el, { center: [40.4168, -3.7038], zoom: 6 });
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

    async onBulkGeolocate() {
        if (this.state.geolocating) {
            return;
        }
        const candidates = await this.orm.call(
            "res.partner",
            "get_bulk_geolocation_candidates",
            []
        );
        if (!candidates.count) {
            this.notification.add(
                "No hay contactos pendientes con una dirección utilizable.",
                { type: "info" }
            );
            return;
        }
        const skippedMessage = candidates.without_address
            ? " " + candidates.without_address + " contactos sin dirección se omitirán."
            : "";
        this.dialog.add(ConfirmationDialog, {
            title: "Geolocalizar todos los contactos",
            body:
                "Se procesarán " +
                candidates.count +
                " contactos pendientes." +
                skippedMessage +
                " El proceso puede tardar varios minutos.",
            confirmLabel: "Geolocalizar",
            confirm: () => {
                void this.runBulkGeolocation(candidates.ids);
            },
            cancel: () => {},
        });
    }

    async runBulkGeolocation(partnerIds) {
        this.state.geolocating = true;
        this.state.geolocationDone = 0;
        this.state.geolocationTotal = partnerIds.length;
        let localizedCount = 0;
        const failedNames = [];
        try {
            for (const partnerId of partnerIds) {
                const result = await this.orm.call(
                    "res.partner",
                    "bulk_geo_localize_partners",
                    [[partnerId]]
                );
                localizedCount += result.localized_ids.length;
                failedNames.push(...result.failed.map((partner) => partner.name));
                this.state.geolocationDone += 1;
                if (result.error) {
                    throw new Error(result.error);
                }
                if (this.state.geolocationDone < partnerIds.length) {
                    await new Promise((resolve) => setTimeout(resolve, 1100));
                }
            }
            this.state.partners = await this.orm.call(
                "res.partner",
                "get_customer_equipment_map_data",
                []
            );
            this.renderMarkers();
            const failedMessage = failedNames.length
                ? " No se encontró la dirección de " + failedNames.length + " contactos."
                : "";
            this.notification.add(
                "Geolocalización terminada: " +
                    localizedCount +
                    " contactos actualizados." +
                    failedMessage,
                { type: failedNames.length ? "warning" : "success", sticky: true }
            );
        } catch (error) {
            this.notification.add(
                error.message || "Se produjo un error durante la geolocalización.",
                { type: "danger", sticky: true }
            );
        } finally {
            this.state.geolocating = false;
        }
    }

    onSearchInput(event) {
        this.state.search = event.target.value;
        this.renderMarkers();
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
                icon: window.L.divIcon({
                    className: "o_customer_equipment_map_marker",
                    html: `<span>${partner.equipment.length}</span>`,
                    iconSize: [34, 42],
                    iconAnchor: [17, 42],
                    popupAnchor: [0, -40],
                }),
                title: partner.name,
            });
            marker.bindPopup(this.buildPopup(partner), { minWidth: 280 });
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
        container.className = "o_customer_equipment_map_popup";
        const title = document.createElement("h5");
        title.textContent = partner.name;
        container.appendChild(title);
        for (const value of [partner.address, partner.phone, partner.email]) {
            if (value) {
                const line = document.createElement("div");
                line.className = "mb-1";
                line.textContent = value;
                container.appendChild(line);
            }
        }
        const equipmentTitle = document.createElement("strong");
        equipmentTitle.textContent = `Equipos instalados: ${partner.equipment.length}`;
        container.appendChild(equipmentTitle);
        if (partner.equipment.length) {
            const list = document.createElement("ul");
            list.className = "mt-1 mb-2 ps-3";
            for (const equipment of partner.equipment) {
                const item = document.createElement("li");
                item.textContent = [equipment.name, equipment.category, equipment.serial_no]
                    .filter(Boolean)
                    .join(" · ");
                list.appendChild(item);
            }
            container.appendChild(list);
        }
        const buttons = document.createElement("div");
        buttons.className = "d-flex gap-2 mt-2";
        const partnerButton = document.createElement("button");
        partnerButton.type = "button";
        partnerButton.className = "btn btn-primary btn-sm";
        partnerButton.textContent = "Abrir cliente";
        partnerButton.addEventListener("click", () => this.openPartner(partner.id));
        buttons.appendChild(partnerButton);
        const equipmentButton = document.createElement("button");
        equipmentButton.type = "button";
        equipmentButton.className = "btn btn-secondary btn-sm";
        equipmentButton.textContent = "Ver equipos";
        equipmentButton.addEventListener("click", () =>
            this.openEquipment(partner.id, partner.name)
        );
        buttons.appendChild(equipmentButton);
        container.appendChild(buttons);
        return container;
    }

    focusPartner(partnerId) {
        const marker = this.markers.get(partnerId);
        if (marker) {
            this.map.setView(marker.getLatLng(), Math.max(this.map.getZoom(), 14));
            marker.openPopup();
        }
    }

    openPartner(partnerId) {
        return this.actionService.doAction({
            type: "ir.actions.act_window",
            res_model: "res.partner",
            res_id: partnerId,
            views: [[false, "form"]],
            target: "current",
        });
    }

    openEquipment(partnerId, partnerName) {
        return this.actionService.doAction({
            type: "ir.actions.act_window",
            name: `Equipos de ${partnerName}`,
            res_model: "maintenance.equipment",
            views: [[false, "list"], [false, "form"]],
            domain: [["partner_id", "=", partnerId]],
            context: { default_partner_id: partnerId },
            target: "current",
        });
    }
}

registry.category("actions").add(
    "rms_customer_equipment_map.customer_map",
    CustomerEquipmentMap
);
