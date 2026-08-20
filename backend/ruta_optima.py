# -*- coding: utf-8 -*-
"""
ruta_optima.py
================
Algoritmos de planificación académica para TrackIng.

Adaptado al esquema real de las mallas curriculares de la Facultad de
Ingeniería de la USAC (las que exporta redesEstudio), donde cada curso
tiene esta forma:

    {
        "codigo": "0101",
        "nombre": "Área Matemática Básica 1",
        "creditos": 9,
        "semestre": 1,
        "prerequisitos": [],
        "obligatorio": true
    }

Esas mallas NO incluyen horas teóricas ni de laboratorio (solo créditos),
así que para la ruta de vacaciones (que sí necesita horas teóricas) este
módulo usa el número de créditos como aproximación cuando el curso no
trae "horas_teoricas" explícito. Si en algún momento tienes datos reales
de horas (por ejemplo en horarios_vacaciones.json), basta con agregar
"horas_teoricas" / "horas_laboratorio" a esos cursos y se usarán en lugar
de la aproximación. Ver `horas_teoricas_de` y `horas_laboratorio_de`.

Contiene dos algoritmos independientes:

- calcular_ruta_regular:
    Asignación dinámica por "slots" semestrales (no por el campo
    "semestre" estático del pénsum). Cada slot se llena hasta el límite
    de créditos del estudiante, sin respetar ciegamente el orden del
    pénsum, y permite reprogramar cursos reprobados en el primer slot
    futuro con cupo disponible, siempre validando estrictamente los
    prerequisitos.

- calcular_ruta_vacaciones:
    Planifica periodos vacacionales respetando un límite de 4 horas
    teóricas (excluyendo horas de laboratorio), filtrando únicamente
    cursos publicados en el horario vacacional, permitiendo optativos
    que desbloqueen obligatorios futuros, y limitando a 3 cursos por
    periodo.

Ambas funciones retornan diccionarios con la misma forma:
    {clave_periodo: [lista_de_cursos]}
donde cada curso es el diccionario original tal como aparece en la malla
curricular (codigo, nombre, creditos, semestre, obligatorio,
prerequisitos, ...).

Compatible con Windows, Python 3.13 y NetworkX 3.6.1. Única dependencia
externa: networkx.
"""

from __future__ import annotations

from typing import Iterable

import networkx as nx


class RutaOptimaError(Exception):
    """
    Error de dominio para la planificación académica.

    Se lanza cuando la malla curricular contiene un ciclo de
    prerequisitos, cuando existen cursos bloqueados sin una combinación
    de prerequisitos alcanzable, o cuando un curso individual excede por
    sí solo el límite de créditos/horas disponible.
    """


# ---------------------------------------------------------------------------
# Helpers de horas (las mallas de USAC solo traen créditos)
# ---------------------------------------------------------------------------

def horas_teoricas_de(curso: dict) -> float:
    """
    Horas teóricas semanales de un curso.

    Las mallas oficiales de USAC (redesEstudio) no incluyen este campo,
    así que si no está presente se usa el número de créditos como
    aproximación razonable. Si tu curso sí trae "horas_teoricas" (por
    ejemplo porque lo agregaste manualmente en horarios_vacaciones.json),
    ese valor tiene prioridad sobre la aproximación.
    """
    if "horas_teoricas" in curso and curso["horas_teoricas"] is not None:
        return curso["horas_teoricas"]
    return curso.get("creditos", 0)


def horas_laboratorio_de(curso: dict) -> float:
    """Horas de laboratorio semanales; 0 si el curso no las especifica."""
    return curso.get("horas_laboratorio", 0) or 0


def _es_obligatorio(curso: dict) -> bool:
    """Un curso sin el campo 'obligatorio' se asume obligatorio por defecto."""
    return bool(curso.get("obligatorio", True))


# ---------------------------------------------------------------------------
# Utilidades internas compartidas
# ---------------------------------------------------------------------------

