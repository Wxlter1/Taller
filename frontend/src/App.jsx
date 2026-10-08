import { useEffect, useMemo, useRef, useState } from 'react'

const API_URL = import.meta.env.VITE_API_URL ?? `http://${window.location.hostname}:8000`
const CAMERA_WATCH_URL = import.meta.env.VITE_CAMERA_WATCH_URL
  || 'http://146.83.194.142:1932/watch/w5DiM5QUILZ3lyTd70vCnEbt6Y9IkRNG_q9D5pPxYKU'

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


const ZONE_META = {
  parking: { label: 'Área de estacionamiento', icon: '▩' },
  street: { label: 'Calle', icon: '▦' },
  sidewalk: { label: 'Vereda', icon: '▤' },
  building: { label: 'Edificio', icon: '⌂' },
  empty: { label: 'Fuera del mapa', icon: '◻' },
}


const BLOCKING_ZONES = ['street', 'sidewalk', 'building', 'empty']

function getMeta(status) {
  return STATUS_META[status] ?? STATUS_META.free
}


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
 
  const [parkingSpots, setParkingSpots] = useState({})
  const [stats, setStats] = useState({ total: 0, free: 0, occupied: 0, leaving: 0 })
  const [status, setStatus] = useState('Iniciando sistema...')
  const [autoRefresh, setAutoRefresh] = useState(true)
  const [searchTerm, setSearchTerm] = useState('')
  const [activeFilter, setActiveFilter] = useState('all')
  const [selectedSpotId, setSelectedSpotId] = useState(null)


  const [editMode, setEditMode] = useState(false)
  const [gridCols, setGridCols] = useState(DEFAULT_GRID.cols)
  const [gridRows, setGridRows] = useState(DEFAULT_GRID.rows)
  const [cellTypes, setCellTypes] = useState({})       
  const [mapLayout, setMapLayout] = useState({})        
  const [brush, setBrush] = useState('spot')            
  const [manualSpotId, setManualSpotId] = useState('')  
  const [layoutStatusMsg, setLayoutStatusMsg] = useState('')
  const layoutLoadedRef = useRef(false)
  const [cameraZones, setCameraZones] = useState([])
  const [cameraDraft, setCameraDraft] = useState([])
  const [cameraZoneEditing, setCameraZoneEditing] = useState(false)
  const [cameraZonesMsg, setCameraZonesMsg] = useState('')
  const [cameraAspectRatio, setCameraAspectRatio] = useState('16 / 9')

  
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

  
  useEffect(() => {
    fetch(`${API_URL}/api/parking/layout`)
      .then((r) => r.json())
      .then((data) => {
        setMapLayout(data.layout || {})
        
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

  useEffect(() => {
    fetch(`${API_URL}/api/camera/zones`)
      .then((response) => {
        if (!response.ok) throw new Error(`HTTP ${response.status}`)
        return response.json()
      })
      .then((data) => setCameraZones(data.zones || []))
      .catch((error) => {
        console.error('Error cargando las plazas de cámara:', error)
        setCameraZonesMsg('No se pudieron cargar las plazas guardadas.')
      })
  }, [])

  function handleCameraOverlayClick(event) {
    if (!cameraZoneEditing) return
    const bounds = event.currentTarget.getBoundingClientRect()
    setCameraDraft((points) => [
      ...points,
      {
        x: Math.min(1, Math.max(0, (event.clientX - bounds.left) / bounds.width)),
        y: Math.min(1, Math.max(0, (event.clientY - bounds.top) / bounds.height)),
      },
    ])
  }

  function handleFinishCameraZone() {
    if (cameraDraft.length < 3) {
      setCameraZonesMsg('Marca al menos 3 puntos para cerrar una plaza.')
      return
    }
    const usedIds = new Set(cameraZones.map((zone) => zone.id))
    let nextId = 1
    while (usedIds.has(`spot_${nextId}`)) nextId += 1
    setCameraZones((zones) => [
      ...zones,
      { id: `spot_${nextId}`, points: cameraDraft },
    ])
    setCameraDraft([])
    setCameraZonesMsg('')
  }

  async function handleSaveCameraZones() {
    setCameraZonesMsg('Guardando plazas...')
    try {
      const response = await fetch(`${API_URL}/api/camera/zones`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ zones: cameraZones }),
      })
      if (!response.ok) throw new Error(`HTTP ${response.status}`)
      setCameraDraft([])
      setCameraZoneEditing(false)
      setCameraZonesMsg(`Se guardaron ${cameraZones.length} plazas. El detector las actualizará en unos segundos.`)
    } catch (error) {
      console.error('Error guardando las plazas de cámara:', error)
      setCameraZonesMsg('No se pudieron guardar las plazas. Revisa la conexión con el backend.')
    }
  }

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

 
  const unassignedSpotIds = useMemo(
    () => spotIds.filter((id) => !mapLayout[id]),
    [spotIds, mapLayout]
  )

  function getLayoutFor(id, index, total) {
    if (mapLayout[id]) return mapLayout[id]
    return getFallbackLayout(index, total)
  }

  
  function cellKey(r, c) {
    return `${r}-${c}`
  }

  function handleCellClick(r, c) {
    const key = cellKey(r, c)
    const x = ((c + 0.5) / gridCols) * 100
    const y = ((r + 0.5) / gridRows) * 100

   
    const placedHere = Object.entries(mapLayout).find(([, pos]) => pos.r === r && pos.c === c)

    if (brush === 'erase') {
      
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
      
      if (placedHere) {
        setLayoutStatusMsg(`⛔ La celda tiene ubicado "${placedHere[0]}" — borralo antes de cambiar la zona.`)
        return
      }
      setCellTypes((prev) => ({ ...prev, [key]: brush }))
      return
    }

    
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

      
      let freedId = null
      for (const [spotId, pos] of Object.entries(next)) {
        if (pos.r === r && pos.c === c && spotId !== idToPlace) {
          delete next[spotId]
          freedId = spotId
        }
      }

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
    setManualSpotId('') 
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

  
  const hasZones = Object.keys(cellTypes).length > 0

 
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
            <p>Cámara en vivo y mapa de estacionamientos con eventos en tiempo real.</p>
          </div>
          <div className="stat-pills">
            <div className="pill"><strong>{stats.total}</strong><span>Total</span></div>
            <div className="pill pill-free"><strong>{stats.free}</strong><span>Libres</span></div>
            <div className="pill pill-occupied"><strong>{stats.occupied}</strong><span>Ocupados</span></div>
            <div className="pill pill-leaving"><strong>{stats.leaving}</strong><span>Liberándose</span></div>
          </div>
        </header>

        <section className="camera-panel">
          <div className="camera-panel-head">
            <h3>Cámara en vivo · plazas superpuestas</h3>
            <div className="camera-panel-actions">
              <button
                className={`mode-toggle ${cameraZoneEditing ? 'is-editing' : ''}`}
                onClick={() => {
                  setCameraZoneEditing((editing) => !editing)
                  setCameraDraft([])
                  setCameraZonesMsg('')
                }}
              >
                {cameraZoneEditing ? '✓ Terminar edición' : '✎ Marcar plazas'}
              </button>
              <a href={CAMERA_WATCH_URL} target="_blank" rel="noreferrer">
                Cámara original
              </a>
            </div>
          </div>
          <div
            className={`camera-stage ${cameraZoneEditing ? 'is-editing' : ''}`}
            style={{ aspectRatio: cameraAspectRatio }}
          >
            <img
              className="camera-player"
              src={`${API_URL}/api/camera/stream`}
              alt="Cámara en vivo con detecciones y plazas"
              onLoad={(event) => {
                const { naturalWidth, naturalHeight } = event.currentTarget
                if (naturalWidth && naturalHeight) {
                  setCameraAspectRatio(`${naturalWidth} / ${naturalHeight}`)
                }
              }}
            />
            <svg
              className="camera-zone-overlay"
              viewBox="0 0 1000 1000"
              preserveAspectRatio="none"
              onClick={handleCameraOverlayClick}
              aria-label="Editor de polígonos de plazas"
            >
              {cameraZones.map((zone) => {
                const points = zone.points
                  .map((point) => `${point.x * 1000},${point.y * 1000}`)
                  .join(' ')
                const occupied = parkingSpots[zone.id]?.status === 'occupied'
                const color = occupied ? '#f87171' : '#34d399'
                return (
                  <g key={zone.id}>
                    <polygon
                      points={points}
                      fill={cameraZoneEditing ? `${color}30` : 'transparent'}
                      stroke={color}
                      strokeWidth="5"
                      vectorEffect="non-scaling-stroke"
                    />
                    <text
                      x={zone.points[0].x * 1000}
                      y={zone.points[0].y * 1000 - 10}
                      fill={color}
                      stroke="#07111f"
                      strokeWidth="4"
                      paintOrder="stroke"
                      fontSize="26"
                      fontWeight="700"
                    >
                      {zone.id} · {occupied ? 'Ocupado' : 'Libre'}
                    </text>
                  </g>
                )
              })}
              {cameraDraft.length > 0 && (
                <g>
                  <polyline
                    points={cameraDraft.map((point) => `${point.x * 1000},${point.y * 1000}`).join(' ')}
                    fill="none"
                    stroke="#5eead4"
                    strokeWidth="5"
                    strokeDasharray="12 8"
                    vectorEffect="non-scaling-stroke"
                  />
                  {cameraDraft.map((point, index) => (
                    <circle key={index} cx={point.x * 1000} cy={point.y * 1000} r="10" fill="#5eead4" />
                  ))}
                </g>
              )}
            </svg>
          </div>
          {cameraZoneEditing && (
            <div className="camera-zone-editor">
              <p>Haz clic en las esquinas de cada plaza (mínimo 3 puntos); dibújalas dentro de la cámara.</p>
              <div className="camera-zone-controls">
                <button className="save-btn" onClick={handleFinishCameraZone} disabled={cameraDraft.length < 3}>
                  Cerrar plaza ({cameraDraft.length} puntos)
                </button>
                <button className="mode-toggle" onClick={() => setCameraDraft((points) => points.slice(0, -1))} disabled={!cameraDraft.length}>
                  Deshacer punto
                </button>
                <button className="save-btn" onClick={handleSaveCameraZones}>
                  Guardar plazas
                </button>
                {cameraZones.map((zone) => (
                  <button
                    className="camera-zone-remove"
                    key={zone.id}
                    onClick={() => setCameraZones((zones) => zones.filter((item) => item.id !== zone.id))}
                  >
                    Quitar {zone.id}
                  </button>
                ))}
              </div>
              {cameraZonesMsg && <p className="camera-zones-message">{cameraZonesMsg}</p>}
            </div>
          )}
          {!cameraZoneEditing && cameraZonesMsg && <p className="camera-zones-message">{cameraZonesMsg}</p>}
        </section>

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