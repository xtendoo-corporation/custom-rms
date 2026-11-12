#!/usr/bin/env bash
set -euo pipefail

# Resolver la raíz desde el script, independientemente del directorio actual.
REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
cd -- "$REPO_ROOT"

# El renderizador SVG interno de ImageMagick pinta los degradados en negro:
# se renderiza con Chrome/Chromium sin interfaz (CHROME para otra ruta).
CHROME="${CHROME:-}"
if [[ -z "$CHROME" ]]; then
    for candidate in "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" google-chrome chromium chromium-browser; do
        if command -v "$candidate" >/dev/null 2>&1 || [[ -x "$candidate" ]]; then CHROME="$candidate"; break; fi
    done
fi
if [[ -z "$CHROME" ]]; then
    printf '%s\n' 'Error: se requiere Chrome/Chromium (variable CHROME).' >&2
    exit 1
fi

render_svg() {
    local source="$1" size="$2"
    "$CHROME" --headless=new --disable-gpu --hide-scrollbars \
        --default-background-color=00000000 --window-size=512,512 \
        --screenshot="$REPO_ROOT/${source%.svg}.png" "file://$REPO_ROOT/$source" >/dev/null 2>&1
    # Los SVG son de 512: los tamaños menores se reducen tras renderizar.
    if [[ "$size" != 512 ]]; then
        magick "${source%.svg}.png" -resize "${size}x${size}" "${source%.svg}.png"
    fi
}

# Validar todos los argumentos antes de renderizar cualquier archivo.
for module in "$@"; do
    case "$module" in
        ''|.*|*/*)
            printf 'Nombre de módulo no válido: %s\n' "$module" >&2
            exit 1
            ;;
    esac
    if [[ ! -d "$module" ]]; then
        printf 'No existe el módulo: %s\n' "$module" >&2
        exit 1
    fi
done

render_module() {
    local module="$1"
    local source
    source="$module/static/description/icon.svg"
    if [[ -f "$source" ]]; then
        render_svg "$source" 512
        printf 'Generado: %s\n' "${source%.svg}.png"
    fi
    if [[ "$module" == 'rms_web_redirect' ]]; then
        for source in "$module"/static/img/*.svg; do
            [[ -f "$source" ]] || continue
            render_svg "$source" 256
            printf 'Generado: %s\n' "${source%.svg}.png"
        done
    fi
}

if [[ "$#" -gt 0 ]]; then
    for module in "$@"; do
        render_module "$module"
    done
else
    for directory in */; do
        module="${directory%/}"
        case "$module" in
            .claude|docs) continue ;;
        esac
        render_module "$module"
    done
fi
