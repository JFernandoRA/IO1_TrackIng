"""
Servicio de validación de prerequisitos: dado un curso y la lista de
cursos aprobados por el estudiante, determina si puede inscribirlo y,
si no, cuáles prerequisitos le faltan.
"""

from typing import Dict, List

from models.malla import Curso
from models.response import ValidarPrerequisitosResponse


def validar_prerequisitos(
    curso_codigo: str, cursos_aprobados: List[str], malla: Dict[str, Curso]
) -> ValidarPrerequisitosResponse:
    codigo = curso_codigo.strip().upper()
    aprobados = set(c.strip().upper() for c in cursos_aprobados)

    if codigo not in malla:
        return ValidarPrerequisitosResponse(puede_inscribir=False, prerequisitos_faltantes=[], curso_existe=False)

    curso = malla[codigo]
    faltantes = [p for p in curso.prerequisitos if p not in aprobados]

    return ValidarPrerequisitosResponse(
        puede_inscribir=len(faltantes) == 0,
        prerequisitos_faltantes=faltantes,
        curso_existe=True,
    )
