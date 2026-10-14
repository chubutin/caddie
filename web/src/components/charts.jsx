import { useState } from 'react'
import { num, fmt } from '../api'

/* Ejes y grilla recesivos, marcas finas, tooltip en hover: ver guia de viz. */

const PAD = { t: 14, r: 16, b: 28, l: 38 }

function useHover() {
  const [hover, setHover] = useState(null)
  return [hover, setHover]
}

function Tooltip({ x, y, lines, width }) {
  const w = 150
  const flip = x + w + 12 > width
  return (
    <g transform={`translate(${flip ? x - w - 10 : x + 10}, ${Math.max(y - 10, 4)})`}>
      <rect width={w} height={16 + lines.length * 15} rx="7"
            fill="var(--paper-raised)" stroke="var(--rule)" />
      {lines.map((l, i) => (
        <text key={i} x="10" y={20 + i * 15} fontSize="11.5"
              fill={i === 0 ? 'var(--ink)' : 'var(--ink-2)'}>
          {l}
        </text>
      ))}
    </g>
  )
}

/* ---------------------------------------------------------------- tendencia */
/* Una sola serie (tu score): puntos = rondas, linea = media movil.
   Sin caja de leyenda — el titulo nombra la serie. */
export function TrendChart({
  data, height = 260, valueKey = 'score_vs_par', rollingKey = 'rolling_vs_par',
  tickStep = 10, prefix = '+', label = 'golpes', decimals = 0,
}) {
  const [hover, setHover] = useHover()
  const W = 880, H = height
  if (!data.length) return <p className="msg">Sin rondas completas todavia.</p>

  const xs = data.map((d) => new Date(d.date).getTime())
  const ys = data.map((d) => num(d[valueKey]))
  const x0 = Math.min(...xs), x1 = Math.max(...xs)
  const y0 = Math.min(...ys) - 2, y1 = Math.max(...ys) + 2
  const px = (t) => PAD.l + ((t - x0) / (x1 - x0 || 1)) * (W - PAD.l - PAD.r)
  const py = (v) => PAD.t + (1 - (v - y0) / (y1 - y0 || 1)) * (H - PAD.t - PAD.b)

  const rolling = data.filter((d) => d[rollingKey] !== null)
  const path = rolling
    .map((d, i) => `${i ? 'L' : 'M'}${px(new Date(d.date).getTime()).toFixed(1)},${py(num(d[rollingKey])).toFixed(1)}`)
    .join('')

  const ticks = []
  for (let v = Math.ceil(y0 / tickStep) * tickStep; v <= y1; v += tickStep) ticks.push(v)
  const years = [...new Set(data.map((d) => d.date.slice(0, 4)))]

  return (
    <svg viewBox={`0 0 ${W} ${H}`} width="100%" role="img"
         aria-label="Score sobre el par por ronda, con media movil">
      {ticks.map((v) => (
        <g key={v}>
          <line x1={PAD.l} x2={W - PAD.r} y1={py(v)} y2={py(v)} stroke="var(--grid)" strokeWidth="1" />
          <text x={PAD.l - 8} y={py(v) + 4} fontSize="11" textAnchor="end" fill="var(--ink-3)">
            {prefix}{v}
          </text>
        </g>
      ))}
      {years.map((y) => {
        const t = new Date(`${y}-01-01`).getTime()
        if (t < x0 || t > x1) return null
        return (
          <text key={y} x={px(t)} y={H - 8} fontSize="11" textAnchor="middle" fill="var(--ink-3)">
            {y}
          </text>
        )
      })}
      {data.map((d, i) => {
        const cx = px(new Date(d.date).getTime()), cy = py(num(d[valueKey]))
        return (
          <circle key={i} cx={cx} cy={cy} r={hover === i ? 5 : 3.2}
                  fill="var(--series-1)" fillOpacity={hover === i ? 1 : 0.32}
                  stroke="var(--paper-raised)" strokeWidth="1.5"
                  onMouseEnter={() => setHover(i)} onMouseLeave={() => setHover(null)} />
        )
      })}
      <path d={path} fill="none" stroke="var(--series-1)" strokeWidth="2"
            strokeLinejoin="round" strokeLinecap="round" />
      {hover !== null && (
        <Tooltip width={W}
          x={px(new Date(data[hover].date).getTime())}
          y={py(num(data[hover][valueKey]))}
          lines={[
            data[hover].date,
            `${fmt(data[hover][valueKey], decimals)} ${label}`,
            `media movil ${fmt(data[hover][rollingKey], 1)}`,
          ]} />
      )}
    </svg>
  )
}

