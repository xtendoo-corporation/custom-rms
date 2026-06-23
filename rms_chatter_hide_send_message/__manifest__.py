# -*- coding: utf-8 -*-
{
    "name": "RMS Chatter Hide Send Message",
    "version": "19.0.1.0.0",
    "category": "Extra Tools",
    "summary": "Hides the Send Message button in Chatter to force using internal notes.",
    "author": "Xtendoo",
    "website": "https://xtendoo.es",
    "license": "LGPL-3",
    "depends": [
        "mail",
    ],
    "assets": {
        "web.assets_backend": [
            "rms_chatter_hide_send_message/static/src/scss/chatter_custom.scss",
        ],
    },
    "installable": True,
    "application": False,
}
