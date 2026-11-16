import { registry } from "@web/core/registry";
import { session } from "@web/session";

registry.category("services").add("rms_user_background", {
    start() {
        if (session.rms_background_url) {
            document.body.classList.add("rms-user-background");
            document.documentElement.style.setProperty(
                "--rms-user-background-image",
                `url("${session.rms_background_url}")`
            );
        }
    },
});
