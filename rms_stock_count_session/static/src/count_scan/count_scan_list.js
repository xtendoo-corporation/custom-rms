/** @odoo-module **/

// Vista "Lista" del escáner de recuento: todo lo que Sage dice que hay en la
// nave (marca > producto > nº de serie) y cada equipo en su color al leerlo.
//
// Va como parche de StockCountScan para no tocar la cola local, la captura de
// ráfagas ni la vista "Lecturas": aquí solo se LEE lo que pasa (las lecturas
// que entran por _mergeHistory) y se pinta. La carga es perezosa: marcas al
// abrir la vista, productos al abrir una marca, nº de serie al abrir un producto.

import { ConfirmationDialog } from "@web/core/confirmation_dialog/confirmation_dialog";
import { patch } from "@web/core/utils/patch";
import { onWillUnmount, useEffect, useRef } from "@odoo/owl";

import { StockCountScan } from "./count_scan";

const MODEL = "rms.stock.count.operator";
const LIST_REFRESH_MS = 30000; // lecturas de otros operarios
const LIST_AFTER_SCAN_MS = 800; // agrupa las lecturas seguidas de la pistola
const LIST_SEARCH_MS = 350;
// La pistola disparada con el cursor en el buscador (mismos tiempos que la casilla de lectura).
const BURST_JOIN_MS = 90;
const BURST_PAUSE_MS = 160;
const SAGE_STATE_CODE = { nuevo: "new", demo: "demo", "2mano": "second_hand" };
const STATE_LABEL = { new: "Nuevo", demo: "Demo", second_hand: "2ª mano", ex_demo: "Ex-Demo" };

