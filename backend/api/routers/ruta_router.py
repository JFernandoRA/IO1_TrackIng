"""
Router para el cálculo de ruta académica y la validación de
prerequisitos.
"""

import logging
from typing import List

from fastapi import APIRouter, HTTPException, Query

from config import cargar_carreras, resolver_carrera
from models.request import CalcularRutaRequest
from models.response import CalcularRutaResponse, ValidarPrerequisitosResponse
from services import ruta_service, validacion_service
from services.ruta_service import CursoNoEncontradoError, MallaConCiclosError

logger = logging.getLogger("trackIng")
router = APIRouter(tags=["Ruta Académica"])


@router.post(
    "/calcular-ruta",
    response_model=CalcularRutaResponse,
    summary="Calcula la ruta académica óptima según cursos aprobados y meta del estudiante",
)
def calcular_ruta(request: CalcularRutaRequest):
    try:
        carreras = cargar_carreras()
    except FileNotFoundError as e:
        logger.exception("Error cargando las mallas curriculares")
        raise HTTPException(status_code=500, detail=str(e))

    clave = resolver_carrera(request.carrera, carreras)
    if clave is None:
        raise HTTPException(status_code=404, detail=f"No se encontró la carrera '{request.carrera}'")

    malla = carreras[clave].cursos

    try:
        return ruta_service.calcular_ruta(request, malla)
    except CursoNoEncontradoError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except MallaConCiclosError as e:
        raise HTTPException(status_code=500, detail=str(e))
    except Exception:
        logger.exception("Error inesperado calculando la ruta")
        raise HTTPException(status_code=500, detail="Error interno calculando la ruta académica")


@router.get(
    "/validar-prerequisitos",
    response_model=ValidarPrerequisitosResponse,
    summary="Verifica si un estudiante puede inscribir un curso dado sus cursos aprobados",
)
def validar_prerequisitos(
    carrera: str = Query(..., description="Carrera del estudiante, ej: 'ingenieriaCivil' o 'Ingeniería Civil'"),
    curso_codigo: str = Query(..., description="Código del curso a validar, ej: '0028'"),
    cursos_aprobados: List[str] = Query(default=[], description="Lista de códigos de cursos ya aprobados"),
):
    try:
        carreras = cargar_carreras()
    except FileNotFoundError as e:
        logger.exception("Error cargando las mallas curriculares")
        raise HTTPException(status_code=500, detail=str(e))

    clave = resolver_carrera(carrera, carreras)
    if clave is None:
        raise HTTPException(status_code=404, detail=f"No se encontró la carrera '{carrera}'")

    malla = carreras[clave].cursos

    resultado = validacion_service.validar_prerequisitos(curso_codigo, cursos_aprobados, malla)
    if not resultado.curso_existe:
        raise HTTPException(
            status_code=404,
            detail=f"El curso '{curso_codigo}' no existe en la malla de '{carrera}'",
        )
    return resultado
