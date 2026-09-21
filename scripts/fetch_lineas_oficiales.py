#!/usr/bin/env python3
"""
Descarga el listado oficial de líneas de Rosario (con geometría real de
recorrido y paradas) desde el mismo webservice municipal que ya usamos para
geocodificar, y lo matchea contra las combinaciones línea+bandera que
salieron de los PDFs del EMR (bastante irregulares: "143-136- 137" vs
"143/136/ 137" vs "143136137", "ENLACE NOROE" truncado, "1,4E+08" corrupto
por un PDF que exportó un número como notación científica, etc).

Fuente: https://ws.rosario.gob.ar/ubicaciones/public/lineas?nombre=all
        https://ws.rosario.gob.ar/ubicaciones/public/linea/{idEmpresa}/{id}
        (la misma API que usa el proyecto hermano "lineas" — ver ../lineas)

Uso:
    python3 fetch_lineas_oficiales.py
"""
import json
import re
import ssl
import sys
import time
import unicodedata
import urllib.request
from pathlib import Path

ROOT = Path(__file__).parent.parent
DATA_DIR = ROOT / "data"
OFICIAL_DIR = DATA_DIR / "oficial"

API_BASE = "https://ws.rosario.gob.ar/ubicaciones/public"
SSL_CTX = ssl.create_default_context()
SSL_CTX.check_hostname = False
SSL_CTX.verify_mode = ssl.CERT_NONE


def fetch_json(url):
    req = urllib.request.Request(url, headers={"User-Agent": "bondiario/1.0"})
    with urllib.request.urlopen(req, timeout=30, context=SSL_CTX) as r:
        return json.load(r)


def normalize_alnum(s: str) -> str:
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode()
    return re.sub(r"[^A-Z0-9]", "", s.upper())


def normalize_digits(s: str) -> str:
    """Solo dígitos: la API a veces agrega una letra suelta al codigoEMR
    para diferenciar variantes (ej. '153 N' para el negro vs '153' para el
    rojo), lo que separaría en dos grupos algo que es la misma línea."""
    return re.sub(r"[^0-9]", "", s or "")


def bandera_stem(s: str) -> str:
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().upper()
    if "NEGR" in s:
        return "NEGRO"
    if "ROJ" in s:
        return "ROJO"
    if "VERD" in s:
        return "VERDE"
    if "AERO" in s:
        return "AERO"
    if "CABIN" in s:
        return "CABIN"
    if "SOLDINI" in s:
        return "SOLDINI"
    return "UNICO"


def cargar_lineas_api():
    lineas = fetch_json(f"{API_BASE}/lineas?nombre=all")
    for linea in lineas:
        linea["_codigo_digits"] = normalize_digits(linea.get("codigoEMR", ""))
        linea["_codigo_alnum"] = normalize_alnum(linea.get("codigoEMR", ""))
        # el "nombre" trae el/los número(s) de línea + la variante
        # (color/apodo); nos quedamos con la variante sola para el stem,
        # quitando el prefijo numérico en vez de comparar contra codigoEMR
        # (que a veces trae una letra de más, ej. "153 N" para el negro)
        sufijo = re.sub(r"^[0-9/\- ]+", "", linea.get("nombre", ""))
        linea["_bandera_stem"] = bandera_stem(sufijo)
        linea["_nombre_norm"] = normalize_alnum(linea.get("nombre", ""))
    return lineas


def index_por(lineas_api, campo):
    idx = {}
    for linea in lineas_api:
        if linea[campo]:
            idx.setdefault(linea[campo], []).append(linea)
    return idx


