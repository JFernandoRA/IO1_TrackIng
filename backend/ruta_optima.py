"""
ruta_optima.py

Algoritmo puro (sin FastAPI, sin rutas HTTP) que calcula la ruta académica
más rápida posible para terminar los cursos OBLIGATORIOS de una malla
curricular, respetando estrictamente las dependencias de prerequisitos y
un límite máximo de créditos por semestre.

Conceptos de teoría de grafos aplicados:
  - Cada curso pendiente es un NODO de un grafo dirigido (DiGraph).
  - Cada prerequisito genera una ARISTA dirigida prerequisito -> curso,
    es decir, "para llegar a este nodo hay que pasar antes por el otro".
  - Que la malla no tenga ciclos es indispensable: un ciclo significaría
    que un curso es prerequisito de sí mismo (directa o indirectamente),
    lo cual es imposible de cursar. Se valida con
    nx.is_directed_acyclic_graph().
  - El ORDEN de asignación dentro de cada semestre usa el out-degree de
    cada nodo (cuántos cursos dependen DIRECTAMENTE de él) como medida de
    "qué tan crítico" es liberarlo pronto: mientras más cursos desbloquea,
    antes conviene cursarlo, porque retrasarlo retrasa en cascada a todo
    lo que depende de él.
  - El bucle principal es, en esencia, un ordenamiento topológico
    (equivalente a Kahn's algorithm) pero agrupado "por capas": en cada
    iteración se calculan todos los nodos cuyas dependencias ya están
    resueltas (in-degree efectivo cero contra lo ya aprobado/asignado) y
    de esa capa se seleccionan tantos como quepan en el límite de
    créditos, dejando el resto para la siguiente capa/semestre.
"""

from typing import Dict, List, Optional, Any
import networkx as nx


class RutaOptimaError(ValueError):
    """Errores de validación básica de entrada (no de lógica de negocio)."""


