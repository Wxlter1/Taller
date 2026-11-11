import { useEffect, useRef, useState } from 'react'

function LoginModal({ apiUrl, onSuccess, onClose }) {
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)
  const userInputRef = useRef(null)
  const onCloseRef = useRef(onClose)
  onCloseRef.current = onClose

  // Se ejecuta UNA sola vez al abrir la ventana. (Antes dependía de onClose, que
  // cambia en cada actualización en vivo de la página, y devolvía el foco al
  // campo de usuario mientras se escribía la contraseña.)
  useEffect(() => {
    userInputRef.current?.focus()
    const onKeyDown = (event) => {
      if (event.key === 'Escape') onCloseRef.current()
    }
    window.addEventListener('keydown', onKeyDown)
    return () => window.removeEventListener('keydown', onKeyDown)
  }, [])

  async function handleSubmit(event) {
    event.preventDefault()
    setError('')
    setLoading(true)
    try {
      const response = await fetch(`${apiUrl}/api/auth/login`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ username: username.trim(), password }),
      })
      const data = await response.json().catch(() => ({}))
      if (!response.ok) {
        setError(typeof data.detail === 'string' ? data.detail : 'No se pudo iniciar sesión.')
        setPassword('')
        return
      }
      onSuccess(data)
    } catch {
      setError('No se pudo conectar con el servidor. Revisa que el backend esté corriendo.')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="login-backdrop" onMouseDown={(event) => event.target === event.currentTarget && onClose()}>
      <form className="login-card" onSubmit={handleSubmit} aria-labelledby="login-title">
        <button type="button" className="login-close" onClick={onClose} aria-label="Cerrar">✕</button>
        <img className="login-logo" src="/assets/escudo-monocromatico-oscuro.png" alt="" />
        <span className="section-kicker">SmartParking · Administración</span>
        <h3 id="login-title">Iniciar sesión</h3>

        <label className="login-field">
          <span>Usuario</span>
          <input
            ref={userInputRef}
            type="text"
            autoComplete="username"
            value={username}
            onChange={(event) => setUsername(event.target.value)}
            required
          />
        </label>
        <label className="login-field">
          <span>Contraseña</span>
          <input
            type="password"
            autoComplete="current-password"
            value={password}
            onChange={(event) => setPassword(event.target.value)}
            required
          />
        </label>

        {error && <p className="login-error" role="alert">{error}</p>}

        <button type="submit" className="login-submit" disabled={loading || !username.trim() || !password}>
          {loading ? 'Verificando...' : 'Ingresar'}
        </button>
      </form>
    </div>
  )
}

export default LoginModal
