// Configuración del plano general del campus.
//
// Cada área es un punto interactivo sobre la imagen del plano. Las coordenadas
// van en PORCENTAJE respecto de la imagen (0–100), así se mantienen alineadas
// aunque la imagen cambie de tamaño o se reemplace por una de mayor resolución
// (siempre que conserve el mismo encuadre).
//
//   x, y  → centro del área
//   w, h  → ancho y alto del contorno (elipse)
//   cameraId → id de la cámara (en cameras.json) que vigila este estacionamiento.
//              Si se deja en null, el área se muestra pero indica que aún no
//              tiene cámara asociada.
//   type  → 'parking' por ahora; queda preparado para otros tipos en el futuro
//           (por ejemplo 'bicicletero', 'acceso', 'edificio').

export const CAMPUS_MAP = {
  src: '/assets/plano-campus.jpg',
  width: 442,
  height: 234,
  alt: 'Plano del Campus Concepción de la Universidad del Bío-Bío',
}

export const AREA_TYPES = {
  parking: { label: 'Estacionamiento', icon: 'P' },
}

export const CAMPUS_AREAS = [
  {
    id: 'estacionamiento-1',
    name: 'Estacionamiento FACE',
    shortName: 'FACE',
    sector: 'Campus Concepción',
    description: 'Disponibilidad de plazas actualizada en tiempo real.',
    type: 'parking',
    cameraId: 'face',
    x: 57.5,
    y: 25,
    w: 4,
    h: 7.5,
  },
  {
    id: 'estacionamiento-2',
    name: 'Estacionamiento AC',
    shortName: 'AC',
    sector: 'Campus Concepción',
    description: 'Disponibilidad de plazas actualizada en tiempo real.',
    type: 'parking',
    cameraId: 'ac',
    x: 56.8,
    y: 37.3,
    w: 4,
    h: 7.5,
  },
]
