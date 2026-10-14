# caddie

Tu propia data de golf, extraída del reloj y analizada en serio.

Un **Garmin Approach S62** captura cada tiro con coordenadas GPS, el palo, la
distancia y la tarjeta completa. La app de Garmin Golf muestra una fracción de
eso y no deja exportarlo. Esto lo baja entero, lo normaliza y lo analiza.

**232 vueltas · 14.509 tiros con GPS · 25 canchas · 2022 a 2026.**

Garmin no publica una API de golf. `python-garminconnect` se autentica con el
mismo flujo SSO que la app de Android y expone los endpoints internos.

---

## Arquitectura

| Capa | Qué hace |
|---|---|
| **1. Fetch** | Baja de Garmin y guarda **crudo** en `data/raw/`, un JSON por respuesta. Sync incremental vía `_manifest.json`. |
| **2. Normalize** | De los JSON crudos a Postgres + PostGIS: canchas, vueltas, hoyos, tiros, palos. |
| **3. Analyze** | API FastAPI de solo lectura + frontend React. |

Es una API reverseada, así que la capa 1 le pega a la red **una sola vez** por
recurso. El parseo se itera offline contra los JSON ya guardados.

## Arrancar

```bash
uv sync
cp .env.example .env          # completar GARMIN_EMAIL y GARMIN_PASSWORD

uv run garmin-golf sync       # host:   Garmin -> data/raw
docker compose up -d          # db + api + web
docker compose run --rm etl   # docker: data/raw -> Postgres
```

La UI queda en **http://localhost:5173**, la API en **http://localhost:8010**.

También se puede sincronizar **desde la UI**, en la pestaña *Datos*: entrás con
tu cuenta de Garmin (incluido el MFA, que ahí funciona mejor que por stdin) y
un botón trae las vueltas nuevas y recarga la base.

### Credenciales

La contraseña se usa **una sola vez** para que Garmin emita el token OAuth, y
no se guarda en ningún lado: no va a la base, no queda en el navegador, no se
escribe en los logs. Lo único que se persiste es el token, en un volumen de
Docker. Es exactamente lo mismo que ya pasaba corriendo el CLI a mano.

El estado pendiente del MFA vive en memoria del proceso de la API y se vence a
los cinco minutos: no se serializa a ningún lado.

**La API no tiene autenticación propia.** Por eso los tres puertos están
atados a `127.0.0.1` en `docker-compose.yml`. Si alguna vez esto corre en un
servidor, hay que ponerle auth antes de exponerlo.

| Servicio | Qué es | Puerto |
|---|---|---|
| `db` | Postgres 16 + PostGIS 3.5 (imagen arm64 nativa) | 5433 |
| `api` | FastAPI, solo lectura | 8010 |
| `web` | React + Vite | 5173 |
| `etl` | Capa 2, a demanda (`profiles: tools`) | – |

### Otros comandos

```bash
uv run garmin-golf status                # qué hay bajado, sin tocar la red
uv run garmin-golf sync --limit 10       # solo las 10 vueltas más recientes
uv run python -m garmin_golf.probe data/raw/summary/*.json   # inspector de estructura
```

## Qué analiza

- **Distancia real por palo** — mediana y rango intercuartil sobre los tiros crudos, no el promedio que publica Garmin.
- **Dispersión** — desvío lateral firmado respecto de la línea de juego, con sesgo y apertura por palo.
- **Tendencia de score** — vuelta a vuelta con media móvil.
- **Estrategia** — probabilidad de par según el largo del hoyo, cuánto cambia pegar la calle, y dónde se van los golpes en total. Todo con tamaño de muestra e intervalo de Wilson al 95%.
- **Largo del hoyo** — reconstruido de los propios tiros, incluyendo detección de doglegs.
- **Putting** — cantidad de putts por hoyo y su relación con los greens en regulación.

## Rarezas verificadas de la API

Todo comprobado contra respuestas reales, no contra la doc de la librería.
Ver `src/garmin_golf/endpoints.py`.