def _construir_grafo(cursos: list[dict]) -> nx.DiGraph:
    """
    Construye el grafo dirigido prerequisito -> curso a partir de la malla.

    Se valida que todo prerequisito referenciado exista en la propia malla,
    para evitar fallos silenciosos por datos inconsistentes.
    """
    grafo = nx.DiGraph()
    por_codigo = {curso["codigo"]: curso for curso in cursos}

    for curso in cursos:
        grafo.add_node(curso["codigo"], **curso)

    for curso in cursos:
        for prereq in curso.get("prerequisitos", []):
            if prereq not in por_codigo:
                raise RutaOptimaError(
                    f"El curso '{curso['codigo']}' ({curso.get('nombre', '')}) "
                    f"declara el prerequisito '{prereq}', que no existe en la "
                    "malla curricular cargada."
                )
            grafo.add_edge(prereq, curso["codigo"])

    return grafo


def _validar_sin_ciclos(grafo: nx.DiGraph) -> None:
    """Lanza RutaOptimaError con el ciclo exacto si la malla no es un DAG."""
    if nx.is_directed_acyclic_graph(grafo):
        return

    ciclo = nx.find_cycle(grafo)
    secuencia = " -> ".join(origen for origen, _destino in ciclo)
    secuencia = f"{secuencia} -> {ciclo[0][0]}"
    raise RutaOptimaError(
        "La malla curricular contiene un ciclo de prerequisitos y no puede "
        f"planificarse: {secuencia}"
    )


def _diagnosticar_bloqueo(
    pendientes: Iterable[str],
    por_codigo: dict[str, dict],
    aprobados_acumulado: set[str],
) -> str:
    """
    Genera un mensaje legible indicando, para cada curso pendiente que no
    pudo entrar en el slot actual, qué prerequisitos le faltan.
    """
    detalle = []
    for codigo in sorted(pendientes):
        curso = por_codigo[codigo]
        faltan = sorted(set(curso.get("prerequisitos", [])) - aprobados_acumulado)
        if faltan:
            detalle.append(f"'{codigo}' ({curso.get('nombre', '')}) requiere {faltan}")
    if not detalle:
        # No debería ocurrir si _validar_sin_ciclos ya se ejecutó, pero se
        # deja como red de seguridad con un mensaje genérico útil.
        detalle.append(
            f"cursos {sorted(pendientes)} no tienen combinación de "
            "prerequisitos alcanzable con lo aprobado hasta el momento."
        )
    return "; ".join(detalle)


# ---------------------------------------------------------------------------
# Ruta regular (slots semestrales dinámicos)
# ---------------------------------------------------------------------------

