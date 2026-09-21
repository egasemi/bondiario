"""Utilidades geométricas simples (aproximación plana local, suficiente a
la escala de una ciudad) para medir distancia punto-a-recorrido."""
import math

LAT_SCALE = 111320.0  # metros por grado de latitud, aprox.


def punto_a_segmento_m(p, a, b):
    """Distancia en metros de un punto p=(lat,lon) al segmento a-b=(lat,lon)."""
    lat0 = (p[0] + a[0] + b[0]) / 3
    lon_scale = LAT_SCALE * math.cos(math.radians(lat0))
    px, py = p[1] * lon_scale, p[0] * LAT_SCALE
    ax, ay = a[1] * lon_scale, a[0] * LAT_SCALE
    bx, by = b[1] * lon_scale, b[0] * LAT_SCALE
    dx, dy = bx - ax, by - ay
    if dx == 0 and dy == 0:
        return math.hypot(px - ax, py - ay)
    t = ((px - ax) * dx + (py - ay) * dy) / (dx * dx + dy * dy)
    t = max(0.0, min(1.0, t))
    projx, projy = ax + t * dx, ay + t * dy
    return math.hypot(px - projx, py - projy)


def distancia_a_geometria_m(lat, lon, geometry):
    """Distancia mínima en metros de (lat,lon) a una geometría GeoJSON
    LineString o MultiLineString (coordenadas en [lon,lat], como GeoJSON)."""
    if not geometry:
        return None
    tipo = geometry.get("type")
    coords = geometry.get("coordinates") or []
    if tipo == "LineString":
        paths = [coords]
    elif tipo == "MultiLineString":
        paths = coords
    else:
        return None

    p = (lat, lon)
    mejor = None
    for path in paths:
        for i in range(len(path) - 1):
            a = (path[i][1], path[i][0])
            b = (path[i + 1][1], path[i + 1][0])
            d = punto_a_segmento_m(p, a, b)
            if mejor is None or d < mejor:
                mejor = d
    return mejor
