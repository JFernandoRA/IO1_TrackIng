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
        o bien, si se quiere indicar horas reales del curso vacacional
        (distintas a la aproximación por créditos),
        {"nombre": str, "cursos_disponibles": [
            {"codigo": str, "horas_teoricas": float, "horas_laboratorio": float},
            ...
        ]}
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

        # "cursos_disponibles" acepta dos formas: una lista simple de
        # códigos (string), o una lista de dicts con horas reales del
        # curso vacacional ("codigo", "horas_teoricas", "horas_laboratorio").
        # Esto último tiene prioridad sobre la aproximación por créditos.
        horas_reales: dict[str, tuple[float, float]] = {}
        disponibles_json: set[str] = set()
        for entrada in periodo.get("cursos_disponibles", []):
            if isinstance(entrada, dict):
                codigo = entrada.get("codigo")
                if codigo is None:
                    continue
                disponibles_json.add(codigo)
                if entrada.get("horas_teoricas") is not None or entrada.get("horas_laboratorio") is not None:
                    horas_reales[codigo] = (
                        entrada.get("horas_teoricas", 0) or 0,
                        entrada.get("horas_laboratorio", 0) or 0,
                    )
            else:
                disponibles_json.add(entrada)

        def _horas_teoricas_periodo(codigo: str) -> float:
            if codigo in horas_reales:
                return horas_reales[codigo][0]
            return horas_teoricas_de(por_codigo[codigo])

        def _horas_laboratorio_periodo(codigo: str) -> float:
            if codigo in horas_reales:
                return horas_reales[codigo][1]
            return horas_laboratorio_de(por_codigo[codigo])

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
            -_horas_teoricas_periodo(c),
        ))

        horas_slot = 0.0
        seleccionados: list[str] = []
        for codigo in candidatos:
            if len(seleccionados) >= max_cursos_por_periodo:
                break
            horas = _horas_teoricas_periodo(codigo)
            if horas_slot + horas <= limite_horas_teoricas:
                seleccionados.append(codigo)
                horas_slot += horas

        # Se anota, sobre una copia del curso, las horas reales usadas en
        # este periodo vacacional (si venían en el JSON), para que
        # imprimir_ruta / _totales_periodo reflejen el dato real y no la
        # aproximación por créditos.
        cursos_seleccionados = []
        for codigo in seleccionados:
            curso_copia = dict(por_codigo[codigo])
            if codigo in horas_reales:
                curso_copia["horas_teoricas"] = _horas_teoricas_periodo(codigo)
                curso_copia["horas_laboratorio"] = _horas_laboratorio_periodo(codigo)
            cursos_seleccionados.append(curso_copia)

        ruta[clave] = cursos_seleccionados
        aprobados_acumulado.update(seleccionados)

    return ruta


# ---------------------------------------------------------------------------
# Plan del próximo año (2 semestres + 2 periodos vacacionales)
# ---------------------------------------------------------------------------

MODOS_PLAN_ANUAL = {"avanzar", "nivelarse", "tiempo_normal"}
"""
- "avanzar":       usa siempre el límite máximo de créditos que permite el
                    promedio, para cerrar la carrera lo antes posible.
- "nivelarse":      igual que "avanzar" en cupo (usa el máximo permitido),
                    pero además reporta si con eso alcanza a ponerse al día
                    con los cursos atrasados dentro del horizonte de 1 año,
                    o solo se acerca lo más posible.
- "tiempo_normal":  no adelanta más allá de la carga oficial del pénsum para
                    el semestre que le toca (no se "adelanta" aunque el
                    promedio le permitiría más), salvo lo necesario para no
                    seguir atrasándose.
"""