/* ------------------------------------------------- distancias por palo */
/* Rango p25-p75 + mediana. Una sola serie: sin leyenda. */
export function ClubRange({ data }) {
  const [hover, setHover] = useHover()
  const rows = data.filter((d) => d.median_yd !== null)
  if (!rows.length) return <p className="msg">Sin tiros con palo asignado.</p>

  const W = 880, rowH = 30, H = rows.length * rowH + PAD.t + PAD.b
  const L = 150
  const max = Math.max(...rows.map((d) => num(d.p75_yd) || 0)) * 1.08
  const px = (v) => L + (v / max) * (W - L - 56)

  return (
    <svg viewBox={`0 0 ${W} ${H}`} width="100%" role="img"
         aria-label="Distancia por palo: rango intercuartil y mediana, en yardas">
      {[0, 50, 100, 150, 200, 250].filter((v) => v <= max).map((v) => (
        <g key={v}>
          <line x1={px(v)} x2={px(v)} y1={PAD.t - 6} y2={H - PAD.b + 2}
                stroke="var(--grid)" strokeWidth="1" />
          <text x={px(v)} y={H - 10} fontSize="11" textAnchor="middle" fill="var(--ink-3)">{v}</text>
        </g>
      ))}
      <text x={W - 50} y={H - 10} fontSize="11" fill="var(--ink-3)">yd</text>
      {rows.map((d, i) => {
        const y = PAD.t + i * rowH + rowH / 2
        const a = px(num(d.p25_yd)), b = px(num(d.p75_yd)), m = px(num(d.median_yd))
        const on = hover === i
        return (
          <g key={d.id} onMouseEnter={() => setHover(i)} onMouseLeave={() => setHover(null)}>
            <rect x="0" y={y - rowH / 2} width={W} height={rowH} fill="transparent" />
            <text x={L - 12} y={d.club_sub ? y : y + 4} fontSize="12.5"
                  textAnchor="end" fill="var(--ink)"
                  opacity={d.retired ? 0.6 : 1}>
              {d.club_label}
            </text>
            {d.club_sub && (
              <text x={L - 12} y={y + 12} fontSize="10.5" textAnchor="end" fill="var(--ink-3)">
                {d.club_sub}
              </text>
            )}
            <rect x={a} y={y - 5} width={Math.max(b - a, 2)} height="10" rx="4"
                  fill="var(--series-1)" fillOpacity={on ? 0.42 : 0.26}
                  opacity={d.retired ? 0.55 : 1} />
            <circle cx={m} cy={y} r={on ? 6 : 4.5} fill="var(--series-1)"
                    stroke="var(--paper-raised)" strokeWidth="2"
                    opacity={d.retired ? 0.55 : 1} />
            <text x={b + 10} y={y + 4} fontSize="12" fill="var(--ink-2)">{d.median_yd}</text>
          </g>
        )
      })}
      {hover !== null && (
        <Tooltip width={W} x={px(num(rows[hover].median_yd))}
          y={PAD.t + hover * rowH + 6}
          lines={[
            rows[hover].club_label,
            `mediana ${rows[hover].median_yd} yd`,
            `p25-p75 ${rows[hover].p25_yd}-${rows[hover].p75_yd} yd`,
            `${rows[hover].shots_measured} tiros medidos`,
          ]} />
      )}
    </svg>
  )
}

/* --------------------------------------------- distribucion por par */
/* Rampa ordinal de un solo tono: claro = mejor, oscuro = peor.
   Validada con validate_palette.js --ordinal en light y dark. */
export const ORD_SEGMENTS = [
  { key: 'pct_par_o_mejor', label: 'Par o mejor', color: 'var(--ord-1)', ink: 'var(--on-ord-1)' },
  { key: 'pct_bogey',       label: 'Bogey',       color: 'var(--ord-2)', ink: 'var(--on-ord-2)' },
  { key: 'pct_doble_o_peor',label: 'Doble o peor',color: 'var(--ord-3)', ink: 'var(--on-ord-3)' },
]

