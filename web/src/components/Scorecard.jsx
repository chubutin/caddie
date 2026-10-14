/* Tarjeta de golf: circulo = bajo par, cuadrado = sobre par. Es la convencion
   de papel de toda la vida; no hace falta explicarla. */

function cls(vsPar, strokes) {
  if (strokes === null || strokes === undefined) return 'blank'
  if (vsPar <= -2) return 'eagle'
  if (vsPar === -1) return 'birdie'
  if (vsPar === 1) return 'bogey'
  if (vsPar >= 2) return 'dbl'
  return ''
}

export default function Scorecard({ holes }) {
  const front = holes.filter((h) => h.hole_number <= 9)
  const back = holes.filter((h) => h.hole_number > 9)
  const sum = (hs, k) => hs.reduce((a, h) => a + (Number(h[k]) || 0), 0)

  const Col = ({ h }) => (
    <div className="sc-col">
      <span className="sc-hole">{h.hole_number}</span>
      <span className={`sc-box ${cls(h.score_vs_par, h.strokes)}`}>{h.strokes ?? '–'}</span>
      <span className="sc-par">{h.par}</span>
    </div>
  )
  const Total = ({ label, hs }) => (
    <div className="sc-col" style={{ minWidth: 44 }}>
      <span className="sc-hole">{label}</span>
      <span className="sc-box" style={{ fontVariationSettings: "'wdth' 108, 'wght' 700" }}>
        {sum(hs, 'strokes')}
      </span>
      <span className="sc-par">{sum(hs, 'par')}</span>
    </div>
  )

  return (
    <div>
      <div className="scorecard">
        {front.map((h) => <Col key={h.hole_number} h={h} />)}
        <Total label="ida" hs={front} />
        <div className="sc-sep" />
        {back.map((h) => <Col key={h.hole_number} h={h} />)}
        <Total label="vta" hs={back} />
        <div className="sc-sep" />
        <Total label="tot" hs={holes} />
      </div>
      <div className="sc-legend">
        <span><i className="c" />bajo par</span>
        <span><i className="s" />sobre par</span>
        <span>sin marca: par</span>
        <span style={{ marginLeft: 'auto' }}>el número chico es el par</span>
      </div>
    </div>
  )
}
