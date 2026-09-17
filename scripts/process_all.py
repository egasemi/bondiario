#!/usr/bin/env python3
"""
Orquesta el pipeline completo (parse -> geocode -> build_final) para todos
los PDFs descargados por scrape_lineas.py (data/cuadros_origen.json).

Reusa un único CalleIndex y un cache de geocoding compartido entre todos los
cuadros (las 3 variantes de día de una misma línea comparten los mismos
puntos físicos, así que se geocodifican una sola vez).

Los PDFs de más de una página (algunos "Enlace", "Ronda", líneas con
recorridos muy largos) usan un layout distinto que el parser actual no
soporta todavía; se listan aparte al final en vez de forzarlos.

Uso:
    python3 process_all.py
"""
import json
import sys
import traceback
from pathlib import Path

import pdfplumber

sys.path.insert(0, str(Path(__file__).parent))
from calles_ref import CalleIndex  # noqa: E402
from parse_cuadro import parse_pdf  # noqa: E402
from geocode_puntos import geocodificar_cuadro, cargar_cache, guardar_cache, cargar_overrides  # noqa: E402
from build_final import main as build_final_main  # noqa: E402
from build_manifest import main as build_manifest_main  # noqa: E402

ROOT = Path(__file__).parent.parent
CUADROS_DIR = ROOT / "cuadros"
DATA_DIR = ROOT / "data"

# el campo "Día:" que trae cada PDF varía en texto (Normal, LABORAL, Medio
# Festivo con saltos de línea, etc.); se normaliza a un label único por
# carpeta de origen, que es la fuente de verdad real.
DIA_CANONICO = {
    "Laboral": "Día hábil",
    "Medio festivo": "Medio festivo",
    "Festivo": "Domingos y feriados",
}


def slug(s: str) -> str:
    return (
        s.replace(" ", "-")
        .replace("í", "i").replace("á", "a").replace("é", "e").replace("ó", "o").replace("ú", "u")
    )


def main():
    origen = json.loads((DATA_DIR / "cuadros_origen.json").read_text(encoding="utf-8"))
    if "--limit" in sys.argv:
        n = int(sys.argv[sys.argv.index("--limit") + 1])
        origen = origen[:n]
    index = CalleIndex()
    cache = cargar_cache()
    overrides = cargar_overrides()

    ok, error_parseo, sin_datos = [], [], []

    for i, o in enumerate(origen):
        pdf_path = ROOT / o["path_local"]
        base = Path(o["archivo"]).stem
        cuadro_id = f"{slug(o['tipo_dia'])}__{slug(base)}"

        try:
            cuadro = parse_pdf(str(pdf_path))
            dia_normalizado = DIA_CANONICO.get(o["tipo_dia"], o["tipo_dia"])
            cuadro["ida"]["dia"] = dia_normalizado
            cuadro["vuelta"]["dia"] = dia_normalizado
            n_ida = len(cuadro["ida"]["servicios"])
            n_vuelta = len(cuadro["vuelta"]["servicios"])
            if n_ida == 0 and n_vuelta == 0:
                sin_datos.append({"id": cuadro_id, "archivo": o["path_local"]})
                continue

            cuadro_path = DATA_DIR / f"{cuadro_id}.json"
            cuadro_path.write_text(json.dumps(cuadro, ensure_ascii=False, indent=2), encoding="utf-8")

            geo = geocodificar_cuadro(cuadro, index, cache, overrides)
            stats = geo.pop("_stats")
            puntos_path = DATA_DIR / f"{cuadro_id}.puntos.json"
            puntos_path.write_text(json.dumps(geo, ensure_ascii=False, indent=2), encoding="utf-8")

            final_path = DATA_DIR / f"{cuadro_id}.final.json"
            build_final_main(str(cuadro_path), str(puntos_path), str(final_path))

            ok.append(
                {
                    "id": cuadro_id,
                    "archivo": o["path_local"],
                    "linea": cuadro["linea"],
                    "puntos_auto": stats["auto"],
                    "puntos_manual": stats["manual"],
                    "n_ida": n_ida,
                    "n_vuelta": n_vuelta,
                }
            )
            print(f"[{i+1}/{len(origen)}] OK {cuadro_id} (puntos manual: {stats['manual']})")

        except Exception as e:
            error_parseo.append({"id": cuadro_id, "archivo": o["path_local"], "error": str(e)})
            print(f"[{i+1}/{len(origen)}] ERROR {cuadro_id}: {e}")
            traceback.print_exc(limit=2)

        if (i + 1) % 10 == 0:
            guardar_cache(cache)  # checkpoint periódico

    guardar_cache(cache)
    build_manifest_main()

    reporte = {"ok": ok, "error_parseo": error_parseo, "sin_datos": sin_datos}
    (DATA_DIR / "process_all_report.json").write_text(
        json.dumps(reporte, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    total_manual = sum(e["puntos_manual"] for e in ok)
    print("\n=== resumen ===")
    print(f"procesados OK: {len(ok)}")
    print(f"error de parseo: {len(error_parseo)}")
    print(f"sin datos (0 servicios): {len(sin_datos)}")
    print(f"total de puntos que requieren revisión manual (suma de todos los cuadros): {total_manual}")


if __name__ == "__main__":
    main()
