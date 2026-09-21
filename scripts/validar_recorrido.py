#!/usr/bin/env python3
"""
Compara cada punto de referencia geocodificado contra el recorrido oficial
real (geojsonIda/geojsonVuelta de ws.rosario.gob.ar, bajado por
fetch_lineas_oficiales.py) y marca los que quedan demasiado lejos de
cualquiera de las dos geometrías: son candidatos a estar mal geocodificados
(calle equivocada, intersección incorrecta, etc).

Escribe el flag directamente en cada *.puntos.json (campo
"distancia_recorrido_m" / "fuera_de_recorrido") y regenera los *.final.json
afectados para que el visor lo pueda mostrar.

Uso:
    python3 validar_recorrido.py [--umbral 150]
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from geo_utils import distancia_a_geometria_m  # noqa: E402
from build_final import main as build_final_main  # noqa: E402

DATA_DIR = Path(__file__).parent.parent / "data"
OFICIAL_DIR = DATA_DIR / "oficial"

UMBRAL_DEFAULT_M = 150


def cargar_oficial_map():
    mapping = json.loads((DATA_DIR / "oficial_map.json").read_text(encoding="utf-8"))
    idx = {}
    for e in mapping:
        if e.get("match"):
            idx[(e["linea"], e["bandera"])] = e["match"]
    return idx


def cargar_geometria(match):
    clave = f"{match['idEmpresa']}_{match['id']}"
    path = OFICIAL_DIR / f"{clave}.json"
    if not path.exists():
        return None, None
    detalle = json.loads(path.read_text(encoding="utf-8"))
    return detalle.get("geojsonIda"), detalle.get("geojsonVuelta")


def main():
    umbral = UMBRAL_DEFAULT_M
    if "--umbral" in sys.argv:
        umbral = float(sys.argv[sys.argv.index("--umbral") + 1])

    oficial_por_linea = cargar_oficial_map()
    geometria_cache = {}

    reporte = []
    lineas_con_anomalias = {}
    n_cuadros_evaluados = 0
    n_puntos_evaluados = 0
    n_puntos_lejos = 0

    for puntos_path in sorted(DATA_DIR.glob("*.puntos.json")):
        cuadro_id = puntos_path.name[: -len(".puntos.json")]
        data = json.loads(puntos_path.read_text(encoding="utf-8"))
        linea, bandera = data.get("linea"), None

        cuadro_path = DATA_DIR / f"{cuadro_id}.json"
        if not cuadro_path.exists():
            continue
        cuadro = json.loads(cuadro_path.read_text(encoding="utf-8"))
        bandera = cuadro["ida"].get("bandera") or cuadro["vuelta"].get("bandera")

        match = oficial_por_linea.get((linea, bandera))
        if not match:
            continue

        clave_geo = f"{match['idEmpresa']}_{match['id']}"
        if clave_geo not in geometria_cache:
            geometria_cache[clave_geo] = cargar_geometria(match)
        geo_ida, geo_vuelta = geometria_cache[clave_geo]
        if not geo_ida and not geo_vuelta:
            continue

        n_cuadros_evaluados += 1
        tocado = False
        for p in data["puntos"]:
            geo = p.get("geocode") or {}
            if geo.get("status") != "ok":
                continue
            lat, lon = geo["lat"], geo["lon"]
            d_ida = distancia_a_geometria_m(lat, lon, geo_ida)
            d_vuelta = distancia_a_geometria_m(lat, lon, geo_vuelta)
            candidatos = [d for d in (d_ida, d_vuelta) if d is not None]
            if not candidatos:
                continue
            distancia = min(candidatos)
            n_puntos_evaluados += 1
            fuera = distancia > umbral
            if p.get("distancia_recorrido_m") != distancia or p.get("fuera_de_recorrido") != fuera:
                tocado = True
            p["distancia_recorrido_m"] = round(distancia, 1)
            p["fuera_de_recorrido"] = fuera
            if fuera:
                n_puntos_lejos += 1
                lineas_con_anomalias.setdefault(f"{linea} {bandera}", 0)
                lineas_con_anomalias[f"{linea} {bandera}"] += 1
                reporte.append(
                    {
                        "cuadro_id": cuadro_id,
                        "linea": linea,
                        "bandera": bandera,
                        "punto_id": p["id"],
                        "clave": p["clave"],
                        "tokens": p["tokens"],
                        "lat": lat,
                        "lon": lon,
                        "distancia_m": round(distancia, 1),
                    }
                )

        if tocado:
            puntos_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
            final_path = DATA_DIR / f"{cuadro_id}.final.json"
            build_final_main(str(cuadro_path), str(puntos_path), str(final_path))

    reporte.sort(key=lambda r: -r["distancia_m"])
    (DATA_DIR / "puntos_fuera_de_recorrido.json").write_text(
        json.dumps(reporte, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    print(f"cuadros con recorrido oficial matcheado: {n_cuadros_evaluados}")
    print(f"puntos evaluados: {n_puntos_evaluados} | a más de {umbral:.0f}m del recorrido real: {n_puntos_lejos}")
    if lineas_con_anomalias:
        print("\nlíneas con puntos fuera de recorrido:")
        for linea_bandera, n in sorted(lineas_con_anomalias.items(), key=lambda x: -x[1]):
            print(f"  {linea_bandera}: {n} punto(s)")
    print(f"\nreporte -> {DATA_DIR / 'puntos_fuera_de_recorrido.json'}")


if __name__ == "__main__":
    main()
