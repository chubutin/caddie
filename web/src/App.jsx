import { useEffect, useState } from 'react'
import { get, fmt } from './api'
import Scorecard from './components/Scorecard'
import {
  TrendChart, ClubRange, OrdinalStack, LateralChart, ScoreByDistance,
  ProbChart, PairedChart, PUTT_SEGMENTS, ORD_SEGMENTS,
} from './components/charts'

function useApi(path, deps = []) {
  const [s, set] = useState({ loading: true, data: null, error: null })
  useEffect(() => {
    let alive = true
    set({ loading: true, data: null, error: null })
    get(path)
      .then((d) => alive && set({ loading: false, data: d, error: null }))
      .catch((e) => alive && set({ loading: false, data: null, error: e.message }))
    return () => { alive = false }
  }, deps) // eslint-disable-line react-hooks/exhaustive-deps
  return s
}

function Panel({ state, children, empty = 'Todavía no hay datos para esto.' }) {
  if (state.loading) return <p className="msg">Cargando</p>
  if (state.error) return <p className="msg err">No se pudo leer: {state.error}</p>
  if (!state.data || (Array.isArray(state.data) && !state.data.length))
    return <p className="msg">{empty}</p>
  return children(state.data)
}

function Block({ title, note, framed = true, children }) {
  return (
    <section className="block">
      {title && <h2>{title}</h2>}
      {note && <p className="note">{note}</p>}
      <div className={framed ? 'framed plot' : 'plot'}>{children}</div>
    </section>
  )
}

