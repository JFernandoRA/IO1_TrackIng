"""
Configuración general de la aplicación.

Carga la malla curricular desde el archivo JSON estático una sola vez
(al importar este módulo) y la deja disponible en memoria para todos
los servicios. Esto evita leer el archivo en cada petición, lo cual
es importante en un entorno serverless donde cada "cold start"
debería ser lo más rápido posible.
"""

import json
import logging
import os
import unicodedata
from functools import lru_cache
from typing import Dict, Optional

from models.malla import CarreraInfo, CarreraMalla, Curso

logger = logging.getLogger("trackIng")
logging.basicConfig(level=logging.INFO)

# Ruta absoluta a los datos, calculada de forma relativa a este archivo
# para que funcione tanto en local como en Vercel (serverless).
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# JSON de ejemplo (12 cursos, carrera "sistemas", con horarios ficticios).
# Solo lo usa /api/generar-horario, porque las mallas reales no traen
# datos de horario (ver cargar_carreras más abajo).
MALLA_PATH = os.path.join(BASE_DIR, "data", "malla_curricular.json")

# Carpeta con las mallas curriculares reales, una archivo por carrera
# (y potencialmente más de un pénsum por carrera, ej. 2022 y 2025).
MALLAS_DIR = os.path.join(BASE_DIR, "data", "mallas")


@lru_cache(maxsize=1)
def cargar_malla() -> Dict[str, Curso]:
    """
    Carga y valida el JSON de ejemplo (malla_curricular.json).

    Se usa exclusivamente para /api/generar-horario, que necesita el
    campo `horarios_disponibles` (profesor/día/hora/aula) que las
    mallas reales de `data/mallas/` no incluyen.
    """
    if not os.path.exists(MALLA_PATH):
        logger.error("No se encontró el archivo de malla curricular en %s", MALLA_PATH)
        raise FileNotFoundError(f"No se encontró malla_curricular.json en {MALLA_PATH}")

    with open(MALLA_PATH, "r", encoding="utf-8") as f:
        data_raw = json.load(f)

    malla: Dict[str, Curso] = {}
    for codigo, datos in data_raw.items():
        # Aseguramos que el código dentro del objeto coincida con la llave.
        datos.setdefault("codigo", codigo)
        malla[codigo.upper()] = Curso(**datos)

    logger.info("Malla de ejemplo cargada con %d cursos", len(malla))
    return malla


@lru_cache(maxsize=1)
def cargar_carreras() -> Dict[str, CarreraMalla]:
    """
    Carga todas las mallas curriculares reales desde `data/mallas/`
    (un archivo JSON por carrera/pénsum, formato: carrera, carrera_id,
    pensum, vigente_desde, fuente, total_cursos, cursos: [...]).

    Cada malla queda separada por carrera (no se fusiona todo en un
    solo diccionario código -> Curso) porque un mismo código de curso
    puede tener `semestre` y/o `prerequisitos` distintos según la
    carrera en la que esté matriculado.

    La llave del diccionario resultante es el nombre de archivo sin
    extensión (ej. "ingenieriaEnCienciasYSistemas_2025"), ya que
    `carrera_id` por sí solo no es único cuando hay más de un pénsum
    vigente para la misma carrera.
    """
    if not os.path.isdir(MALLAS_DIR):
        logger.error("No se encontró la carpeta de mallas curriculares en %s", MALLAS_DIR)
        raise FileNotFoundError(f"No se encontró la carpeta de mallas en {MALLAS_DIR}")

    carreras: Dict[str, CarreraMalla] = {}

    for filename in sorted(os.listdir(MALLAS_DIR)):
        if not filename.endswith(".json"):
            continue

        path = os.path.join(MALLAS_DIR, filename)
        with open(path, "r", encoding="utf-8") as f:
            raw = json.load(f)

        carrera_id = raw["carrera_id"]
        info = CarreraInfo(
            carrera=raw["carrera"],
            carrera_id=carrera_id,
            pensum=raw.get("pensum"),
            vigente_desde=raw.get("vigente_desde"),
            fuente=raw.get("fuente"),
            total_cursos=raw.get("total_cursos"),
        )

        cursos: Dict[str, Curso] = {}
        for c in raw.get("cursos", []):
            codigo = str(c["codigo"]).strip().upper()
            cursos[codigo] = Curso(
                nombre=c["nombre"],
                codigo=codigo,
                semestre_oficial=c["semestre"],
                creditos=c["creditos"],
                prerequisitos=[str(p).strip().upper() for p in c.get("prerequisitos", [])],
                postrequisitos=[],  # se calcula abajo, invirtiendo prerequisitos
                obligatorio=c.get("obligatorio", True),
                carrera_id=carrera_id,
                horarios_disponibles=[],  # no disponible en los datos reales
            )

        # postrequisitos = inverso de prerequisitos, dentro de esta misma carrera.
        for codigo, curso in cursos.items():
            for prereq in curso.prerequisitos:
                if prereq in cursos:
                    cursos[prereq].postrequisitos.append(codigo)
                # Si el prerequisito no existe en esta malla (dato faltante/typo
                # en la fuente), lo ignoramos igual que hace grafo_service.

        clave = os.path.splitext(filename)[0]
        carreras[clave] = CarreraMalla(info=info, cursos=cursos)

    logger.info("Cargadas %d mallas curriculares reales desde %s", len(carreras), MALLAS_DIR)
    return carreras


def _normalizar_texto(texto: str) -> str:
    """minúsculas + sin acentos, para comparar 'Ingeniería Civil' con 'ingenieria civil'."""
    texto = texto.strip().lower()
    texto = unicodedata.normalize("NFD", texto)
    return "".join(ch for ch in texto if unicodedata.category(ch) != "Mn")


def resolver_carrera(carrera: str, carreras: Dict[str, CarreraMalla]) -> Optional[str]:
    """
    Encuentra la llave real (ej. "ingenieriaCivil_2022") a partir de lo
    que escriba el usuario: puede ser la llave exacta, el `carrera_id`
    (ej. "ingenieriaCivil"), o el nombre de la carrera (ej. "Ingeniería
    Civil"), sin distinguir mayúsculas/acentos.

    Cuando el texto coincide con varias mallas de la misma carrera
    (varios pénsums, ej. Ciencias y Sistemas 2022 y 2025), se prefiere
    la de `vigente_desde` más reciente.
    """
    objetivo = _normalizar_texto(carrera)

    # 1) Coincidencia exacta con la llave de archivo.
    for clave in carreras:
        if _normalizar_texto(clave) == objetivo:
            return clave

    # 2) Coincidencia con carrera_id o nombre de carrera; si hay varias
    #    (varios pénsums), se toma la de vigente_desde más alto.
    candidatas = [
        clave
        for clave, malla in carreras.items()
        if _normalizar_texto(malla.info.carrera_id) == objetivo
        or _normalizar_texto(malla.info.carrera) == objetivo
    ]
    if not candidatas:
        return None

    return max(candidatas, key=lambda clave: carreras[clave].info.vigente_desde or 0)


# Constantes de negocio
CARGA_MAXIMA_DEFECTO = 25
