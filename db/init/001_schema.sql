-- Capa 2: esquema normalizado de la data de golf.
--
-- Unidades: TODAS las distancias se guardan en METROS (es lo que devuelve
-- Garmin; guardarlo asi no pierde nada). La conversion a yardas pasa en la
-- capa de presentacion. Las columnas llevan sufijo _m para que no se mezclen.
--
-- Coordenadas: geography(Point, 4326) en grados WGS84, ya desescaladas desde
-- los semicirculos de Garmin.

CREATE EXTENSION IF NOT EXISTS postgis;

-- ---------------------------------------------------------------- canchas --
CREATE TABLE courses (
    course_global_id   BIGINT PRIMARY KEY,
    name               TEXT NOT NULL,
    city               TEXT,
    state              TEXT,
    country            TEXT,
    location           geography(Point, 4326),
    round_par          SMALLINT,
    front_nine_par     SMALLINT,
    back_nine_par      SMALLINT,
    hole_pars          TEXT,          -- "453453444434354445", un digito por hoyo
    design_year        SMALLINT
);
COMMENT ON TABLE courses IS
  'Una fila por courseGlobalId. El courseName del summary viene sucio
   (mismo club con 3 strings distintos); el id es la clave confiable.';

CREATE TABLE course_tees (
    course_global_id   BIGINT NOT NULL REFERENCES courses ON DELETE CASCADE,
    name               TEXT NOT NULL,         -- Mens / Womens
    handicap_type      TEXT,
    rating             REAL,
    slope              SMALLINT,
    hole_handicaps     TEXT,                  -- 2 digitos por hoyo
    PRIMARY KEY (course_global_id, name)
);
COMMENT ON COLUMN course_tees.hole_handicaps IS
  'Lo unico que Garmin da por tee. NO hay yardaje: no existe endpoint de
   canchas (37 rutas probadas, todas 404). El largo se deriva en hole_profiles.';

-- ----------------------------------------------------------------- rondas --
CREATE TABLE rounds (
    id                   BIGINT PRIMARY KEY,
    course_global_id     BIGINT REFERENCES courses ON DELETE SET NULL,
    course_name_raw      TEXT,
    started_at           TIMESTAMPTZ NOT NULL,
    ended_at             TIMESTAMPTZ,
    score_type           TEXT,        -- STROKE_PLAY / STABLEFORD
    round_type           TEXT,        -- ALL / FRONT_9 / BACK_9
    holes_completed      SMALLINT,
    strokes              SMALLINT,
    handicapped_strokes  SMALLINT,
    par                  SMALLINT,    -- sum(hole_pars), recalculado
    score_vs_par         SMALLINT,    -- strokes - par
    player_handicap      SMALLINT,
    tee_box              TEXT,
    tee_box_rating       REAL,
    tee_box_slope        SMALLINT,
    distance_walked_m    INTEGER,
    steps_taken          INTEGER,
    sensor_on_putter     BOOLEAN,
    exclude_from_stats   BOOLEAN NOT NULL DEFAULT FALSE,
    is_complete          BOOLEAN NOT NULL,   -- todos los hoyos con strokes
    has_shot_data        BOOLEAN NOT NULL DEFAULT FALSE
);
CREATE INDEX ON rounds (started_at DESC);
CREATE INDEX ON rounds (course_global_id);
COMMENT ON COLUMN rounds.is_complete IS
  'FALSE si algun hoyo no tiene strokes. 17 de 232 rondas estan incompletas;
   filtrarlas antes de cualquier promedio.';

-- Stats que Garmin ya calcula, por segmento. No los recalculamos: los
-- guardamos y los contrastamos.
CREATE TABLE round_stats (
    round_id             BIGINT NOT NULL REFERENCES rounds ON DELETE CASCADE,
    segment              TEXT NOT NULL CHECK (segment IN ('round','front','back')),
    holes_played         SMALLINT,
    strokes              SMALLINT,
    handicapped_strokes  SMALLINT,
    putts                SMALLINT,
    mean_putts_per_hole  REAL,
    chips                SMALLINT,
    greens_in_regulation SMALLINT,
    greens_recorded      SMALLINT,
    fairways_hit         SMALLINT,
    fairways_left        SMALLINT,
    fairways_right       SMALLINT,
    fairways_recorded    SMALLINT,
    ups_and_downs        SMALLINT,
    holes_eagle          SMALLINT,
    holes_birdie         SMALLINT,
    holes_par            SMALLINT,
    holes_bogey          SMALLINT,
    holes_over_bogey     SMALLINT,
    PRIMARY KEY (round_id, segment)
);

-- ------------------------------------------------------------------ hoyos --
CREATE TABLE holes (
    round_id         BIGINT NOT NULL REFERENCES rounds ON DELETE CASCADE,
    hole_number      SMALLINT NOT NULL,
    par              SMALLINT,
    hole_handicap    SMALLINT,
    strokes          SMALLINT,
    putts            SMALLINT,
    penalties        SMALLINT,
    fairway_outcome  TEXT,            -- HIT / LEFT / RIGHT
    -- NO es la bandera del dia: es el punto de referencia del green que trae
    -- el mapa de la cancha. Verificado: toma 2-4 valores distintos en 79
    -- rondas del mismo hoyo. Sirve como objetivo estable (centro del green),
    -- no para medir proximity al pin.
    green_ref        geography(Point, 4326),
    -- Largo derivado de los tiros de ESTA ronda (ver hole_length.py).
    straight_m       REAL,            -- tee -> pin, linea recta
    corridor_m       REAL,            -- tee -> caida del drive -> pin
    score_vs_par     SMALLINT GENERATED ALWAYS AS (strokes - par) STORED,
    PRIMARY KEY (round_id, hole_number)
);
CREATE INDEX ON holes (par);
COMMENT ON COLUMN holes.straight_m IS
  'Distancia que REALMENTE jugaste ese dia (tee y bandera de la jornada).
   Garmin no da yardaje de tarjeta; esto es la alternativa y para correlacionar
   score con distancia es la variable correcta.';

