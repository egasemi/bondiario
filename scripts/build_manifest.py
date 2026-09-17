#!/usr/bin/env python3
"""
Escanea data/*.final.json y genera data/manifest.json con la lista de
línea/bandera/día disponibles, para que el visor pueda ofrecer un selector
(hoy hay una sola combinación; cuando se agreguen más líneas o los cuadros de
domingos y feriados, aparecen solas acá).

Uso:
    python3 build_manifest.py
"""
import json
from pathlib import Path

DATA_DIR = Path(__file__).parent.parent / "data"


def main():
    entradas = []
    for path in sorted(DATA_DIR.glob("*.final.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        entradas.append(
            {
                "archivo": path.name,
                "linea": data.get("linea"),
                "bandera": data.get("bandera"),
                "dia": data.get("dia"),
                "n_viajes": len(data.get("viajes", [])),
            }
        )
    out = DATA_DIR / "manifest.json"
    out.write_text(json.dumps(entradas, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"{len(entradas)} cuadro(s) -> {out}")


if __name__ == "__main__":
    main()
