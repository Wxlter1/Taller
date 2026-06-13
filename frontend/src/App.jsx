import { useEffect, useMemo, useState, useRef } from 'react'

const API_URL = 'http://localhost:8000'

const STATUS_META = {
  free: { label: 'Libre', color: 'var(--free)', soft: 'var(--free-soft)' },
  occupied: { label: 'Ocupado', color: 'var(--occupied)', soft: 'var(--occupied-soft)' },
  leaving: { label: 'Liberándose', color: 'var(--leaving)', soft: 'var(--leaving-soft)' },
}

const FILTERS = [
  { key: 'all', label: 'Todas' },
  { key: 'free', label: 'Libres' },
  { key: 'occupied', label: 'Ocupadas' },
  { key: 'leaving', label: 'Liberándose' },
]

function getMeta(status) {
  return STATUS_META[status] ?? STATUS_META.free
}

function App() {
  const [parkingSpots, setParkingSpots] = useState({})
  const [stats, setStats] = useState({ total: 0, free: 0, occupied: 0, leaving: 0 })
  const [status, setStatus] = useState('Conectando al backend...')
  const [autoRefresh, setAutoRefresh] = useState(true)
  const [searchTerm, setSearchTerm] = useState('')
  const [activeFilter, setActiveFilter] = useState('all')
  const [selectedSpotId, setSelectedSpotId] = useState(null)
  const pollIntervalRef = useRef(null)

  // Obtiene el estado de estacionamientos cada 2 segundos
  useEffect(() => {
    const fetchParkingStatus = async () => {
      try {
        const response = await fetch(`${API_URL}/api/parking/status`)
        const data = await response.json()

        if (data.success) {
          setParkingSpots(data.spots)
          setStats({
            total: data.total_spots,
            free: data.free_spots,
            occupied: data.occupied_spots,
            leaving: data.leaving_spots ?? 0,
          })
          setStatus(`Actualizado: ${data.free_spots} libres / ${data.occupied_spots} ocupados / ${data.leaving_spots ?? 0} liberándose`)
        }
      } catch (error) {
        setStatus(`Error: ${error.message}`)
      }
    }

    if (autoRefresh) {
      fetchParkingStatus()
      pollIntervalRef.current = setInterval(fetchParkingStatus, 2000)
    }

    return () => {
      if (pollIntervalRef.current) {
        clearInterval(pollIntervalRef.current)
      }
    }
  }, [autoRefresh])

  const spotIds = useMemo(() => Object.keys(parkingSpots).sort(), [parkingSpots])

  const filteredSpotIds = useMemo(() => {
    return spotIds.filter((id) => {
      const spot = parkingSpots[id]
      if (activeFilter !== 'all' && spot.status !== activeFilter) return false
      if (searchTerm && !id.toLowerCase().includes(searchTerm.toLowerCase())) return false
      return true
    })
  }, [spotIds, parkingSpots, activeFilter, searchTerm])

  const selectedSpot = selectedSpotId ? parkingSpots[selectedSpotId] : null

  const handleSelectSpot = (id) => {
    setSelectedSpotId((current) => (current === id ? null : id))
  }

  return (
    <div className="dashboard">
      <aside className="sidebar">
        <div className="brand">
          <span className="brand-mark">P</span>
          <div>
            <h1>SmartParking</h1>
            <p>Monitoreo en tiempo real</p>
          </div>
        </div>

        <div className="search-row">
          <input
            type="text"
            placeholder="Buscar plaza..."
            value={searchTerm}
            onChange={(e) => setSearchTerm(e.target.value)}
          />
        </div>

        <div className="filter-row">
          {FILTERS.map((filter) => (
            <button
              key={filter.key}
              className={activeFilter === filter.key ? 'is-active' : ''}
              onClick={() => setActiveFilter(filter.key)}
            >
              {filter.label}
            </button>
          ))}
        </div>

        <div className="spot-list">
          {filteredSpotIds.length === 0 ? (
            <div className="empty-list">
              {spotIds.length === 0
                ? 'Esperando datos del detector...'
                : 'No hay plazas que coincidan con la búsqueda.'}
            </div>
          ) : (
            filteredSpotIds.map((id) => {
              const spot = parkingSpots[id]
              const meta = getMeta(spot.status)
              return (
                <button
                  key={id}
                  className={`spot-list-item ${selectedSpotId === id ? 'is-selected' : ''}`}
                  onClick={() => handleSelectSpot(id)}
                >
                  <span className="dot" style={{ background: meta.color }} />
                  <span className="spot-list-name">{id}</span>
                  <span className="badge" style={{ color: meta.color, background: meta.soft }}>
                    {meta.label}
                  </span>
                </button>
              )
            })
          )}
        </div>

        <div className="sidebar-footer">
          <button
            className={`refresh-toggle ${autoRefresh ? 'is-on' : 'is-off'}`}
            onClick={() => setAutoRefresh((value) => !value)}
          >
            {autoRefresh ? '⏸ Pausar monitoreo' : '▶ Reanudar monitoreo'}
          </button>
          <p className="connection-status">{status}</p>
        </div>
      </aside>

      <main className="main">
        <header className="main-header">
          <div>
            <h2>Estacionamientos</h2>
            <p>Plano en vivo de todas las plazas detectadas por las cámaras.</p>
          </div>
          <div className="stat-pills">
            <div className="pill">
              <strong>{stats.total}</strong>
              <span>Total</span>
            </div>
            <div className="pill pill-free">
              <strong>{stats.free}</strong>
              <span>Libres</span>
            </div>
            <div className="pill pill-occupied">
              <strong>{stats.occupied}</strong>
              <span>Ocupados</span>
            </div>
            <div className="pill pill-leaving">
              <strong>{stats.leaving}</strong>
              <span>Liberándose</span>
            </div>
          </div>
        </header>

        <section className="floor-panel">
          <div className="floor-panel-head">
            <h3>Plano del estacionamiento</h3>
            <span className="updated">{spotIds.length} plazas monitoreadas</span>
          </div>

          {spotIds.length === 0 ? (
            <div className="floor-empty">Esperando datos del detector para dibujar el plano...</div>
          ) : (
            <div className="floor-grid">
              {spotIds.map((id) => {
                const spot = parkingSpots[id]
                const meta = getMeta(spot.status)
                return (
                  <button
                    key={id}
                    className={`floor-spot ${selectedSpotId === id ? 'is-active' : ''}`}
                    style={{ '--spot-color': meta.color }}
                    onClick={() => handleSelectSpot(id)}
                  >
                    <span className="floor-spot-icon" style={{ color: meta.color }}>
                      P
                    </span>
                    <span className="floor-spot-id">{id}</span>
                    <span className="floor-spot-tag" style={{ color: meta.color, background: meta.soft }}>
                      {meta.label}
                    </span>
                  </button>
                )
              })}
            </div>
          )}

          {selectedSpot && (
            <div className="spot-detail">
              <div
                className="spot-detail-icon"
                style={{ color: getMeta(selectedSpot.status).color, background: getMeta(selectedSpot.status).soft }}
              >
                P
              </div>
              <div className="spot-detail-body">
                <h4>{selectedSpotId}</h4>
                <span
                  className="badge"
                  style={{ color: getMeta(selectedSpot.status).color, background: getMeta(selectedSpot.status).soft }}
                >
                  {getMeta(selectedSpot.status).label}
                </span>
                <p>Estado detectado en la última lectura del sistema.</p>
              </div>
              <button className="spot-detail-close" onClick={() => setSelectedSpotId(null)} aria-label="Cerrar detalle">
                ✕
              </button>
            </div>
          )}
        </section>

        <section className="legend-panel">
          <h4>Leyenda</h4>
          <div className="legend-items">
            <div className="legend-item">
              <span className="legend-swatch" style={{ background: 'var(--free)' }} />
              <span>Libre</span>
            </div>
            <div className="legend-item">
              <span className="legend-swatch" style={{ background: 'var(--occupied)' }} />
              <span>Ocupado</span>
            </div>
            <div className="legend-item">
              <span className="legend-swatch" style={{ background: 'var(--leaving)' }} />
              <span>Liberándose</span>
            </div>
          </div>
        </section>
      </main>
    </div>
  )
}

export default App
