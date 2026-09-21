# Bondiario

Un día completo del transporte urbano de Rosario, en cámara rápida: todas las
líneas de colectivo (o una a la vez) moviéndose sobre un mapa según los
horarios oficiales, desde la primera salida hasta la última madrugada.

**[▶ Ver la animación en vivo](https://egasemi.github.io/bondiario/)**
(GitHub Pages) — o corriendo `web/index.html` localmente, ver
[Cómo correrlo](#cómo-correrlo-localmente).

## Qué es esto

El [EMR](https://emr.gov.ar) (Ente de la Movilidad de Rosario) publica los
cuadros horarios de cada línea como PDFs — una tabla por sentido con los
horarios de cada servicio en cada punto de referencia del recorrido. Son
datos públicos, pero están pensados para leerse de a una línea, no para
tener una foto completa de cómo respira la ciudad en un día.

Este proyecto toma esos ~150 PDFs, los convierte en datos estructurados,
geolocaliza cada punto de referencia y arma una animación donde se puede ver
(o sentir) la frecuencia real del servicio: los baches nocturnos, los picos
de la mañana, cuántas líneas están circulando en cualquier instante del día.

> **Nota:** los PDFs de origen son bastante irregulares entre líneas
> (distintos formatos, abreviaturas ad-hoc, columnas vacías, algún cuadro
> con datos incompletos), así que algunos puntos de referencia y recorridos
> pueden no ser del todo precisos. Si ves una esquina mal ubicada, se puede
> corregir desde el propio mapa (ver [Metodología](#metodología)).

## Metodología

El pipeline completo vive en `scripts/` y se corre en este orden:

1. **`scrape_lineas.py`** — descarga todos los PDFs publicados en
   [emr.gov.ar/transporte-publico/cuadros-horarios](https://emr.gov.ar/transporte-publico/cuadros-horarios)
   (no hace falta un navegador: el listado completo de línea/bandera/tipo de
   día con su URL de PDF ya está en el HTML de esa página, en un
   `<select>`). Guarda los PDF en `cuadros/<tipo_de_día>/`.

2. **`parse_cuadro.py`** — parsea cada PDF con [pdfplumber](https://github.com/jsvine/pdfplumber),
   reconstruyendo la tabla completa (encabezados, puntos de referencia y
   horarios por servicio). Los PDFs del EMR no siguen un único formato:
   - algunas líneas tienen IDA y VUELTA lado a lado en una sola página;
   - otras traen cada sentido en una tabla separada, a veces repartida en
     varias páginas de continuación cuando hay muchos servicios en el día;
   - los nombres de los puntos de referencia a veces son abreviaturas en
     mayúsculas (`ERIOS - PELLE`) y a veces el nombre completo de la calle
     (`San Lorenzo y Pte. Rocca`);
   - algunos vehículos hacen varias vueltas en el día y el PDF solo imprime
     el nombre del servicio en la primera fila de cada tanda.

   El parser detecta estos casos y normaliza todo a una misma estructura.

3. **`geocode_puntos.py`** — cada punto de referencia queda identificado por
   dos "calles" (a veces abreviadas). Para geolocalizarlo:
   - se resuelve la abreviatura contra el callejero oficial de Rosario
     (~2700 calles, vía la [API georef](https://datosgobar.github.io/georef-ar-api/) de datos.gob.ar), primero por
     coincidencia de prefijo y después con una heurística para abreviaturas
     de dos palabras (`STAFE` → `STA` + `FE` → *Santa Fe*, `SLORE` → `S` +
     `LORE` → *San Lorenzo*);
   - con el nombre resuelto, se geocodifica la intersección contra el
     webservice municipal `ws.rosario.gob.ar/ubicaciones`;
   - cuando la abreviatura tiene más de un candidato posible en el
     callejero, se prueban todas las combinaciones y, si convergen en el
     mismo punto geográfico, se acepta automáticamente sin necesidad de
     saber cuál nombre era el "correcto".

   Todo geocoding exitoso se cachea (`data/geocode_cache.json`) y se
   reutiliza entre las variantes de día y entre líneas que comparten calles.

4. **Panel de resolución manual** (`web/panel.html`) — con este proceso se
   resuelve automáticamente una parte importante de los puntos, pero no
   todos: hay abreviaturas por iniciales, apodos de calles, y errores u
   omisiones directamente en el PDF de origen que ninguna heurística puede
   adivinar con seguridad. Esos puntos quedan listados ahí, deduplicados por
   esquina real (no por línea ni por variante de día), para resolverlos una
   sola vez a mano —buscando la dirección o marcando el punto en el mapa—.
   La corrección se guarda en `data/manual_overrides.json` y se aplica para
   siempre a cualquier línea o cuadro que pase por esa misma esquina.

   Los cuadros del EMR son bastante irregulares entre sí (distinta
   ortografía, abreviaturas ad-hoc, columnas vacías, algún PDF con datos
   incompletos), así que este trabajo de curación manual es continuo: no
   todas las esquinas del sistema están resueltas todavía.

5. **`build_final.py`** — combina el cuadro parseado con las coordenadas
   resueltas y arma el JSON final que consume el visor: cada viaje queda
   como una lista de (segundo del día, punto), con la hora convertida a
   segundos desde medianoche y manejando los viajes que cruzan las 00:00.

6. **`build_manifest.py`** — indexa todos los `*.final.json` generados
   (línea, bandera, día) para que el visor pueda ofrecer el selector.

7. **`fetch_lineas_oficiales.py`** — además de los puntos de referencia
   sueltos que salen de los PDFs, `ws.rosario.gob.ar` expone por separado el
   **recorrido real** de cada línea (geometría GeoJSON de ida y vuelta) y
   sus paradas oficiales. Este script matchea cada combinación línea+bandera
   propia contra ese listado — nada trivial, porque el código de línea que
   trae cada PDF es tan irregular como el resto ("143-136- 137" vs
   "143/136/ 137" vs "143136137", líneas con nombre truncado como
   "ENLACE NOROE", algún PDF con el campo corrupto en notación científica
   por un Excel de origen) — y descarga la geometría de las que matchea.
   Con esto el visor dibuja el trazado real en vez de una línea recta entre
   los puntos de referencia del PDF.

8. **`validar_recorrido.py`** — con el recorrido real ya disponible, compara
   cada punto geocodificado contra la geometría oficial más cercana (ida o
   vuelta) y marca los que quedan a más de 150 metros como sospechosos de
   estar mal ubicados. El visor los resalta en el mapa y el panel tiene una
   sección aparte para revisarlos uno por uno.

El visor (`web/index.html`) es una página estática con [Leaflet](https://leafletjs.com/):
interpola linealmente la posición de cada colectivo entre sus paradas según
la hora simulada, con control de velocidad y un selector de línea / día
(incluyendo la opción de ver todas las líneas circulando juntas). También
muestra, para una línea puntual, un pulso tipo electrocardiograma por
sentido: se acelera cuando la frecuencia de servicio es alta y se aplana
("muere") cuando no hay servicio a esa hora.

## Fuentes de datos

- **Cuadros horarios**: [EMR – Ente de la Movilidad de Rosario](https://emr.gov.ar/transporte-publico/cuadros-horarios) (PDF por línea/bandera/tipo de día).
- **Callejero de Rosario**: [API de Georreferenciación (georef)](https://datosgobar.github.io/georef-ar-api/), Ministerio de Economía de la Nación — datos.gob.ar.
- **Geocodificación de intersecciones**: webservice público `ws.rosario.gob.ar/ubicaciones` (Municipalidad de Rosario), el mismo que usa el mapa oficial de la ciudad.
- **Recorrido real y paradas oficiales**: mismo webservice municipal (`ws.rosario.gob.ar/ubicaciones/public/lineas` y `.../linea/{idEmpresa}/{id}`), identificado a partir de un proyecto hermano que ya lo usaba para publicar los trazados en un mapa propio.
- **Mapa base**: [OpenStreetMap](https://www.openstreetmap.org/copyright).
- **Sistema de coordenadas**: EPSG:22185 (POSGAR94 / Argentina 5), convertido a WGS84 con [pyproj](https://pyproj4.github.io/pyproj/) (pipeline) y [proj4js](http://proj4js.org/) (panel).

## Estructura del repo

```
cuadros/          PDFs originales descargados del EMR, por tipo de día
data/             JSON generados en cada etapa del pipeline + caches
  *.json               cuadro parseado (crudo)
  *.puntos.json        puntos con intento de geocodificación
  *.final.json         archivo definitivo que consume el visor
  manifest.json         índice de línea/bandera/día para el selector
  geocode_cache.json     cache de geocoding (calle1|calle2 -> resultado)
  manual_overrides.json  correcciones manuales permanentes, por esquina
  pending_puntos.json    esquinas sin resolver, deduplicadas
  oficial_map.json        línea+bandera -> línea oficial matcheada
  oficial/                 geometría real y paradas oficiales por línea
  puntos_fuera_de_recorrido.json  puntos sospechosos (lejos del recorrido real)
scripts/          pipeline (scrape, parse, geocode, build, orquestador)
web/              index.html (visor) y panel.html (resolución manual)
server.py         servidor local: sirve /web y /data, y la API del panel
```

## Cómo correrlo localmente

```bash
# pipeline completo (bajar PDFs -> parsear -> geocodificar -> armar final.json)
python3 scripts/scrape_lineas.py
python3 scripts/process_all.py

# recorrido real oficial + detección de puntos fuera de recorrido (opcional)
python3 scripts/fetch_lineas_oficiales.py
python3 scripts/validar_recorrido.py
python3 scripts/build_manifest.py

# servidor local (visor + API del panel)
python3 server.py 8765
```

- Visor: `http://127.0.0.1:8765/web/index.html`
- Panel de resolución manual: `http://127.0.0.1:8765/web/panel.html`

El visor es 100% estático (solo hace `fetch` de archivos JSON), así que
también funciona servido por cualquier hosting estático — incluida la
versión publicada en GitHub Pages. El panel, en cambio, necesita el
servidor local corriendo (`server.py`) porque guarda las correcciones, así
que el enlace "Corregir esta parada" solo aparece corriendo en local.
