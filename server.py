#!/usr/bin/env python3
"""Servidor local de desarrollo: sirve /web (visor) y /data (JSON generados),
y expone la API que usa el panel de resolución manual (panel.html).

Uso:
    python3 server.py [puerto]
"""
import http.server
import json
import socketserver
import sys
from pathlib import Path
from urllib.parse import urlparse, parse_qs

ROOT = Path(__file__).parent
DATA_DIR = ROOT / "data"

sys.path.insert(0, str(ROOT / "scripts"))
from collect_pending import calcular_pendientes, buscar_punto  # noqa: E402
from geocode_puntos import cargar_overrides, guardar_overrides  # noqa: E402
from build_final import main as build_final_main  # noqa: E402


class Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(ROOT), **kwargs)

    def end_headers(self):
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def _json(self, status, payload):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path == "/api/pending":
            self._json(200, calcular_pendientes())
            return
        if parsed.path == "/api/punto":
            clave = parse_qs(parsed.query).get("clave", [None])[0]
            if not clave:
                self.send_error(400, "Falta el parámetro clave")
                return
            item = buscar_punto(clave)
            if item is None:
                self.send_error(404, f"No se encontró ninguna ocurrencia de {clave}")
                return
            self._json(200, item)
            return
        super().do_GET()

    def do_POST(self):
        path = urlparse(self.path).path
        if path != "/api/resolver":
            self.send_error(404, "Not found")
            return

        length = int(self.headers.get("Content-Length", 0))
        try:
            body = json.loads(self.rfile.read(length))
            clave, lat, lon = body["clave"], float(body["lat"]), float(body["lon"])
        except Exception as e:
            self.send_error(400, f"Body inválido: {e}")
            return

        # 1) guardar el override de forma permanente (se reutiliza para
        #    siempre en cualquier línea/día que comparta esta esquina)
        overrides = cargar_overrides()
        geocode = {"status": "ok", "lat": lat, "lon": lon, "manual": True}
        overrides[clave] = geocode
        guardar_overrides(overrides)

        # 2) aplicar el fix a todos los cuadros que ya tenían ese punto
        #    pendiente, y regenerar su archivo definitivo (*.final.json)
        cuadros_afectados = set()
        for puntos_path in DATA_DIR.glob("*.puntos.json"):
            data = json.loads(puntos_path.read_text(encoding="utf-8"))
            tocado = False
            for p in data["puntos"]:
                if p.get("clave") == clave:
                    p["status"] = "auto"
                    p["geocode"] = geocode
                    tocado = True
            if tocado:
                puntos_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
                cuadro_id = puntos_path.name[: -len(".puntos.json")]
                cuadros_afectados.add(cuadro_id)

        for cuadro_id in cuadros_afectados:
            cuadro_path = DATA_DIR / f"{cuadro_id}.json"
            puntos_path = DATA_DIR / f"{cuadro_id}.puntos.json"
            final_path = DATA_DIR / f"{cuadro_id}.final.json"
            if cuadro_path.exists():
                build_final_main(str(cuadro_path), str(puntos_path), str(final_path))

        self._json(200, {"ok": True, "cuadros_actualizados": sorted(cuadros_afectados)})


class Server(socketserver.TCPServer):
    allow_reuse_address = True


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8765
    with Server(("127.0.0.1", port), Handler) as httpd:
        print(f"Sirviendo {ROOT} en http://127.0.0.1:{port}/web/")
        print(f"Panel de resolución manual en http://127.0.0.1:{port}/web/panel.html")
        httpd.serve_forever()