def calcular_ruta_optima(
    cursos_aprobados: List[str],
    malla_curricular: Dict[str, Dict[str, Any]],
    limite_creditos_semestre: int,
) -> Dict[str, Any]:
    """
    Calcula la ruta semestre a semestre para terminar los cursos
    obligatorios pendientes de una malla curricular en el menor número
    de semestres posible, respetando prerequisitos y el límite de
    créditos por semestre.

    Parámetros
    ----------
    cursos_aprobados : List[str]
        Códigos de cursos que el estudiante ya aprobó (de cualquier tipo,
        obligatorio u optativo).
    malla_curricular : Dict[str, Dict]
        Diccionario código -> datos del curso. Cada curso debe traer al
        menos: "codigo", "nombre", "creditos", "semestre",
        "prerequisitos" (lista de códigos) y "obligatorio" (bool).
    limite_creditos_semestre : int
        Máximo de créditos permitidos por semestre regular.

    Retorna
    -------
    Dict[str, Any]
        - Caso éxito: diccionario con claves "Semestre_1", "Semestre_2", ...
          cada una con una lista de diccionarios
          {"codigo", "nombre", "creditos", "semestre_oficial"}.
        - Caso bloqueo (ciclo en la malla, créditos insuficientes para un
          curso individual, o cuello de botella de prerequisitos):
          diccionario con:
            {
              "advertencia": "<mensaje explicando el problema>",
              "cursos_bloqueados": ["COD1", "COD2", ...],
              "ruta_parcial": {<lo que sí se logró asignar antes de trabar>}
            }
    """
    # ------------------------------------------------------------------
    # 0) Validación básica de entrada (manejo de errores de tipo/forma).
    # ------------------------------------------------------------------
    if not isinstance(malla_curricular, dict):
        raise RutaOptimaError("malla_curricular debe ser un diccionario código -> curso")
    if not isinstance(cursos_aprobados, list):
        raise RutaOptimaError("cursos_aprobados debe ser una lista de códigos")
    if not isinstance(limite_creditos_semestre, int) or limite_creditos_semestre <= 0:
        raise RutaOptimaError("limite_creditos_semestre debe ser un entero mayor a cero")

    # Normalizamos códigos a mayúsculas para comparar de forma consistente
    # (los datos reales usan códigos numéricos, pero esto también soporta
    # códigos alfanuméricos sin distinguir mayúsculas/minúsculas).
    aprobados_set = {str(codigo).strip().upper() for codigo in cursos_aprobados}

    # ------------------------------------------------------------------
    # 1) Filtrado: solo cursos OBLIGATORIOS y NO aprobados.
    #    Los optativos se ignoran por completo desde este punto en
    #    adelante, tal como pide el requerimiento.
    # ------------------------------------------------------------------
    malla_pendiente: Dict[str, Dict[str, Any]] = {}
    for codigo_raw, curso in malla_curricular.items():
        codigo = str(codigo_raw).strip().upper()
        if not curso.get("obligatorio", True):
            continue  # se descarta: no es obligatorio
        if codigo in aprobados_set:
            continue  # se descarta: ya aprobado
        malla_pendiente[codigo] = curso

    # Si no queda nada pendiente, la ruta está completa desde el inicio.
    if not malla_pendiente:
        return {}

    # ------------------------------------------------------------------
    # 2) Construcción del grafo dirigido de prerequisitos.
    #    Nodo = curso pendiente. Arista prereq -> curso = dependencia.
    #    Solo se agregan aristas entre nodos que EXISTEN en el grafo
    #    (es decir, entre cursos obligatorios aún pendientes); si un
    #    prerequisito ya está aprobado o no es obligatorio, no genera
    #    arista porque no representa una restricción pendiente dentro
    #    de esta ruta, pero sí se sigue validando su cumplimiento más
    #    abajo contra el set de aprobados.
    # ------------------------------------------------------------------
    grafo = nx.DiGraph()
    grafo.add_nodes_from(malla_pendiente.keys())

    for codigo, curso in malla_pendiente.items():
        for prereq_raw in curso.get("prerequisitos", []) or []:
            prereq = str(prereq_raw).strip().upper()
            if prereq in malla_pendiente:
                grafo.add_edge(prereq, codigo)

    # ------------------------------------------------------------------
    # 3) Validación de ciclos: una malla bien diseñada es un DAG
    #    (grafo acíclico dirigido). Si hay un ciclo, es imposible generar
    #    una ruta válida porque algún curso terminaría dependiendo,
    #    directa o indirectamente, de sí mismo.
    # ------------------------------------------------------------------
    if not nx.is_directed_acyclic_graph(grafo):
        ciclo = nx.find_cycle(grafo)
        cursos_en_ciclo = sorted({nodo for arista in ciclo for nodo in arista})
        return {
            "advertencia": (
                "Se detectó un ciclo de prerequisitos en la malla curricular; "
                "no es posible calcular una ruta válida."
            ),
            "cursos_bloqueados": cursos_en_ciclo,
            "ruta_parcial": {},
        }

    # ------------------------------------------------------------------
    # 4) Prioridad de asignación: out-degree de cada nodo.
    #    out_degree(curso) = cantidad de cursos que dependen DIRECTAMENTE
    #    de él en el grafo. A mayor out-degree, más "cuellos de botella"
    #    desbloquea, así que se prioriza sobre cursos con out-degree bajo.
    #    Como criterio de desempate se usa el semestre oficial más bajo
    #    (para respetar en lo posible el orden natural del pénsum) y,
    #    por último, el código para que el resultado sea determinista.
    # ------------------------------------------------------------------
    out_degree = dict(grafo.out_degree())

    def clave_prioridad(codigo: str):
        curso = malla_pendiente[codigo]
        return (
            -out_degree.get(codigo, 0),          # mayor out-degree primero
            curso.get("semestre", 0),             # semestre oficial más bajo primero
            codigo,                                # desempate determinista
        )

    # ------------------------------------------------------------------
    # 5) Verificación temprana: si algún curso individual excede por sí
    #    solo el límite de créditos por semestre, es imposible asignarlo
    #    jamás y hay que reportarlo como advertencia en vez de entrar en
    #    un bucle infinito.
    # ------------------------------------------------------------------
    imposibles = [
        codigo
        for codigo, curso in malla_pendiente.items()
        if curso.get("creditos", 0) > limite_creditos_semestre
    ]
    if imposibles:
        return {
            "advertencia": (
                "Hay cursos obligatorios cuyos créditos superan el límite máximo "
                f"por semestre ({limite_creditos_semestre}); no se pueden asignar nunca "
                "con ese límite."
            ),
            "cursos_bloqueados": sorted(imposibles),
            "ruta_parcial": {},
        }

    # ------------------------------------------------------------------
    # 6) Bucle greedy semestre por semestre (topological sort por capas
    #    + empaquetado por créditos, tipo "knapsack" simple/goloso).
    # ------------------------------------------------------------------
    pendientes = set(malla_pendiente.keys())
    asignados_acumulados: set = set()  # cursos ya colocados en semestres previos de ESTA ruta
    ruta: Dict[str, List[Dict[str, Any]]] = {}
    numero_semestre = 1

    def prerequisitos_cumplidos(codigo: str) -> bool:
        """
        Un curso está disponible para cursarse cuando TODOS sus
        prerequisitos ya están satisfechos: o bien porque el estudiante
        ya los aprobó antes de esta ruta, o porque quedaron asignados en
        un semestre anterior de la ruta que se está construyendo.
        Esto equivale a decir que, en el grafo, todas sus aristas
        entrantes provienen de nodos ya "resueltos" (in-degree efectivo
        cero contra el conjunto ya cubierto).
        """
        curso = malla_pendiente[codigo]
        for prereq_raw in curso.get("prerequisitos", []) or []:
            prereq = str(prereq_raw).strip().upper()
            if prereq in aprobados_set or prereq in asignados_acumulados:
                continue
            # Si el prerequisito no está en la malla pendiente, en la
            # malla original (obligatorio u optativo) tampoco cuenta como
            # cumplido salvo que ya esté en aprobados; se marca como no
            # cumplido para forzar que se reporte el bloqueo.
            return False
        return True

    while pendientes:
        # Capa actual: cursos cuyos prerequisitos ya quedaron resueltos.
        candidatos = [codigo for codigo in pendientes if prerequisitos_cumplidos(codigo)]

        if not candidatos:
            # Cuello de botella: quedan cursos pendientes pero ninguno
            # tiene sus prerequisitos satisfechos. Esto normalmente pasa
            # cuando un prerequisito depende de un curso optativo o ya
            # descartado que el estudiante nunca aprobó.
            return {
                "advertencia": (
                    "No se puede continuar la ruta: quedan cursos obligatorios "
                    "pendientes pero ninguno tiene sus prerequisitos cumplidos. "
                    "Revisa si falta aprobar un prerequisito (posiblemente un "
                    "curso optativo o no incluido en la lista de aprobados)."
                ),
                "cursos_bloqueados": sorted(pendientes),
                "ruta_parcial": ruta,
            }

        # Se ordenan los candidatos disponibles por prioridad (out-degree
        # descendente) y se van empacando en el semestre actual mientras
        # quepan en el límite de créditos.
        candidatos.sort(key=clave_prioridad)

        cursos_del_semestre: List[str] = []
        creditos_usados = 0
        for codigo in candidatos:
            creditos_curso = malla_pendiente[codigo].get("creditos", 0)
            if creditos_usados + creditos_curso <= limite_creditos_semestre:
                cursos_del_semestre.append(codigo)
                creditos_usados += creditos_curso

        # Por el chequeo del paso 5, siempre debería caber al menos un
        # curso; esta guarda es solo una red de seguridad adicional.
        if not cursos_del_semestre:
            return {
                "advertencia": (
                    "No fue posible asignar ningún curso disponible dentro del "
                    "límite de créditos del semestre."
                ),
                "cursos_bloqueados": sorted(candidatos),
                "ruta_parcial": ruta,
            }

        clave_semestre = f"Semestre_{numero_semestre}"
        ruta[clave_semestre] = [
            {
                "codigo": codigo,
                "nombre": malla_pendiente[codigo].get("nombre"),
                "creditos": malla_pendiente[codigo].get("creditos"),
                "semestre_oficial": malla_pendiente[codigo].get("semestre"),
            }
            for codigo in cursos_del_semestre
        ]

        asignados_acumulados.update(cursos_del_semestre)
        pendientes -= set(cursos_del_semestre)
        numero_semestre += 1

    return ruta