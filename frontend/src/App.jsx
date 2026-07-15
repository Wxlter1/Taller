import { useEffect, useMemo, useRef, useState } from 'react'

const API_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000'

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

const DEFAULT_GRID = { cols: 24, rows: 14 }

function getMeta(status) {
  return STATUS_META[status] ?? STATUS_META.free
}

/**
 * Fallback SOLO para spot_id que la cámara ya está reportando pero que todavía
 * no fueron ubicados en el editor de matriz. Así nunca "desaparece" un spot
 * nuevo: se ve con una distribución genérica hasta que lo ubiques a mano.
 */
function getFallbackLayout(index, totalSpots) {
  const COLS_PER_ROW = 8
  const row = Math.floor(index / COLS_PER_ROW)
  const col = index % COLS_PER_ROW
  const rowYPositions = [15, 35, 65, 85]
  const y = rowYPositions[row] || 50
  const x = 10 + col * (80 / (COLS_PER_ROW - 1 || 1))
  const rotate = row === 1 || row === 3 ? 180 : 0
  return { x, y, rotate }
}

function App() {
  // ---------- Estado operativo (idéntico al original: cámara -> SSE -> UI) ----------
  const [parkingSpots, setParkingSpots] = useState({})
  const [stats, setStats] = useState({ total: 0, free: 0, occupied: 0, leaving: 0 })
  const [status, setStatus] = useState('Iniciando sistema...')
  const [autoRefresh, setAutoRefresh] = useState(true)
  const [searchTerm, setSearchTerm] = useState('')
  const [activeFilter, setActiveFilter] = useState('all')
  const [selectedSpotId, setSelectedSpotId] = useState(null)

  // ---------- Estado del EDITOR DE MATRIZ (mapa fijo del lugar) ----------
  const [editMode, setEditMode] = useState(false)
  const [gridCols, setGridCols] = useState(DEFAULT_GRID.cols)
  const [gridRows, setGridRows] = useState(DEFAULT_GRID.rows)
  const [cellTypes, setCellTypes] = useState({})       // "r-c" -> 'street' | 'empty'
  const [mapLayout, setMapLayout] = useState({})        // spot_id -> {x, y, rotate}
  const [brush, setBrush] = useState('spot')            // 'spot' | 'street' | 'empty' | 'erase'
  const [manualSpotId, setManualSpotId] = useState('')  // para asignar un spot_id elegido a mano
  const [layoutStatusMsg, setLayoutStatusMsg] = useState('')
  const layoutLoadedRef = useRef(false)

  // FLUJO DE DATOS REACTIVO (Server-Sent Events) — sin cambios respecto al original
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

    return () => {
      eventSource.close()
    }
  }, [autoRefresh])

  // Cargar el layout guardado UNA vez al montar (no interfiere con el SSE de estados)
  useEffect(() => {
    fetch(`${API_URL}/api/parking/layout`)
      .then((r) => r.json())
      .then((data) => {
        setMapLayout(data.layout || {})
        setCellTypes(data.cells || {})
        if (data.grid?.cols) setGridCols(data.grid.cols)
        if (data.grid?.rows) setGridRows(data.grid.rows)
        layoutLoadedRef.current = true
      })
      .catch(() => {
        setLayoutStatusMsg('No se pudo cargar el mapa guardado (¿backend corriendo?).')
      })
  }, [])

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

  const hasSavedLayout = useMemo(
    () => Object.keys(mapLayout).length > 0 || Object.keys(cellTypes).length > 0,
    [mapLayout, cellTypes]
  )

  const handleSelectSpot = (id) => {
    setSelectedSpotId((current) => (current === id ? null : id))
  }

  // spot_id que la cámara ya reporta pero que todavía no fueron ubicados en el mapa
  const unassignedSpotIds = useMemo(
    () => spotIds.filter((id) => !mapLayout[id]),
    [spotIds, mapLayout]
  )

  function getLayoutFor(id, index, total) {
    if (mapLayout[id]) return mapLayout[id]
    return getFallbackLayout(index, total)
  }

  function renderSavedLayoutLayer() {
    return (
      <div className="saved-layout-layer">
        {Object.entries(cellTypes)
          .filter(([, type]) => type !== 'spot')
          .map(([key, type]) => {
            const [r, c] = key.split('-').map(Number)
            return (
              <div
                key={key}
                className={`saved-layout-cell saved-layout-cell-${type}`}
                style={{
                  left: `${(c / gridCols) * 100}%`,
                  top: `${(r / gridRows) * 100}%`,
                  width: `${100 / gridCols}%`,
                  height: `${100 / gridRows}%`,
                }}
              />
            )
          })}
      </div>
    )
  }

  // ---------- Acciones del editor ----------
  function cellKey(r, c) {
    return `${r}-${c}`
  }

  function handleCellClick(r, c) {
    const key = cellKey(r, c)
    const x = ((c + 0.5) / gridCols) * 100
    const y = ((r + 0.5) / gridRows) * 100

    if (brush === 'erase') {
      // Si la celda tenía un spot asignado, lo libera para poder reubicarlo
      setMapLayout((prev) => {
        const next = { ...prev }
        for (const [spotId, pos] of Object.entries(next)) {
          if (pos.r === r && pos.c === c) delete next[spotId]
        }
        return next
      })
      setCellTypes((prev) => {
        const next = { ...prev }
        delete next[key]
        return next
      })
      return
    }

    if (brush === 'street' || brush === 'empty') {
      setCellTypes((prev) => ({ ...prev, [key]: brush }))
      return
    }

    // brush === 'spot': asigna un spot_id real a esta celda
    const idToPlace = manualSpotId || unassignedSpotIds[0]
    if (!idToPlace) {
      setLayoutStatusMsg('No hay spot_id sin ubicar. Elegí uno en el selector o esperá a que la cámara lo reporte.')
      return
    }

    setMapLayout((prev) => {
      const next = { ...prev }

      // ¿Esta celda ya tenía otro spot_id asignado? Si es así, NO lo pisamos
      // en silencio: lo liberamos para que vuelva a la lista de pendientes.
      let freedId = null
      for (const [spotId, pos] of Object.entries(next)) {
        if (pos.r === r && pos.c === c && spotId !== idToPlace) {
          delete next[spotId]
          freedId = spotId
        }
      }

      // Por seguridad, si el id a colocar ya estaba puesto en OTRA celda
      // (no debería pasar, pero evita duplicados), se quita de ahí también.
      if (next[idToPlace] && (next[idToPlace].r !== r || next[idToPlace].c !== c)) {
        delete next[idToPlace]
      }

      next[idToPlace] = { x, y, rotate: 0, r, c }

      if (freedId) {
        setLayoutStatusMsg(`"${freedId}" quedó liberado de esta celda — ubicalo en su lugar correcto.`)
      } else {
        setLayoutStatusMsg(`"${idToPlace}" ubicado.`)
      }

      return next
    })
    setCellTypes((prev) => ({ ...prev, [key]: 'spot' }))
    setManualSpotId('') // vuelve a autoasignar el próximo disponible
  }

  async function handleSaveLayout() {
    try {
      setLayoutStatusMsg('Guardando...')
      const res = await fetch(`${API_URL}/api/parking/layout`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          layout: mapLayout,
          cells: cellTypes,
          grid: { cols: gridCols, rows: gridRows },
        }),
      })
      if (!res.ok) throw new Error('Respuesta no OK')
      setLayoutStatusMsg('Mapa guardado ✓')
    } catch (err) {
      console.error(err)
      setLayoutStatusMsg('Error al guardar el mapa. Revisá que el backend esté corriendo.')
    }
  }

  function handleResetLayout() {
    if (!window.confirm('¿Borrar todo el mapa dibujado? Esto no afecta el estado libre/ocupado, solo las posiciones.')) return
    setMapLayout({})
    setCellTypes({})
  }

  // ---------- Render de la grilla del editor ----------
  function renderEditorGrid() {
    const cells = []
    const placedBySpot = {}
    Object.entries(mapLayout).forEach(([spotId, pos]) => {
      if (pos.r !== undefined) placedBySpot[cellKey(pos.r, pos.c)] = spotId
    })

    for (let r = 0; r < gridRows; r++) {
      for (let c = 0; c < gridCols; c++) {
        const key = cellKey(r, c)
        const placedSpotId = placedBySpot[key]
        const cellType = placedSpotId ? 'spot' : cellTypes[key] || 'void'
        cells.push(
          <div
            key={key}
            className={`editor-cell editor-cell-${cellType}`}
            style={{
              left: `${(c / gridCols) * 100}%`,
              top: `${(r / gridRows) * 100}%`,
              width: `${100 / gridCols}%`,
              height: `${100 / gridRows}%`,
            }}
            title={placedSpotId ? placedSpotId : `(${r},${c})`}
            onClick={() => handleCellClick(r, c)}
          >
            {placedSpotId ? placedSpotId.replace('spot_', '') : ''}
          </div>
        )
      }
    }
    return cells
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
            <div className="floor-panel-actions">
              <span className="updated">{spotIds.length} plazas detectadas</span>
              <button
                className={`mode-toggle ${editMode ? 'is-editing' : ''}`}
                onClick={() => setEditMode((v) => !v)}
              >
                {editMode ? '✓ Salir del editor' : '✎ Editar mapa'}
              </button>
            </div>
          </div>

          {editMode && (
            <div className="editor-toolbar">
              <div className="editor-toolbar-row">
                <div className="brush-group">
                  <button className={brush === 'spot' ? 'is-active' : ''} onClick={() => setBrush('spot')}>🅿 Estacionamiento</button>
                  <button className={brush === 'street' ? 'is-active' : ''} onClick={() => setBrush('street')}>▦ Calle</button>
                  <button className={brush === 'empty' ? 'is-active' : ''} onClick={() => setBrush('empty')}>◻ Fuera del mapa</button>
                  <button className={brush === 'erase' ? 'is-active' : ''} onClick={() => setBrush('erase')}>⌫ Borrar</button>
                </div>
                <div className="grid-size-group">
                  <label>Columnas
                    <input type="number" min="4" max="60" value={gridCols} onChange={(e) => setGridCols(Number(e.target.value) || 1)} />
                  </label>
                  <label>Filas
                    <input type="number" min="4" max="60" value={gridRows} onChange={(e) => setGridRows(Number(e.target.value) || 1)} />
                  </label>
                </div>
              </div>

              {brush === 'spot' && (
                <div className="editor-toolbar-row">
                  <label className="assign-label">
                    Próximo a ubicar:
                    <select value={manualSpotId} onChange={(e) => setManualSpotId(e.target.value)}>
                      <option value="">
                        {unassignedSpotIds[0] ? `(auto) ${unassignedSpotIds[0]}` : '— sin spot_id pendientes —'}
                      </option>
                      {unassignedSpotIds.map((id) => (
                        <option key={id} value={id}>{id}</option>
                      ))}
                    </select>
                  </label>
                  <span className="assign-hint">
                    {unassignedSpotIds.length} spot_id de la cámara sin ubicar todavía
                  </span>
                </div>
              )}

              <div className="editor-toolbar-row">
                <button className="save-btn" onClick={handleSaveLayout}>💾 Guardar mapa</button>
                <button className="reset-btn" onClick={handleResetLayout}>Reiniciar mapa</button>
                {layoutStatusMsg && <span className="layout-status-msg">{layoutStatusMsg}</span>}
              </div>
            </div>
          )}

          {spotIds.length === 0 && !editMode ? (
            <div className="floor-empty">Esperando transmisión de la cámara de seguridad...</div>
          ) : (
            <div className="minimap-container">
              {!editMode && !hasSavedLayout && (
                <>
                  <div className="minimap-lane lane-horizontal" style={{ top: '50%', left: '5%', width: '90%' }} />
                  <div className="minimap-lane lane-horizontal" style={{ top: '25%', left: '5%', width: '90%', height: '40px' }} />
                  <div className="minimap-lane lane-horizontal" style={{ top: '75%', left: '5%', width: '90%', height: '40px' }} />
                  <div className="minimap-gate" style={{ top: '50%', left: '5%' }}>ENTRADA</div>
                  <div className="minimap-gate" style={{ top: '50%', left: '95%' }}>SALIDA</div>
                </>
              )}

              {editMode ? (
                <div className="editor-grid-layer">{renderEditorGrid()}</div>
              ) : (
                <>
                  {hasSavedLayout && renderSavedLayoutLayer()}
                  {spotIds.map((id, index) => {
                    const spot = parkingSpots[id]
                    const meta = getMeta(spot.status)
                    const layout = getLayoutFor(id, index, spotIds.length)
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
                </>
              )}
            </div>
          )}

          {selectedSpot && !editMode && (
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