| Qué | Detalle |
|---|---|
| Paginación del summary | Se pagina con `page` (1-based). El `start=N` que manda `get_golf_summary()` **se ignora**: devuelve siempre la página 1, así que su loop baja lo mismo N veces. Por eso llamamos a `connectapi` directo. |
| Batching de scorecards | `scorecard-ids` acepta varias separadas por `-`. Coma, espacio y parámetro repetido dan 400. 10 ids andan, 25 dan 400. |
| Filtro de hoyos en tiros | `hole-numbers` descarta los hoyos 10-18. Hay que pedir la vuelta entera sin filtro. |
| Coordenadas | **Dos escalas en la misma respuesta**: `courseSnapshots.lat/lon` son grados × 1e6; los tiros y `pinPosition` son semicírculos (× 2³¹/180). |
| Snapshots de cancha | Una misma cancha tiene **varios** `courseSnapshots` (versiones del campo, layouts de 9 y 18, pares distintos). Hay que elegir el que indica `courseSnapshotId` de la tarjeta, no el primero. |
| Par de la vuelta | Se suma sobre los hoyos **realmente jugados**, con par cíclico: en una cancha de 9 jugada dos veces, el hoyo 10 es el 1. |
| Nombres de palos | `model` es el nombre del **set**, no del palo: ocho hierros llegan como `Ping 430`. Lo que los distingue es `clubTypeId`. `shaftLength` **no** sirve: varios traen 45.5 por defecto. |
| Yardaje de canchas | **No existe y no hay endpoint** — 37 rutas probadas, todas 404. Se deriva del tiro de salida al green. |
| `pinPosition` | **No es la bandera del día**: es un punto fijo del mapa de la cancha (2 a 4 valores distintos en 79 vueltas del mismo hoyo). Sirve como línea de juego, no para medir proximity. |

## Calidad de la data

| año | vueltas | captura AutoShot | con `clubId` | putts con GPS |
|---|---|---|---|---|
| 2022 | 41 | 89% | 88% | 636 |
| 2023 | 50 | 82% | 56% | 862 |
| 2024 | 58 | 84% | 34% | 1639 |
| 2025 | 39 | 81% | 53% | 475 |
| 2026 | 44 | 83% | **71%** | **0** |

AutoShot captura entre el 81% y el 89% de los golpes sin putt: es un **muestreo,
no un censo**. Los putts con GPS solo existen con sensores de palo, que se
usaron hasta 2025.

**No hay métricas de distancia de putt, a propósito.** Cuando se miden, el
porcentaje de embocados sale plano en ~50% desde cero hasta veinte yardas, lo
que es imposible: la posición de la bola en el green no tiene la precisión
necesaria. Se probó con el `pinPosition` registrado y deduciendo el hoyo del
último putt; misma curva plana en ambos casos.

## Decisiones

**Postgres + PostGIS, no SQLite.** Con un `docker compose` de por medio SQLite
pierde su única ventaja. Las consultas que importan son espaciales —
dispersión, distancia al green, largo de hoyo— y `ST_Distance` sobre
`geography` las resuelve en SQL. Validación de que la geometría entró bien:
recalcular con PostGIS la distancia de cada tiro da **0,15 m de error medio**
contra el `meters` de Garmin, sobre 14.434 tiros.

**La base guarda metros, la API devuelve yardas.** Los metros son la unidad de
origen y no se pierde nada; todo campo de distancia que sale de la API termina
en `_yd`.

**El raw es la fuente de verdad.** El ETL hace `TRUNCATE` y recarga: la base es
derivada y descartable. Para iterar el esquema no hace falta volver a tocar la
red.

**Los palos se nombran por ranura (`clubTypeId`), no por id.** Al cambiar de
set, el hierro 5 nuevo entra con otro id pero la misma ranura, así que hereda
el nombre solo y los tiros viejos quedan en el palo viejo. Ver
`config/club_labels.json`.

## Layout

```
src/garmin_golf/
  config.py       credenciales y rutas
  client.py       login con cache de token + MFA
  endpoints.py    URLs y rarezas verificadas de la API
  raw_store.py    escritura atómica + manifest (sync incremental)
  fetch.py        CLI de la capa 1
  bulk.py         bajada masiva incremental
  probe.py        inspector de estructura de JSON
  geo.py          coordenadas y haversine
  hole_length.py  largo de hoyo derivado + detección de doglegs
  stats.py        intervalo de Wilson
  units.py        metros -> yardas
  etl.py          capa 2
  db.py / api.py  capa 3
web/              React + Vite
db/init/          esquema SQL
config/           mapeo de nombres de palos
```

`data/`, `.env` y los tokens están en `.gitignore`. La paleta está documentada
en `docs-palette.md`.