export function OrdinalStack({ data, segments = ORD_SEGMENTS, rowLabel, caption }) {
  const W = 880, barH = 42, gap = 16
  const H = data.length * (barH + gap) + 20
  const L = 86, R = 20

  return (
    <>
      <div className="legend">
        {segments.map((s) => (
          <span key={s.key}><i style={{ background: s.color }} />{s.label}</span>
        ))}
      </div>
      <svg viewBox={`0 0 ${W} ${H}`} width="100%" role="img"
           aria-label="Distribucion de resultados por par">
        {data.map((d, i) => {
          const y = i * (barH + gap) + 8
          let acc = 0
          return (
            <g key={d.par}>
              <text x={L - 14} y={y + barH / 2 + 5} fontSize="13" textAnchor="end"
                    fill="var(--ink)">{rowLabel(d)}</text>
              {segments.map((s) => {
                const pct = num(d[s.key])
                const w = (pct / 100) * (W - L - R)
                const x = L + (acc / 100) * (W - L - R)
                acc += pct
                return (
                  <g key={s.key}>
                    {/* 2px de surface entre segmentos */}
                    <rect x={x} y={y} width={Math.max(w - 2, 0)} height={barH} rx="4" fill={s.color} />
                    {w > 54 && (
                      <text x={x + w / 2 - 1} y={y + barH / 2 + 5} fontSize="12.5"
                            textAnchor="middle" fill={s.ink}>{pct}%</text>
                    )}
                  </g>
                )
              })}
              <text x={L} y={y + barH + 13} fontSize="11" fill="var(--ink-3)">
                {caption(d)}
              </text>
            </g>
          )
        })}
      </svg>
    </>
  )
}


/* ------------------------------------------------ dispersion lateral */
/* Rango p10-p90 centrado en la linea de juego, con la mediana (el sesgo).
   Una sola serie: la polaridad la marca el eje cero, no el color. */
export function LateralChart({ data }) {
  const [hover, setHover] = useHover()
  if (!data.length) return <p className="msg">Sin tiros suficientes.</p>
  const W = 880, rowH = 30, H = data.length * rowH + 44
  const L = 160
  const max = Math.max(...data.map((d) => Math.max(Math.abs(num(d.p10_yd)), Math.abs(num(d.p90_yd))))) * 1.1
  const mid = L + (W - L - 40) / 2
  const px = (v) => mid + (v / max) * ((W - L - 40) / 2)

  return (
    <svg viewBox={`0 0 ${W} ${H}`} width="100%" role="img"
         aria-label="Desvio lateral por palo, en yardas">
      {[-max, -max / 2, 0, max / 2, max].map((v, i) => (
        <g key={i}>
          <line x1={px(v)} x2={px(v)} y1="8" y2={H - 28}
                stroke={v === 0 ? 'var(--ink-3)' : 'var(--grid)'}
                strokeWidth={v === 0 ? 1.5 : 1} />
          <text x={px(v)} y={H - 12} fontSize="11" textAnchor="middle" fill="var(--ink-3)">
            {v === 0 ? '0' : `${v > 0 ? '+' : ''}${v.toFixed(0)}`}
          </text>
        </g>
      ))}
      <text x={L + 4} y={H - 12} fontSize="11" fill="var(--ink-3)">← izquierda</text>
      <text x={W - 40} y={H - 12} fontSize="11" textAnchor="end" fill="var(--ink-3)">derecha →</text>
      {data.map((d, i) => {
        const y = 16 + i * rowH + rowH / 2
        const a = px(num(d.p10_yd)), b = px(num(d.p90_yd)), m = px(num(d.bias_yd))
        const on = hover === i
        return (
          <g key={d.club_id} onMouseEnter={() => setHover(i)} onMouseLeave={() => setHover(null)}>
            <rect x="0" y={y - rowH / 2} width={W} height={rowH} fill="transparent" />
            <text x={L - 12} y={y + 4} fontSize="12.5" textAnchor="end" fill="var(--ink)">
              {d.club_label}
            </text>
            <rect x={a} y={y - 5} width={Math.max(b - a, 2)} height="10" rx="4"
                  fill="var(--series-1)" fillOpacity={on ? 0.42 : 0.26} />
            <circle cx={m} cy={y} r={on ? 6 : 4.5} fill="var(--series-1)"
                    stroke="var(--paper-raised)" strokeWidth="2" />
          </g>
        )
      })}
      {hover !== null && (
        <Tooltip width={W} x={px(num(data[hover].bias_yd))} y={16 + hover * rowH}
          lines={[
            data[hover].club_label,
            `sesgo ${data[hover].bias_yd > 0 ? '+' : ''}${data[hover].bias_yd} yd`,
            `p10-p90: ${data[hover].p10_yd} a ${data[hover].p90_yd} yd`,
            `${data[hover].pct_izq}% izq · ${data[hover].pct_centro}% centro · ${data[hover].pct_der}% der`,
            `${data[hover].shots} tiros`,
          ]} />
      )}
    </svg>
  )
}

