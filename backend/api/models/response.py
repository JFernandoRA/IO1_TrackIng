"""
Modelos Pydantic para las respuestas de la API.
"""

from typing import Dict, List, Optional
from pydantic import BaseModel


class HorarioAsignado(BaseModel):
    profesor: Optional[str] = None
    dias: Optional[str] = None
    hora: Optional[str] = None
    aula: Optional[str] = None


class CursoSugerido(BaseModel):
    codigo: str
    nombre: str
    creditos: int
    horario_sugerido: Optional[HorarioAsignado] = None
    justificacion: str


class SemestreSugerido(BaseModel):
    semestre: int
    cursos: List[CursoSugerido]
    total_creditos: int


class Estadisticas(BaseModel):
    semestres_totales: int
    creditos_totales: int
    cursos_faltantes: int
    porcentaje_avance: float


class CalcularRutaResponse(BaseModel):
    ruta_optima: List[SemestreSugerido]
    estadisticas: Estadisticas
    advertencias: List[str] = []


class BloqueHorario(BaseModel):
    curso_codigo: str
    curso_nombre: str
    profesor: str
    dias: str
    hora: str
    aula: str


class ConflictoHorario(BaseModel):
    curso_a: str
    curso_b: str
    motivo: str


class GenerarHorarioResponse(BaseModel):
    horario: List[BloqueHorario]
    conflictos: List[ConflictoHorario] = []
    cursos_sin_asignar: List[str] = []


class ValidarPrerequisitosResponse(BaseModel):
    puede_inscribir: bool
    prerequisitos_faltantes: List[str] = []
    curso_existe: bool = True