def matchear(nuestra_linea: str, nuestra_bandera: str, lineas_api, idx_digits, idx_alnum):
    candidatos = idx_digits.get(normalize_digits(nuestra_linea), [])
    metodo = "codigo" if candidatos else None

    if not candidatos:
        candidatos = idx_alnum.get(normalize_alnum(nuestra_linea), [])
        if candidatos:
            metodo = "codigo"

    if not candidatos:
        # líneas con nombre propio (ENLACE, RONDA, K...): nuestro "linea" es
        # un nombre descriptivo, no un código corto; buscamos por texto,
        # tolerando truncamientos de un lado o del otro
        nombre_norm = normalize_alnum(nuestra_linea)
        if len(nombre_norm) >= 4:
            candidatos = [
                l for l in lineas_api
                if nombre_norm and l["_nombre_norm"] and (
                    nombre_norm in l["_nombre_norm"] or l["_nombre_norm"] in nombre_norm
                )
            ]
            if candidatos:
                metodo = "nombre"

    if not candidatos:
        return None, None

    if len(candidatos) == 1:
        return candidatos[0], metodo

    stem = bandera_stem(nuestra_bandera)
    exactos = [l for l in candidatos if l["_bandera_stem"] == stem]
    if exactos:
        return exactos[0], metodo

    genericos = [l for l in candidatos if l["_bandera_stem"] == "UNICO"]
    if genericos:
        return genericos[0], metodo + "+generico"

    return None, None


def combos_propios():
    """Todas las combinaciones (linea, bandera) presentes en nuestros
    cuadros ya parseados (data/*.json crudos, no los .puntos/.final)."""
    combos = set()
    for path in DATA_DIR.glob("*.json"):
        if path.name.endswith((".puntos.json", ".final.json")):
            continue
        try:
            cuadro = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if not isinstance(cuadro, dict) or "ida" not in cuadro or "vuelta" not in cuadro:
            continue
        linea = cuadro.get("linea")
        bandera = cuadro["ida"].get("bandera") or cuadro["vuelta"].get("bandera")
        if linea:
            combos.add((linea, bandera))
    return sorted(combos, key=lambda x: (str(x[0]), str(x[1])))


def main():
    print("Descargando listado de líneas oficiales...")
    lineas_api = cargar_lineas_api()
    idx_digits = index_por(lineas_api, "_codigo_digits")
    idx_alnum = index_por(lineas_api, "_codigo_alnum")
    print(f"{len(lineas_api)} líneas oficiales encontradas.")

    combos = combos_propios()
    print(f"{len(combos)} combinaciones línea+bandera propias a matchear.")

    OFICIAL_DIR.mkdir(parents=True, exist_ok=True)
    mapping = []
    cache_detalle = {}
    matcheadas, sin_match = 0, 0

    for linea, bandera in combos:
        api_linea, metodo = matchear(linea, bandera, lineas_api, idx_digits, idx_alnum)
        if api_linea is None:
            mapping.append({"linea": linea, "bandera": bandera, "match": None})
            sin_match += 1
            print(f"  SIN MATCH  linea={linea!r} bandera={bandera!r}")
            continue

        clave_api = f"{api_linea['idEmpresa']}_{api_linea['id']}"
        mapping.append(
            {
                "linea": linea,
                "bandera": bandera,
                "match": {
                    "idEmpresa": api_linea["idEmpresa"],
                    "id": api_linea["id"],
                    "nombre": api_linea["nombre"],
                    "color": api_linea["color"],
                    "metodo": metodo,
                },
            }
        )
        matcheadas += 1

        if clave_api not in cache_detalle:
            url = (
                f"{API_BASE}/linea/{api_linea['idEmpresa']}/{api_linea['id']}"
                "?conGeometria=true&usarCoordenadasWGS84=true&conParadas=true"
            )
            try:
                detalle = fetch_json(url)
                cache_detalle[clave_api] = detalle
                (OFICIAL_DIR / f"{clave_api}.json").write_text(
                    json.dumps(detalle, ensure_ascii=False), encoding="utf-8"
                )
                n_paradas = len(detalle.get("paradas") or [])
                print(f"  OK  linea={linea!r} bandera={bandera!r} -> {api_linea['nombre']} "
                      f"({metodo}, {n_paradas} paradas oficiales)")
            except Exception as e:
                print(f"  ERROR descargando detalle de {api_linea['nombre']}: {e}")
                cache_detalle[clave_api] = None
            time.sleep(0.15)
        else:
            print(f"  OK  linea={linea!r} bandera={bandera!r} -> {api_linea['nombre']} ({metodo}, cacheado)")

    (DATA_DIR / "oficial_map.json").write_text(
        json.dumps(mapping, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"\nmatcheadas: {matcheadas} | sin match: {sin_match}")
    print(f"mapeo -> {DATA_DIR / 'oficial_map.json'}")
    print(f"geometrías/paradas oficiales -> {OFICIAL_DIR}/")


if __name__ == "__main__":
    main()