/* -------------------------------------- score vs largo del hoyo */
/* Small multiples: un panel por par. Una serie por panel, sin leyenda. */
export function ScoreByDistance({ data }) {
  const pars = [...new Set(data.map((d) => d.par))].sort()
  return (
    <div style={{ display: 'grid', gap: 18 }}>
      {pars.map((par) => {
        const rows = data.filter((d) => d.par === par)
        const W = 860, H = 150, PADL = 34, PADB = 34
        const max = Math.max(...rows.map((r) => num(r.avg_vs_par))) * 1.15
        const bw = (W - PADL - 16) / rows.length
        return (
          <div key={par}>
            <div style={{ fontSize: 13, marginBottom: 4 }}>
              Par {par} <span style={{ color: 'var(--ink-3)' }}>
                · {rows.reduce((a, r) => a + Number(r.holes), 0)} hoyos
              </span>
            </div>
            <svg viewBox={`0 0 ${W} ${H}`} width="100%" role="img"
                 aria-label={`Golpes sobre el par en hoyos par ${par}, por tramo de yardaje`}>
              {[0, 1, 2].filter((v) => v <= max).map((v) => (
                <g key={v}>
                  <line x1={PADL} x2={W - 8} y1={H - PADB - (v / max) * (H - PADB - 10)}
                        y2={H - PADB - (v / max) * (H - PADB - 10)}
                        stroke="var(--grid)" strokeWidth="1" />
                  <text x={PADL - 6} y={H - PADB - (v / max) * (H - PADB - 10) + 4}
                        fontSize="10.5" textAnchor="end" fill="var(--ink-3)">+{v}</text>
                </g>
              ))}
              {rows.map((r, i) => {
                const v = num(r.avg_vs_par)
                const h = (v / max) * (H - PADB - 10)
                const x = PADL + i * bw
                return (
                  <g key={i}>
                    <rect x={x + 2} y={H - PADB - h} width={bw - 6} height={h} rx="4"
                          fill="var(--series-1)" />
                    <text x={x + bw / 2} y={H - PADB - h - 5} fontSize="10.5"
                          textAnchor="middle" fill="var(--ink-2)">{r.avg_vs_par}</text>
                    <text x={x + bw / 2} y={H - PADB + 13} fontSize="10"
                          textAnchor="middle" fill="var(--ink-3)">{r.from_yd}</text>
                    <text x={x + bw / 2} y={H - PADB + 25} fontSize="9.5"
                          textAnchor="middle" fill="var(--ink-3)">n={r.holes}</text>
                  </g>
                )
              })}
              <text x={W - 8} y={H - PADB + 13} fontSize="10" textAnchor="end" fill="var(--ink-3)">yd</text>
            </svg>
          </div>
        )
      })}
    </div>
  )
}

export const PUTT_SEGMENTS = [
  { key: 'pct_1_putt',   label: '1 putt',    color: 'var(--ord-1)', ink: 'var(--on-ord-1)' },
  { key: 'pct_2_putts',  label: '2 putts',   color: 'var(--ord-2)', ink: 'var(--on-ord-2)' },
  { key: 'pct_3_o_mas',  label: '3 o mas',   color: 'var(--ord-3)', ink: 'var(--on-ord-3)' },
]

/* ------------------------------------ probabilidad con intervalo (Wilson) */
/* Punto = estimacion, barra = intervalo de 95%. Si dos barras se solapan,
   la diferencia no esta sostenida por la muestra. Una sola serie. */
