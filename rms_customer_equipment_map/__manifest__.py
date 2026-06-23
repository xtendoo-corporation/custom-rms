{
    "name": "Customer Equipment Map",
    "version": "19.0.4.0.0",
    "category": "Services/Maintenance",
    "summary": "Geolocaliza clientes y vincula sus equipos instalados",
    "author": "Xtendoo",
    "website": "https://xtendoo.es",
    "license": "LGPL-3",
    "depends": [
        "base",
        "contacts",
        "base_geolocalize",
        "maintenance",
    ],
    "data": [
        "views/maintenance_equipment_views.xml",
        "views/res_partner_views.xml",
        "views/customer_equipment_map_views.xml",
    ],
    "assets": {
        "web.assets_backend": [
            "rms_customer_equipment_map/static/src/scss/customer_equipment_map.scss",
            "rms_customer_equipment_map/static/lib/leaflet/leaflet.js",
            "rms_customer_equipment_map/static/src/js/customer_equipment_map.js",
            "rms_customer_equipment_map/static/src/xml/customer_equipment_map.xml",
        ],
    },
    "installable": True,
    "application": True,
}
