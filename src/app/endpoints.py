"""URLs y rarezas de la API interna de golf de Garmin.

Todo lo de aca esta verificado contra respuestas reales de la cuenta, no
contra la documentacion de la libreria (que en varios puntos miente).
"""

from __future__ import annotations

SUMMARY = "/gcs-golfcommunity/api/v2/scorecard/summary"
SCORECARD_DETAIL = "/gcs-golfcommunity/api/v2/scorecard/detail"
SHOTS = "/gcs-golfcommunity/api/v2/shot/scorecard/{scorecard_id}/hole"
CLUB_STATS = "/gcs-golfcommunity/api/v2/club/player"
USER_STATS = "/gcs-golfcommunity/api/v2/player/stats"

# --- Rarezas verificadas -----------------------------------------------------
#
# summary: pagina con `page` (1-based), NO con `start`. `start` se ignora en
#   silencio y devuelve siempre la pagina 1. `get_golf_summary()` de la
#   libreria usa `start`, asi que su paginacion esta rota.
#
# scorecard/detail: acepta varias rondas en `scorecard-ids` separadas por '-'
#   (la coma da 400, el espacio da 400, el parametro repetido da 400).
#   10 ids andan; 25 dan 400. Ver SCORECARD_BATCH_SIZE.
#
# shot/scorecard: el filtro `hole-numbers` se come los hoyos 10-18. Siempre
#   pedir la ronda entera sin filtro.
#
# Coordenadas: DOS escalas distintas en la misma respuesta.
#   - courseSnapshots.lat/lon  -> grados * 1e6
#   - shots y pinPosition      -> semicirculos Garmin (grados * 2^31/180)

SCORECARD_BATCH_SIZE = 10
SEMICIRCLE_TO_DEGREES = 180.0 / 2**31
COURSE_COORD_SCALE = 1e6


# --- Lo que NO existe (probado, todo 404) ------------------------------------
#
# No hay forma de bajar la ficha de una cancha por courseGlobalId con este
# token. Probados y 404: /course/{id}, /course/detail?course-id=,
# /course/global/{id}, /course/snapshot/{id}, /coursesnapshot/{id},
# /course/{id}/hole[s], /course/{id}/tee, /hole/course/{id},
# /course/version/{id}, /course/search, /course/nearby, y los servicios
# /gcs-course-service/* y /gcs-coursemap-service/*.
# Los parametros `include-course-details` e `include-hole-details` en
# scorecard/detail devuelven 200 pero no agregan ni un campo.
#
# Consecuencia: el YARDAJE OFICIAL POR HOYO no esta disponible. Lo unico que
# trae courseSnapshots.tees es handicap por hoyo, rating y slope.
# El largo se deriva del tee shot al pin (ver hole_length.py).