export function ProbChart({ data, labelOf, valueKey = 'pct_par_o_mejor',
                            loKey = 'par_o_mejor_lo', hiKey = 'par_o_mejor_hi',
                            nKey = 'n', title = 'par o mejor' }) {
  const [hover, setHover] = useHover()
  if (!data.length) return <p className="msg">Sin datos suficientes.</p>
  const W = 880, rowH = 30, H = data.length * rowH + 44, L = 120
  const max = Math.min(100, Math.max(...data.map((d) => num(d[hiKey]))) * 1.15)
  const px = (v) => L + (v / max) * (W - L - 132)

  return (
    <svg viewBox={`0 0 ${W} ${H}`} width="100%" role="img"
         aria-label={`Probabilidad de ${title} con intervalo de confianza`}>
      {[0, 10, 20, 30, 40, 50, 60].filter((v) => v <= max).map((v) => (
        <g key={v}>
          <line x1={px(v)} x2={px(v)} y1="8" y2={H - 28} stroke="var(--grid)" strokeWidth="1" />
          <text x={px(v)} y={H - 12} fontSize="11" textAnchor="middle" fill="var(--ink-3)">{v}%</text>
        </g>
      ))}
      {data.map((d, i) => {
        const y = 16 + i * rowH + rowH / 2
        const lo = px(num(d[loKey])), hi = px(num(d[hiKey])), m = px(num(d[valueKey]))
        const on = hover === i
        return (
          <g key={i} onMouseEnter={() => setHover(i)} onMouseLeave={() => setHover(null)}>
            <rect x="0" y={y - rowH / 2} width={W} height={rowH} fill="transparent" />
            <text x={L - 12} y={y + 4} fontSize="12.5" textAnchor="end" fill="var(--ink)">
              {labelOf(d)}
            </text>
            <line x1={lo} x2={hi} y1={y} y2={y} stroke="var(--series-1)"
                  strokeOpacity={on ? 0.75 : 0.4} strokeWidth="8" strokeLinecap="round" />
            <circle cx={m} cy={y} r={on ? 6 : 4.5} fill="var(--series-1)"
                    stroke="var(--paper-raised)" strokeWidth="2" />
            <text x={W - 118} y={y + 4} fontSize="12.5" fill="var(--ink)"
                  style={{ fontVariationSettings: "'wdth' 102, 'wght' 600" }}>
              {d[valueKey]}%
            </text>
            <text x={W - 6} y={y + 4} fontSize="11" textAnchor="end" fill="var(--ink-3)">
              {d[nKey]} hoyos
            </text>
          </g>
        )
      })}
      {hover !== null && (
        <Tooltip width={W} x={px(num(data[hover][valueKey]))} y={16 + hover * rowH}
          lines={[labelOf(data[hover]),
                  `${data[hover][valueKey]}% ${title}`,
                  `IC 95%: ${data[hover][loKey]}–${data[hover][hiKey]}%`,
                  `${data[hover][nKey]} hoyos`]} />
      )}
    </svg>
  )
}

/* --------------------------------- comparacion pareada (calle vs fuera) */
const PAIR = [
  { key: 'calle', label: 'Pegaste la calle', color: 'var(--series-1)' },
  { key: 'fuera', label: 'Fuera de calle',   color: 'var(--series-2)' },
]

export function PairedChart({ data, labelOf, valueKey = 'pct_par_o_mejor' }) {
  const groups = {}
  for (const d of data) (groups[labelOf(d)] ||= {})[d.resultado_salida] = d
  const keys = Object.keys(groups)
  const W = 880, rowH = 38, H = keys.length * rowH + 48, L = 120
  const all = data.map((d) => num(d[valueKey]))
  const max = Math.max(...all) * 1.2
  const px = (v) => L + (v / max) * (W - L - 90)

  return (
    <>
      <div className="legend">
        {PAIR.map((s) => (
          <span key={s.key}><i style={{ background: s.color }} />{s.label}</span>
        ))}
      </div>
      <svg viewBox={`0 0 ${W} ${H}`} width="100%" role="img"
           aria-label="Par o mejor segun si pegaste la calle, por tramo de yardaje">
        {[0, 10, 20, 30, 40].filter((v) => v <= max).map((v) => (
          <g key={v}>
            <line x1={px(v)} x2={px(v)} y1="8" y2={H - 30} stroke="var(--grid)" strokeWidth="1" />
            <text x={px(v)} y={H - 12} fontSize="11" textAnchor="middle" fill="var(--ink-3)">{v}%</text>
          </g>
        ))}
        {keys.map((k, i) => {
          const y = 14 + i * rowH + rowH / 2
          const a = groups[k].calle, b = groups[k].fuera
          if (!a || !b) return null
          const xa = px(num(a[valueKey])), xb = px(num(b[valueKey]))
          const delta = num(a[valueKey]) - num(b[valueKey])
          return (
            <g key={k}>
              <text x={L - 12} y={y + 4} fontSize="12.5" textAnchor="end" fill="var(--ink)">{k}</text>
              <line x1={Math.min(xa, xb)} x2={Math.max(xa, xb)} y1={y} y2={y}
                    stroke="var(--ink-3)" strokeOpacity="0.35" strokeWidth="2" />
              <circle cx={xb} cy={y} r="6" fill={PAIR[1].color} stroke="var(--paper-raised)" strokeWidth="2" />
              <circle cx={xa} cy={y} r="6" fill={PAIR[0].color} stroke="var(--paper-raised)" strokeWidth="2" />
              <text x={W - 10} y={y + 4} fontSize="12" textAnchor="end" fill="var(--ink-2)">
                {delta > 0 ? '+' : ''}{delta.toFixed(0)} pts
              </text>
              <text x={L} y={y + rowH / 2 + 2} fontSize="10" fill="var(--ink-3)">
                n: {a.n} en calle · {b.n} fuera
              </text>
            </g>
          )
        })}
      </svg>
    </>
  )
}
