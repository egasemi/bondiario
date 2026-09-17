#!/usr/bin/env python3
"""
Descarga todos los cuadros horarios publicados en
https://emr.gov.ar/transporte-publico/cuadros-horarios

La página es un sitio tradicional (no SPA): el <select id="selectLinea">
trae, para cada línea/bandera/tipo de día, un atributo data-pdf con la URL
directa del PDF. No hace falta navegador: alcanza con parsear el HTML.

El certificado de emr.gov.ar falla la verificación en este entorno (falta la
CA intermedia en el trust store local), así que se usa un contexto SSL sin
verificar — el sitio es público y solo se leen PDFs de horarios.

Uso:
    python3 scrape_lineas.py            # descarga todo lo que falte
    python3 scrape_lineas.py --list     # solo lista lo encontrado, no descarga
"""
import html
import json
import re
import ssl
import sys
import time
import urllib.request
from pathlib import Path
from urllib.parse import quote

BASE_URL = "https://emr.gov.ar/transporte-publico/cuadros-horarios"
CUADROS_DIR = Path(__file__).parent.parent / "cuadros"
DATA_DIR = Path(__file__).parent.parent / "data"

SSL_CTX = ssl.create_default_context()
SSL_CTX.check_hostname = False
SSL_CTX.verify_mode = ssl.CERT_NONE


def fetch(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (bondiario-scraper)"})
    with urllib.request.urlopen(req, timeout=30, context=SSL_CTX) as r:
        return r.read()


def parse_opciones(pagina_html: str):
    """Devuelve una lista de dicts {id, tipo_dia, fecha, archivo, url}."""
    opts = re.findall(r'<option value="(\d*)" data-pdf="([^"]+)">', pagina_html)
    out = []
    for value, pdf_url in opts:
        pdf_url = html.unescape(pdf_url)
        m = re.search(r"/uploads/cuadros horarios/([^/]+)/(?:([^/]+)/)?([^/]+\.pdf)$", pdf_url)
        if not m:
            continue
        tipo_dia, fecha, archivo = m.groups()
        out.append(
            {
                "id": value,
                "tipo_dia": tipo_dia,
                "fecha": fecha,
                "archivo": archivo,
                "url": pdf_url,
            }
        )
    return out


def url_segura(url: str) -> str:
    # las rutas del servidor tienen espacios sin encodear
    return quote(url, safe=":/")


def main():
    solo_listar = "--list" in sys.argv

    print(f"Descargando listado desde {BASE_URL} ...")
    pagina = fetch(BASE_URL).decode("utf-8", errors="replace")
    opciones = parse_opciones(pagina)
    print(f"{len(opciones)} cuadros encontrados en el sitio.")

    por_tipo = {}
    for o in opciones:
        por_tipo.setdefault(o["tipo_dia"], []).append(o)
    for tipo, lst in por_tipo.items():
        print(f"  {tipo}: {len(lst)}")

    if solo_listar:
        return

    origen = []
    ok, fallidos, ya_existian = 0, 0, 0
    for o in opciones:
        carpeta = CUADROS_DIR / o["tipo_dia"].replace(" ", "-")
        carpeta.mkdir(parents=True, exist_ok=True)
        destino = carpeta / o["archivo"]
        registro = {**o, "path_local": str(destino.relative_to(CUADROS_DIR.parent))}
        origen.append(registro)
        if destino.exists() and destino.stat().st_size > 0:
            ya_existian += 1
            continue
        try:
            contenido = fetch(url_segura(o["url"]))
            destino.write_bytes(contenido)
            ok += 1
            print(f"  OK  {o['tipo_dia']}/{o['archivo']} ({len(contenido)} bytes)")
        except Exception as e:
            fallidos += 1
            print(f"  ERROR {o['tipo_dia']}/{o['archivo']}: {e}")
        time.sleep(0.2)

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    (DATA_DIR / "cuadros_origen.json").write_text(
        json.dumps(origen, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"\nnuevos: {ok} | ya existían: {ya_existian} | fallidos: {fallidos}")
    print(f"registro de origen -> {DATA_DIR / 'cuadros_origen.json'}")


if __name__ == "__main__":
    main()
