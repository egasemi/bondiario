#!/usr/bin/env python3
"""
Combina el cuadro parseado (parse_cuadro.py) con los puntos geocodificados
(geocode_puntos.py, + overrides manuales del panel) para producir el JSON
final que consume el visor web: puntos con lat/lon y viajes con tiempos en
segundos desde medianoche (manejando el cruce de las 00:00).

Uso:
    python3 build_final.py data/107-NEGRO.json data/107-NEGRO.puntos.json data/107-NEGRO.final.json
"""
import json
import sys
from pathlib import Path


def hora_a_segundos_seq(horas):
    """Convierte una lista de horas 'HH:MM' en segundos desde medianoche,
    sumando 24h cada vez que la hora retrocede (viaje que cruza medianoche)."""
    out = []
    offset = 0
    prev = None
    for h in horas:
        hh, mm = int(h[:2]), int(h[3:5])
        t = hh * 3600 + mm * 60
        if prev is not None and t + offset < prev:
            offset += 24 * 3600
        t += offset
        out.append(t)
        prev = t
    return out


def col_to_punto_id(puntos_geo):
    mapping = {}  # (sentido, col) -> punto_id
    for p in puntos_geo["puntos"]:
        for oc in p["ocurrencias"]:
            mapping[(oc["sentido"], oc["col"])] = p["id"]
    return mapping


def main(cuadro_path, puntos_path, out_path):
    cuadro = json.loads(Path(cuadro_path).read_text(encoding="utf-8"))
    puntos_geo = json.loads(Path(puntos_path).read_text(encoding="utf-8"))
    col_map = col_to_punto_id(puntos_geo)

    puntos_out = {}
    sin_coords = []
    for p in puntos_geo["puntos"]:
        geo = p.get("geocode") or {}
        if geo.get("status") == "ok":
            punto_out = {
                "lat": geo["lat"],
                "lon": geo["lon"],
                "label": " - ".join(p["tokens"]) if len(p["tokens"]) == 2 else p["tokens"],
                "clave": p["clave"],
            }
            if p.get("fuera_de_recorrido"):
                punto_out["fuera_de_recorrido"] = True
                punto_out["distancia_recorrido_m"] = p.get("distancia_recorrido_m")
            puntos_out[p["id"]] = punto_out
        else:
            sin_coords.append(p["id"])

    viajes = []
    for sentido in ("ida", "vuelta"):
        for serv in cuadro[sentido]["servicios"]:
            paradas = []
            horas = [par["hora"] for par in serv["paradas"]]
            segundos = hora_a_segundos_seq(horas)
            for par, seg in zip(serv["paradas"], segundos):
                punto_id = col_map.get((sentido, par["col"]))
                if punto_id is None or punto_id not in puntos_out:
                    continue  # punto sin geocodificar todavia, se omite este waypoint
                paradas.append({"t": seg, "punto": punto_id})
            if len(paradas) >= 2:
                viajes.append(
                    {
                        "id": serv["id"],
                        "sentido": sentido,
                        "servicio": serv["servicio"],
                        "paradas": paradas,
                    }
                )

    out = {
        "linea": cuadro["linea"],
        "bandera": cuadro["ida"].get("bandera") or cuadro["vuelta"].get("bandera"),
        "dia": cuadro["ida"].get("dia") or cuadro["vuelta"].get("dia"),
        "puntos": puntos_out,
        "viajes": viajes,
    }
    Path(out_path).write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(
        f"viajes: {len(viajes)} | puntos geocodificados: {len(puntos_out)} | "
        f"puntos sin coords (excluidos): {len(sin_coords)} {sin_coords}"
    )


if __name__ == "__main__":
    if len(sys.argv) != 4:
        print("Uso: build_final.py <cuadro.json> <puntos.json> <out.final.json>", file=sys.stderr)
        sys.exit(1)
    main(sys.argv[1], sys.argv[2], sys.argv[3])
