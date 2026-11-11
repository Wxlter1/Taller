import { useEffect, useRef, useState } from 'react'
import { AREA_TYPES, CAMPUS_AREAS, CAMPUS_MAP } from './campusAreas'

const HIDE_DELAY_MS = 180

// Estado de un área según su cámara: 'live' (enviando datos), 'offline' (sin señal) o 'none' (sin cámara).
function areaStatus(area, camerasState) {
  if (!area.cameraId) return 'none'
  return camerasState[area.cameraId]?.online ? 'live' : 'offline'
}

function AreaStats({ area, camera, status }) {
  if (status === 'none') {
    return <p className="campus-card-offline">Sin cámara asociada todavía</p>
  }
  if (status === 'offline') {
    return <p className="campus-card-offline">Monitoreo sin señal en este momento</p>
  }
  return (
    <div className="campus-card-stats">
      <div><strong className="free-text">{camera.free_spots}</strong><span>Libres</span></div>
      <div><strong className="occupied-text">{camera.occupied_spots}</strong><span>Ocupadas</span></div>
      <div><strong>{camera.total_spots}</strong><span>Total</span></div>
    </div>
  )
}

const STATE_BADGE = {
  live: { label: 'En vivo', className: 'is-live' },
  offline: { label: 'Sin señal', className: '' },
  none: { label: 'Pronto', className: '' },
}

function CampusMap({ camerasState, onOpenArea }) {
  const [activeId, setActiveId] = useState(null)
  const hideTimerRef = useRef(null)
  const activeArea = CAMPUS_AREAS.find((area) => area.id === activeId) ?? null

  useEffect(() => () => clearTimeout(hideTimerRef.current), [])

  useEffect(() => {
    if (!activeId) return undefined
    const onKeyDown = (event) => {
      if (event.key === 'Escape') setActiveId(null)
    }
    window.addEventListener('keydown', onKeyDown)
    return () => window.removeEventListener('keydown', onKeyDown)
  }, [activeId])

  function showArea(id) {
    clearTimeout(hideTimerRef.current)
    setActiveId(id)
  }

  function scheduleHide() {
    clearTimeout(hideTimerRef.current)
    hideTimerRef.current = setTimeout(() => setActiveId(null), HIDE_DELAY_MS)
  }

  // La tarjeta se abre hacia el lado con más espacio libre.
  function cardPosition(area) {
    const opensLeft = area.x > 50
    return {
      top: `${area.y}%`,
      ...(opensLeft
        ? { right: `${100 - area.x + area.w / 2}%` }
        : { left: `${area.x + area.w / 2}%` }),
    }
  }

  return (
    <section className="campus-panel">
      <div className="campus-panel-head">
        <div>
          <h3>Plano del campus</h3>
          <p>Pasa el cursor sobre un estacionamiento para ver su resumen y haz clic para abrir su plano de distribución.</p>
        </div>
        <span className="updated">{CAMPUS_AREAS.length} áreas en el plano</span>
      </div>

      <div className="campus-layout">
        <div
          className={`campus-stage ${activeArea ? 'has-active' : ''}`}
          style={{ aspectRatio: `${CAMPUS_MAP.width} / ${CAMPUS_MAP.height}` }}
        >
          <img className="campus-image" src={CAMPUS_MAP.src} alt={CAMPUS_MAP.alt} draggable="false" />
          <div className="campus-dim" aria-hidden="true" />

          {CAMPUS_AREAS.map((area) => {
            const typeMeta = AREA_TYPES[area.type] ?? AREA_TYPES.parking
            const isActive = activeId === area.id
            const status = areaStatus(area, camerasState)
            return (
              <button
                key={area.id}
                type="button"
                className={`campus-hotspot ${isActive ? 'is-active' : ''} ${status === 'live' ? 'is-live' : 'is-offline'}`}
                style={{
                  left: `${area.x}%`,
                  top: `${area.y}%`,
                  width: `${area.w}%`,
                  height: `${area.h}%`,
                }}
                onMouseEnter={() => showArea(area.id)}
                onMouseLeave={scheduleHide}
                onFocus={() => showArea(area.id)}
                onBlur={scheduleHide}
                onClick={() => onOpenArea(area.id)}
                aria-label={`${area.name}: abrir plano de distribución`}
              >
                <span className="campus-hotspot-ring" aria-hidden="true" />
                <span className="campus-hotspot-pin" aria-hidden="true">{typeMeta.icon}</span>
                <span className="campus-hotspot-label" aria-hidden="true">{area.shortName}</span>
              </button>
            )
          })}

          {activeArea && (
            <div
              className={`campus-card ${activeArea.x > 50 ? 'opens-left' : 'opens-right'}`}
              style={cardPosition(activeArea)}
              onMouseEnter={() => showArea(activeArea.id)}
              onMouseLeave={scheduleHide}
              role="dialog"
              aria-label={`Resumen de ${activeArea.name}`}
            >
              <span className="section-kicker">{activeArea.sector}</span>
              <h4>{activeArea.name}</h4>
              <p>{activeArea.description}</p>
              <AreaStats
                area={activeArea}
                camera={camerasState[activeArea.cameraId]}
                status={areaStatus(activeArea, camerasState)}
              />
              <button type="button" className="campus-card-cta" onClick={() => onOpenArea(activeArea.id)}>
                Ver plano de distribución →
              </button>
            </div>
          )}
        </div>

        <aside className="map-status-panel campus-area-panel">
          <div className="map-status-head">
            <div>
              <span className="section-kicker">Campus Concepción</span>
              <h4>Estacionamientos</h4>
            </div>
            <span className="map-count">{CAMPUS_AREAS.length}</span>
          </div>
          <div className="campus-area-list">
            {CAMPUS_AREAS.map((area) => {
              const typeMeta = AREA_TYPES[area.type] ?? AREA_TYPES.parking
              const status = areaStatus(area, camerasState)
              const camera = camerasState[area.cameraId]
              const badge = STATE_BADGE[status]
              return (
                <button
                  key={area.id}
                  type="button"
                  className={`campus-area-item ${activeId === area.id ? 'is-selected' : ''}`}
                  onMouseEnter={() => showArea(area.id)}
                  onMouseLeave={scheduleHide}
                  onClick={() => onOpenArea(area.id)}
                >
                  <span className="campus-area-icon">{typeMeta.icon}</span>
                  <span className="campus-area-text">
                    <strong>{area.name}</strong>
                    <small>
                      {status === 'live'
                        ? `${camera.free_spots} libres de ${camera.total_spots}`
                        : status === 'offline' ? 'Sin señal' : 'Sin cámara asociada'}
                    </small>
                  </span>
                  <span className={`campus-area-state ${badge.className}`}>{badge.label}</span>
                </button>
              )
            })}
          </div>
          <p className="campus-area-hint">Selecciona un estacionamiento para ver sus plazas y ubicarte dentro de él.</p>
        </aside>
      </div>
    </section>
  )
}

export default CampusMap
