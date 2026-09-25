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
            isAdmin: false,
            withoutAddressIds: [],
            failedIds: [],
            pendingCount: 0,
        });
        this.markers = new Map();

        onWillStart(async () => {
            const [data] = await Promise.all([
                this.orm.call(
                    "res.partner",
                    "get_customer_equipment_map_data",
                    []
                ),
                loadLeafletStyles(),
            ]);
            this.state.partners = Array.isArray(data.partners) ? data.partners : [];
            this.state.isAdmin = data.is_admin;
            this.state.loading = false;
            if (this.state.isAdmin) {
                void this.refreshWithoutAddress();
            }
        });
        onMounted(() => this.initializeMap());
        onWillUnmount(() => {
            this.resizeObserver?.disconnect();
            this.map?.remove();
        });
    }

    get filteredPartners() {
        const term = this.state.search.trim().toLowerCase();
        return this.state.partners.filter((partner) => {
            if (!term) {
                return true;
            }
            const equipment = partner.equipment
                .map((item) => item.name + " " + item.serial_no + " " + item.category)
                .join(" ");
            return [
                partner.name,
                partner.address,
                partner.phone,
                partner.email,
                partner.salesperson?.name || "",
                partner.country?.name || "",
                partner.industry?.name || "",
                equipment,
            ]
                .join(" ")
                .toLowerCase()
                .includes(term);
        });
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

    async refreshWithoutAddress() {
        const candidates = await this.orm.call(
            "res.partner",
            "get_bulk_geolocation_candidates",
            []
        );
        this.state.withoutAddressIds = candidates.without_address_ids || [];
        this.state.failedIds = candidates.failed_ids || [];
        this.state.pendingCount = candidates.pending || 0;
        return candidates;
    }

    async onViewPartnersWithoutAddress() {
        const action = await this.orm.call(
            "res.partner",
            "action_view_partners_without_address",
            [this.state.withoutAddressIds]
        );
        return this.actionService.doAction(action);
    }

    async onViewPartnersGeolocationFailed() {
        const action = await this.orm.call(
            "res.partner",
            "action_view_partners_geo_localize_failed",
            [this.state.failedIds]
        );
        return this.actionService.doAction(action);
    }

    async onBulkGeolocate() {
        if (this.state.geolocating) {
            return;
        }
        const candidates = await this.refreshWithoutAddress();
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
                "Se encolarán " +
                candidates.count +
                " contactos pendientes o con error." +
                skippedMessage +
                " La geolocalización se hace en segundo plano en el servidor:" +
                " puedes cerrar esta pantalla y los clientes irán apareciendo en el mapa.",
            confirmLabel: "Geolocalizar",
            confirm: () => {
                void this.enqueueGeolocation();
            },
            cancel: () => {},
        });
    }

    async enqueueGeolocation() {
        this.state.geolocating = true;
        try {
            const result = await this.orm.call(
                "res.partner",
                "action_enqueue_geo_localize",
                []
            );
            await this.refreshWithoutAddress();
            this.notification.add(
                result.count +
                    " contactos encolados. Se geolocalizarán en segundo plano" +
                    " (aprox. " +
                    Math.max(1, Math.ceil((result.count * 1.5) / 60)) +
                    " min).",
                { type: "success", sticky: true }
            );
        } catch (error) {
            this.notification.add(
                error.data?.message || "No se pudo encolar la geolocalización.",
                { type: "danger", sticky: true }
            );
        } finally {
            this.state.geolocating = false;
        }
    }

    async onReloadPartners() {
        const data = await this.orm.call(
            "res.partner",
            "get_customer_equipment_map_data",
            []
        );
        this.state.partners = Array.isArray(data.partners) ? data.partners : [];
        this.state.isAdmin = data.is_admin;
        this.renderMarkers();
        if (this.state.isAdmin) {
            await this.refreshWithoutAddress();
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
            const equipmentCount = partner.equipment.length;
            const marker = window.L.marker(coordinates, {
                icon: window.L.divIcon({
                    className: "o_customer_equipment_map_marker",
                    html: equipmentCount ? `<span>${equipmentCount}</span>` : "",
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


}

registry.category("actions").add(
    "rms_customer_equipment_map.customer_map",
    CustomerEquipmentMap
);