def calcular_ruta_regular(
    cursos: list[dict],
    aprobados: Iterable[str] | None = None,
    reprobados: Iterable[str] | None = None,
    limite_creditos: int = 37,
) -> dict[str, list[dict]]:
    """
    Calcula la ruta académica regular usando slots semestrales dinámicos.

    A diferencia de una ruta "por pénsum fijo", cada slot se llena hasta el
    límite de créditos disponible combinando cursos de distintos semestres
    oficiales (campo "semestre") cuando sus prerequisitos ya están
    satisfechos. Los cursos reprobados se reintegran a la bolsa de
    pendientes y compiten por el primer slot futuro donde exista cupo, con
    prioridad sobre el resto.

    Solo se planifican cursos con "obligatorio": true (usa
    `inyectar_prerequisitos_optativos` antes de llamar a esta función si
    algún optativo es prerequisito de un obligatorio, para que también se
    incluya). El grafo de prerequisitos se construye con la malla completa
    recibida, para poder validar cualquier tipo de curso.

    Parameters
    ----------
    cursos:
        Lista completa de cursos de la malla (dict con al menos codigo,
        nombre, creditos, obligatorio, prerequisitos).
    aprobados:
        Códigos de cursos ya aprobados por el estudiante.
    reprobados:
        Códigos de cursos que el estudiante cursó y reprobó. Se excluyen
        de "aprobados" para el cálculo y se priorizan en el primer slot
        futuro con cupo.
    limite_creditos:
        Créditos máximos permitidos por slot, según el promedio del
        estudiante.

    Returns
    -------
    dict[str, list[dict]]
        {"Semestre_1": [...], "Semestre_2": [...], ...}

    Raises
    ------
    RutaOptimaError
        Si la malla tiene ciclos, si existen cursos bloqueados sin
        combinación de prerequisitos alcanzable, o si un curso excede por
        sí solo el límite de créditos.
    """
    if limite_creditos <= 0:
        raise RutaOptimaError("El límite de créditos por slot debe ser mayor a 0.")

    aprobados = set(aprobados or [])
    reprobados = set(reprobados or [])

    grafo = _construir_grafo(cursos)
    _validar_sin_ciclos(grafo)

    por_codigo = {curso["codigo"]: curso for curso in cursos}

    # Universo de cursos a planificar: solo obligatorios (tras la posible
    # inyección de optativos-prerequisito hecha por el caller).
    objetivo = {
        codigo for codigo, curso in por_codigo.items() if _es_obligatorio(curso)
    }

    pendientes = {
        codigo for codigo in objetivo
        if codigo not in aprobados or codigo in reprobados
    }
    aprobados_acumulado = (aprobados - reprobados) | {
        codigo for codigo in por_codigo if codigo not in objetivo and codigo in aprobados
    }

    ruta: dict[str, list[dict]] = {}
    slot_index = 0

    while pendientes:
        slot_index += 1
        clave = f"Semestre_{slot_index}"

        candidatos = [
            codigo for codigo in pendientes
            if set(por_codigo[codigo].get("prerequisitos", [])) <= aprobados_acumulado
        ]

        if not candidatos:
            mensaje = _diagnosticar_bloqueo(pendientes, por_codigo, aprobados_acumulado)
            raise RutaOptimaError(
                "No es posible continuar la planificación regular: hay cursos "
                f"bloqueados sin prerequisitos alcanzables -> {mensaje}"
            )

        # Prioridad: 1) reprobados (reprogramar cuanto antes), 2) orden de
        # pénsum ("semestre") como guía suave, 3) mayor cantidad de
        # créditos primero para aprovechar mejor el cupo del slot.
        candidatos.sort(key=lambda c: (
            0 if c in reprobados else 1,
            por_codigo[c].get("semestre", 99),
            -por_codigo[c].get("creditos", 0),
        ))

        creditos_slot = 0
        seleccionados: list[str] = []
        for codigo in candidatos:
            creditos_curso = por_codigo[codigo].get("creditos", 0)
            if creditos_slot + creditos_curso <= limite_creditos:
                seleccionados.append(codigo)
                creditos_slot += creditos_curso

        if not seleccionados:
            codigo_problema = candidatos[0]
            raise RutaOptimaError(
                f"El curso '{codigo_problema}' "
                f"({por_codigo[codigo_problema].get('creditos', 0)} créditos) "
                f"excede por sí solo el límite de créditos permitido "
                f"({limite_creditos}). Ajusta el límite o revisa la malla."
            )

        ruta[clave] = [por_codigo[codigo] for codigo in seleccionados]

        for codigo in seleccionados:
            pendientes.discard(codigo)
            aprobados_acumulado.add(codigo)
            reprobados.discard(codigo)

    return ruta


# ---------------------------------------------------------------------------
# Ruta de vacaciones
# ---------------------------------------------------------------------------

def _desbloquea_obligatorio_futuro(
    codigo_optativo: str,
    grafo: nx.DiGraph,
    por_codigo: dict[str, dict],
    aprobados_acumulado: set[str],
) -> bool:
    """True si aprobar este optativo abre el paso a algún obligatorio pendiente."""
    if codigo_optativo not in grafo:
        return False
    for sucesor in nx.descendants(grafo, codigo_optativo):
        if sucesor in aprobados_acumulado:
            continue
        if _es_obligatorio(por_codigo[sucesor]):
            return True
    return False


