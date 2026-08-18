"""
Modelos Pydantic que representan la malla curricular.

Cada carrera vive en su propio archivo JSON (ver api/data/mallas/),
con el formato real provisto por la fuente de datos:
    {
      "carrera": "Ingeniería en Ciencias y Sistemas",
      "carrera_id": "ingenieriaEnCienciasYSistemas",
      "pensum": "CLAR",
      "vigente_desde": 2025,
      "fuente": "...",
      "total_cursos": 75,
      "cursos": [ { "codigo": ..., "nombre": ..., "creditos": ...,
                    "semestre": ..., "prerequisitos": [...],
                    "obligatorio": true }, ... ]
    }

IMPORTANTE: el mismo código de curso puede aparecer en varias carreras
con un `semestre` y/o `prerequisitos` distintos (cursos de área común
ubicados en puntos diferentes de cada pénsum). Por eso la malla NO se
fusiona en un solo diccionario global código -> Curso; se mantiene
separada por carrera (ver `CarreraMalla` / `config.cargar_carreras`).

Estos modelos se usan tanto para validar los JSON estáticos que se
cargan al iniciar la app, como para las respuestas de la API.
"""

from typing import Dict, List, Optional
from pydantic import BaseModel, Field


class HorarioDisponible(BaseModel):
    """Una opción de horario/sección para un curso.

    Nota: los datos reales de `api/data/mallas/` NO incluyen horarios
    (no hay profesor/día/hora/aula por curso), así que en la práctica
    esta lista queda vacía para esos cursos. Se conserva el modelo
    para no romper el endpoint /api/generar-horario, que sigue
    funcionando con el JSON de ejemplo `data/malla_curricular.json`.
    """

    profesor: str
    dias: str
    hora: str
    aula: str


class Curso(BaseModel):
    """Representa un curso dentro de la malla curricular de una carrera."""

    nombre: str
    codigo: str
    semestre_oficial: int = Field(..., ge=1, description="Semestre en que se ubica oficialmente el curso")
    creditos: int = Field(..., ge=0)
    prerequisitos: List[str] = Field(default_factory=list)
    postrequisitos: List[str] = Field(
        default_factory=list,
        description="Calculado automáticamente invirtiendo 'prerequisitos' dentro de la misma carrera.",
    )
    obligatorio: bool = Field(
        default=True,
        description="true/false tal como viene en los datos fuente. "
        "(Pendiente de refinar a categorías obligatorio/electivo/optativo más adelante.)",
    )
    carrera_id: Optional[str] = Field(
        default=None,
        description="Identificador de la carrera dueña de este curso dentro de su malla (ej: 'ingenieriaCivil').",
    )
    horarios_disponibles: List[HorarioDisponible] = Field(default_factory=list)


class CarreraInfo(BaseModel):
    """Metadatos de una carrera/pénsum, tomados directamente del JSON fuente."""

    carrera: str
    carrera_id: str
    pensum: Optional[str] = None
    vigente_desde: Optional[int] = None
    fuente: Optional[str] = None
    total_cursos: Optional[int] = None


class CarreraMalla(BaseModel):
    """La malla curricular completa de una carrera: metadatos + cursos por código."""

    info: CarreraInfo
    cursos: Dict[str, Curso]


# Clave usada para identificar cada malla cargada: el nombre de archivo
# sin extensión (ej. "ingenieriaEnCienciasYSistemas_2025"), porque una
# misma carrera puede tener más de un pénsum vigente (2022 y 2025 para
# Ciencias y Sistemas, por ejemplo) y `carrera_id` por sí solo no es único.
MallaPorCarrera = Dict[str, CarreraMalla]

# Malla plana usada por el flujo de demo/horarios: código -> Curso.
MallaCurricular = dict[str, Curso]
