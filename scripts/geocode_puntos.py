#!/usr/bin/env python3
"""
Toma el JSON de un cuadro horario ya parseado (parse_cuadro.py), unifica los
puntos de referencia de IDA y VUELTA (deduplicando esquinas repetidas),
intenta resolver cada abreviatura de calle contra el callejero de Rosario, y
geocodifica las intersecciones resueltas usando el webservice municipal
ws.rosario.gob.ar/ubicaciones.

Uso:
    python3 geocode_puntos.py data/107-NEGRO.json data/107-NEGRO.puntos.json
"""
import json
import re
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from calles_ref import CalleIndex, normalize  # noqa: E402

import pyproj  # noqa: E402

API_BASE = "https://ws.rosario.gob.ar/ubicaciones/public/geojson/ubicaciones"
TRANSFORMER = pyproj.Transformer.from_crs("EPSG:22185", "EPSG:4326", always_xy=True)
CACHE_PATH = Path(__file__).parent.parent / "data" / "geocode_cache.json"
OVERRIDES_PATH = Path(__file__).parent.parent / "data" / "manual_overrides.json"


def cargar_cache():
    if CACHE_PATH.exists():
        return json.loads(CACHE_PATH.read_text(encoding="utf-8"))
    return {}


def guardar_cache(cache):
    CACHE_PATH.write_text(json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8")


def cargar_overrides():
    if OVERRIDES_PATH.exists():
        return json.loads(OVERRIDES_PATH.read_text(encoding="utf-8"))
    return {}


def guardar_overrides(overrides):
    OVERRIDES_PATH.write_text(json.dumps(overrides, ensure_ascii=False, indent=2), encoding="utf-8")


def clave_cache(calle1: str, calle2: str) -> str:
    return "|".join(sorted([normalize(calle1), normalize(calle2)]))


def clave_punto(tokens) -> str:
    """Identificador estable de un punto de referencia a partir de sus dos
    tokens de calle tal como aparecen en el PDF (sin resolver todavía). Es la
    clave que comparten todas las variantes de día y todas las líneas que
    pasan por la misma esquina, y la que usan los overrides manuales."""
    if len(tokens) != 2:
        return "unparsed::" + (tokens[0] if tokens else "?")
    norm = sorted(t.upper().replace(".", "").strip() for t in tokens)
    return "||".join(norm)


def split_tokens(label_guess: str):
    parts = [p.strip() for p in label_guess.split(" - ") if p.strip()]
    if len(parts) == 2:
        return parts
    partes_y = re.split(r"\s+y\s+", label_guess, maxsplit=1, flags=re.IGNORECASE)
    if len(partes_y) == 2:
        return [p.strip() for p in partes_y]
    # fallback: intentar separar por el último "-" suelto
    return [p.strip() for p in label_guess.split("-") if p.strip()]


def unify_puntos(cuadro: dict):
    """Combina los puntos de IDA y VUELTA en una lista de puntos únicos,
    usando como clave el conjunto (sin orden) de los dos tokens de calle."""
    puntos_by_key = {}
    for sentido in ("ida", "vuelta"):
        for p in cuadro[sentido]["puntos"]:
            if not p["label_guess"].strip():
                continue  # columna sin nombre en el PDF (artefacto de layout), no es una parada real
            tokens = split_tokens(p["label_guess"])
            if len(tokens) != 2:
                key = ("__unparsed__", p["label_guess"])
            else:
                key = frozenset(t.upper().replace(".", "") for t in tokens)
            entry = puntos_by_key.setdefault(
                key,
                {
                    "tokens": tokens,
                    "ocurrencias": [],
                },
            )
            entry["ocurrencias"].append({"sentido": sentido, "col": p["col"], "pos_label": p["pos_label"], "label_raw": p["label_raw"]})
    return list(puntos_by_key.values())


MAX_CANDIDATOS_POR_TOKEN = 6
CONVERGENCIA_GRADOS = 0.0003  # ~30m


def resolve_tokens(index: CalleIndex, tokens):
    if len(tokens) != 2:
        return {"status": "unparsed", "candidatos": []}
    resolved = []
    for t in tokens:
        cands = index.resolve_token(t)
        if not cands:
            cands = index.resolve_token_multiword(t)
        resolved.append(cands)
    if all(len(c) == 1 for c in resolved):
        calle1 = resolved[0][0]
        calle2 = resolved[1][0]
        return {"status": "auto", "calle1": calle1, "calle2": calle2, "candidatos": resolved}
    return {"status": "manual", "candidatos": resolved}


def geocode_por_convergencia(cands1, cands2, cache=None):
    """Cuando alguno de los dos tokens tiene varios candidatos de calle
    posibles, prueba las combinaciones y acepta automáticamente si todos los
    intentos que dieron un resultado limpio (ok) convergen en el mismo punto
    geográfico, sin necesidad de saber cuál nombre es el 'correcto'."""
    c1 = cands1[:MAX_CANDIDATOS_POR_TOKEN] or [None]
    c2 = cands2[:MAX_CANDIDATOS_POR_TOKEN] or [None]
    if c1 == [None] or c2 == [None]:
        return None
    oks = []
    for a in c1:
        for b in c2:
            geo = geocode_interseccion(a, b, cache)
            if geo["status"] == "ok":
                oks.append((a, b, geo))
    if not oks:
        return None
    lat0, lon0 = oks[0][2]["lat"], oks[0][2]["lon"]
    for _, _, g in oks:
        if abs(g["lat"] - lat0) > CONVERGENCIA_GRADOS or abs(g["lon"] - lon0) > CONVERGENCIA_GRADOS:
            return None  # no convergen, sigue siendo ambiguo
    calle1, calle2, geo = oks[0]
    return {"calle1": calle1, "calle2": calle2, "geocode": geo, "n_convergentes": len(oks)}


def geocode_interseccion(calle1: str, calle2: str, cache=None):
    key = clave_cache(calle1, calle2) if cache is not None else None
    if cache is not None and key in cache:
        return cache[key]

    term = f"{calle1} y {calle2}"
    url = API_BASE + "?" + urllib.parse.urlencode({"term": term})
    try:
        with urllib.request.urlopen(url, timeout=15) as r:
            data = json.load(r)
        time.sleep(0.12)
    except Exception as e:
        return {"status": "error", "error": str(e)}
    features = data.get("features", [])
    # descartar "puntos de control" de rutas y quedarnos con intersecciones reales
    features = [f for f in features if f["properties"].get("subtipo") == "DIRECCIÓN"]

    def matches(f):
        calle_a = normalize(f["properties"].get("nombreCalle", ""))
        calle_b = normalize(f["properties"].get("nombreInterseccion", ""))
        c1, c2 = normalize(calle1), normalize(calle2)
        return (calle_a.startswith(c1) and calle_b.startswith(c2)) or (
            calle_a.startswith(c2) and calle_b.startswith(c1)
        )

    exact = [f for f in features if matches(f)]
    if exact:
        features = exact

    if len(features) == 0:
        result = {"status": "not_found"}
    elif len(features) > 1:
        result = {"status": "ambiguous", "n": len(features)}
    else:
        coords = features[0]["geometry"]["coordinates"]
        lon, lat = TRANSFORMER.transform(coords[0], coords[1])
        result = {"status": "ok", "lat": lat, "lon": lon, "x": coords[0], "y": coords[1]}

    if cache is not None:
        cache[key] = result
    return result


def geocodificar_cuadro(cuadro: dict, index: CalleIndex, cache: dict, overrides: dict = None) -> dict:
    """Toma un cuadro ya parseado y devuelve el JSON de puntos geocodificados.
    `cache` se muta in-place (para reutilizar entre múltiples cuadros).
    `overrides` son correcciones manuales hechas una vez desde el panel y
    reutilizadas para siempre en cualquier línea/día que comparta la esquina."""
    puntos = unify_puntos(cuadro)
    overrides = overrides or {}

    n_auto_geocoded = 0
    n_manual = 0
    for i, punto in enumerate(puntos):
        punto["id"] = f"pt{i:03d}"
        punto["clave"] = clave_punto(punto["tokens"])
        if punto["clave"] in overrides:
            punto["status"] = "auto"
            punto["geocode"] = overrides[punto["clave"]]
            n_auto_geocoded += 1
            continue
        res = resolve_tokens(index, punto["tokens"])
        punto.update(res)
        if res["status"] == "auto":
            geo = geocode_interseccion(res["calle1"], res["calle2"], cache)
            punto["geocode"] = geo
            if geo["status"] == "ok":
                n_auto_geocoded += 1
                continue
        # intento de desambiguación por convergencia (candidatos múltiples,
        # o único candidato pero geocoding ambiguo/no encontrado)
        cands = res.get("candidatos", [[], []])
        if len(cands) == 2 and cands[0] and cands[1]:
            conv = geocode_por_convergencia(cands[0], cands[1], cache)
            if conv:
                punto["status"] = "auto"
                punto["calle1"] = conv["calle1"]
                punto["calle2"] = conv["calle2"]
                punto["geocode"] = conv["geocode"]
                punto["resuelto_por_convergencia"] = conv["n_convergentes"]
                n_auto_geocoded += 1
                continue
        punto["status"] = "manual"
        n_manual += 1

    return {
        "linea": cuadro["linea"],
        "puntos": puntos,
        "_stats": {"auto": n_auto_geocoded, "manual": n_manual},
    }


def main(in_path, out_path):
    cuadro = json.loads(Path(in_path).read_text(encoding="utf-8"))
    index = CalleIndex()
    cache = cargar_cache()
    overrides = cargar_overrides()
    out = geocodificar_cuadro(cuadro, index, cache, overrides)
    guardar_cache(cache)
    stats = out.pop("_stats")
    Path(out_path).write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(
        f"puntos totales: {len(out['puntos'])} | geocodificados auto: {stats['auto']} | "
        f"requieren revisión manual: {stats['manual']}"
    )


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("Uso: geocode_puntos.py <cuadro.json> <out.puntos.json>", file=sys.stderr)
        sys.exit(1)
    main(sys.argv[1], sys.argv[2])
