/** @odoo-module **/

import { registry } from "@web/core/registry";

const FRAME_ID = "o_rms_label_print_frame";

function isIOS() {
    const ua = navigator.userAgent || "";
    // iPadOS se presenta como Mac: se distingue por la pantalla táctil.
    return /iPad|iPhone|iPod/.test(ua) || (navigator.platform === "MacIntel" && navigator.maxTouchPoints > 1);
}

function openTab(url) {
    window.open(url, "_blank");
}

/**
 * Imprime la etiqueta sin pasar por una pestaña: el PDF se carga en un marco
 * invisible y se abre el cuadro de impresión del navegador (que recuerda la
 * Brother y su configuración). En el iPad el PDF no se puede imprimir desde un
 * marco: ahí, o si algo falla, se abre la pestaña como antes.
 */
export function printLabelUrl(url) {
    if (!url) {
        return;
    }
    if (isIOS()) {
        openTab(url);
        return;
    }
    document.getElementById(FRAME_ID)?.remove();
    const frame = document.createElement("iframe");
    frame.id = FRAME_ID;
    frame.setAttribute("aria-hidden", "true");
    frame.style.cssText = "position:fixed;right:0;bottom:0;width:1px;height:1px;border:0;opacity:0;pointer-events:none;";
    let done = false;
    frame.onload = () => {
        if (done) {
            return;
        }
        done = true;
        // Un momento para que el visor de PDF termine de pintar la página.
        setTimeout(() => {
            try {
                frame.contentWindow.focus();
                frame.contentWindow.print();
            } catch {
                openTab(url);
            }
        }, 500);
    };
    frame.src = url;
    document.body.appendChild(frame);
}

registry.category("actions").add("rms_print_label", (env, action) => {
    printLabelUrl(action.params?.url);
    if (action.params?.close) {
        return { type: "ir.actions.act_window_close" };
    }
});
