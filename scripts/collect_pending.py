#!/usr/bin/env python3
"""
Recorre todos los data/*.puntos.json y arma la lista global de puntos de
referencia que todavía no se pudieron geocodificar automáticamente,
deduplicada por esquina real (el mismo cruce de calles aparece en varias
líneas y en varias variantes de día, pero acá se resuelve una sola vez).

Uso:
    python3 collect_pending.py              # imprime un resumen
"""
import json
from pathlib import Path

DATA_DIR = Path(__file__).parent.parent / "data"


def calcular_pendientes():
    pendientes = {}
    for path in sorted(DATA_DIR.glob("*.puntos.json")):
        cuadro_id = path.name[: -len(".puntos.json")]
        data = json.loads(path.read_text(encoding="utf-8"))
        linea = data.get("linea")
        for p in data["puntos"]:
            resuelto = p.get("status") == "auto" and p.get("geocode", {}).get("status") == "ok"
            if resuelto:
                continue
            clave = p["clave"]
            entry = pendientes.setdefault(
                clave,
                {"clave": clave, "tokens": p["tokens"], "ocurrencias": []},
            )
            entry["ocurrencias"].append(
                {
                    "cuadro_id": cuadro_id,
                    "punto_id": p["id"],
                    "linea": linea,
                    "labels_raw": [oc["label_raw"] for oc in p["ocurrencias"]],
                }
            )
    lista = sorted(pendientes.values(), key=lambda e: -len(e["ocurrencias"]))
    return lista


def buscar_punto(clave: str):
    """Busca TODAS las ocurrencias de una esquina por su clave, esté o no
    resuelta (a diferencia de calcular_pendientes, que solo lista las que
    faltan). Sirve para poder corregir desde el mapa un punto que ya tiene
    posición pero está mal ubicado."""
    ocurrencias = []
    tokens = None
    estado_actual = None
    for path in sorted(DATA_DIR.glob("*.puntos.json")):
        cuadro_id = path.name[: -len(".puntos.json")]
        data = json.loads(path.read_text(encoding="utf-8"))
        linea = data.get("linea")
        for p in data["puntos"]:
            if p["clave"] != clave:
                continue
            tokens = p["tokens"]
            if p.get("status") == "auto" and p.get("geocode", {}).get("status") == "ok":
                estado_actual = p["geocode"]
            ocurrencias.append(
                {
                    "cuadro_id": cuadro_id,
                    "punto_id": p["id"],
                    "linea": linea,
                    "labels_raw": [oc["label_raw"] for oc in p["ocurrencias"]],
                }
            )
    if not ocurrencias:
        return None
    return {"clave": clave, "tokens": tokens, "ocurrencias": ocurrencias, "estado_actual": estado_actual}


def main():
    lista = calcular_pendientes()
    out = DATA_DIR / "pending_puntos.json"
    out.write_text(json.dumps(lista, ensure_ascii=False, indent=2), encoding="utf-8")
    n_ocurrencias = sum(len(e["ocurrencias"]) for e in lista)
    print(f"{len(lista)} esquinas únicas pendientes ({n_ocurrencias} ocurrencias entre todos los cuadros) -> {out}")


if __name__ == "__main__":
    main()
