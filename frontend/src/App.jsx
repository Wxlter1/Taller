import { useEffect, useMemo, useRef, useState } from 'react'

// Si no se define VITE_API_URL, el backend se asume en el mismo host que sirve
// la página (puerto 8000). Así el deploy funciona en cualquier servidor sin config.
const API_URL = import.meta.env.VITE_API_URL || `http://${window.location.hostname}:8000`

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

// Tipos de zona que se pueden pintar en el editor para delimitar el mapa real.
// 'parking' es la única zona donde se permite ubicar spots.
const ZONE_META = {
  parking: { label: 'Área de estacionamiento', icon: '▩' },
  street: { label: 'Calle', icon: '▦' },
  sidewalk: { label: 'Vereda', icon: '▤' },
  building: { label: 'Edificio', icon: '⌂' },
  empty: { label: 'Fuera del mapa', icon: '◻' },
}

// Zonas sobre las que está PROHIBIDO ubicar un estacionamiento.
const BLOCKING_ZONES = ['street', 'sidewalk', 'building', 'empty']

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
        // Mapas guardados con la versión anterior marcaban la celda del spot
        // como 'spot'; ahora esa celda pasa a ser zona 'parking'.
        const normalizedCells = {}
        Object.entries(data.cells || {}).forEach(([key, type]) => {
          normalizedCells[key] = type === 'spot' ? 'parking' : type
        })
        setCellTypes(normalizedCells)
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

  // ---------- Acciones del editor ----------
  function cellKey(r, c) {
    return `${r}-${c}`
  }

  function handleCellClick(r, c) {
    const key = cellKey(r, c)
    const x = ((c + 0.5) / gridCols) * 100
    const y = ((r + 0.5) / gridRows) * 100

    // ¿Hay un spot ya colocado en esta celda?
    const placedHere = Object.entries(mapLayout).find(([, pos]) => pos.r === r && pos.c === c)

    if (brush === 'erase') {
      // Primer clic: libera el spot (la zona pintada debajo se conserva).
      // Segundo clic (celda sin spot): borra la zona pintada.
      if (placedHere) {
        const [spotId] = placedHere
        setMapLayout((prev) => {
          const next = { ...prev }
          delete next[spotId]
          return next
        })
        setLayoutStatusMsg(`"${spotId}" quitado del mapa. Volvé a clickear para borrar la zona.`)
        return
      }
      setCellTypes((prev) => {
        const next = { ...prev }
        delete next[key]
        return next
      })
      return
    }

    if (brush !== 'spot') {
      // Pinceles de zona: área de estacionamiento, calle, vereda, edificio, fuera de mapa
      if (placedHere) {
        setLayoutStatusMsg(`⛔ La celda tiene ubicado "${placedHere[0]}" — borralo antes de cambiar la zona.`)
        return
      }
      setCellTypes((prev) => ({ ...prev, [key]: brush }))
      return
    }

    // brush === 'spot': asigna un spot_id real a esta celda.
    // VALIDACIÓN DE ZONA: nunca sobre calle/vereda/edificio/fuera de mapa, y si
    // hay un área de estacionamiento demarcada, solo se permite dentro de ella.
    const zone = cellTypes[key]
    if (BLOCKING_ZONES.includes(zone)) {
      setLayoutStatusMsg(`⛔ No se puede ubicar un estacionamiento sobre "${ZONE_META[zone].label}".`)
      return
    }
    if (zone !== 'parking') {
      setLayoutStatusMsg('⛔ Primero demarcá el ▩ área de estacionamiento: los spots solo se pueden ubicar dentro de ella.')
      return
    }

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

  // ¿El usuario ya delimitó zonas en el editor? Si sí, el plano se dibuja con
  // esas zonas; si no, se muestra la escena decorativa genérica como fallback.
  const hasZones = Object.keys(cellTypes).length > 0

  // ---------- Capa de zonas (mapa interactivo dibujado desde el editor) ----------
  function renderZonesLayer() {
    return (
      <div className="zones-layer" aria-hidden="true">
        {Object.entries(cellTypes).map(([key, type]) => {
          const [r, c] = key.split('-').map(Number)
          if (r >= gridRows || c >= gridCols || !ZONE_META[type]) return null
          return (
            <div
              key={key}
              className={`zone-cell zone-${type}`}
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

  // ---------- Escena decorativa del plano (basada en el croquis real del lugar) ----------
  // Zona achurada arriba, calle con línea amarilla, ingreso, seto verde en U
  // alrededor de la primera fila, segunda zona de estacionamientos, fachada del
  // edificio abajo y canal a la derecha.
  function renderSceneBackdrop() {
    return (
      <div className="scene-backdrop" aria-hidden="true">
        <div className="scene-hatched" />
        <div className="scene-road">
          <div className="scene-road-line" />
        </div>
        <div className="scene-entry"><span className="scene-entry-arrow" /><span className="scene-entry-label">Ingreso</span></div>
        <div className="scene-hedge" />
        <div className="scene-parking-zone scene-parking-zone-1"><span>Estacionamientos</span></div>
        <div className="scene-parking-zone scene-parking-zone-2"><span>Estacionamientos</span></div>
        <div className="scene-side-right" />
        <div className="scene-stream" />
        <div className="scene-side-bottom" />
        <div className="scene-building"><span>Edificio</span></div>
      </div>
    )
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
                  <button className={brush === 'spot' ? 'is-active' : ''} onClick={() => setBrush('spot')}>🅿 Ubicar spot</button>
                  {Object.entries(ZONE_META).map(([type, meta]) => (
                    <button
                      key={type}
                      className={brush === type ? 'is-active' : ''}
                      onClick={() => setBrush(type)}
                    >
                      {meta.icon} {meta.label}
                    </button>
                  ))}
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
                <span className="brush-hint">
                  Pintá primero el ▩ área de estacionamiento: los spots 🅿 solo se pueden
                  ubicar dentro de esa zona, nunca sobre calle, vereda, edificio o fuera del mapa.
                </span>
              </div>

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
            <div className={`minimap-container ${editMode ? 'is-editing' : ''}`}>
              {hasZones ? renderZonesLayer() : renderSceneBackdrop()}

              {editMode ? (
                <div className="editor-grid-layer">{renderEditorGrid()}</div>
              ) : (
                <>
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
            {hasZones && (
              <>
                <div className="legend-item"><span className="legend-swatch legend-zone-parking" /><span>Estacionamiento</span></div>
                <div className="legend-item"><span className="legend-swatch legend-zone-street" /><span>Calle</span></div>
                <div className="legend-item"><span className="legend-swatch legend-zone-sidewalk" /><span>Vereda</span></div>
                <div className="legend-item"><span className="legend-swatch legend-zone-building" /><span>Edificio</span></div>
                <div className="legend-item"><span className="legend-swatch legend-zone-empty" /><span>Fuera del mapa</span></div>
              </>
            )}
          </div>
        </section>
      </main>
    </div>
  )
}

export default App