{
    "name": "RMS Global Equipment Map",
    "version": "19.0.1.0.0",
    "category": "Services/Maintenance",
    "summary": "Mapa global de clientes con Equipos del Cliente",
    "author": "Xtendoo",
    "website": "https://xtendoo.es",
    "license": "LGPL-3",
    "depends": [
        "base",
        "web",
        "base_geolocalize",
        "rms_partner_equipment_model_import",
    ],
    "data": [
        "views/global_equipment_map_views.xml",
    ],
    "assets": {
        "web.assets_backend": [
            "rms_global_equipment_map/static/src/scss/global_equipment_map.scss",
            "rms_global_equipment_map/static/lib/leaflet/leaflet.js",
            "rms_global_equipment_map/static/src/js/global_equipment_map.js",
            "rms_global_equipment_map/static/src/xml/global_equipment_map.xml",
        ],
    },
    "installable": True,
    "application": True,
}
