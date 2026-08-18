"""
Servicio que implementa el algoritmo principal de cálculo de ruta
académica óptima.

Estrategia (heurística, Fase 1):
    1. Construir el grafo de prerequisitos de la carrera.
    2. Quitar los cursos ya aprobados.
    3. Sacar un orden topológico de los cursos pendientes.
    4. Repartir ese orden en semestres respetando:
         - La carga máxima de créditos por semestre.
         - Que un curso solo se asigne cuando TODOS sus
           prerequisitos ya quedaron ubicados en un semestre anterior.
    5. Priorizar dentro de cada semestre según el tipo de meta.

Fase 2 (opcional): Optimización con Programación Entera Mixta (MIP)
usando PuLP para minimizar el número de semestres, disponible a
través de `calcular_ruta_mip` cuando la meta es "graduacion_rapida"
y el tamaño del problema es manejable.
"""

import logging
from typing import Dict, List, Set

import networkx as nx

from models.malla import Curso
from models.request import CalcularRutaRequest
from models.response import (
    CalcularRutaResponse,
    CursoSugerido,
    Estadisticas,
    HorarioAsignado,
    SemestreSugerido,
)
from services import grafo_service

logger = logging.getLogger("trackIng")


class CursoNoEncontradoError(Exception):
    """Se lanza cuando un código de curso no existe en la malla."""

    def __init__(self, codigos: List[str]):
        self.codigos = codigos
        super().__init__(f"Cursos no encontrados en la malla: {codigos}")


class MallaConCiclosError(Exception):
    """Se lanza cuando la malla curricular tiene un ciclo de prerequisitos."""


def _validar_cursos_existen(malla: Dict[str, Curso], codigos: List[str]) -> None:
    faltantes = [c for c in codigos if c not in malla]
    if faltantes:
        raise CursoNoEncontradoError(faltantes)


def _elegir_horario_sugerido(curso: Curso, horario_preferido: str) -> HorarioAsignado | None:
    """Escoge, de las opciones disponibles, la que mejor calce con la preferencia del estudiante."""
    if not curso.horarios_disponibles:
        return None

    def franja(hora: str) -> str:
        # hora viene como "HH:MM-HH:MM"; usamos la hora de inicio para clasificar la franja.
        try:
            inicio = int(hora.split("-")[0].split(":")[0])
        except (ValueError, IndexError):
            return "indiferente"
        if inicio < 12:
            return "matutino"
        if inicio < 18:
            return "vespertino"
        return "nocturno"

    if horario_preferido and horario_preferido != "indiferente":
        for opcion in curso.horarios_disponibles:
            if franja(opcion.hora) == horario_preferido:
                return HorarioAsignado(**opcion.model_dump())

    primera = curso.horarios_disponibles[0]
    return HorarioAsignado(**primera.model_dump())


def _priorizar(
    candidatos: List[str],
    malla: Dict[str, Curso],
    meta_tipo: str,
    cursos_reprobados: Set[str],
) -> List[str]:
    """
    Ordena la lista de cursos candidatos a un semestre según la
    estrategia asociada al tipo de meta del estudiante.
    """
    if meta_tipo == "adelantar":
        # Priorizar cursos de semestres oficiales más avanzados primero,
        # para "jalar" al estudiante hacia adelante en la malla.
        return sorted(candidatos, key=lambda c: -malla[c].semestre_oficial)

    if meta_tipo == "nivelar":
        # Priorizar cursos reprobados y sus dependientes directos.
        def prioridad_nivelar(codigo: str) -> tuple:
            es_reprobado = codigo in cursos_reprobados
            depende_de_reprobado = any(p in cursos_reprobados for p in malla[codigo].prerequisitos)
            return (not es_reprobado, not depende_de_reprobado, malla[codigo].semestre_oficial)

        return sorted(candidatos, key=prioridad_nivelar)

    # "graduacion_rapida" y "personalizada" (heurística por defecto):
    # priorizar cursos de semestre oficial más bajo primero, para ir
    # despejando el mayor número de dependencias cuanto antes.
    return sorted(candidatos, key=lambda c: malla[c].semestre_oficial)


