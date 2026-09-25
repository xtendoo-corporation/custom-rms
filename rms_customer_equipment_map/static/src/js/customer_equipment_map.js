/** @odoo-module **/

import { registry } from "@web/core/registry";
import { loadCSS, loadJS } from "@web/core/assets";
import { useService } from "@web/core/utils/hooks";
import { useDebounced } from "@web/core/utils/timing";
import { standardActionServiceProps } from "@web/webclient/actions/action_service";
import { Dropdown } from "@web/core/dropdown/dropdown";
import { DropdownItem } from "@web/core/dropdown/dropdown_item";
import { deserializeDateTime, formatDateTime } from "@web/core/l10n/dates";
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
const { DateTime } = luxon;
const SIDEBAR_PAGE_SIZE = 200;
// Reload the markers every N batches while geolocating from the map.
const GEO_RELOAD_EVERY_BATCHES = 4;
// When Nominatim answers "too many requests", wait and resume this many times.
const GEO_MAX_AUTOMATIC_WAITS = 3;
const GEO_MAX_WAIT_SECONDS = 120;

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
    static components = { Dropdown, DropdownItem };

    setup() {
        this.orm = useService("orm");
        this.actionService = useService("action");
        this.notification = useService("notification");
        this.mapRef = useRef("map");
        this.state = useState({
            loading: true,
            search: "",
            // Bumped whenever the (non reactive) partner list changes.
            dataVersion: 0,
            sidebarLimit: SIDEBAR_PAGE_SIZE,
            isAdmin: false,
            geoSummary: null,
            // Progress of a geolocation launched from the map.
            geoRun: null,
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
                await this.refreshGeoSummary();
            }
        });
        onMounted(() => this.initializeMap());
        onWillUnmount(() => {
            this.isDestroyed = true;
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

    // ------------------------------------------------------------------
    // Geolocation panel (administrators only)
    // ------------------------------------------------------------------

    get geoTotal() {
        const summary = this.state.geoSummary;
        return summary ? summary.done + summary.pending + summary.failed : 0;
    }

    get geoPercent() {
        const total = this.geoTotal;
        return total ? Math.floor((this.state.geoSummary.done / total) * 100) : 100;
    }

    get geoToProcess() {
        const summary = this.state.geoSummary;
        return summary ? summary.pending + summary.failed : 0;
    }

    /** Whether the background geolocation is running or about to start. */
    get isGeoRunImminent() {
        const nextRun = this.state.geoSummary?.next_run;
        return Boolean(
            nextRun && deserializeDateTime(nextRun) <= DateTime.now().plus({ minutes: 2 })
        );
    }

    get geoNextRunLabel() {
        const nextRun = this.state.geoSummary?.next_run;
        if (!nextRun) {
            return "";
        }
        if (this.isGeoRunImminent) {
            return "en unos instantes";
        }
        return formatDateTime(deserializeDateTime(nextRun), { format: "ccc d LLL, HH:mm" });
    }

    get geoRows() {
        const summary = this.state.geoSummary || {};
        return [
            {
                state: "done",
                label: "Geolocalizados",
                icon: "fa-check-circle text-success",
                count: summary.done || 0,
            },
            {
                state: "pending",
                label: "Pendientes",
                icon: "fa-clock-o text-warning",
                count: summary.pending || 0,
            },
            {
                state: "failed",
                label: "Con error",
                help: "Dirección no encontrada: corrígela y se reintentará sola",
                icon: "fa-times-circle text-danger",
                count: summary.failed || 0,
            },
            {
                state: "no_address",
                label: "Sin dirección",
                help: "Completa la dirección para que aparezcan en el mapa",
                icon: "fa-question-circle text-muted",
                count: summary.no_address || 0,
            },
        ];
    }

    async refreshGeoSummary() {
        if (!this.state.isAdmin) {
            return;
        }
        this.state.geoSummary = await this.orm.call(
            "res.partner",
            "get_geo_localize_summary",
            []
        );
    }

    async openGeoList(state) {
        const action = await this.orm.call(
            "res.partner",
            "action_view_geo_localize_partners",
            [state]
        );
        return this.actionService.doAction(action);
    }

    get geoRunPercent() {
        const run = this.state.geoRun;
        return run && run.total ? Math.floor((run.processed / run.total) * 100) : 0;
    }

    /**
     * Geolocate the pending contacts from the map, in small batches, so the
     * administrator sees the progress. Closing the map stops the run; the
     * nightly cron takes over the contacts left.
     */
    async onGeolocateNow() {
        if (this.state.geoRun?.running) {
            return;
        }
        let total;
        try {
            ({ count: total } = await this.orm.call(
                "res.partner",
                "action_enqueue_geo_localize",
                []
            ));
        } catch (error) {
            this.notification.add(
                error.data?.message || "No se pudo iniciar la geolocalización.",
                { type: "danger", sticky: true }
            );
            return;
        }
        if (!total) {
            this.notification.add("No hay contactos pendientes de geolocalizar.", {
                type: "info",
            });
            await this.refreshGeoSummary();
            return;
        }
        this.state.geoRun = {
            running: true,
            total,
            processed: 0,
            located: 0,
            failed: 0,
            // Seconds left before resuming after a "too many requests".
            waiting: 0,
            serviceError: false,
        };
        // Work on the reactive proxy so that the panel shows each step.
        const run = this.state.geoRun;
        let batches = 0;
        let waits = 0;
        try {
            while (run.running && !this.isDestroyed) {
                const result = await this.orm.call(
                    "res.partner",
                    "action_geo_localize_batch",
                    []
                );
                run.located += result.located;
                run.failed += result.failed;
                run.processed = Math.min(run.total, run.processed + result.located + result.failed);
                batches++;
                if (result.service_error) {
                    if (result.retry_after && waits < GEO_MAX_AUTOMATIC_WAITS) {
                        // Nominatim asked to slow down: wait and resume.
                        waits++;
                        await this.waitGeoRetry(run, result.retry_after);
                        continue;
                    }
                    run.serviceError = result.service_error;
                    break;
                }
                waits = 0;
                if (!result.remaining || !(result.located + result.failed)) {
                    break;
                }
                await this.refreshGeoSummary();
                if (result.located && batches % GEO_RELOAD_EVERY_BATCHES === 0) {
                    await this.reloadPartners();
                }
                // Each batch may run in another server process: keep the pause
                // between requests that Nominatim requires across batches too.
                await new Promise((resolve) => setTimeout(resolve, 1500));
            }
        } catch (error) {
            run.serviceError = error.data?.message || "Error inesperado durante la geolocalización.";
        } finally {
            run.running = false;
        }
        if (this.isDestroyed) {
            return;
        }
        await this.reloadPartners();
        await this.refreshGeoSummary();
        if (run.serviceError) {
            this.notification.add(
                "El servicio de geolocalización no responde. Se han geolocalizado " +
                    run.located +
                    " contactos; el resto se reintentará automáticamente.",
                { type: "danger", sticky: true }
            );
        } else {
            this.notification.add(
                "Geolocalización terminada: " +
                    run.located +
                    " encontrados" +
                    (run.failed ? ", " + run.failed + " con error." : "."),
                { type: run.failed ? "warning" : "success" }
            );
        }
    }

    async waitGeoRetry(run, seconds) {
        run.waiting = Math.min(seconds, GEO_MAX_WAIT_SECONDS);
        while (run.waiting > 0 && run.running && !this.isDestroyed) {
            await new Promise((resolve) => setTimeout(resolve, 1000));
            run.waiting--;
        }
        run.waiting = 0;
    }

    onStopGeolocation() {
        if (this.state.geoRun) {
            this.state.geoRun.running = false;
        }
    }

    async reloadPartners() {
        const data = await this.orm.call(
            "res.partner",
            "get_customer_equipment_map_data",
            []
        );
        this.setPartners(data);
        this.renderMarkers();
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
