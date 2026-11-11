/** Marca visual de la base de pruebas: solo si el nombre de la BD contiene "sandbox". */
import { Component, onWillDestroy } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { session } from "@web/session";

export const SANDBOX_CLASS = "o_rms_sandbox";

export function isSandboxDb(dbName) {
    return /sandbox/i.test(dbName || "");
}

export class RmsSandboxMarker extends Component {
    static template = "rms_sandbox_marker.SandboxMarker";
    static props = {};

    setup() {
        this.dbName = session.db;
        document.body.classList.add(SANDBOX_CLASS);
        onWillDestroy(() => document.body.classList.remove(SANDBOX_CLASS));
    }
}

if (isSandboxDb(session.db)) {
    registry.category("main_components").add("RmsSandboxMarker", { Component: RmsSandboxMarker });
}
