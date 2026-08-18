"""
Modelos Pydantic para los cuerpos (bodies) de las peticiones de la API.
"""

from typing import List, Literal, Optional
from pydantic import BaseModel, Field, field_validator


class Meta(BaseModel):
    """Meta académica que el estudiante quiere alcanzar."""

    tipo: Literal["adelantar", "nivelar", "graduacion_rapida", "personalizada"]
    semestres_objetivo: Optional[int] = Field(
        default=None, ge=1, description="Número de semestres en los que el estudiante quiere graduarse"
    )


class Preferencias(BaseModel):
    """Preferencias de horario del estudiante."""

    horario_preferido: Optional[Literal["matutino", "vespertino", "nocturno", "indiferente"]] = "indiferente"
    evitar_vacaciones: bool = False
    dias_libres: List[str] = Field(default_factory=list)


class CalcularRutaRequest(BaseModel):
    """Body de POST /api/calcular-ruta."""

    carrera: str
    cursos_aprobados: List[str] = Field(default_factory=list)
    meta: Meta
    carga_maxima_por_semestre: int = Field(default=25, ge=1, le=60)
    preferencias: Preferencias = Field(default_factory=Preferencias)

    @field_validator("cursos_aprobados")
    @classmethod
    def normalizar_codigos(cls, v: List[str]) -> List[str]:
        return [codigo.strip().upper() for codigo in v]


class GenerarHorarioRequest(BaseModel):
    """Body de POST /api/generar-horario."""

    cursos: List[str] = Field(..., min_length=1)
    preferencias: Preferencias = Field(default_factory=Preferencias)

    @field_validator("cursos")
    @classmethod
    def normalizar_codigos(cls, v: List[str]) -> List[str]:
        return [codigo.strip().upper() for codigo in v]
