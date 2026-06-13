from fastapi import FastAPI
from pydantic import BaseModel
from typing import Dict

# Inicializamos la aplicación
app = FastAPI(
    title="API Datos - SmartParking",
    description="Servidor central para la gestión de estados de estacionamiento."
)

# Simularemos una base de datos en memoria RAM (diccionario)
# En una Fase 3, esto se puede conectar a MySQL o PostgreSQL
memoria_plazas: Dict[str, str] = {}

# Definimos la estructura de datos que esperamos recibir
class ActualizacionPlaza(BaseModel):
    estado_plazas: Dict[str, str]

@app.post("/actualizar_estado")
def recibir_datos_edge(datos: ActualizacionPlaza):
    """
    Ruta que utilizara el Contenedor 1 (Cámara/YOLO) para inyectar los estados.
    """
    global memoria_plazas
    
    # Actualizamos el diccionario con los datos frescos
    memoria_plazas.update(datos.estado_plazas)
    
    return {
        "mensaje": "Sincronizacion exitosa", 
        "plazas_registradas": len(memoria_plazas)
    }

@app.get("/estado_plazas")
def enviar_datos_frontend():
    """
    Ruta que utilizara el Contenedor 3 (Página Web) para leer como están los estacionamientos.
    """
    return {"plazas": memoria_plazas}