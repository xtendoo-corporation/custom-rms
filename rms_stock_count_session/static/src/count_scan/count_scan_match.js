/** @odoo-module **/

// Dos ayudas del escáner de recuento, como parche de StockCountScan (no tocan
// la cola local ni la captura de ráfagas):
//
// 1. "Coincidencia probable": una lectura que no está en Sage pero se parece
//    a un nº de serie de Sage sin leer sale en ámbar con "¿Es este?" y los
//    botones "Sí, es este" / "No, es otro" (en Lecturas y en la Lista).
// 2. Catálogo de Sage en el selector de producto: si el producto no existe en
//    Odoo se busca el artículo en el maestro de Sage y el responsable lo crea.
//
// Las dos son ACCIONES (no lecturas): si fallan por red se avisa y el botón
// queda libre para repetir; el servidor las admite repetidas sin duplicar.

import { patch } from "@web/core/utils/patch";

import { StockCountScan } from "./count_scan";
// La Lista se parchea antes: aquí se amplían sus filas.
import "./count_scan_list";

const SCAN = "rms.stock.count.scan";
const OPERATOR = "rms.stock.count.operator";
const NET_ERROR = "No se ha podido guardar (sin conexión o el servidor no contesta). No se ha perdido nada: ";

patch(StockCountScan.prototype, {
    setup() {
        super.setup(...arguments);
        this.state.matchBusy = {}; // lectura -> true mientras se guarda la respuesta
        this.state.catalog = null; // catálogo de Sage abierto en el selector de producto
    },

    // ------------------------------------------------------------------
    // Coincidencia probable
    // ------------------------------------------------------------------

    verdictKind(result) {
        const scan = result.scan;
        if (result.status !== "duplicate" && scan && scan.match && scan.match.state === "suggested") {
            return "prob";
        }
        return super.verdictKind(...arguments);
    },

    verdictFor(result) {
        const verdict = super.verdictFor(...arguments);
        const match = result.scan && result.scan.match;
        if (verdict.kind === "prob") {
            verdict.text = result.scan.message || "Se parece a un nº de serie de Sage. ¿Es este?";
            verdict.detail = "Contesta en la fila de la lectura: «Sí, es este» o «No, es otro»";
        } else if (match && match.state === "confirmed") {
            const note = `La etiqueta dice ${result.scan.lot_name || result.scan.code}; en Sage figura como ` +
                `${match.serial}${match.by ? ` (lo confirmó ${match.by}${match.at ? ` · ${match.at}` : ""})` : ""}`;
            verdict.detail = verdict.detail ? `${verdict.detail} · ${note}` : note;
        }
        return verdict;
    },

    verdictIcon(kind) {
        return kind === "prob" ? "≈" : super.verdictIcon(...arguments);
    },

    _feedback(kind, status) {
        // Mismo doble pitido que el resto de avisos en ámbar.
        return super._feedback(kind === "prob" ? "est" : kind, status);
    },

    shortReason(scan, kind) {
        const match = scan.match;
        if (kind === "prob") {
            const candidates = (match && match.candidates) || [];
            return candidates.length === 1 ? `¿Es ${candidates[0].serial} de Sage?`
                : `Se parece a ${candidates.length} de Sage: ¿cuál es?`;
        }
        const reason = super.shortReason(...arguments);
        if (match && match.state === "confirmed" && scan.type === "serial") {
            return reason ? `${reason} · ≈ Sage ${match.serial}` : `≈ en Sage: ${match.serial}`;
        }
        return reason;
    },

    matchCandidates(scan) {
        return (scan.match && scan.match.candidates) || [];
    },

    async _matchCall(scanId, method, args, retryLabel) {
        if (this.state.matchBusy[scanId]) {
            return;
        }
        const op = this.state.operatorState.operator;
        this.state.matchBusy[scanId] = true;
        try {
            const result = await this._send(SCAN, method, [[scanId], ...args], { operator_id: op.id });
            // Solo las lecturas propias están en "Lecturas"; desde la Lista se
            // puede contestar la de un compañero.
            if (result.scan && this.state.history.some((scan) => scan.id === scanId)) {
                this._mergeHistory([result.scan]);
            }
            this.state.conn = this.state.conn === "expired" ? "expired" : "ok";
            this._scheduleProgress(0);
            this._listSchedule(0);
            return result;
        } catch (error) {
            const kind = await this._errorKind(error);
            if (kind === "expired") {
                this.state.conn = "expired";
            }
            const text = kind === "user" ? ((error.data && error.data.message) || "No se puede hacer.")
                : kind === "expired" ? `Tu sesión ha caducado: vuelve a entrar y pulsa otra vez «${retryLabel}».`
                : `${NET_ERROR}vuelve a pulsar «${retryLabel}».`;
            this.notification.add(text, { type: kind === "user" ? "warning" : "danger", sticky: kind !== "user" });
            return null;
        } finally {
            delete this.state.matchBusy[scanId];
            if (this.state.inputMode === "pda") {
                this._focusInput();
            }
        }
    },

    async matchConfirm(scanId, key) {
        const result = await this._matchCall(scanId, "scanner_match_confirm", [key || false], "Sí, es este");
        if (result) {
            this._feedback("ok", "ok");
        }
    },

    async matchReject(scanId) {
        await this._matchCall(scanId, "scanner_match_reject", [], "No, es otro");
    },

    // Filas de la Lista: sugerencia sin confirmar (ámbar) y emparejadas.
    listRowKind(row, waiting) {
        const kind = super.listRowKind(...arguments);
        return kind === "todo" && row.sug ? "prob" : kind;
    },

    listRowClass(row, kind) {
        if (kind === "prob") {
            return "o_rms_cs_k_prob" + (this.state.list.detail === row.id ? " o_rms_cs_l_open" : "");
        }
        return super.listRowClass(...arguments);
    },

    listRowText(row, kind) {
        if (kind === "prob") {
            return `¿es ${row.sug.serial}?`;
        }
        const text = super.listRowText(...arguments);
        if (row.read_as && (kind === "ok" || kind === "est")) {
            return `≈ leído como ${row.read_as}${kind === "est" ? ` · ${text}` : (row.here ? "" : ` · ${text}`)}`;
        }
        return text;
    },

    // ------------------------------------------------------------------
    // Catálogo de Sage en el selector de producto
    // ------------------------------------------------------------------

    openPanel() {
        this.state.catalog = null;
        return super.openPanel(...arguments);
    },

    closePanel() {
        this.state.catalog = null;
        return super.closePanel(...arguments);
    },

    onPanelQueryInput() {
        // Se ha cambiado lo buscado: el catálogo abierto ya no corresponde.
        this.state.catalog = null;
        return super.onPanelQueryInput(...arguments);
    },

    async catalogSearch() {
        const op = this.state.operatorState.operator;
        const query = this.state.panelQuery;
        this.state.catalog = { query, loading: true, error: null, can_create: false, articles: [], pick: null,
            byQuantity: false, busy: false, note: null };
        try {
            const data = await this._send(OPERATOR, "scanner_catalog_search", [[op.id], query]);
            if (this.state.catalog && this.state.catalog.query === query) {
                Object.assign(this.state.catalog, { loading: false, can_create: data.can_create, articles: data.articles });
                if (data.articles.length === 1) {
                    this.state.catalog.pick = data.articles[0];
                }
            }
        } catch {
            if (this.state.catalog && this.state.catalog.query === query) {
                Object.assign(this.state.catalog, { loading: false,
                    error: "No se ha podido buscar en el catálogo (sin conexión o el servidor no contesta)." });
            }
        }
    },

    catalogPick(article) {
        const catalog = this.state.catalog;
        catalog.pick = catalog.pick && catalog.pick.id === article.id ? null : article;
        catalog.byQuantity = false;
        catalog.note = null;
    },

    async catalogUse(article) {
        await this.pickPanelResult({ id: article.product_id });
        this.state.catalog = null;
    },

    async catalogCreate() {
        const catalog = this.state.catalog;
        const article = catalog && catalog.pick;
        if (!article || catalog.busy) {
            return;
        }
        const op = this.state.operatorState.operator;
        catalog.busy = true;
        catalog.note = null;
        try {
            const result = await this._send(OPERATOR, "scanner_catalog_create", [[op.id], article.id, catalog.byQuantity]);
            if (result.status === "created" || result.status === "exists") {
                this._applyState(result.state);
                this.notification.add(
                    (result.status === "created" ? `Producto creado: ${result.product_name}. ` : `Ya existía: ${result.product_name}. `) +
                    "Queda elegido: vuelve a leer el nº de serie del equipo.", { type: "success" });
                this.state.catalog = null;
                this.state.panel = null;
                return;
            }
            // Archivado o con varias coincidencias: no se ha creado nada.
            article.status = result.status;
            article.product_name = result.product_name || article.product_name;
            catalog.note = result.message;
        } catch (error) {
            const kind = await this._errorKind(error);
            catalog.note = kind === "user" ? ((error.data && error.data.message) || "No se puede crear el producto.")
                : kind === "expired" ? "Tu sesión ha caducado: vuelve a entrar y pulsa otra vez «Crear este producto»."
                : "No se ha podido crear (sin conexión o el servidor no contesta). Vuelve a pulsar «Crear este producto»: no se creará dos veces.";
        } finally {
            if (this.state.catalog === catalog) {
                catalog.busy = false;
            }
        }
    },
});