function Table({ cols, rows }) {
  return (
    <div className="scroll">
      <table>
        <thead><tr>{cols.map((c) => <th key={c.k}>{c.h}</th>)}</tr></thead>
        <tbody>
          {rows.map((r, i) => (
            <tr key={i}>{cols.map((c) => <td key={c.k}>{c.f ? c.f(r) : (r[c.k] ?? '–')}</td>)}</tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

const Fig = ({ v, k }) => (
  <div><div className="v fig">{v}</div><div className="k">{k}</div></div>
)

const signed = (v) => (v === null || v === undefined ? '–' : v > 0 ? `+${v}` : `${v}`)
// Garmin guarda en `model` el nombre del JUEGO, no el del palo: ocho hierros
// del mismo set llegan todos como "Ping 430". El nombre sale de la ranura
// (clubTypeId); el set va como subtitulo SOLO cuando dos palos comparten
// ranura — que es lo que pasa al cambiar de juego: el Ping 430 5 retirado y
// el Srixon 5 nuevo conviven en "Hierro 5".
function withClubNames(rows) {
  const perSlot = {}
  for (const c of rows) {
    const k = c.slot || c.label
    if (k) perSlot[k] = (perSlot[k] || 0) + 1
  }
  return rows.map((c) => {
    const label = c.label
      || (c.name ? `${c.name}°` : null)
      || c.model
      || `palo ${c.club_id || c.id}`
    const slotShared = (perSlot[c.slot || c.label] || 0) > 1
    return {
      ...c,
      club_label: label,
      club_sub: slotShared && c.model ? c.model : null,
    }
  })
}
const range = (d) => `${d.from_yd}-${d.to_yd} yd`

/* ================================================================== vistas */

function Resumen() {
  const h = useApi('/api/hero')
  const ov = useApi('/api/overview')
  const par = useApi('/api/scoring/by-par')
  const tr = useApi('/api/trend')

  return (
    <>
      <h1 className="page">Tu última vuelta</h1>
      <Panel state={h}>{(d) => {
        const r = d.round
        const delta = d.avg_vs_par_10 !== null ? r.score_vs_par - Number(d.avg_vs_par_10) : null
        return (
          <>
            <p className="page-note">
              {r.course}, {new Date(r.started_at).toLocaleDateString('es-AR',
                { day: 'numeric', month: 'long', year: 'numeric' })}
            </p>
            <div className="headline">
              <div className="big fig-xl">{signed(r.score_vs_par)}<small>&nbsp;sobre el par</small></div>
              <p className="caption">
                {r.strokes} golpes para un par {r.par}.{' '}
                {delta === null ? '' : delta < 0
                  ? `${Math.abs(delta).toFixed(1)} golpes mejor que tu promedio de las últimas diez.`
                  : `${delta.toFixed(1)} golpes por encima de tu promedio de las últimas diez.`}
              </p>
            </div>
            <div className="framed plot" style={{ marginBottom: 14 }}>
              <Scorecard holes={d.holes} />
            </div>
            <div className="figrow" style={{ marginBottom: 38 }}>
              <Fig v={r.putts ?? '–'} k="putts" />
              <Fig v={r.greens_recorded ? `${r.greens_in_regulation}/${r.greens_recorded}` : '–'} k="greens en regulación" />
              <Fig v={r.fairways_recorded ? `${r.fairways_hit}/${r.fairways_recorded}` : '–'} k="calles" />
            </div>
          </>
        )
      }}</Panel>

      <Panel state={ov}>{(d) => (
        <section className="block">
          <h2>Todo lo que llevas registrado</h2>
          <p className="note">
            Desde {new Date(d.first_round).getFullYear()}, bajado del reloj y guardado entero.
          </p>
          <div className="figrow">
            <Fig v={d.rounds} k="vueltas" />
            <Fig v={d.full_rounds} k="de 18 completas" />
            <Fig v={fmt(d.avg_18, 1)} k="golpes promedio" />
            <Fig v={d.best_18} k="tu mejor vuelta" />
            <Fig v={d.shots.toLocaleString('es-AR')} k="tiros con GPS" />
            <Fig v={d.courses} k="canchas" />
          </div>
        </section>
      )}</Panel>

      <Block title="Cómo viene el score"
             note="Cada punto es una vuelta de 18 completa; la línea es el promedio de las últimas diez.">
        <Panel state={tr}>{(d) => <TrendChart data={d} />}</Panel>
      </Block>

      <Block title="Cómo te va según el par"
             note="El yardaje sale de tus propios tiros: Garmin no publica el largo de los hoyos.">
        <Panel state={par}>{(d) => (
          <OrdinalStack data={d} segments={ORD_SEGMENTS}
            rowLabel={(r) => `Par ${r.par}`}
            caption={(r) => `${r.holes} hoyos, ${r.avg_length_yd} yardas de promedio, ${r.avg_strokes} golpes`} />
        )}</Panel>
      </Block>
    </>
  )
}

function Rondas() {
  const rounds = useApi('/api/rounds?limit=100')
  return (
    <>
      <h1 className="page">Vueltas</h1>
      <p className="page-note">Las últimas cien, de la más reciente a la más vieja.</p>
      <Block framed={false}>
        <Panel state={rounds}>{(d) => (
          <Table rows={d} cols={[
            { k: 'started_at', h: 'Fecha', f: (r) => r.started_at.slice(0, 10) },
            { k: 'course', h: 'Cancha' },
            { k: 'holes_completed', h: 'Hoyos' },
            { k: 'strokes', h: 'Golpes' },
            { k: 'score_vs_par', h: 'Sobre el par', f: (r) => signed(r.score_vs_par) },
            { k: 'putts', h: 'Putts' },
            { k: 'gir', h: 'Greens', f: (r) => r.greens_recorded ? `${r.greens_in_regulation}/${r.greens_recorded}` : '–' },
            { k: 'fw', h: 'Calles', f: (r) => r.fairways_recorded ? `${r.fairways_hit}/${r.fairways_recorded}` : '–' },
            { k: 'ok', h: '', f: (r) => !r.is_complete ? <span className="tag">incompleta</span> : '' },
          ]} />
        )}</Panel>
      </Block>
    </>
  )
}

function Palos() {
  const [soloBolsa, setSoloBolsa] = useState(false)
  const clubs = useApi(`/api/clubs?solo_bolsa_actual=${soloBolsa}`, [soloBolsa])
  const prep = withClubNames
  return (
    <>
      <h1 className="page">Palos</h1>
      <p className="page-note">
        Qué distancia pegás realmente con cada uno, medido tiro por tiro. Los
        palos retirados siguen acá: sus tiros son historia real y sacarlos
        falsearía las temporadas en que los jugaste.
      </p>
      <div className="switch" style={{ marginBottom: 18 }}>
        {[[false, 'Toda la bolsa'], [true, 'Solo los que juego hoy']].map(([v, l]) => (
          <button key={String(v)} aria-current={soloBolsa === v}
                  onClick={() => setSoloBolsa(v)}>{l}</button>
        ))}
      </div>
      <Block title="Distancia por palo"
             note="La mediana con su rango intercuartil, sin putts. AutoShot no siempre identifica el palo, así que la muestra es menor que el total de golpes.">
        <Panel state={clubs}>{(d) => <ClubRange data={prep(d)} />}</Panel>
      </Block>
      <Block title="Tus números contra los de Garmin" framed={false}
             note="Garmin publica un promedio; acá calculamos la mediana sobre los tiros crudos. Cuando difieren, la mediana manda: el promedio se arrastra con topazos y tiros raros. Los palos sin nombre se mapean en config/club_labels.json.">
        <Panel state={clubs}>{(d) => (
          <Table rows={prep(d)} cols={[
            { k: 'club_label', h: 'Palo', f: (r) => (
              <>
                {r.club_label}
                {r.club_sub && <span style={{ color: 'var(--ink-3)' }}> · {r.club_sub}</span>}
                {r.retired && <span className="tag" style={{ marginLeft: 8 }}>retirado</span>}
              </>
            )},
            { k: 'shots_count', h: 'Tiros' },
            { k: 'shots_measured', h: 'Medidos' },
            { k: 'garmin_avg_yd', h: 'Promedio Garmin' },
            { k: 'median_yd', h: 'Mediana' },
            { k: 'p25_yd', h: 'p25' },
            { k: 'p75_yd', h: 'p75' },
            { k: 'max_recent_yd', h: 'Máxima reciente' },
          ]} />
        )}</Panel>
      </Block>
    </>
  )
}

function Dispersion() {
  const [tipo, setTipo] = useState('TEE')
  const lat = useApi(`/api/dispersion/lateral?shot_type=${tipo}`, [tipo])
  const prep = withClubNames
  return (
    <>
      <h1 className="page">Dispersión</h1>
      <p className="page-note">
        Cuánto te vas a izquierda o derecha de la línea de juego. El punto es tu
        sesgo; la barra, dónde cae el 80% central de tus tiros.
      </p>
      <div className="switch" style={{ marginBottom: 18 }}>
        {[['TEE', 'Tiros de salida'], ['APPROACH', 'Approach']].map(([k, l]) => (
          <button key={k} aria-current={tipo === k} onClick={() => setTipo(k)}>{l}</button>
        ))}
      </div>
      <Block note="La línea de referencia es el centro del green: el pinPosition que guarda Garmin es un punto fijo del mapa, no la bandera del día. En los tiros de salida se excluyen los doglegs, donde apuntar al green no significa nada.">
        <Panel state={lat}>{(d) => <LateralChart data={prep(d)} />}</Panel>
      </Block>
      <Block title="Detalle" framed={false}>
        <Panel state={lat}>{(d) => (
          <Table rows={prep(d)} cols={[
            { k: 'club_label', h: 'Palo', f: (r) => (
              <>{r.club_label}{r.club_sub && <span style={{ color: 'var(--ink-3)' }}> · {r.club_sub}</span>}</>
            )},
            { k: 'shots', h: 'Tiros' },
            { k: 'bias_yd', h: 'Sesgo', f: (r) => signed(r.bias_yd) },
            { k: 'spread_yd', h: 'Apertura' },
            { k: 'pct_izq', h: 'Izquierda' },
            { k: 'pct_centro', h: 'Centro' },
            { k: 'pct_der', h: 'Derecha' },
          ]} />
        )}</Panel>
      </Block>
    </>
  )
}

function Estrategia() {
  const [par, setPar] = useState(4)
  const out = useApi(`/api/analysis/outcomes?par=${par}&bucket_yd=25`, [par])
  const fw = useApi(`/api/analysis/fairway?par=${par >= 4 ? par : 4}&bucket_yd=50`, [par])
  const tee = useApi(`/api/analysis/tee-club?par=${par}`, [par])
  const leaks = useApi('/api/analysis/leaks')

  return (
    <>
      <h1 className="page">Estrategia</h1>
      <p className="page-note">
        Dónde perdés golpes y qué podés cambiar. Todo viene con el tamaño de la
        muestra y su intervalo de confianza.
      </p>

      <Block title="Dónde se te van los golpes" framed={false}
             note="Ordenado por golpes perdidos en total, no por promedio: un tramo donde perdés poco pero jugás muchísimo pesa más en el score final que uno catastrófico y raro.">
        <Panel state={leaks}>{(d) => (
          <Table rows={d} cols={[
            { k: 'segmento', h: 'Segmento' },
            { k: 'hoyos', h: 'Hoyos' },
            { k: 'golpes_perdidos', h: 'Golpes perdidos' },
            { k: 'por_hoyo', h: 'Por hoyo' },
            { k: 'pct_par_o_mejor', h: 'Par o mejor' },
            { k: 'pct_doble_o_peor', h: 'Doble o peor' },
            { k: 'pct_gir', h: 'Greens' },
            { k: 'avg_putts', h: 'Putts' },
            { k: 'penalties_por_hoyo', h: 'Penalidades' },
          ]} />
        )}</Panel>
      </Block>

      <div className="switch" style={{ marginBottom: 20 }}>
        {[3, 4, 5].map((p) => (
          <button key={p} aria-current={par === p} onClick={() => setPar(p)}>Par {p}</button>
        ))}
      </div>

      <Block title={`Chance de par o mejor en los par ${par}, según el largo`}
             note="El punto es la estimación; la barra es el intervalo del 95%. Si dos barras se solapan, la muestra no sostiene la diferencia.">
        <Panel state={out}>{(d) => <ProbChart data={d} labelOf={range} />}</Panel>
      </Block>

      <Block title="Cómo termina cada tramo"
             note="Lo mismo, completo: qué parte termina en par o mejor, en bogey, y en doble o peor.">
        <Panel state={out}>{(d) => (
          <OrdinalStack data={d} segments={ORD_SEGMENTS} rowLabel={range}
            caption={(r) => `${r.n} hoyos, greens ${r.pct_gir}%, calles ${r.pct_fairway ?? '–'}%, ${r.avg_strokes} golpes`} />
        )}</Panel>
      </Block>

      {par >= 4 && (
        <Block title="Cuánto te cambia pegar la calle"
               note="Si en los hoyos largos pegar la calle casi no mueve la aguja, conviene darle; si la mueve mucho, conviene asegurar la salida.">
          <Panel state={fw}>{(d) => <PairedChart data={d} labelOf={range} />}</Panel>
        </Block>
      )}

      <Block title={`Con qué palo salís en los par ${par}`} framed={false}
             note="Esto no es un experimento: elegís el palo según el hoyo, así que los palos más cortos aparecen en hoyos más cortos. La columna del largo medio está para que veas esa selección antes de comparar.">
        <Panel state={tee} empty="No hay salidas con palo identificado para este par.">{(d) => (
          <Table rows={withClubNames(d)} cols={[
            { k: 'club_label', h: 'Palo' },
            { k: 'n', h: 'Hoyos' },
            { k: 'avg_hole_yd', h: 'Largo medio' },
            { k: 'avg_tee_yd', h: 'Salida media' },
            { k: 'pct_fairway', h: 'Calles' },
            { k: 'pct_gir', h: 'Greens' },
            { k: 'pct_par_o_mejor', h: 'Par o mejor', f: (r) => `${r.pct_par_o_mejor}% ±${r.par_o_mejor_ci}` },
            { k: 'avg_vs_par', h: 'Sobre el par' },
          ]} />
        )}</Panel>
      </Block>
    </>
  )
}

function Distancia() {
  const d = useApi('/api/scoring/by-distance?bucket_yd=25')
  return (
    <>
      <h1 className="page">Largo del hoyo</h1>
      <p className="page-note">
        Golpes sobre el par por tramo de yardaje. Solo tramos con diez hoyos o más.
      </p>
      <Block framed={false}>
        <Panel state={d}>{(x) => <ScoreByDistance data={x} />}</Panel>
      </Block>
    </>
  )
}

function Putting() {
  const byPar = useApi('/api/putting')
  const tr = useApi('/api/putting/trend')
  return (
    <>
      <h1 className="page">Putting</h1>
      <p className="page-note">
        Cantidad de putts, de la tarjeta. No hay métricas de distancia: cuando se
        miden, el porcentaje de embocados sale plano en 50% desde cero hasta
        veinte yardas, y eso es imposible. La posición de la bola en el green no
        tiene la precisión necesaria.
      </p>
      <Block title="Putts por hoyo">
        <Panel state={byPar}>{(d) => (
          <OrdinalStack data={d} segments={PUTT_SEGMENTS}
            rowLabel={(r) => `Par ${r.par}`}
            caption={(r) => `${r.holes} hoyos, ${r.avg_putts} putts de promedio, greens en regulación ${r.pct_gir}%`} />
        )}</Panel>
      </Block>
      <Block title="Putts por vuelta de 18">
        <Panel state={tr}>{(d) => (
          <TrendChart data={d} valueKey="putts" rollingKey="rolling_putts"
                      tickStep={5} prefix="" label="putts" />
        )}</Panel>
      </Block>
      <Block title="Putts y greens en regulación" framed={false}
             note="Cuando pegás el green en regulación quedás más lejos del hoyo y putteás más. Que la columna con greens sea mayor es lo esperable, no un problema.">
        <Panel state={byPar}>{(d) => (
          <Table rows={d} cols={[
            { k: 'par', h: 'Par', f: (r) => `Par ${r.par}` },
            { k: 'holes', h: 'Hoyos' },
            { k: 'avg_putts', h: 'Putts' },
            { k: 'pct_gir', h: 'Greens en regulación' },
            { k: 'putts_con_gir', h: 'Putts con green' },
            { k: 'putts_sin_gir', h: 'Putts sin green' },
            { k: 'pct_3_o_mas', h: 'Tres putts o más' },
          ]} />
        )}</Panel>
      </Block>
    </>
  )
}

function Canchas() {
  const courses = useApi('/api/courses')
  const [sel, setSel] = useState(null)
  const holes = useApi(sel ? `/api/courses/${sel}/holes` : '/api/health', [sel])
  return (
    <>
      <h1 className="page">Canchas</h1>
      <p className="page-note">
        Agrupadas por su identificador de Garmin: el nombre que devuelve viene
        sucio y repite el mismo club con varios strings. El largo está
        reconstruido de tus tiros.
      </p>
      <Block framed={false}>
        <Panel state={courses}>{(d) => (
          <Table rows={d} cols={[
            { k: 'name', h: 'Cancha', f: (r) => (
              <button className="linklike" onClick={() => setSel(r.course_global_id)}>{r.name}</button>
            )},
            { k: 'city', h: 'Ciudad' },
            { k: 'rounds', h: 'Vueltas' },
            { k: 'round_par', h: 'Par' },
            { k: 'length_yd', h: 'Largo' },
            { k: 'avg_18', h: 'Promedio' },
          ]} />
        )}</Panel>
      </Block>
      {sel && (
        <Block title="Hoyo por hoyo" framed={false}
               note="El largo va del tee al green, mediana sobre todas tus vueltas. La forma compara el corredor real contra la línea recta, calibrada contra los par 3, donde no puede haber dogleg.">
          <Panel state={holes} empty="Todavía no hay perfil de esta cancha.">{(d) => (
            <Table rows={d} cols={[
              { k: 'hole_number', h: 'Hoyo' },
              { k: 'par', h: 'Par' },
              { k: 'length_yd', h: 'Largo' },
              { k: 'p10_yd', h: 'p10' },
              { k: 'p90_yd', h: 'p90' },
              { k: 'shape', h: 'Forma', f: (r) => r.shape ? <span className="tag">{r.shape}</span> : '–' },
              { k: 'n_rounds', h: 'Vueltas' },
              { k: 'avg_strokes', h: 'Golpes' },
              { k: 'avg_vs_par', h: 'Sobre el par' },
            ]} />
          )}</Panel>
        </Block>
      )}
    </>
  )
}

function Calidad() {
  const dq = useApi('/api/data-quality')
  return (
    <>
      <h1 className="page">Calidad de los datos</h1>
      <p className="page-note">
        Importa para leer todo lo demás. AutoShot captura entre el 80 y el 90 por
        ciento de los golpes sin putt. Los putts con GPS existían solo con
        sensores de palo: se usaron hasta 2025 y en 2026 no hay ninguno.
      </p>
      <Block framed={false}>
        <Panel state={dq}>{(d) => (
          <Table rows={d} cols={[
            { k: 'year', h: 'Año' },
            { k: 'rounds', h: 'Vueltas' },
            { k: 'strokes', h: 'Golpes' },
            { k: 'putts', h: 'Putts' },
            { k: 'shots_non_putt', h: 'Tiros capturados' },
            { k: 'pct_capture', h: 'Captura' },
            { k: 'pct_with_club', h: 'Con palo' },
            { k: 'shots_putt', h: 'Putts con GPS' },
            { k: 'pct_sensor', h: 'Con sensor' },
          ]} />
        )}</Panel>
      </Block>
    </>
  )
}

const TABS = [
  ['Resumen', Resumen],
  ['Vueltas', Rondas],
  ['Palos', Palos],
  ['Dispersión', Dispersion],
  ['Largo del hoyo', Distancia],
  ['Estrategia', Estrategia],
  ['Putting', Putting],
  ['Canchas', Canchas],
  ['Calidad', Calidad],
]

export default function App() {
  const [tab, setTab] = useState(0)
  const View = TABS[tab][1]
  return (
    <div className="shell">
      <aside className="rail">
        <div className="mark">
          <b>Poletti</b>
          <span>Copa Classic · estadísticas</span>
        </div>
        <nav>
          {TABS.map(([name], i) => (
            <button key={name} aria-current={i === tab} onClick={() => setTab(i)}>{name}</button>
          ))}
        </nav>
      </aside>
      <main><View /></main>
    </div>
  )
}
