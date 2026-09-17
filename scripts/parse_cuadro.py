#!/usr/bin/env python3
"""
Parsea un PDF de "cuadro horario" del EMR (Rosario) y lo convierte a JSON
estructurado: puntos de referencia (columnas) + viajes (filas) con sus
horarios.

Soporta dos layouts observados en los PDFs del sitio:
  a) una sola página con IDA y VUELTA lado a lado (una tabla, dos bloques de
     columnas), como en la mayoría de las líneas cortas.
  b) IDA y VUELTA en tablas separadas, cada una eventualmente repartida en
     varias páginas de continuación (mismas columnas, más filas de
     servicios), como en líneas con muchos viajes por día.

También soporta dos estilos de nombre de punto de referencia:
  - abreviado en mayúsculas ("BATTLE - AREQUIPA")
  - nombre completo de calle en minúsculas/mayúsculas mixtas
    ("Ayala Gauna y Tarragona")

Uso:
    python3 parse_cuadro.py cuadros/107-NEGRO.pdf data/107-NEGRO.json
"""
import json
import re
import sys
from pathlib import Path

import pdfplumber

CONECTORES = {"y", "de", "del", "la", "las", "los", "al", "a"}


def es_todo_mayusculas(s: str) -> bool:
    letras = [c for c in s if c.isalpha()]
    return bool(letras) and all(c.isupper() for c in letras)


def clean_guess(raw: str) -> str:
    """Reconstruye el nombre de un punto de referencia a partir del texto de
    la celda (que trae saltos de línea por el ajuste de ancho de columna).
    Los cuadros "abreviados" (todo en mayúsculas) suelen partir una palabra
    en dos líneas sin espacio real; los de "nombre completo" casi siempre
    cortan justo en un espacio real, así que se unen distinto."""
    lines = [l for l in raw.split("\n") if l != ""]
    if not lines:
        return ""
    if es_todo_mayusculas(raw):
        text = "".join(lines)
    else:
        text = " ".join(lines)
    text = re.sub(r"-(?!\s)", "- ", text)
    text = re.sub(r"(?<!\s)-", " -", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def norm_key(s: str) -> str:
    return (s or "").replace("\n", "").replace(" ", "").upper()


def parse_header_bloques(row0):
    """Devuelve una lista de dicts {sentido, linea, bandera, dia}, en el
    orden en que aparecen los bloques "SENTIDO: ..." en la fila."""
    bloques = []
    actual = None
    pending_key = None
    for cell in row0:
        if not cell:
            continue
        key = norm_key(cell)
        if key.startswith("SENTIDO"):
            actual = {}
            bloques.append(actual)
            if "IDA" in key and "VUELTA" not in key:
                actual["sentido"] = "IDA"
                pending_key = None
            elif "VUELTA" in key:
                actual["sentido"] = "VUELTA"
                pending_key = None
            else:
                pending_key = "sentido"
            continue
        if key.startswith("LINEA"):
            pending_key = "linea"
            continue
        if key.startswith("BANDERA"):
            pending_key = "bandera"
            continue
        if key.startswith("DIA") or key.startswith("DÍA"):
            pending_key = "dia"
            continue
        if pending_key and actual is not None:
            actual[pending_key] = cell.replace("\n", " ").strip()
            pending_key = None
    return bloques


def find_column_blocks(row_index):
    """Agrupa los índices de columna (a partir de la 2da, la 1ra es
    'Nro: Servicio') en bloques que van de INICIO a FIN. Tolerante a labels
    fusionados como '12 FIN' (columna de índice y FIN pegados)."""
    blocks = []
    current = None
    for i, label in enumerate(row_index):
        if i == 0:
            continue
        norm = norm_key(label)
        if norm.startswith("INICIO"):
            current = []
            blocks.append(current)
        if current is not None:
            current.append(i)
            if "FIN" in norm:
                current = None
    return blocks


def build_puntos(row_names, row_index, cols):
    puntos = []
    for i in cols:
        raw = row_names[i] or ""
        puntos.append(
            {
                "col": i,
                "pos_label": (row_index[i] or "").replace("\n", " ").strip(),
                "label_raw": raw,
                "label_guess": clean_guess(raw),
            }
        )
    return puntos


def build_servicios(rows, cols, contador_inicial):
    """Convierte filas de datos en viajes. Cuando la columna 'Nro: Servicio'
    viene vacía pero la fila tiene horarios, es la continuación de otro
    viaje del mismo vehículo (se ve en líneas con muchos servicios por día:
    el nombre solo se imprime en la primera fila de cada tanda)."""
    servicios = []
    contador = contador_inicial
    ultimo_nombre = None
    for row in rows:
        nombre_celda = (row[0] or "").strip()
        paradas = []
        for i in cols:
            t = row[i]
            if t:
                t = t.strip()
            if t:
                paradas.append({"col": i, "hora": t})
        if not paradas:
            continue
        if nombre_celda:
            ultimo_nombre = nombre_celda
        nombre_efectivo = ultimo_nombre or "SERVICIO"
        servicios.append(
            {
                "id": f"{nombre_efectivo}__{contador}",
                "servicio": nombre_efectivo,
                "paradas": paradas,
            }
        )
        contador += 1
    return servicios, contador


def parse_pdf(pdf_path: str) -> dict:
    resultado = {
        "linea": None,
        "ida": {"sentido": "IDA", "puntos": None, "servicios": []},
        "vuelta": {"sentido": "VUELTA", "puntos": None, "servicios": []},
    }
    contador_global = 0

    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            tablas = page.find_tables()
            if not tablas:
                continue
            rows = tablas[0].extract()
            if len(rows) < 3:
                continue
            row0, row_names, row_index = rows[0], rows[1], rows[2]
            data_rows = rows[3:]

            header_bloques = parse_header_bloques(row0)
            col_bloques = find_column_blocks(row_index)

            for header, cols in zip(header_bloques, col_bloques):
                valor_sentido = (header.get("sentido") or "").upper()
                if "IDA" in valor_sentido:
                    sentido = "ida"
                elif "VUELTA" in valor_sentido:
                    sentido = "vuelta"
                else:
                    continue

                if resultado["linea"] is None and header.get("linea"):
                    resultado["linea"] = header["linea"]

                if resultado[sentido]["puntos"] is None:
                    resultado[sentido]["puntos"] = build_puntos(row_names, row_index, cols)
                    for k in ("bandera", "dia"):
                        if header.get(k):
                            resultado[sentido][k] = header[k]

                servicios, contador_global = build_servicios(data_rows, cols, contador_global)
                resultado[sentido]["servicios"].extend(servicios)

    for sentido in ("ida", "vuelta"):
        if resultado[sentido]["puntos"] is None:
            resultado[sentido]["puntos"] = []
    return resultado


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("Uso: parse_cuadro.py <input.pdf> <output.json>", file=sys.stderr)
        sys.exit(1)
    data = parse_pdf(sys.argv[1])
    out_path = Path(sys.argv[2])
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    n_ida = len(data["ida"]["servicios"])
    n_vuelta = len(data["vuelta"]["servicios"])
    print(f"OK: linea={data['linea']} ida={n_ida} servicios, vuelta={n_vuelta} servicios -> {out_path}")
