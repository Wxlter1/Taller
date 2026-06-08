import { useEffect, useState, useRef } from 'react'

const API_URL = 'http://localhost:8000'

function App() {
  const [parkingSpots, setParkingSpots] = useState({})
  const [stats, setStats] = useState({ total: 0, free: 0, occupied: 0 })
  const [status, setStatus] = useState('Conectando al backend...')
  const [autoRefresh, setAutoRefresh] = useState(true)
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
          })
          setStatus(`Actualizado: ${data.free_spots} libres / ${data.occupied_spots} ocupados`)
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

  const getSpotIcon = (status) => {
    switch (status) {
      case 'free':
        return '🟢'
      case 'occupied':
        return '🔴'
      case 'leaving':
        return '🟡'
      default:
        return '⚪'
    }
  }

  const getSpotColor = (status) => {
    switch (status) {
      case 'free':
        return '#10b981'
      case 'occupied':
        return '#ef4444'
      case 'leaving':
        return '#f59e0b'
      default:
        return '#9ca3af'
    }
  }

  const spotIds = Object.keys(parkingSpots).sort()

  return (
    <div className="app-container">
      <header>
        <h1>🅿️ SmartParking - Sistema de Detección</h1>
        <p>Monitoreo en tiempo real de estacionamientos</p>
      </header>

      <section className="control-panel">
        <div className="stats-grid">
          <div className="stat-card">
            <div className="stat-number">{stats.total}</div>
            <div className="stat-label">Total</div>
          </div>
          <div className="stat-card" style={{ borderColor: '#10b981' }}>
            <div className="stat-number" style={{ color: '#10b981' }}>{stats.free}</div>
            <div className="stat-label">Libres</div>
          </div>
          <div className="stat-card" style={{ borderColor: '#ef4444' }}>
            <div className="stat-number" style={{ color: '#ef4444' }}>{stats.occupied}</div>
            <div className="stat-label">Ocupados</div>
          </div>
        </div>

        <div className="control-buttons">
          <button
            onClick={() => setAutoRefresh(!autoRefresh)}
            style={{
              backgroundColor: autoRefresh ? '#2563eb' : '#9ca3af',
            }}
          >
            {autoRefresh ? '⏸ Pausar' : '▶ Reanudar'}
          </button>
        </div>

        <div className="status">{status}</div>
      </section>

      <section className="parking-grid">
        <h2>Estado de Estacionamientos</h2>
        <div className="grid-container">
          {spotIds.length === 0 ? (
            <div style={{ gridColumn: '1 / -1', textAlign: 'center', padding: '40px', color: '#999' }}>
              Esperando datos del edge detector...
            </div>
          ) : (
            spotIds.map((spotId) => {
              const spot = parkingSpots[spotId]
              const spotNumber = spotId.replace('spot_', '')
              return (
                <div
                  key={spotId}
                  className="spot-card"
                  style={{
                    borderColor: getSpotColor(spot.status),
                    backgroundColor:
                      spot.status === 'free'
                        ? 'rgba(16, 185, 129, 0.1)'
                        : spot.status === 'occupied'
                        ? 'rgba(239, 68, 68, 0.1)'
                        : 'rgba(245, 158, 11, 0.1)',
                  }}
                >
                  <div className="spot-icon">{getSpotIcon(spot.status)}</div>
                  <div className="spot-label">Estac. {spotNumber}</div>
                  <div className="spot-status">{spot.status.toUpperCase()}</div>
                  {spot.confidence && (
                    <div className="spot-confidence">
                      Conf: {(spot.confidence * 100).toFixed(0)}%
                    </div>
                  )}
                </div>
              )
            })
          )}
        </div>
      </section>

      <section className="legend">
        <h3>Leyenda</h3>
        <div className="legend-items">
          <div className="legend-item">
            <span className="legend-icon">🟢</span>
            <span>Libre</span>
          </div>
          <div className="legend-item">
            <span className="legend-icon">🔴</span>
            <span>Ocupado</span>
          </div>
          <div className="legend-item">
            <span className="legend-icon">🟡</span>
            <span>Se está liberando</span>
          </div>
        </div>
      </section>
    </div>
  )
}

export default App
