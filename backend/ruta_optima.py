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
    if "horas_teoricas" in curso and curso["horas_teoricas"] is not None:
        return curso["horas_teoricas"]
    return curso.get("creditos", 0)


def horas_laboratorio_de(curso: dict) -> float:
    return curso.get("horas_laboratorio", 0) or 0


def _es_obligatorio(curso: dict) -> bool:
    return bool(curso.get("obligatorio", True))


# ---------------------------------------------------------------------------
# Utilidades internas compartidas
# ---------------------------------------------------------------------------

def _construir_grafo(cursos: list[dict]) -> nx.DiGraph:
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
    detalle = []
    for codigo in sorted(pendientes):
        curso = por_codigo[codigo]
        faltan = sorted(set(curso.get("prerequisitos", [])) - aprobados_acumulado)
        if faltan:
            detalle.append(f"'{codigo}' ({curso.get('nombre', '')}) requiere {faltan}")
    if not detalle:
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
    if limite_creditos <= 0:
        raise RutaOptimaError("El límite de créditos por slot debe ser mayor a 0.")

    aprobados = set(aprobados or [])
    reprobados = set(reprobados or [])
    solo_vacaciones = set(solo_vacaciones or [])

    grafo = _construir_grafo(cursos)
    _validar_sin_ciclos(grafo)

    por_codigo = {curso["codigo"]: curso for curso in cursos}

    bloqueados_por_vacaciones = set(solo_vacaciones)
    for codigo in solo_vacaciones:
        if codigo in grafo:
            bloqueados_por_vacaciones |= nx.descendants(grafo, codigo)

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
            if not ruta:
                ruta[clave] = []
            break

        if not candidatos:
            mensaje = _diagnosticar_bloqueo(pendientes, por_codigo, aprobados_acumulado)
            raise RutaOptimaError(
                "No es posible continuar la planificación regular: hay cursos "
                f"bloqueados sin prerequisitos alcanzables -> {mensaje}"
            )

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
    aprobados_acumulado = set(aprobados or [])
    excluir_codigos = set(excluir_codigos or [])
    prioritarios = set(prioritarios or [])
    por_codigo = {curso["codigo"]: curso for curso in cursos}

    grafo = _construir_grafo(cursos)
    _validar_sin_ciclos(grafo)

    ruta: dict[str, list[dict]] = {}

    for periodo in periodos_vacacionales:
        clave = periodo["nombre"]
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

SOCIAL_HUMANISTICA_REQUERIDOS = 8
IDIOMA_TECNICO_CODIGOS = ("0006", "0008", "0009", "0011")

CREDITOS_PENSUM_10_SEMESTRES = 300
CREDITOS_PENSUM_12_SEMESTRES = 360


def tipo_de_curso(curso: dict) -> str:
    if curso.get("codigo") in SOCIAL_HUMANISTICA_CODIGOS:
        return "social_humanistica"
    if curso.get("codigo") in IDIOMA_TECNICO_CODIGOS:
        return "idioma"
    return "obligatorio" if _es_obligatorio(curso) else "optativo"


def creditos_requeridos_pensum(cursos: list[dict]) -> int:
    ultimo = max((c.get("semestre", 0) or 0 for c in cursos), default=0)
    return CREDITOS_PENSUM_12_SEMESTRES if ultimo >= 11 else CREDITOS_PENSUM_10_SEMESTRES


def excluir_cursos(
    cursos: list[dict],
    excluidos: Iterable[str],
    aprobados: Iterable[str] = (),
) -> tuple[list[dict], set[str]]:
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
    copia = [dict(c) for c in cursos]
    por_codigo = {c["codigo"]: c for c in copia}
    aprobados = {a for a in aprobados if a in por_codigo}

    def _en_plan(codigo: str) -> bool:
        return codigo in aprobados or _es_obligatorio(por_codigo[codigo])

    agregados: list[str] = []

    def _agregar_con_prerequisitos(codigo: str) -> bool:
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

    if incluir_idiomas:
        for curso in sorted(copia, key=lambda c: (c.get("semestre", 99), c["codigo"])):
            if curso["codigo"] in IDIOMA_TECNICO_CODIGOS:
                _agregar_con_prerequisitos(curso["codigo"])

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
MAX_SEMESTRES_SEGURIDAD = 40

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

    rapido["modo"] = "tiempo_normal"
    return rapido


def sanear_aprobados_por_prerequisitos(
    cursos: list[dict],
    aprobados: Iterable[str],
) -> tuple[set[str], set[str]]:
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