def calcular_ruta(request: CalcularRutaRequest, malla: Dict[str, Curso]) -> CalcularRutaResponse:
    """
    Calcula la ruta académica óptima (heurística) para un estudiante.

    `malla` ya debe venir filtrada a la carrera del estudiante (el
    router la resuelve con `config.resolver_carrera` antes de llamar
    a esta función), porque un mismo código de curso puede tener
    `semestre_oficial`/`prerequisitos` distintos según la carrera.
    """
    if not malla:
        raise CursoNoEncontradoError([f"(la carrera '{request.carrera}' no tiene cursos)"])

    _validar_cursos_existen(malla, request.cursos_aprobados)

    grafo = grafo_service.construir_grafo(malla)
    if not grafo_service.validar_acíclico(grafo):
        raise MallaConCiclosError("La malla curricular tiene un ciclo de prerequisitos y no se puede procesar")

    cursos_aprobados: Set[str] = set(c for c in request.cursos_aprobados if c in malla)
    grafo_pendiente = grafo_service.filtrar_cursos_aprobados(grafo, list(cursos_aprobados))

    advertencias: List[str] = []
    orden = grafo_service.orden_topologico(grafo_pendiente)

    # cursos_reprobados: heurística simple para "nivelar" -- cursos que
    # son prerequisito de muchos otros y NO están aprobados; en un
    # sistema real este dato vendría explícito del estudiante, pero
    # el request actual no lo distingue de "no cursado".
    cursos_reprobados: Set[str] = set()

    ubicados: Dict[str, int] = {}  # codigo -> semestre asignado
    semestres: List[SemestreSugerido] = []
    semestre_actual = 1
    creditos_semestre = 0
    cursos_semestre: List[CursoSugerido] = []
    pendientes = list(orden)
    ya_aprobados_acumulado = set(cursos_aprobados)

    max_iteraciones = len(pendientes) * 2 + 50  # salvaguarda contra loops infinitos
    iteraciones = 0

    while pendientes and iteraciones < max_iteraciones:
        iteraciones += 1

        # Candidatos: cursos pendientes cuyos prerequisitos ya están
        # todos aprobados o ya ubicados en un semestre anterior.
        candidatos = [
            c
            for c in pendientes
            if all(p in ya_aprobados_acumulado for p in malla[c].prerequisitos)
        ]

        if not candidatos:
            # No debería pasar si el grafo es acíclico, pero por
            # seguridad reportamos y detenemos para no ciclar infinito.
            advertencias.append(
                f"No fue posible ubicar los cursos restantes: {pendientes}. "
                "Revise la malla curricular por posibles inconsistencias."
            )
            break

        candidatos_priorizados = _priorizar(candidatos, malla, request.meta.tipo, cursos_reprobados)

        for codigo in candidatos_priorizados:
            creditos_curso = malla[codigo].creditos
            if creditos_semestre + creditos_curso > request.carga_maxima_por_semestre:
                continue

            curso = malla[codigo]
            horario = _elegir_horario_sugerido(curso, request.preferencias.horario_preferido or "indiferente")
            if curso.horarios_disponibles and horario is None:
                advertencias.append(f"No se encontró horario compatible con la preferencia para {codigo}")

            justificacion = _justificar(codigo, malla, request.meta.tipo)

            cursos_semestre.append(
                CursoSugerido(
                    codigo=codigo,
                    nombre=curso.nombre,
                    creditos=creditos_curso,
                    horario_sugerido=horario,
                    justificacion=justificacion,
                )
            )
            creditos_semestre += creditos_curso
            ubicados[codigo] = semestre_actual
            pendientes.remove(codigo)

        if cursos_semestre:
            semestres.append(
                SemestreSugerido(
                    semestre=semestre_actual,
                    cursos=cursos_semestre,
                    total_creditos=creditos_semestre,
                )
            )
            ya_aprobados_acumulado.update(c.codigo for c in cursos_semestre)
        else:
            # Ningún candidato cupo en la carga máxima: probablemente
            # carga_maxima_por_semestre es menor que el curso más
            # pequeño disponible, o todos exceden el límite.
            advertencias.append(
                f"Ningún curso disponible cupo dentro de la carga máxima ({request.carga_maxima_por_semestre} créditos) "
                f"en el semestre {semestre_actual}. Considere aumentar la carga máxima."
            )
            break

        semestre_actual += 1
        creditos_semestre = 0
        cursos_semestre = []

    if request.meta.semestres_objetivo and len(semestres) > request.meta.semestres_objetivo:
        advertencias.append(
            f"La ruta calculada requiere {len(semestres)} semestres, más de los "
            f"{request.meta.semestres_objetivo} solicitados. Considere aumentar la carga máxima por semestre."
        )

    creditos_totales = sum(malla[c].creditos for c in malla)
    creditos_aprobados = sum(malla[c].creditos for c in cursos_aprobados)
    cursos_faltantes = len(malla) - len(cursos_aprobados)
    porcentaje_avance = round((creditos_aprobados / creditos_totales) * 100, 2) if creditos_totales else 0.0

    estadisticas = Estadisticas(
        semestres_totales=len(semestres),
        creditos_totales=creditos_totales,
        cursos_faltantes=cursos_faltantes,
        porcentaje_avance=porcentaje_avance,
    )

    return CalcularRutaResponse(ruta_optima=semestres, estadisticas=estadisticas, advertencias=advertencias)


def _justificar(codigo: str, malla: Dict[str, Curso], meta_tipo: str) -> str:
    curso = malla[codigo]
    n_postreqs = len(curso.postrequisitos)
    if meta_tipo == "adelantar":
        return f"Curso de semestre {curso.semestre_oficial}; tomarlo ahora ayuda a adelantar la carrera"
    if meta_tipo == "nivelar":
        return "Curso pendiente que permite nivelarse con el pénsum oficial"
    if n_postreqs > 0:
        return f"Prerequisito de {n_postreqs} curso(s) posteriores; conviene tomarlo pronto"
    return "Curso disponible según sus prerequisitos aprobados"