-- ------------------------------------------------------------------ tiros --
CREATE TABLE shots (
    id                 BIGINT PRIMARY KEY,
    round_id           BIGINT NOT NULL REFERENCES rounds ON DELETE CASCADE,
    hole_number        SMALLINT NOT NULL,
    shot_order         SMALLINT,
    club_id            BIGINT,          -- 0 o NULL = AutoShot no supo el palo
    shot_type          TEXT,            -- TEE/APPROACH/LAYUP/RECOVERY/CHIP/PUTT/UNKNOWN
    shot_source        TEXT,            -- DEVICE_AUTO / SENSOR / CLIENT
    auto_shot_type     TEXT,
    shot_at            TIMESTAMPTZ,
    meters             REAL,
    start_loc          geography(Point, 4326),
    start_lie          TEXT,            -- TeeBox/Fairway/Rough/Bunker/Green
    end_loc            geography(Point, 4326),
    end_lie            TEXT,
    exclude_from_stats BOOLEAN NOT NULL DEFAULT FALSE
);
CREATE INDEX ON shots (round_id, hole_number, shot_order);
CREATE INDEX ON shots (club_id) WHERE club_id IS NOT NULL;
CREATE INDEX ON shots (shot_type);
CREATE INDEX ON shots USING GIST (end_loc);
COMMENT ON TABLE shots IS
  'AutoShot captura ~82-91% de los golpes sin putt. Los PUTT solo existen
   cuando hubo sensores de palo (2022-2025); en 2026 no hay ninguno.
   Tratar como muestreo, no como censo.';

-- ------------------------------------------------------------------ palos --
CREATE TABLE clubs (
    id                    BIGINT PRIMARY KEY,
    model                 TEXT,
    name                  TEXT,
    -- Garmin guarda el nombre del SET en `model`, no el del palo. El nombre
    -- se mapea por clubTypeId (la ranura en la bolsa) en
    -- config/club_labels.json, asi un set nuevo lo hereda solo.
    label                 TEXT,
    slot                  TEXT,
    club_type_id          SMALLINT,
    flex_type             TEXT,
    shaft_length          REAL,
    retired               BOOLEAN,
    deleted               BOOLEAN NOT NULL DEFAULT FALSE,
    -- stats que Garmin ya calcula
    shots_count           INTEGER,
    avg_distance_m        REAL,
    max_recent_m          REAL,
    min_recent_m          REAL,
    max_lifetime_m        REAL,
    pct_fairway_hit       REAL,
    pct_fairway_left      REAL,
    pct_fairway_right     REAL,
    pct_green_hit         REAL,
    pct_green_miss_left   REAL,
    pct_green_miss_right  REAL,
    pct_green_miss_long   REAL,
    pct_green_miss_short  REAL
);

-- Nombres de palos puestos por el usuario desde la UI. Garmin guarda en
-- `model` el nombre del SET, no el del palo: ocho hierros del mismo juego
-- llegan todos igual. Esta tabla NO la toca el TRUNCATE del ETL — si se
-- borrara con cada recarga habria que renombrar la bolsa cada vez.
CREATE TABLE club_labels (
    scope TEXT NOT NULL CHECK (scope IN ('slot','club')),
    key   TEXT NOT NULL,
    label TEXT NOT NULL,
    PRIMARY KEY (scope, key)
);
COMMENT ON COLUMN club_labels.scope IS
  'slot -> por clubTypeId, lo hereda un set nuevo en la misma posicion de la
   bolsa. club -> por id de palo, para excepciones.';

-- Etiquetas de palos puestas por el usuario, para agrupar y filtrar.
-- Mismo criterio que club_labels: el TRUNCATE del ETL no la toca.
CREATE TABLE club_tags (
    scope TEXT NOT NULL CHECK (scope IN ('slot','club')),
    key   TEXT NOT NULL,
    tag   TEXT NOT NULL,
    PRIMARY KEY (scope, key, tag)
);
COMMENT ON COLUMN club_tags.scope IS
  'slot -> por clubTypeId, la hereda un set nuevo en la misma posicion
   ("hierros", "wedges"). club -> por id de palo, para lo que es propio de
   ese palo y no de la posicion ("set viejo").';

-- --------------------------------------------- perfil derivado de un hoyo --
CREATE TABLE hole_profiles (
    course_global_id   BIGINT NOT NULL REFERENCES courses ON DELETE CASCADE,
    hole_number        SMALLINT NOT NULL,
    par                SMALLINT,
    n_rounds           SMALLINT NOT NULL,
    straight_median_m  REAL NOT NULL,
    straight_p10_m     REAL,
    straight_p90_m     REAL,
    corridor_median_m  REAL,
    dogleg_excess_m    REAL,
    shape              TEXT,     -- recto / curva / dogleg, vs el piso de ruido
    PRIMARY KEY (course_global_id, hole_number)
);
COMMENT ON TABLE hole_profiles IS
  'Largo de cada hoyo reconstruido con los tiros propios a lo largo de todas
   las rondas. El piso de ruido se calibra contra los par 3, donde el exceso
   corredor-vs-recta no puede ser dogleg sino dispersion propia.';

-- ---------------------------------------------------------- metadata ETL --
CREATE TABLE etl_runs (
    id            SERIAL PRIMARY KEY,
    ran_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    raw_manifest_entries INTEGER,
    rounds_loaded INTEGER,
    shots_loaded  INTEGER,
    notes         TEXT
);
