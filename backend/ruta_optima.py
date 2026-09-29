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
    solo_vacaciones: Iterable[str] | None = None,
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
    solo_vacaciones = set(solo_vacaciones or [])

    grafo = _construir_grafo(cursos)
    _validar_sin_ciclos(grafo)

    por_codigo = {curso["codigo"]: curso for curso in cursos}

    # Cursos que el estudiante no quiere llevar en semestre (solo vacaciones)
    # y todo lo que depende de ellos: esperan a que esos cursos se ganen.
    bloqueados_por_vacaciones = set(solo_vacaciones)
    for codigo in solo_vacaciones:
        if codigo in grafo:
            bloqueados_por_vacaciones |= nx.descendants(grafo, codigo)

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
            and codigo not in solo_vacaciones
        ]

        if not candidatos and solo_vacaciones and pendientes <= bloqueados_por_vacaciones:
            # Lo único que queda depende de cursos reservados para vacaciones.
            if not ruta:
                ruta[clave] = []
            break

        if not candidatos:
            mensaje = _diagnosticar_bloqueo(pendientes, por_codigo, aprobados_acumulado)
            raise RutaOptimaError(
                "No es posible continuar la planificación regular: hay cursos "
                f"bloqueados sin prerequisitos alcanzables -> {mensaje}"
            )

        # Prioridad: 1) reprobados (reprogramar cuanto antes), 2) orden de
        # pénsum ("semestre") como guía suave, 3) mayor cantidad de
        # créditos primero para aprovechar mejor el cupo del slot, 4)
        # código como desempate final puramente determinista (evita que
        # el resultado cambie de una ejecución a otra cuando hay empates
        # reales en semestre y créditos).
        candidatos.sort(key=lambda c: (
            0 if c in reprobados else 1,
            por_codigo[c].get("semestre", 99),
            -por_codigo[c].get("creditos", 0),
            c,
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
    excluir_codigos: Iterable[str] | None = None,
    prioritarios: Iterable[str] | None = None,
) -> dict[str, list[dict]]:
    """
    Calcula la ruta de cursos vacacionales.

    `excluir_codigos`: cursos que el estudiante no quiere llevar en
    vacaciones (solo semestre). `prioritarios`: cursos que solo pueden
    llevarse en vacaciones, por lo que entran primero.

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
    excluir_codigos = set(excluir_codigos or [])
    prioritarios = set(prioritarios or [])
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
        disponibles_json: list[str] = []
        vistos: set[str] = set()
        for entrada in periodo.get("cursos_disponibles", []):
            if isinstance(entrada, dict):
                codigo = entrada.get("codigo")
                if codigo is None:
                    continue
                if entrada.get("horas_teoricas") is not None or entrada.get("horas_laboratorio") is not None:
                    horas_reales[codigo] = (
                        entrada.get("horas_teoricas", 0) or 0,
                        entrada.get("horas_laboratorio", 0) or 0,
                    )
            else:
                codigo = entrada
            if codigo not in vistos:
                vistos.add(codigo)
                disponibles_json.append(codigo)

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
            if codigo in aprobados_acumulado or codigo in excluir_codigos:
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

        # Prioridad: (1) obligatorios antes que optativos habilitantes;
        # (2) el que más horas teóricas aporta, para aprovechar mejor el
        # límite de 4 horas; (3) el de semestre oficial más bajo, para
        # priorizar lo más atrasado/antiguo en el pénsum; (4) código, como
        # desempate final puramente determinista (evita que el resultado
        # cambie de una ejecución a otra cuando hay empates reales).
        candidatos.sort(key=lambda c: (
            0 if c in prioritarios else 1,
            0 if _es_obligatorio(por_codigo[c]) else 1,
            -_horas_teoricas_periodo(c),
            por_codigo[c].get("semestre", 0),
            c,
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
# Cursos no obligatorios: social humanística, idiomas técnicos y créditos
# ---------------------------------------------------------------------------

SOCIAL_HUMANISTICA_CODIGOS = ("0017", "0019", "0010", "0018", "0001")
"""Cursos del área Social Humanística que existen en las mallas cargadas:
Social Humanística 1 y 2, Lógica, Filosofía de la Ciencia y Ética Profesional.
Si agregas otro curso del área a las mallas, basta con añadir su código aquí."""

SOCIAL_HUMANISTICA_REQUERIDOS = 8
"""Para cerrar pénsum se deben completar 8 CRÉDITOS de los 10 disponibles del
área (Social Humanística 1 y 2 = 3+3, Lógica = 1, Filosofía = 1, Ética = 2)."""

IDIOMA_TECNICO_CODIGOS = ("0006", "0008", "0009", "0011")

CREDITOS_PENSUM_10_SEMESTRES = 300
CREDITOS_PENSUM_12_SEMESTRES = 360


def tipo_de_curso(curso: dict) -> str:
    """'social_humanistica' | 'idioma' | 'obligatorio' | 'optativo'."""
    if curso.get("codigo") in SOCIAL_HUMANISTICA_CODIGOS:
        return "social_humanistica"
    if curso.get("codigo") in IDIOMA_TECNICO_CODIGOS:
        return "idioma"
    return "obligatorio" if _es_obligatorio(curso) else "optativo"


def creditos_requeridos_pensum(cursos: list[dict]) -> int:
    """300 créditos (10 semestres) o 360 (carreras de 12 semestres)."""
    ultimo = max((c.get("semestre", 0) or 0 for c in cursos), default=0)
    return CREDITOS_PENSUM_12_SEMESTRES if ultimo >= 11 else CREDITOS_PENSUM_10_SEMESTRES


def excluir_cursos(
    cursos: list[dict],
    excluidos: Iterable[str],
    aprobados: Iterable[str] = (),
) -> tuple[list[dict], set[str]]:
    """
    Quita de la malla los cursos que el estudiante no quiere llevar y, en
    cadena, todo lo que dependa de ellos (no podría cursarse sin ellos).
    Nunca se quita un curso ya aprobado.

    Retorna (cursos_filtrados, codigos_removidos).
    """
    aprobados = set(aprobados)
    hijos: dict[str, list[str]] = {}
    for curso in cursos:
        for prereq in curso.get("prerequisitos", []):
            hijos.setdefault(prereq, []).append(curso["codigo"])

    existentes = {c["codigo"] for c in cursos}
    removidos: set[str] = set()
    pila = [c for c in set(excluidos) if c in existentes and c not in aprobados]
    while pila:
        actual = pila.pop()
        if actual in removidos:
            continue
        removidos.add(actual)
        pila.extend(h for h in hijos.get(actual, []) if h not in aprobados)

    return [c for c in cursos if c["codigo"] not in removidos], removidos


def seleccionar_cursos_objetivo(
    cursos: list[dict],
    aprobados: Iterable[str],
    incluir_idiomas: bool = False,
) -> tuple[list[dict], dict]:
    """
    Decide qué cursos NO obligatorios entran al plan para poder cerrar
    pénsum. Devuelve una COPIA de la malla donde esos cursos quedan con
    "obligatorio": true (así los planifican las funciones existentes) y un
    diccionario informativo.

    Reglas:
    1. Social Humanística: entre lo aprobado y lo planificado deben sumar 8
       cursos del área (SOCIAL_HUMANISTICA_CODIGOS).
    2. Idiomas técnicos: solo entran si `incluir_idiomas` es True.
    3. Créditos: aprobados + planificados deben llegar a 300 (o 360 en
       carreras de 12 semestres). Si faltan, se completan con los optativos
       más convenientes: primero los que no son deportes, luego el semestre
       oficial más bajo y más créditos. Los idiomas técnicos solo se usan
       para completar si el estudiante los pidió.
       Si un optativo tiene prerequisitos optativos, estos se agregan también.
    """
    copia = [dict(c) for c in cursos]
    por_codigo = {c["codigo"]: c for c in copia}
    aprobados = {a for a in aprobados if a in por_codigo}

    def _en_plan(codigo: str) -> bool:
        return codigo in aprobados or _es_obligatorio(por_codigo[codigo])

    agregados: list[str] = []

    def _agregar_con_prerequisitos(codigo: str) -> bool:
        """Agrega el curso y sus prerequisitos optativos pendientes."""
        if codigo in aprobados or _es_obligatorio(por_codigo[codigo]):
            return True
        cadena, pila = [], [codigo]
        while pila:
            actual = pila.pop()
            if actual in aprobados or _es_obligatorio(por_codigo[actual]) or actual in cadena:
                continue
            cadena.append(actual)
            for prereq in por_codigo[actual].get("prerequisitos", []):
                if prereq not in por_codigo:
                    return False
                pila.append(prereq)
        for c in cadena:
            por_codigo[c]["obligatorio"] = True
            agregados.append(c)
        return True

    # 1) Social Humanística
    sh_en_malla = sorted(
        (c for c in copia if c["codigo"] in SOCIAL_HUMANISTICA_CODIGOS),
        key=lambda c: (c.get("semestre", 99), c["codigo"]),
    )

    def _creditos_sh() -> int:
        return sum(c.get("creditos", 0) for c in sh_en_malla if _en_plan(c["codigo"]))

    for curso in sh_en_malla:
        if _creditos_sh() >= SOCIAL_HUMANISTICA_REQUERIDOS:
            break
        if not _en_plan(curso["codigo"]):
            _agregar_con_prerequisitos(curso["codigo"])

    # 2) Idiomas técnicos
    if incluir_idiomas:
        for curso in sorted(copia, key=lambda c: (c.get("semestre", 99), c["codigo"])):
            if curso["codigo"] in IDIOMA_TECNICO_CODIGOS:
                _agregar_con_prerequisitos(curso["codigo"])

    # 3) Créditos totales
    meta = creditos_requeridos_pensum(cursos)

    def _creditos_plan() -> int:
        return sum(c.get("creditos", 0) for c in copia if _en_plan(c["codigo"]))

    if _creditos_plan() < meta:
        candidatos = [
            c for c in copia
            if not _en_plan(c["codigo"])
            and c["codigo"] not in IDIOMA_TECNICO_CODIGOS
            and c["codigo"] not in SOCIAL_HUMANISTICA_CODIGOS
        ]
        candidatos.sort(key=lambda c: (
            "deporte" in _normalizar_texto(c.get("nombre", "")),
            c.get("semestre", 99),
            -c.get("creditos", 0),
            c["codigo"],
        ))
        for curso in candidatos:
            if _creditos_plan() >= meta:
                break
            _agregar_con_prerequisitos(curso["codigo"])

    idiomas_por_necesidad = False
    if _creditos_plan() < meta and not incluir_idiomas:
        # Último recurso: sin idiomas no alcanzan los créditos del pénsum.
        for curso in sorted(copia, key=lambda c: (c.get("semestre", 99), c["codigo"])):
            if _creditos_plan() >= meta:
                break
            if curso["codigo"] in IDIOMA_TECNICO_CODIGOS and not _en_plan(curso["codigo"]):
                if _agregar_con_prerequisitos(curso["codigo"]):
                    idiomas_por_necesidad = True

    total_plan = _creditos_plan()
    sh_total = _creditos_sh()
    info = {
        "creditos_requeridos": meta,
        "creditos_totales_plan": total_plan,
        "creditos_faltantes": max(0, meta - total_plan),
        "social_humanistica_requeridos": SOCIAL_HUMANISTICA_REQUERIDOS,
        "social_humanistica_en_plan": sh_total,
        "social_humanistica_faltantes": max(0, SOCIAL_HUMANISTICA_REQUERIDOS - sh_total),
        "optativos_agregados": agregados,
        "idiomas_agregados_por_necesidad": idiomas_por_necesidad,
    }
    return copia, info


def _normalizar_texto(texto: str) -> str:
    import unicodedata
    texto = (texto or "").lower()
    return "".join(
        ch for ch in unicodedata.normalize("NFKD", texto) if not unicodedata.combining(ch)
    )


# ---------------------------------------------------------------------------
# Plan hasta el cierre de la carrera (todos los semestres que faltan)
# ---------------------------------------------------------------------------

MODOS_PLAN_ANUAL = {"avanzar", "nivelarse", "tiempo_normal"}
"""
- "avanzar":       usa siempre el límite máximo de créditos que permite el
                    promedio, para cerrar la carrera lo antes posible.
- "nivelarse":      igual que "avanzar" en cupo (usa el máximo permitido);
                    la diferencia frente a "avanzar" es solo de mensaje /
                    interpretación, ya que maximizar créditos priorizando
                    siempre lo más atrasado primero es simultáneamente la
                    forma más rápida de graduarse Y de ponerse al día.
- "tiempo_normal":  puede adelantar cursos, pero no termina antes de la
                    duración normal del pénsum: reparte lo pendiente en
                    partes iguales hasta ese semestre (sin pasar del límite
                    de créditos que permite el promedio).
"""

MAX_SEMESTRES_SEGURIDAD = 40
"""Límite de seguridad para detectar mallas con bloqueos irresolubles en
vez de quedar en un ciclo infinito."""


def _plan_restante(
    cursos: list[dict],
    periodos_vacacionales: list[dict],
    semestre_actual: int,
    aprobados: Iterable[str] | None = None,
    reprobados: Iterable[str] | None = None,
    limite_creditos: int = 37,
    modo: str = "nivelarse",
    iniciar_en_vacaciones: bool = False,
    duracion_normal_pensum: int | None = None,
    semestres_objetivo: int | None = None,
    solo_vacaciones: Iterable[str] | None = None,
    solo_semestre: Iterable[str] | None = None,
) -> dict:
    """
    Arma el plan completo desde donde va el estudiante hasta el cierre de
    la carrera: Semestre, Vacaciones, Semestre, Vacaciones, ... hasta que
    ya no queden cursos obligatorios pendientes. Si el estudiante va
    atrasado y el límite de créditos no alcanza para nivelarse dentro de
    la duración normal del pénsum, el plan simplemente sigue agregando los
    semestres adicionales que hagan falta hasta cerrar.

    Es una capa sobre `calcular_ruta_regular` / `calcular_ruta_vacaciones`.

    Parameters
    ----------
    cursos:
        Malla curricular completa (usa `inyectar_prerequisitos_optativos`
        antes de llamar a esta función si aplica, igual que con
        `calcular_ruta_regular`).
    periodos_vacacionales:
        Periodos vacacionales disponibles, en el orden en que ocurrirán
        (uno después de cada semestre planificado, mientras sigan quedando
        cursos pendientes y haya periodos disponibles en la lista). Ver
        `calcular_ruta_vacaciones` para el formato.
    semestre_actual:
        Semestre oficial del pénsum en el que va el estudiante ahora mismo
        (se usa para: (a) nombrar los slots resultantes, y (b) determinar
        qué cursos obligatorios de semestres ANTERIORES a este están
        "atrasados" si no aparecen en `aprobados`).
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
        "periodos": {clave_periodo: [cursos]} en orden cronológico, hasta
            el cierre de la carrera.
        "atrasados_iniciales": cursos obligatorios de semestre ANTERIOR a
            semestre_actual que el estudiante NO tiene ganados al arrancar.
        "duracion_normal_pensum": último semestre oficial que declara la
            malla para cursos obligatorios (p. ej. 10).
        "semestres_cursados": cantidad de semestres (sin contar
            vacaciones) que se planificaron en este plan.
        "semestre_estimado_cierre": número de semestre en el que el plan
            proyecta que el estudiante se gradúa
            (semestre_actual + semestres_cursados - 1).
        "semestres_extra": cuántos semestres por encima de la duración
            normal del pénsum haría falta cursar (0 si cierra a tiempo o
            antes).
        "modo": el modo usado.

    Raises
    ------
    RutaOptimaError
        Si `modo` no es válido, si el plan supera
        `MAX_SEMESTRES_SEGURIDAD` (probable bloqueo irresoluble en la
        malla), o por las mismas razones que `calcular_ruta_regular` /
        `calcular_ruta_vacaciones`.
    """
    if modo not in MODOS_PLAN_ANUAL:
        raise RutaOptimaError(
            f"Modo de planificación inválido: '{modo}'. "
            f"Debe ser uno de {sorted(MODOS_PLAN_ANUAL)}."
        )

    por_codigo = {curso["codigo"]: curso for curso in cursos}

    aprob_actual = set(aprobados or [])
    reprob_actual = set(reprobados or [])
    solo_vacaciones = set(solo_vacaciones or [])
    solo_semestre = set(solo_semestre or [])

    atrasados_iniciales = sorted(
        codigo for codigo, curso in por_codigo.items()
        if _es_obligatorio(curso)
        and curso.get("semestre", 0) < semestre_actual
        and (codigo not in aprob_actual or codigo in reprob_actual)
    )

    if duracion_normal_pensum is None:
        duracion_normal_pensum = max(
            (curso.get("semestre", 0) for curso in cursos if _es_obligatorio(curso)),
            default=semestre_actual,
        )

    def _pendientes_obligatorios() -> set[str]:
        return {
            curso["codigo"] for curso in cursos
            if _es_obligatorio(curso)
            and (curso["codigo"] not in aprob_actual or curso["codigo"] in reprob_actual)
        }

    periodos_out: dict[str, list[dict]] = {}
    vac_idx = 0
    indice_semestre = 0

    # Si el estudiante está ahora en vacaciones (semestre_actual es el
    # semestre que sigue), el primer periodo del plan es ese periodo vacacional.
    if iniciar_en_vacaciones and _pendientes_obligatorios() and vac_idx < len(periodos_vacacionales):
        periodo = periodos_vacacionales[vac_idx]
        vac_idx += 1
        resultado_vac = calcular_ruta_vacaciones(
            cursos, [periodo], aprobados=aprob_actual,
            excluir_codigos=solo_semestre, prioritarios=solo_vacaciones,
        )
        clave_vac = f"Vacaciones de semestre {semestre_actual - 1}"
        resultado_vac = {clave_vac: next(iter(resultado_vac.values()))}
        periodos_out[clave_vac] = resultado_vac[clave_vac]
        for curso in resultado_vac[clave_vac]:
            aprob_actual.add(curso["codigo"])
            reprob_actual.discard(curso["codigo"])

    while _pendientes_obligatorios():
        if indice_semestre >= MAX_SEMESTRES_SEGURIDAD:
            raise RutaOptimaError(
                "El plan superó el límite de seguridad de "
                f"{MAX_SEMESTRES_SEGURIDAD} semestres sin lograr cerrar la "
                "carrera; probablemente hay un bloqueo irresoluble en la "
                "malla (revisa prerequisitos huérfanos o ciclos)."
            )

        limite_efectivo = limite_creditos
        if modo == "tiempo_normal":
            # Se puede adelantar cursos, pero sin terminar antes de la
            # duración normal del pénsum: se reparte lo pendiente en partes
            # iguales entre los semestres que quedan hasta ese cierre
            # (nunca más que el límite que permite el promedio).
            pendientes = _pendientes_obligatorios() - solo_vacaciones
            total_objetivo = semestres_objetivo or (duracion_normal_pensum - semestre_actual + 1)
            semestres_restantes = max(1, total_objetivo - indice_semestre)
            creditos_pendientes = sum(por_codigo[c].get("creditos", 0) for c in pendientes)
            carga = -(-creditos_pendientes // semestres_restantes)
            mayor_curso = max((por_codigo[c].get("creditos", 0) for c in pendientes), default=0)
            limite_efectivo = min(limite_creditos, max(carga, mayor_curso, 1))

        parcial = calcular_ruta_regular(
            cursos,
            aprobados=aprob_actual,
            reprobados=reprob_actual,
            limite_creditos=limite_efectivo,
            solo_vacaciones=solo_vacaciones,
        )
        primera_clave = next(iter(parcial))
        cursos_semestre = parcial[primera_clave]
        clave_final = f"Semestre_{semestre_actual + indice_semestre}"
        periodos_out[clave_final] = cursos_semestre
        indice_semestre += 1

        for curso in cursos_semestre:
            aprob_actual.add(curso["codigo"])
            reprob_actual.discard(curso["codigo"])

        if _pendientes_obligatorios() and vac_idx < len(periodos_vacacionales):
            periodo = periodos_vacacionales[vac_idx]
            vac_idx += 1
            resultado_vac = calcular_ruta_vacaciones(
                cursos, [periodo], aprobados=aprob_actual,
                excluir_codigos=solo_semestre, prioritarios=solo_vacaciones,
            )
            clave_vac = f"Vacaciones de semestre {semestre_actual + indice_semestre - 1}"
            resultado_vac = {clave_vac: next(iter(resultado_vac.values()))}
            periodos_out[clave_vac] = resultado_vac[clave_vac]
            for curso in resultado_vac[clave_vac]:
                aprob_actual.add(curso["codigo"])
                reprob_actual.discard(curso["codigo"])

    semestre_estimado_cierre = semestre_actual + indice_semestre - 1
    semestres_extra = max(0, semestre_estimado_cierre - duracion_normal_pensum)

    return {
        "periodos": periodos_out,
        "atrasados_iniciales": atrasados_iniciales,
        "duracion_normal_pensum": duracion_normal_pensum,
        "semestres_cursados": indice_semestre,
        "semestre_estimado_cierre": semestre_estimado_cierre,
        "semestres_extra": semestres_extra,
        "modo": modo,
    }

def calcular_plan_restante(
    cursos: list[dict],
    periodos_vacacionales: list[dict],
    semestre_actual: int,
    aprobados: Iterable[str] | None = None,
    reprobados: Iterable[str] | None = None,
    limite_creditos: int = 37,
    modo: str = "nivelarse",
    iniciar_en_vacaciones: bool = False,
    duracion_normal_pensum: int | None = None,
    solo_vacaciones: Iterable[str] | None = None,
    solo_semestre: Iterable[str] | None = None,
) -> dict:
    """
    Igual que `_plan_restante` (ver su documentación). Para los modos
    "avanzar" y "nivelarse" es exactamente ese cálculo. Para "tiempo_normal"
    se busca el reparto de carga que cierre justo en la duración normal del
    pénsum (o lo más pronto posible si el estudiante ya no llega a tiempo),
    sin terminar antes.
    """
    argumentos = dict(
        cursos=cursos,
        periodos_vacacionales=periodos_vacacionales,
        semestre_actual=semestre_actual,
        aprobados=aprobados,
        reprobados=reprobados,
        limite_creditos=limite_creditos,
        iniciar_en_vacaciones=iniciar_en_vacaciones,
        duracion_normal_pensum=duracion_normal_pensum,
        solo_vacaciones=solo_vacaciones,
        solo_semestre=solo_semestre,
    )
    if modo != "tiempo_normal":
        return _plan_restante(modo=modo, **argumentos)

    rapido = _plan_restante(modo="nivelarse", **argumentos)
    duracion = rapido["duracion_normal_pensum"]
    meta = max(duracion - semestre_actual + 1, rapido["semestres_cursados"])

    for objetivo in range(meta, max(rapido["semestres_cursados"], 1) - 1, -1):
        plan = _plan_restante(modo="tiempo_normal", semestres_objetivo=objetivo, **argumentos)
        if plan["semestres_cursados"] == meta:
            return plan

    # Ningún reparto cierra exactamente en la meta (por cadenas de
    # prerequisitos): se usa el plan más rápido posible, que nunca es peor.
    rapido["modo"] = "tiempo_normal"
    return rapido


def sanear_aprobados_por_prerequisitos(
    cursos: list[dict],
    aprobados: Iterable[str],
) -> tuple[set[str], set[str]]:
    """
    Depura un conjunto de cursos "aprobados" declarados, quitando
    cualquier curso cuyo(s) prerequisito(s) no estén también (transitiva
    y consistentemente) dentro de ese mismo conjunto.

    Esto existe porque, al planificar, es común asumir automáticamente
    "ya ganó todo lo de semestres anteriores al actual" y solo pedirle al
    estudiante que indique lo que perdió (p. ej. Física 1, Intermedia 3).
    Esa asunción por sí sola es inconsistente: si el estudiante nunca ganó
    Intermedia 3, tampoco pudo haber ganado ningún curso que la requiera
    como prerequisito (p. ej. Matemática Aplicada 1), ni lo que dependa de
    ESE curso (p. ej. Teoría de Sistemas 1), aunque esos cursos
    "numéricamente" pertenezcan a un semestre anterior al actual.

    El cálculo es de punto fijo: un curso solo se considera realmente
    aprobado si TODOS sus prerequisitos también quedaron dentro del
    conjunto consistente (y así sucesivamente hacia atrás en la cadena).

    Parameters
    ----------
    cursos:
        Malla curricular completa.
    aprobados:
        Códigos que se habían declarado/asumido como aprobados.

    Returns
    -------
    (aprobados_consistentes, removidos_por_arrastre)
        aprobados_consistentes: subconjunto de `aprobados` que sí es
            alcanzable respetando la cadena de prerequisitos.
        removidos_por_arrastre: los códigos que se quitaron de
            `aprobados` porque dependían, directa o indirectamente, de un
            curso que no está en `aprobados`.
    """
    por_codigo = {curso["codigo"]: curso for curso in cursos}
    declarados = set(aprobados)

    aprobados_consistentes: set[str] = set()
    pendientes_por_validar = set(declarados)

    while True:
        agregado_este_ciclo = False
        for codigo in list(pendientes_por_validar):
            curso = por_codigo.get(codigo)
            if curso is None:
                pendientes_por_validar.discard(codigo)
                continue
            prerequisitos = set(curso.get("prerequisitos", []))
            prerequisitos_relevantes = {p for p in prerequisitos if p in por_codigo}
            if prerequisitos_relevantes <= aprobados_consistentes:
                aprobados_consistentes.add(codigo)
                pendientes_por_validar.discard(codigo)
                agregado_este_ciclo = True
        if not agregado_este_ciclo:
            break

    removidos_por_arrastre = declarados - aprobados_consistentes
    return aprobados_consistentes, removidos_por_arrastre

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