import { useEffect, useMemo, useState } from 'react'

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

/**
 * MAP_LAYOUT: Almacenará tus coordenadas fijas del mapa definitivo (X, Y de 0 a 100).
 * Ejemplo: 'A1': { x: 12, y: 15, rotate: 90 }
 */
const MAP_LAYOUT = {}

function getMeta(status) {
  return STATUS_META[status] ?? STATUS_META.free
}

/**
 * Algoritmo dinámico: distribuye de forma automática cualquier número de plazas
 * (como tus 32 espacios) de manera simétrica en un mapa de parking funcional.
 */
function getDynamicLayout(index, totalSpots) {
  const COLS_PER_ROW = 8 // Máximo de 8 cajones alineados por bloque
  const row = Math.floor(index / COLS_PER_ROW)
  const col = index % COLS_PER_ROW

  // Ejes Y calculados de forma que queden pasillos vehiculares transitables en el medio
  const rowYPositions = [15, 35, 65, 85]
  const y = rowYPositions[row] || 50

  // Distribución en el eje X cubriendo del 10% al 90% del lienzo
  const x = 10 + col * (80 / (COLS_PER_ROW - 1 || 1))

  // Rotaciones alternadas espalda con espalda
  const rotate = row === 1 || row === 3 ? 180 : 0

  return { x, y, rotate }
}

function App() {
  const [parkingSpots, setParkingSpots] = useState({})
  const [stats, setStats] = useState({ total: 0, free: 0, occupied: 0, leaving: 0 })
  const [status, setStatus] = useState('Iniciando sistema...')
  const [autoRefresh, setAutoRefresh] = useState(true)
  const [searchTerm, setSearchTerm] = useState('')
  const [activeFilter, setActiveFilter] = useState('all')
  const [selectedSpotId, setSelectedSpotId] = useState(null)

  // FLUJO DE DATOS REACTIVO (Server-Sent Events)
  useEffect(() => {
    if (!autoRefresh) {
      setStatus('Monitoreo en tiempo real pausado.')
      return
    }

    setStatus('Conectando al flujo SSE en tiempo real...')
    const eventSource = new EventSource(`${API_URL}/api/parking/stream`)

    eventSource.onopen = () => {
      setStatus('Conexión SSE establecida. Escuchando cambios...')
    }

    eventSource.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data)
        setParkingSpots(data.spots)
        setStats({
          total: data.total_spots,
          free: data.free_spots,
          occupied: data.occupied_spots,
          leaving: data.leaving_spots ?? 0,
        })
        setStatus(`En vivo (SSE): ${data.free_spots} libres / ${data.occupied_spots} ocupados`)
      } catch (err) {
        console.error('Error procesando el flujo SSE:', err)
      }
    }

    eventSource.onerror = (error) => {
      console.error('Error de conexión SSE:', error)
      setStatus('Canal desconectado. Reconectando de forma automática...')
    }

    // Limpieza al desmontar el componente o pausar el flujo
    return () => {
      eventSource.close()
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
              {spotIds.length === 0 ? 'Esperando datos del detector...' : 'Sin coincidencias.'}
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
            {autoRefresh ? '⏸ Pausar Stream SSE' : '▶ Reanudar Stream SSE'}
          </button>
          <p className="connection-status">{status}</p>
        </div>
      </aside>

      <main className="main">
        <header className="main-header">
          <div>
            <h2>Estacionamientos</h2>
            <p>Minimapa interactivo con conexión persistente de eventos de servidor.</p>
          </div>
          <div className="stat-pills">
            <div className="pill"><strong>{stats.total}</strong><span>Total</span></div>
            <div className="pill pill-free"><strong>{stats.free}</strong><span>Libres</span></div>
            <div className="pill pill-occupied"><strong>{stats.occupied}</strong><span>Ocupados</span></div>
            <div className="pill pill-leaving"><strong>{stats.leaving}</strong><span>Liberándose</span></div>
          </div>
        </header>

        <section className="floor-panel">
          <div className="floor-panel-head">
            <h3>Mapa de Distribución (Plano en vivo)</h3>
            <span className="updated">{spotIds.length} plazas detectadas</span>
          </div>

          {spotIds.length === 0 ? (
            <div className="floor-empty">Esperando transmisión de la cámara de seguridad...</div>
          ) : (
            <div className="minimap-container">
              {/* Calles estructurales por defecto */}
              <div className="minimap-lane lane-horizontal" style={{ top: '50%', left: '5%', width: '90%' }} />
              <div className="minimap-lane lane-horizontal" style={{ top: '25%', left: '5%', width: '90%', height: '40px' }} />
              <div className="minimap-lane lane-horizontal" style={{ top: '75%', left: '5%', width: '90%', height: '40px' }} />
              
              <div className="minimap-gate" style={{ top: '50%', left: '5%' }}>ENTRADA</div>
              <div className="minimap-gate" style={{ top: '50%', left: '95%' }}>SALIDA</div>

              {/* Inyección geométrica de plazas */}
              {spotIds.map((id, index) => {
                const spot = parkingSpots[id]
                const meta = getMeta(spot.status)
                
                const layout = MAP_LAYOUT[id] || getDynamicLayout(index, spotIds.length)
                const isFilteredOut = !filteredSpotIds.includes(id)

                return (
                  <button
                    key={id}
                    className={`minimap-spot ${selectedSpotId === id ? 'is-active' : ''} ${isFilteredOut ? 'is-filtered-out' : ''} status-${spot.status}`}
                    style={{
                      left: `${layout.x}%`,
                      top: `${layout.y}%`,
                      transform: `translate(-50%, -50%) rotate(${layout.rotate}deg)`,
                      '--spot-color': meta.color,
                      '--spot-soft': meta.soft,
                    }}
                    onClick={() => handleSelectSpot(id)}
                  >
                    <span className="map-id">{id.replace('spot_', '')}</span>
                    <div className="car-indicator" />
                  </button>
                )
              })}
            </div>
          )}

          {selectedSpot && (
            <div className="spot-detail">
              <div className="spot-detail-icon" style={{ color: getMeta(selectedSpot.status).color, background: getMeta(selectedSpot.status).soft }}>P</div>
              <div className="spot-detail-body">
                <h4>Plaza seleccionada: {selectedSpotId}</h4>
                <span className="badge" style={{ color: getMeta(selectedSpot.status).color, background: getMeta(selectedSpot.status).soft }}>
                  {getMeta(selectedSpot.status).label}
                </span>
                <p>Métrica de confiabilidad: {(selectedSpot.confidence * 100).toFixed(1)}%</p>
              </div>
              <button className="spot-detail-close" onClick={() => setSelectedSpotId(null)}>✕</button>
            </div>
          )}
        </section>

        <section className="legend-panel">
          <h4>Leyenda</h4>
          <div className="legend-items">
            <div className="legend-item"><span className="legend-swatch" style={{ background: 'var(--free)' }} /><span>Libre</span></div>
            <div className="legend-item"><span className="legend-swatch" style={{ background: 'var(--occupied)' }} /><span>Ocupado</span></div>
            <div className="legend-item"><span className="legend-swatch" style={{ background: 'var(--leaving)' }} /><span>Liberándose</span></div>
          </div>
        </section>
      </main>
    </div>
  )
}

export default App