// Formas comparables de un nº de serie leído (como normalize_serial y
// serial_alternatives del servidor): sin separadores ni ceros delante, y con
// o sin el "SN" que AtlasIED lleva en Sage.
function serialForms(code) {
    let text = String(code || "").replace(/[\x00-\x1f\x7f]/g, "").trim().replace(/'/g, "-");
    text = text.replace(/^\][A-Za-z][0-9A-Za-z]/, "");
    text = text.replace(/^(?:S\s*\/\s*N\s*[:#.\-]?\s*|(?:SN|SERIAL(?:\s*N(?:O|UMBER)?\.?)?)\s*[:#.\-\s]\s*)/i, "");
    let key = text.replace(/[\s\-./_]+/g, "").toUpperCase();
    if (!key) {
        return [];
    }
    key = key.replace(/^0+/, "") || "0";
    const forms = [key, `SN${key}`];
    if (key.startsWith("SN") && key.length > 4) {
        forms.push(key.slice(2).replace(/^0+/, "") || "0");
    }
    return forms;
}

function emptyList() {
    return {
        loaded: false,
        loading: false,
        error: null,
        filter: "all", // all | pending | done
        query: "", // búsqueda aplicada (la que se ha pedido al servidor)
        text: "", // lo que hay escrito en el buscador ahora mismo
        order: "pending", // pending (más pendientes primero) | alpha
        rank: {}, // orden fijado al cargar: leer no hace saltar las marcas
        summary: null, // {has_sage, site, total, counted, brands, extra_count}
        open: {}, // marca abierta
        products: {}, // marca -> {products, qty}
        openProducts: {}, // "marca|producto" abierto
        serials: {}, // "marca|producto" -> {rows, total}
        extraOpen: false,
        extra: null, // altas: {rows, total}
        detail: null, // equipo desplegado
        flashId: null,
        printOpen: false,
        refreshedAt: "",
    };
}

patch(StockCountScan.prototype, {
    setup() {
        super.setup(...arguments);
        this.state.view = "scans"; // scans (Lecturas, la de siempre) | list (Lista)
        this.state.list = emptyList();
        this.listScrollRef = useRef("listScroll");
        this._listSeen = new Map();
        this._listSeq = 0;
        this._listScrollTop = 0;
        this._listStale = false;
        this._listTimer = null;
        // Al volver a la Lista (desde Lecturas o desde un panel) se recupera
        // la posición en la que estaba y, si mientras tanto hubo lecturas o
        // apuntes por cantidad, se ponen al día los contadores.
        useEffect(
            () => {
                const el = this.listScrollRef.el;
                if (el && this._listScrollTop) {
                    el.scrollTop = this._listScrollTop;
                }
                if (this._listStale && this._listActive && this.state.list.loaded) {
                    this._listRefresh();
                }
            },
            () => [this.state.view, this.state.panel, this.state.step, Boolean(this.state.list.summary)]
        );
        onWillUnmount(() => {
            clearInterval(this._listTimer);
            clearTimeout(this._listRefreshTimer);
            clearTimeout(this._listSearchTimer);
            clearTimeout(this._listBurstTimer);
        });
    },

    // ------------------------------------------------------------------
    // Enganches con lo que ya hace el escáner (sin cambiarlo)
    // ------------------------------------------------------------------

    async join(name) {
        this._listSeen = new Map();
        this._listStale = false;
        this._listSeq++;
        const view = this.state.view;
        clearTimeout(this._listSearchTimer);
        this.state.list = { ...emptyList(), filter: this.state.list.filter, order: this.state.list.order };
        await super.join(...arguments);
        if (view === "list" && this.state.step === "scan") {
            this._listRefresh({ reorder: true });
        }
    },

    // Toda lectura confirmada por el servidor pasa por aquí.
    _mergeHistory(scans) {
        super._mergeHistory(...arguments);
        try {
            this._listOnScans(scans || []);
        } catch {
            // La Lista es informativa: nunca debe estorbar a una lectura.
        }
    },

    async deleteScan() {
        await super.deleteScan(...arguments);
        this._listSchedule(0);
    },

    async changeScanState() {
        await super.changeScanState(...arguments);
        this._listSchedule(0);
    },

    openPanel() {
        this._listKeepScroll();
        return super.openPanel(...arguments);
    },

    // ------------------------------------------------------------------
    // Conmutador Lecturas / Lista
    // ------------------------------------------------------------------

    setView(view) {
        if (view === this.state.view) {
            return;
        }
        this._listKeepScroll();
        this.state.view = view;
        if (view === "list") {
            if (!this._listTimer) {
                this._listTimer = setInterval(() => this._listTick(), LIST_REFRESH_MS);
            }
            this._listRefresh({ reorder: !this.state.list.loaded });
        }
        if (this.state.inputMode === "pda") {
            this._focusInput();
        }
    },

    _listKeepScroll() {
        const el = this.listScrollRef.el;
        if (el) {
            this._listScrollTop = el.scrollTop;
        }
    },

    get _listActive() {
        return this.state.view === "list" && this.state.step === "scan" && !this.state.panel;
    },

    _listTick() {
        const ls = this.state.list;
        if (this._listActive && (ls.loaded || ls.error) && !ls.loading && !document.hidden &&
                this.state.conn !== "offline") {
            this._listRefresh();
        }
    },

    _listSchedule(delay = LIST_AFTER_SCAN_MS) {
        clearTimeout(this._listRefreshTimer);
        if (!this.state.list.loaded) {
            return;
        }
        this._listRefreshTimer = setTimeout(() => {
            if (this._listActive) {
                this._listRefresh();
            } else {
                // Con un panel abierto o en "Lecturas": al volver a la Lista.
                this._listStale = true;
            }
        }, delay);
    },

    // ------------------------------------------------------------------
    // Carga y refresco (una sola llamada: totales + grupos abiertos)
    // ------------------------------------------------------------------

    _listOpened() {
        const ls = this.state.list;
        const opened = [];
        for (const brandId of Object.keys(ls.open)) {
            const prefix = `${brandId}|`;
            const products = Object.keys(ls.openProducts)
                .filter((pkey) => pkey.startsWith(prefix))
                .map((pkey) => [pkey.slice(prefix.length), (ls.serials[pkey]?.rows || []).length]);
            opened.push([parseInt(brandId, 10), products]);
        }
        return opened;
    },

    async _listRefresh({ auto = false, reorder = false } = {}) {
        const op = this.state.operatorState?.operator;
        const ls = this.state.list;
        if (!op || this.state.step !== "scan") {
            return;
        }
        clearTimeout(this._listRefreshTimer);
        this._listStale = false;
        const seq = ++this._listSeq;
        ls.loading = true;
        try {
            const data = await this._send(MODEL, "scanner_list_refresh",
                [[op.id], ls.filter, ls.query, auto ? [] : this._listOpened(), auto]);
            if (seq !== this._listSeq || this.state.operatorState?.operator.id !== op.id) {
                return;
            }
            this._listApply(data, { auto, reorder });
            ls.error = null;
        } catch {
            this._listStale = true;
            if (seq === this._listSeq) {
                ls.error = "No se ha podido actualizar la lista (sin conexión o el servidor no contesta). " +
                    "Puedes seguir leyendo: las lecturas se guardan igual.";
            }
        } finally {
            if (seq === this._listSeq) {
                ls.loading = false;
            }
        }
    },

    _listApply(data, { auto = false, reorder = false } = {}) {
        const ls = this.state.list;
        const { products, serials, ...summary } = data;
        ls.summary = summary;
        if (auto) {
            // Buscador: quedan abiertos justo los grupos que casan.
            ls.open = {};
            ls.openProducts = {};
            ls.products = {};
            ls.serials = {};
            for (const brandId of Object.keys(products || {})) {
                ls.open[brandId] = true;
            }
            for (const pkey of Object.keys(serials || {})) {
                ls.openProducts[pkey] = true;
            }
        }
        for (const [brandId, value] of Object.entries(products || {})) {
            ls.products[brandId] = value;
        }
        for (const [pkey, value] of Object.entries(serials || {})) {
            ls.serials[pkey] = value;
        }
        if (reorder || auto || !Object.keys(ls.rank).length) {
            this._listReorder();
        }
        if (ls.extraOpen && summary.extra_count) {
            this._listLoadExtra();
        }
        ls.loaded = true;
        const now = new Date();
        ls.refreshedAt = `${String(now.getHours()).padStart(2, "0")}:${String(now.getMinutes()).padStart(2, "0")}`;
    },

    _listReorder() {
        const ls = this.state.list;
        const brands = [...(ls.summary?.brands || [])];
        const byName = (a, b) => a.name.localeCompare(b.name, "es", { sensitivity: "base" });
        if (ls.order === "pending") {
            brands.sort((a, b) => (b.total - b.counted) - (a.total - a.counted) || byName(a, b));
        } else {
            brands.sort(byName);
        }
        const rank = {};
        brands.forEach((brand, index) => { rank[brand.id] = index; });
        ls.rank = rank;
    },

    // Marcas en el orden fijado al cargar (las nuevas, al final).
    get listBrands() {
        const ls = this.state.list;
        const rank = ls.rank || {};
        const position = (brand) => (brand.id in rank ? rank[brand.id] : 1e9);
        return [...(ls.summary?.brands || [])].sort((a, b) => position(a) - position(b) ||
            a.name.localeCompare(b.name, "es", { sensitivity: "base" }));
    },

    get listOpenBrands() {
        const ls = this.state.list;
        return this.listBrands.filter((brand) => ls.open[brand.id]).slice(0, 4);
    },

    // Filtro o búsqueda nuevos: lo que no está abierto se volverá a pedir.
    _listDropClosed() {
        const ls = this.state.list;
        for (const brandId of Object.keys(ls.products)) {
            if (!ls.open[brandId]) { delete ls.products[brandId]; }
        }
        for (const pkey of Object.keys(ls.serials)) {
            if (!ls.openProducts[pkey]) { delete ls.serials[pkey]; }
        }
        ls.extra = null;
        ls.detail = null;
    },

    listRefreshNow() {
        this._listRefresh({ reorder: true });
        this._listBackToGun();
    },

    setListFilter(filter) {
        const ls = this.state.list;
        if (ls.filter === filter) {
            return;
        }
        ls.filter = filter;
        this._listDropClosed();
        this._listRefresh({ auto: Boolean(ls.query.trim()), reorder: true });
        this._listBackToGun();
    },

    toggleListOrder() {
        const ls = this.state.list;
        ls.order = ls.order === "pending" ? "alpha" : "pending";
        this._listReorder();
        this._listBackToGun();
    },

    _listBackToGun() {
        if (this.state.inputMode === "pda") {
            this._focusInput();
        }
    },

    // ------------------------------------------------------------------
    // Buscador (en el servidor). Si lo que "teclea" es la pistola, es una
    // lectura y no una búsqueda: se saca del buscador y se registra.
    // ------------------------------------------------------------------

    onListQueryInput(ev) {
        const input = ev.target;
        const now = ev.timeStamp || performance.now();
        const burst = this._listBurst;
        if (ev.inputType && ev.inputType.startsWith("delete")) {
            this._listBurst = null;
        } else if (burst && now - burst.last <= BURST_JOIN_MS) {
            burst.last = now;
            burst.chars += 1;
        } else {
            let from = Math.max(0, input.value.length - 1);
            if (burst && this._isScannerBurst(burst) && burst.from < from) {
                // Otra lectura empieza sin pausa: la anterior está completa.
                const code = input.value.slice(burst.from, from);
                input.value = input.value.slice(0, burst.from) + input.value.slice(from);
                from = burst.from;
                this._enqueue(code);
            }
            this._listBurst = { start: now, last: now, chars: 1, from };
        }
        // El texto del buscador va siempre al día: un repintado (marcador,
        // refresco) no debe devolver la casilla a un valor anterior.
        this.state.list.text = input.value;
        clearTimeout(this._listBurstTimer);
        this._listBurstTimer = setTimeout(() => this._listFlushBurst(input), BURST_PAUSE_MS);
        clearTimeout(this._listSearchTimer);
        this._listSearchTimer = setTimeout(() => this._listApplyQuery(input.value), LIST_SEARCH_MS);
    },

    _listFlushBurst(input) {
        const burst = this._listBurst;
        this._listBurst = null;
        clearTimeout(this._listBurstTimer);
        if (!burst || !input || !this._isScannerBurst(burst)) {
            return false;
        }
        const code = input.value.slice(burst.from);
        input.value = input.value.slice(0, burst.from);
        this.state.list.text = input.value;
        this._enqueue(code);
        this._listBackToGun();
        return true;
    },

    onListQueryKeydown(ev) {
        if (ev.key === "Escape") {
            ev.preventDefault();
            this.clearListQuery();
        } else if (ev.key === "Enter" || (ev.key === "Tab" && this._listBurst)) {
            // Pistola con Enter/Tab al final, o Enter a mano: se busca ya y el
            // cursor vuelve a la casilla de lectura.
            ev.preventDefault();
            this._listFlushBurst(ev.target);
            clearTimeout(this._listSearchTimer);
            this._listApplyQuery(ev.target.value);
            this._listBackToGun();
        }
    },

    _listApplyQuery(value) {
        const ls = this.state.list;
        value = value || "";
        if (value === ls.query) {
            return;
        }
        ls.query = value;
        this._listDropClosed();
        this._listScrollTop = 0;
        if (this.listScrollRef.el) {
            this.listScrollRef.el.scrollTop = 0;
        }
        this._listRefresh({ auto: Boolean(value.trim()), reorder: true });
    },

    clearListQuery() {
        clearTimeout(this._listSearchTimer);
        clearTimeout(this._listBurstTimer);
        this._listBurst = null;
        this.state.list.text = "";
        this._listApplyQuery("");
        this._listBackToGun();
    },

    // ------------------------------------------------------------------
    // Abrir y cerrar grupos (carga perezosa)
    // ------------------------------------------------------------------

    async _listCall(method, args) {
        const op = this.state.operatorState.operator;
        try {
            const result = await this._send(MODEL, method, [[op.id], ...args]);
            this.state.list.error = null;
            return result;
        } catch {
            this.state.list.error = "No se ha podido cargar (sin conexión o el servidor no contesta). Vuelve a tocarlo.";
            return null;
        }
    },

    async toggleListBrand(brand) {
        const ls = this.state.list;
        this._listBackToGun();
        if (ls.open[brand.id]) {
            delete ls.open[brand.id];
            return;
        }
        ls.open[brand.id] = true;
        const seq = this._listSeq;
        const data = await this._listCall("scanner_list_products", [brand.id, ls.filter, ls.query]);
        if (seq !== this._listSeq && ls.products[brand.id]) {
            return; // un refresco más nuevo ya lo ha traído
        }
        if (data) {
            ls.products[brand.id] = data;
        } else if (!ls.products[brand.id]) {
            delete ls.open[brand.id];
        }
    },

    async toggleListProduct(brand, product) {
        const ls = this.state.list;
        const pkey = `${brand.id}|${product.key}`;
        this._listBackToGun();
        if (ls.openProducts[pkey]) {
            delete ls.openProducts[pkey];
            return;
        }
        ls.openProducts[pkey] = true;
        const seq = this._listSeq;
        const data = await this._listCall("scanner_list_serials", [brand.id, product.key, ls.filter, ls.query]);
        if (seq !== this._listSeq && ls.serials[pkey]) {
            return;
        }
        if (data) {
            ls.serials[pkey] = data;
        } else if (!ls.serials[pkey]) {
            delete ls.openProducts[pkey];
        }
    },

    async listMoreSerials(brand, product) {
        const ls = this.state.list;
        const pkey = `${brand.id}|${product.key}`;
        const group = ls.serials[pkey];
        if (!group) {
            return;
        }
        this._listBackToGun();
        const data = await this._listCall("scanner_list_serials",
            [brand.id, product.key, ls.filter, ls.query, group.rows.length]);
        const current = ls.serials[pkey];
        if (data && current) {
            const known = new Set(current.rows.map((row) => row.id));
            current.rows.push(...data.rows.filter((row) => !known.has(row.id)));
            current.total = data.total;
        }
    },

    async toggleListExtra() {
        const ls = this.state.list;
        this._listBackToGun();
        ls.extraOpen = !ls.extraOpen;
        if (ls.extraOpen) {
            await this._listLoadExtra();
        }
    },

    async _listLoadExtra() {
        const ls = this.state.list;
        const data = await this._listCall("scanner_list_extra", [ls.query, 0, Math.max(200, (ls.extra?.rows || []).length)]);
        if (data) {
            ls.extra = data;
        }
    },

    async listMoreExtra() {
        const ls = this.state.list;
        if (!ls.extra) {
            return;
        }
        const data = await this._listCall("scanner_list_extra", [ls.query, ls.extra.rows.length]);
        if (data && ls.extra) {
            ls.extra.rows.push(...data.rows);
            ls.extra.total = data.total;
        }
    },

    // ------------------------------------------------------------------
    // En vivo: una lectura propia pone su fila en su color al momento; los
    // contadores exactos llegan con el refresco ligero (sin cerrar nada).
    // ------------------------------------------------------------------

    _listOnScans(scans) {
        const ls = this.state.list;
        let changed = false;
        for (const scan of scans) {
            if (!scan || !scan.id) {
                continue;
            }
            const signature = `${scan.type}|${scan.product_state_id}|${scan.quantity}|${scan.lot_name}`;
            if (this._listSeen.get(scan.id) === signature) {
                continue;
            }
            this._listSeen.set(scan.id, signature);
            if (!["serial", "product", "unknown"].includes(scan.type)) {
                continue;
            }
            changed = true;
            if (scan.type === "serial" && ls.loaded) {
                this._listMark(scan);
            }
        }
        if (changed && ls.loaded) {
            // Una respuesta pedida antes de esta lectura ya no vale.
            this._listSeq++;
            ls.loading = false;
            this._listSchedule();
        }
    },

    _listMark(scan) {
        const ls = this.state.list;
        const os = this.state.operatorState;
        const forms = new Set(serialForms(scan.lot_name || scan.code));
        const hits = [];
        for (const [pkey, group] of Object.entries(ls.serials)) {
            for (const row of group.rows) {
                if (forms.has(row.norm)) {
                    hits.push([pkey, row]);
                }
            }
        }
        // Sony repite nº de serie entre modelos: con dos candidatos decide el servidor.
        if (hits.length !== 1) {
            return;
        }
        const [pkey, row] = hits[0];
        const code = ((os?.product_states || []).find((st) => st.id === scan.product_state_id) || {}).code;
        const kind = code && code in STATE_LABEL && code !== SAGE_STATE_CODE[row.st] ? "est" : "ok";
        const was = row.k;
        Object.assign(row, {
            k: kind, here: true, at: scan.time || "ahora", by: os?.operator.name || "",
            sess: os?.session.name || "", read_state: STATE_LABEL[code] || scan.product_state_name || "",
        });
        ls.flashId = row.id;
        const brandId = pkey.split("|")[0];
        const product = (ls.products[brandId]?.products || []).find((item) => `${brandId}|${item.key}` === pkey);
        const brand = (ls.summary?.brands || []).find((item) => String(item.id) === brandId);
        const counted = was === "todo" ? 1 : 0;
        const review = (kind === "est" ? 1 : 0) - (was === "est" ? 1 : 0);
        for (const target of [product, brand, ls.summary]) {
            if (target) {
                target.counted += counted;
                target.review += review;
            }
        }
    },

    // Lecturas aún en la cola local (sin confirmar por el servidor): su fila
    // sale con el reloj gris, no en verde.
    get listWaiting() {
        const waiting = new Set();
        for (const item of this.state.pending) {
            for (const code of item.codes || [item.code]) {
                for (const form of serialForms(code)) {
                    waiting.add(form);
                }
            }
        }
        return waiting;
    },

    listRowKind(row, waiting) {
        if (row.k !== "todo") {
            return row.k;
        }
        return waiting.has(row.norm) ? "wait" : "todo";
    },

    listRowClass(row, kind) {
        const base = { todo: "o_rms_cs_l_todo", wait: "o_rms_cs_row_pending o_rms_cs_l_wait",
            ok: "o_rms_cs_k_ok", est: "o_rms_cs_k_est" }[kind] || "o_rms_cs_l_todo";
        return base + (this.state.list.detail === row.id ? " o_rms_cs_l_open" : "") +
            (this.state.list.flashId === row.id ? " o_rms_cs_l_flash" : "");
    },

    listRowText(row, kind) {
        if (kind === "est") {
            return `Sage dice ${row.st_name}, leído ${row.read_state || "otro estado"}`;
        }
        if (kind === "wait") {
            return "Pendiente de enviar";
        }
        if (kind === "ok") {
            return row.here ? "Leído" : `Leído en ${row.sess || "otro recuento"}`;
        }
        return "";
    },

    listPercent(group) {
        return group.total ? Math.round((100 * group.counted) / group.total) : 0;
    },

    // ------------------------------------------------------------------
    // Atajos: detalle de un equipo, "Imprimir y contar", "Por cantidad"
    // ------------------------------------------------------------------

    toggleListDetail(row) {
        const ls = this.state.list;
        ls.detail = ls.detail === row.id ? null : row.id;
        this._listBackToGun();
    },

    // Equipo sin pegatina (flycase): se cuenta y se imprime su etiqueta, igual
    // que desde "Buscar en Sage", con confirmación.
    listPrintAndCount(row, product) {
        const op = this.state.operatorState.operator;
        this.dialog.add(ConfirmationDialog, {
            title: "Imprimir y contar",
            body: `¿Contar ${product.name || product.ref} con nº de serie ${row.serial} (${row.st_name}) ` +
                "e imprimir su etiqueta? Hazlo solo si tienes el equipo delante y no tiene pegatina.",
            confirmLabel: "Imprimir y contar",
            cancelLabel: "Cancelar",
            confirm: async () => {
                try {
                    const result = await this.orm.call(MODEL, "scanner_sage_print_and_count", [[op.id], row.id, false]);
                    this._mergeHistory([result.scan]);
                    this._applyState(result.state);
                    this.state.list.detail = null;
                    this._scheduleProgress(0);
                    this._feedback("ok", result.status);
                    await this.action.doAction(result.action);
                } catch (error) {
                    this.notification.add((error.data && error.data.message) || "No se pudo contar ni imprimir.",
                        { type: "warning" });
                }
            },
            cancel: () => {},
        }, { onClose: () => this._listBackToGun() });
    },

    // Artículo sin nº de serie: abre el panel "Por cantidad" de siempre con
    // ese artículo ya elegido.
    listOpenQty(item) {
        this.openPanel("qty");
        this.pickQtyItem({ ...item });
    },

    // ------------------------------------------------------------------
    // Imprimir lista (PDF tipo packing list)
    // ------------------------------------------------------------------

    toggleListPrint() {
        this.state.list.printOpen = !this.state.list.printOpen;
        this._listBackToGun();
    },

    async listPrint(brandId, onlyPending) {
        const op = this.state.operatorState.operator;
        this.state.list.printOpen = false;
        try {
            const action = await this.orm.call(MODEL, "scanner_list_print", [[op.id], brandId || false, onlyPending]);
            await this.action.doAction(action);
        } catch (error) {
            this.notification.add((error.data && error.data.message) || "No se pudo preparar la lista para imprimir.",
                { type: "warning" });
        }
        this._listBackToGun();
    },
});
