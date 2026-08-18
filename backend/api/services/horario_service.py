"""
Servicio de generación de horarios sin conflictos.

Modela el problema como una variante de coloración de grafos:
    - Cada curso es un nodo.
    - Existe una arista entre dos cursos si, para las secciones que
      se les asignarían, sus días y horas se solapan (conflicto).
    - Se usa una heurística greedy ordenando primero los cursos más
      restringidos (menos opciones de horario disponibles), y para
      cada uno se elige la primera sección que no choque con lo ya
      asignado, respetando además las preferencias del estudiante.
"""

import logging
from typing import Dict, List, Set, Tuple

from models.malla import Curso, HorarioDisponible
from models.request import GenerarHorarioRequest
from models.response import BloqueHorario, ConflictoHorario, GenerarHorarioResponse

logger = logging.getLogger("trackIng")


def _parsear_dias(dias: str) -> Set[str]:
    """Convierte un string tipo 'L-M' o 'M-J-V' en un set de días individuales."""
    return set(d.strip().upper() for d in dias.split("-") if d.strip())


def _parsear_hora(hora: str) -> Tuple[int, int]:
    """Convierte 'HH:MM-HH:MM' en (inicio_en_minutos, fin_en_minutos)."""
    inicio_str, fin_str = hora.split("-")
    h_i, m_i = inicio_str.strip().split(":")
    h_f, m_f = fin_str.strip().split(":")
    return int(h_i) * 60 + int(m_i), int(h_f) * 60 + int(m_f)


def _hay_solape(op_a: HorarioDisponible, op_b: HorarioDisponible) -> bool:
    """Determina si dos secciones de horario se solapan en día y hora."""
    dias_a = _parsear_dias(op_a.dias)
    dias_b = _parsear_dias(op_b.dias)
    if not (dias_a & dias_b):
        return False

    try:
        inicio_a, fin_a = _parsear_hora(op_a.hora)
        inicio_b, fin_b = _parsear_hora(op_b.hora)
    except (ValueError, IndexError):
        # Si el formato de hora es inesperado, asumimos conservadoramente que no hay info suficiente.
        return False

    return inicio_a < fin_b and inicio_b < fin_a


def _franja(hora: str) -> str:
    try:
        inicio = int(hora.split("-")[0].split(":")[0])
    except (ValueError, IndexError):
        return "indiferente"
    if inicio < 12:
        return "matutino"
    if inicio < 18:
        return "vespertino"
    return "nocturno"


def _dia_en_libres(dias: str, dias_libres: List[str]) -> bool:
    """Verifica si alguna sección cae en un día que el estudiante quiere libre."""
    dias_curso = _parsear_dias(dias)
    dias_libres_norm = {d.strip().upper()[0] for d in dias_libres}  # primera letra: L, M, X, J, V, S
    return bool(dias_curso & dias_libres_norm)


def generar_horario(request: GenerarHorarioRequest, malla: Dict[str, Curso]) -> GenerarHorarioResponse:
    """
    Genera un horario semanal sin conflictos para la lista de cursos
    solicitada, usando una heurística greedy.
    """
    cursos_faltantes = [c for c in request.cursos if c not in malla]
    cursos_validos = [c for c in request.cursos if c in malla]

    # Ordenar por número de opciones disponibles (menor primero = más restringido).
    cursos_ordenados = sorted(
        cursos_validos,
        key=lambda c: len(malla[c].horarios_disponibles),
    )

    asignados: List[BloqueHorario] = []
    secciones_asignadas: List[Tuple[str, HorarioDisponible]] = []
    conflictos: List[ConflictoHorario] = []
    sin_asignar: List[str] = []

    for codigo in cursos_ordenados:
        curso = malla[codigo]
        opciones = list(curso.horarios_disponibles)

        if not opciones:
            sin_asignar.append(codigo)
            continue

        # Ordenar opciones para priorizar la preferencia del estudiante.
        def puntaje(op: HorarioDisponible) -> tuple:
            no_calza_franja = (
                request.preferencias.horario_preferido not in (None, "indiferente")
                and _franja(op.hora) != request.preferencias.horario_preferido
            )
            cae_en_dia_libre = _dia_en_libres(op.dias, request.preferencias.dias_libres)
            return (no_calza_franja, cae_en_dia_libre)

        opciones.sort(key=puntaje)

        seccion_elegida = None
        for opcion in opciones:
            choca = any(_hay_solape(opcion, asignada) for _, asignada in secciones_asignadas)
            if not choca:
                seccion_elegida = opcion
                break

        if seccion_elegida is None:
            # Ninguna sección libre; reportamos conflicto contra la
            # primera sección propuesta y el curso que ya la ocupaba.
            propuesta = opciones[0]
            for otro_codigo, otra_seccion in secciones_asignadas:
                if _hay_solape(propuesta, otra_seccion):
                    conflictos.append(
                        ConflictoHorario(
                            curso_a=codigo,
                            curso_b=otro_codigo,
                            motivo=f"Horarios solapados: {propuesta.dias} {propuesta.hora} vs {otra_seccion.dias} {otra_seccion.hora}",
                        )
                    )
            sin_asignar.append(codigo)
            continue

        secciones_asignadas.append((codigo, seccion_elegida))
        asignados.append(
            BloqueHorario(
                curso_codigo=codigo,
                curso_nombre=curso.nombre,
                profesor=seccion_elegida.profesor,
                dias=seccion_elegida.dias,
                hora=seccion_elegida.hora,
                aula=seccion_elegida.aula,
            )
        )

    sin_asignar.extend(cursos_faltantes)

    return GenerarHorarioResponse(
        horario=asignados,
        conflictos=conflictos,
        cursos_sin_asignar=sin_asignar,
    )
