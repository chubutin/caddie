import { useEffect, useRef, useState } from 'react'
import { get, post } from '../api'

/* Entrar a Garmin y traer las vueltas nuevas.

   La contraseña se manda una sola vez para acuñar el token OAuth y no se
   guarda en ningún lado: ni en la base, ni en el browser, ni en los logs.
   Lo único que queda es el token del lado del servidor. */

export default function Datos() {
  const [auth, setAuth] = useState(null)
  const [form, setForm] = useState({ email: '', password: '' })
  const [mfa, setMfa] = useState(null)      // { session } cuando Garmin pide código
  const [code, setCode] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)
  const [job, setJob] = useState(null)
  const poll = useRef(null)

  // El chequeo rapido se resuelve leyendo el token guardado, sin red: la
  // pantalla abre al instante. Si todavia no sabemos de quien es la sesion,
  // se lo preguntamos a Garmin aparte, sin bloquear nada.
  const refreshAuth = () =>
    get('/api/auth/status')
      .then((a) => {
        setAuth(a)
        if (a.authenticated && !a.name) {
          get('/api/auth/status?verify=true').then(setAuth).catch(() => {})
        }
        return a
      })
      .catch((e) => setError(e.message))

  useEffect(() => {
    refreshAuth()
    get('/api/sync').then((j) => j.state !== 'inactivo' && setJob(j)).catch(() => {})
    return () => clearInterval(poll.current)
  }, [])

  useEffect(() => {
    clearInterval(poll.current)
    if (job?.state === 'corriendo') {
      poll.current = setInterval(() => {
        get(`/api/sync/${job.id}`).then(setJob).catch(() => {})
      }, 2000)
    }
    return () => clearInterval(poll.current)
  }, [job?.id, job?.state])

  async function submitLogin(e) {
    e.preventDefault()
    setBusy(true); setError(null)
    try {
      const r = await post('/api/auth/login', form)
      // La contraseña cumplió su función: fuera del estado del browser.
      setForm((f) => ({ ...f, password: '' }))
      if (r.needs_mfa) setMfa({ session: r.session })
      else { setMfa(null); await refreshAuth() }
    } catch (e) { setError(e.message) } finally { setBusy(false) }
  }

  async function submitMfa(e) {
    e.preventDefault()
    setBusy(true); setError(null)
    try {
      await post('/api/auth/mfa', { session: mfa.session, code })
      setMfa(null); setCode(''); await refreshAuth()
    } catch (e) { setError(e.message) } finally { setBusy(false) }
  }

  async function startSync() {
    setBusy(true); setError(null)
    try { setJob(await post('/api/sync')) }
    catch (e) { setError(e.message) } finally { setBusy(false) }
  }

  async function doLogout() {
    setBusy(true)
    try { await post('/api/auth/logout'); await refreshAuth() }
    catch (e) { setError(e.message) } finally { setBusy(false) }
  }

  const running = job?.state === 'corriendo'

  return (
    <>
      <h1 className="page">Datos</h1>
      <p className="page-note">
        Traer las vueltas nuevas del reloj. Tu contraseña se usa una sola vez
        para pedirle un token a Garmin y no se guarda en ningún lado: ni en la
        base, ni en el navegador, ni en los registros.
      </p>

      <section className="block">
        <h2>Cuenta de Garmin</h2>
        {auth === null && <p className="msg">Viendo si hay sesión</p>}

        {auth?.authenticated && (
          <div className="framed plot">
            <div className="figrow" style={{ alignItems: 'center' }}>
              <div>
                <div className="v fig" style={{ fontSize: 20 }}>
                  {auth.name || 'Sesión activa'}
                </div>
                <div className="k">
                  {auth.name ? 'sesión activa' : 'confirmando con Garmin'}
                </div>
              </div>
              <button className="btn-quiet" onClick={doLogout} disabled={busy || running}>
                Cerrar sesión
              </button>
            </div>
          </div>
        )}

        {auth && !auth.authenticated && !mfa && (
          <form className="framed plot form" onSubmit={submitLogin}>
            <p className="note" style={{ marginTop: 0 }}>
              {auth.reason === 'el token guardado ya no sirve'
                ? 'El token guardado venció. Entrá de nuevo.'
                : 'Las mismas credenciales que usás en la app de Garmin Golf.'}
            </p>
            <label>
              Correo
              <input type="email" autoComplete="username" required value={form.email}
                     onChange={(e) => setForm({ ...form, email: e.target.value })} />
            </label>
            <label>
              Contraseña
              <input type="password" autoComplete="current-password" required
                     value={form.password}
                     onChange={(e) => setForm({ ...form, password: e.target.value })} />
            </label>
            <button type="submit" disabled={busy}>
              {busy ? 'Entrando' : 'Entrar'}
            </button>
          </form>
        )}

        {mfa && (
          <form className="framed plot form" onSubmit={submitMfa}>
            <p className="note" style={{ marginTop: 0 }}>
              Garmin pide un código de verificación. Revisá tu app, tu mail o
              tus mensajes. Tenés cinco minutos.
            </p>
            <label>
              Código
              <input inputMode="numeric" autoComplete="one-time-code" required
                     value={code} onChange={(e) => setCode(e.target.value)} />
            </label>
            <div style={{ display: 'flex', gap: 10 }}>
              <button type="submit" disabled={busy}>{busy ? 'Verificando' : 'Verificar'}</button>
              <button type="button" className="btn-quiet"
                      onClick={() => { setMfa(null); setCode('') }}>Cancelar</button>
            </div>
          </form>
        )}

        {error && <p className="msg err">{error}</p>}
      </section>

      <section className="block">
        <h2>Sincronizar</h2>
        <p className="note">
          Baja solo lo que falta: las vueltas que ya están en disco no se
          vuelven a pedir. La primera vez tarda unos minutos; después son
          segundos.
        </p>
        <div className="framed plot">
          <button onClick={startSync}
                  disabled={!auth?.authenticated || busy || running}>
            {running ? 'Sincronizando' : 'Traer vueltas nuevas'}
          </button>
          {!auth?.authenticated && (
            <span className="k" style={{ marginLeft: 12 }}>Entrá primero.</span>
          )}

          {job && job.state !== 'inactivo' && (
            <ol className="steps">
              {job.steps.map((s, i) => <li key={i}>{s}</li>)}
              {running && <li className="pending">…</li>}
            </ol>
          )}
          {job?.state === 'listo' && (
            <p className="k" style={{ marginTop: 12 }}>
              Listo. Las otras pantallas ya muestran los datos nuevos.
            </p>
          )}
          {job?.state === 'error' && <p className="msg err">{job.error}</p>}
        </div>
      </section>
    </>
  )
}
