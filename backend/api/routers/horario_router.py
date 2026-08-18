"""
Router para la generación de horarios sin conflictos.
"""

import logging

from fastapi import APIRouter, HTTPException

from config import cargar_malla
from models.request import GenerarHorarioRequest
from models.response import GenerarHorarioResponse
from services import horario_service

logger = logging.getLogger("trackIng")
router = APIRouter(tags=["Horario"])


@router.post(
    "/generar-horario",
    response_model=GenerarHorarioResponse,
    summary="Genera un horario semanal sin conflictos para una lista de cursos",
)
def generar_horario(request: GenerarHorarioRequest):
    try:
        malla = cargar_malla()
    except FileNotFoundError as e:
        logger.exception("Error cargando la malla curricular")
        raise HTTPException(status_code=500, detail=str(e))

    codigos_invalidos = [c for c in request.cursos if c not in malla]
    if codigos_invalidos:
        raise HTTPException(
            status_code=400,
            detail=f"Los siguientes cursos no existen en la malla curricular: {codigos_invalidos}",
        )

    try:
        return horario_service.generar_horario(request, malla)
    except Exception:
        logger.exception("Error inesperado generando el horario")
        raise HTTPException(status_code=500, detail="Error interno generando el horario")