def calcular_ruta_vacaciones(
    cursos: list[dict],
    periodos_vacacionales: list[dict],
    aprobados: Iterable[str] | None = None,
    limite_horas_teoricas: float = 4,
    max_cursos_por_periodo: int = 3,
) -> dict[str, list[dict]]:
    """
    Calcula la ruta de cursos vacacionales.

    Reglas:
    - El límite de 4 horas se aplica solo a horas teóricas (ver
      `horas_teoricas_de`, que usa créditos como respaldo cuando la malla
      no trae horas explícitas); las horas de laboratorio no cuentan para
      el límite (pero sí se reportan).
    - Solo se consideran cursos presentes en `cursos_disponibles` de cada
      periodo del JSON de horarios vacacionales.
    - Los optativos solo se incluyen si desbloquean (directa o
      transitivamente) al menos un curso obligatorio aún no aprobado.
    - Máximo `max_cursos_por_periodo` cursos por periodo vacacional.

    Parameters
    ----------
    cursos:
        Malla curricular completa (para validar prerequisitos y tipo).
    periodos_vacacionales:
        Lista de periodos, cada uno con forma
        {"nombre": str, "cursos_disponibles": [codigo, ...]}
        (tal como se cargan de data/horarios_vacaciones.json).
    aprobados:
        Códigos ya aprobados por el estudiante (acumulado hasta el momento
        en que arranca el primer periodo vacacional considerado).
    limite_horas_teoricas:
        Horas teóricas máximas combinadas por periodo (default 4).
    max_cursos_por_periodo:
        Cantidad máxima de cursos por periodo (default 3).

    Returns
    -------
    dict[str, list[dict]]
        {nombre_periodo: [lista_de_cursos]}

    Raises
    ------
    RutaOptimaError
        Si la malla tiene ciclos de prerequisitos.
    """
    aprobados_acumulado = set(aprobados or [])
    por_codigo = {curso["codigo"]: curso for curso in cursos}

    grafo = _construir_grafo(cursos)
    _validar_sin_ciclos(grafo)

    ruta: dict[str, list[dict]] = {}

    for periodo in periodos_vacacionales:
        clave = periodo["nombre"]
        disponibles_json = set(periodo.get("cursos_disponibles", []))

        candidatos = []
        for codigo in disponibles_json:
            if codigo not in por_codigo:
                # Curso publicado en el horario vacacional pero que no
                # pertenece a esta malla curricular: se ignora.
                continue
            if codigo in aprobados_acumulado:
                continue

            curso = por_codigo[codigo]
            prereqs_ok = set(curso.get("prerequisitos", [])) <= aprobados_acumulado
            if not prereqs_ok:
                continue

            if not _es_obligatorio(curso):
                if not _desbloquea_obligatorio_futuro(
                    codigo, grafo, por_codigo, aprobados_acumulado
                ):
                    continue

            candidatos.append(codigo)

        # Prioridad: obligatorios antes que optativos habilitantes; dentro
        # de cada grupo, se favorece a quien más horas teóricas aporta para
        # aprovechar mejor el límite de 4 horas.
        candidatos.sort(key=lambda c: (
            0 if _es_obligatorio(por_codigo[c]) else 1,
            -horas_teoricas_de(por_codigo[c]),
        ))

        horas_slot = 0.0
        seleccionados: list[str] = []
        for codigo in candidatos:
            if len(seleccionados) >= max_cursos_por_periodo:
                break
            horas = horas_teoricas_de(por_codigo[codigo])
            if horas_slot + horas <= limite_horas_teoricas:
                seleccionados.append(codigo)
                horas_slot += horas

        ruta[clave] = [por_codigo[codigo] for codigo in seleccionados]
        aprobados_acumulado.update(seleccionados)

    return ruta


# ---------------------------------------------------------------------------
# Utilidad de inyección de optativos-prerequisito
# ---------------------------------------------------------------------------

def inyectar_prerequisitos_optativos(cursos: list[dict]) -> list[dict]:
    """
    Devuelve una COPIA de la malla donde cualquier curso optativo que sea
    prerequisito -directo o indirecto- de un curso obligatorio queda
    marcado temporalmente como "obligatorio": true.

    Esto evita que `calcular_ruta_regular` (que solo planifica cursos
    obligatorios) omita un optativo que en realidad es indispensable para
    poder cursar un obligatorio posterior.
    """
    cursos_copia = [dict(curso) for curso in cursos]
    por_codigo = {curso["codigo"]: curso for curso in cursos_copia}

    obligatorios_iniciales = [
        curso["codigo"] for curso in cursos_copia if _es_obligatorio(curso)
    ]

    marcados: set[str] = set()
    pila = list(obligatorios_iniciales)

    while pila:
        actual = pila.pop()
        curso_actual = por_codigo.get(actual)
        if curso_actual is None:
            continue
        for prereq in curso_actual.get("prerequisitos", []):
            curso_prereq = por_codigo.get(prereq)
            if curso_prereq is None:
                continue
            if not _es_obligatorio(curso_prereq) and prereq not in marcados:
                curso_prereq["obligatorio"] = True
                marcados.add(prereq)
                pila.append(prereq)

    return cursos_copia