/** @odoo-module **/

import { registry } from "@web/core/registry";
import { loadCSS, loadJS } from "@web/core/assets";
import { useService } from "@web/core/utils/hooks";
import { useDebounced } from "@web/core/utils/timing";
import { standardActionServiceProps } from "@web/webclient/actions/action_service";
import { ConfirmationDialog } from "@web/core/confirmation_dialog/confirmation_dialog";
import {
    Component,
    markRaw,
    onMounted,
    onWillStart,
    onWillUnmount,
    useRef,
    useState,
} from "@odoo/owl";

const LIB_PATH = "/rms_customer_equipment_map/static/lib";
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
            // Bumped whenever the (non reactive) partner list changes.
            dataVersion: 0,
            sidebarLimit: SIDEBAR_PAGE_SIZE,
            geolocating: false,
            isAdmin: false,
            withoutAddressIds: [],
            failedIds: [],
            pendingCount: 0,
        });
        // Partner data is kept out of the reactive state: wrapping thousands
        // of records in proxies makes every search noticeably slower.
        this.partners = [];
        this.searchIndex = new Map();
        this.markers = new Map();
        this.filterCache = null;
        this.applySearch = useDebounced(() => {
            this.state.search = this.pendingSearch;
            this.state.sidebarLimit = SIDEBAR_PAGE_SIZE;
            this.renderMarkers();
        }, 250);

        onWillStart(async () => {
            const [data] = await Promise.all([
                this.orm.call(
                    "res.partner",
                    "get_customer_equipment_map_data",
                    []
                ),
                loadLeaflet(),
            ]);
            this.setPartners(data);
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

    setPartners(data) {
        this.partners = markRaw(Array.isArray(data.partners) ? data.partners : []);
        this.searchIndex = new Map(
            this.partners.map((partner) => [
                partner.id,
                [
                    partner.name,
                    partner.address,
                    partner.phone,
                    partner.email,
                    partner.salesperson?.name || "",
                    partner.country?.name || "",
                    partner.industry?.name || "",
                    ...partner.equipment.map(
                        (item) => item.name + " " + item.serial_no + " " + item.category
                    ),
                ]
                    .join(" ")
                    .toLowerCase(),
            ])
        );
        // Markers are rebuilt lazily for the new data.
        this.markers.clear();
        this.filterCache = null;
        this.state.isAdmin = data.is_admin;
        this.state.dataVersion++;
    }

    get filteredPartners() {
        const term = this.state.search.trim().toLowerCase();
        const version = this.state.dataVersion;
        if (
            this.filterCache &&
            this.filterCache.term === term &&
            this.filterCache.version === version
        ) {
            return this.filterCache.result;
        }
        const result = term
            ? this.partners.filter((partner) =>
                  this.searchIndex.get(partner.id).includes(term)
              )
            : this.partners;
        this.filterCache = { term, version, result };
        return result;
    }

    get visiblePartners() {
        return this.filteredPartners.slice(0, this.state.sidebarLimit);
    }

    onShowMorePartners() {
        this.state.sidebarLimit += SIDEBAR_PAGE_SIZE;
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
        this.setPartners(data);
        this.renderMarkers();
        if (this.state.isAdmin) {
            await this.refreshWithoutAddress();
        }
    }

    onSearchInput(event) {
        this.pendingSearch = event.target.value;
        this.applySearch();
    }

    getMarker(partner) {
        let marker = this.markers.get(partner.id);
        if (!marker) {
            const equipmentCount = partner.equipment.length;
            marker = window.L.marker([partner.latitude, partner.longitude], {
                icon: window.L.divIcon({
                    className: "o_customer_equipment_map_marker",
                    html: equipmentCount ? `<span>${equipmentCount}</span>` : "",
                    iconSize: [34, 42],
                    iconAnchor: [17, 42],
                    popupAnchor: [0, -40],
                }),
                title: partner.name,
            });
            // The popup content is only built when it is opened.
            marker.bindPopup(() => this.buildPopup(partner), { minWidth: 280 });
            this.markers.set(partner.id, marker);
        }
        return marker;
    }

    renderMarkers() {
        if (!this.markerLayer) {
            return;
        }
        const partners = this.filteredPartners;
        const markers = partners.map((partner) => this.getMarker(partner));
        this.markerLayer.clearLayers();
        this.markerLayer.addLayers(markers);
        if (markers.length === 1) {
            this.map.setView(markers[0].getLatLng(), 14);
        } else if (markers.length > 1) {
            // Bounds are computed from the markers themselves: with chunked
            // loading the cluster layer may still be adding them.
            const bounds = window.L.latLngBounds(markers.map((marker) => marker.getLatLng()));
            this.map.fitBounds(bounds, {
                padding: [40, 40],
                maxZoom: 15,
            });
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
            // The marker may be hidden inside a cluster: zoom until it shows.
            this.markerLayer.zoomToShowLayer(marker, () => marker.openPopup());
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
