"""
Router para los endpoints relacionados con la malla curricular.
"""

import logging
from typing import Dict, List, Optional

from fastapi import APIRouter, HTTPException, Query

from config import cargar_carreras, resolver_carrera
from models.malla import CarreraInfo, CarreraMalla

logger = logging.getLogger("trackIng")
router = APIRouter(tags=["Malla Curricular"])


@router.get(
    "/carreras",
    response_model=List[CarreraInfo],
    summary="Lista las carreras disponibles (y sus pénsums) para usar en los demás endpoints",
)
def listar_carreras():
    try:
        carreras = cargar_carreras()
    except FileNotFoundError as e:
        logger.exception("Error cargando las mallas curriculares")
        raise HTTPException(status_code=500, detail=str(e))

    return [malla.info for malla in carreras.values()]


@router.get(
    "/malla",
    response_model=Dict[str, CarreraMalla],
    summary="Obtiene la malla curricular completa (o filtrada por carrera)",
)
def obtener_malla(
    carrera: Optional[str] = Query(
        default=None,
        description="Filtra por carrera: acepta el carrera_id (ej. 'ingenieriaCivil'), "
        "el nombre (ej. 'Ingeniería Civil') o la llave exacta con año (ej. "
        "'ingenieriaEnCienciasYSistemas_2025'). Ver GET /api/carreras para las opciones válidas.",
    )
):
    try:
        carreras = cargar_carreras()
    except FileNotFoundError as e:
        logger.exception("Error cargando las mallas curriculares")
        raise HTTPException(status_code=500, detail=str(e))

    if carrera:
        clave = resolver_carrera(carrera, carreras)
        if clave is None:
            raise HTTPException(status_code=404, detail=f"No se encontró la carrera '{carrera}'")
        return {clave: carreras[clave]}

    return carreras