def calcular_plan_proximo_anio(
    cursos: list[dict],
    periodos_vacacionales: list[dict],
    semestre_actual: int,
    aprobados: Iterable[str] | None = None,
    reprobados: Iterable[str] | None = None,
    limite_creditos: int = 37,
    modo: str = "nivelarse",
) -> dict:
    """
    Arma el plan de los próximos 4 periodos a partir de dónde va el
    estudiante: Semestre, Vacaciones, Semestre, Vacaciones (2 semestres +
    2 periodos vacacionales, en ese orden intercalado).

    Es una capa sobre `calcular_ruta_regular` / `calcular_ruta_vacaciones`
    pensada para responder directamente la pregunta "¿qué debo llevar el
    próximo año?", en vez de tener que armar la ruta completa hasta el
    cierre de la carrera.

    Parameters
    ----------
    cursos:
        Malla curricular completa (usa `inyectar_prerequisitos_optativos`
        antes de llamar a esta función si aplica, igual que con
        `calcular_ruta_regular`).
    periodos_vacacionales:
        Periodos vacacionales disponibles, en el orden en que ocurrirán;
        se toman como máximo los primeros 2 (uno después de cada semestre
        planificado). Ver `calcular_ruta_vacaciones` para el formato.
    semestre_actual:
        Semestre oficial del pénsum en el que va el estudiante ahora mismo
        (se usa solo para: (a) nombrar los slots resultantes, y (b)
        determinar qué cursos obligatorios de semestres ANTERIORES a este
        están "atrasados" si no aparecen en `aprobados`; los cursos del
        propio `semestre_actual` no cuentan como atraso, ya que se asume
        que el estudiante los está cursando/por cursar ahora).
    aprobados:
        Códigos de cursos que el estudiante ya tiene ganados.
    reprobados:
        Códigos de cursos que el estudiante cursó y perdió (se excluyen de
        "aprobados" y se priorizan para reprogramarse cuanto antes).
    limite_creditos:
        Créditos máximos por semestre según el promedio del estudiante
        (ver `calcular_limite_creditos` en test_algoritmo.py / plan_anual.py).
    modo:
        "avanzar" | "nivelarse" | "tiempo_normal". Ver `MODOS_PLAN_ANUAL`.

    Returns
    -------
    dict con:
        "periodos": {clave_periodo: [cursos]} en orden cronológico.
        "atrasados_iniciales": cursos obligatorios de semestre ANTERIOR a
            semestre_actual que el estudiante NO tiene ganados al arrancar.
        "atrasados_restantes": subconjunto de los anteriores que siguen
            sin ganarse al final del plan de 1 año.
        "nivelado": True si "atrasados_restantes" quedó vacío, es decir,
            si en este horizonte de 1 año alcanzó a ponerse al día.
        "modo": el modo usado.

    Raises
    ------
    RutaOptimaError
        Si `modo` no es válido, o por las mismas razones que
        `calcular_ruta_regular` / `calcular_ruta_vacaciones`.
    """
    if modo not in MODOS_PLAN_ANUAL:
        raise RutaOptimaError(
            f"Modo de planificación inválido: '{modo}'. "
            f"Debe ser uno de {sorted(MODOS_PLAN_ANUAL)}."
        )

    por_codigo = {curso["codigo"]: curso for curso in cursos}

    aprob_actual = set(aprobados or [])
    reprob_actual = set(reprobados or [])

    atrasados_iniciales = sorted(
        codigo for codigo, curso in por_codigo.items()
        if _es_obligatorio(curso)
        and curso.get("semestre", 0) < semestre_actual
        and (codigo not in aprob_actual or codigo in reprob_actual)
    )

    def _creditos_oficiales_semestre(semestre_oficial: int) -> int:
        return sum(
            curso.get("creditos", 0) for curso in cursos
            if _es_obligatorio(curso) and curso.get("semestre") == semestre_oficial
        )

    periodos_out: dict[str, list[dict]] = {}
    semestre_oficial_objetivo = semestre_actual
    vac_idx = 0

    for indice_semestre in range(2):
        pendientes_obligatorios = {
            curso["codigo"] for curso in cursos
            if _es_obligatorio(curso)
            and (curso["codigo"] not in aprob_actual or curso["codigo"] in reprob_actual)
        }
        if not pendientes_obligatorios:
            break  # ya no quedan cursos obligatorios: la carrera se cierra antes.

        limite_efectivo = limite_creditos
        if modo == "tiempo_normal":
            normal = _creditos_oficiales_semestre(semestre_oficial_objetivo)
            if normal:
                limite_efectivo = min(limite_creditos, normal)
        semestre_oficial_objetivo += 1

        parcial = calcular_ruta_regular(
            cursos,
            aprobados=aprob_actual,
            reprobados=reprob_actual,
            limite_creditos=limite_efectivo,
        )
        primera_clave = next(iter(parcial))
        cursos_semestre = parcial[primera_clave]
        clave_final = f"Semestre_{semestre_actual + indice_semestre}"
        periodos_out[clave_final] = cursos_semestre

        for curso in cursos_semestre:
            aprob_actual.add(curso["codigo"])
            reprob_actual.discard(curso["codigo"])

        if vac_idx < len(periodos_vacacionales):
            periodo = periodos_vacacionales[vac_idx]
            vac_idx += 1
            resultado_vac = calcular_ruta_vacaciones(
                cursos, [periodo], aprobados=aprob_actual
            )
            clave_vac = next(iter(resultado_vac))
            periodos_out[clave_vac] = resultado_vac[clave_vac]
            for curso in resultado_vac[clave_vac]:
                aprob_actual.add(curso["codigo"])

    atrasados_restantes = sorted(
        codigo for codigo in atrasados_iniciales if codigo not in aprob_actual
    )

    return {
        "periodos": periodos_out,
        "atrasados_iniciales": atrasados_iniciales,
        "atrasados_restantes": atrasados_restantes,
        "nivelado": len(atrasados_restantes) == 0,
        "modo": modo,
    }


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