"""
Servicio encargado de construir y manipular el grafo de prerequisitos
de la malla curricular usando networkx.

El grafo es dirigido: una arista A -> B significa "A es prerequisito
de B" (hay que aprobar A antes de poder inscribir B).
"""

from typing import Dict, List, Set

import networkx as nx

from models.malla import Curso


def construir_grafo(malla: Dict[str, Curso]) -> nx.DiGraph:
    """Construye el grafo dirigido completo de la malla curricular."""
    grafo = nx.DiGraph()

    for codigo, curso in malla.items():
        grafo.add_node(codigo, **curso.model_dump())

    for codigo, curso in malla.items():
        for prereq in curso.prerequisitos:
            if prereq in malla:
                grafo.add_edge(prereq, codigo)
            # Si el prerequisito no existe en la malla, lo ignoramos
            # silenciosamente: puede ser un curso de otra carrera o un
            # error de datos que no debe tumbar el cálculo de ruta.

    return grafo


def filtrar_cursos_aprobados(grafo: nx.DiGraph, cursos_aprobados: List[str]) -> nx.DiGraph:
    """
    Devuelve una copia del grafo sin los cursos ya aprobados.

    Al eliminar estos nodos, los cursos cuyo único prerequisito
    pendiente era uno de los aprobados quedan automáticamente
    "listos" (sin predecesores) en el grafo resultante.
    """
    subgrafo = grafo.copy()
    aprobados_en_grafo = [c for c in cursos_aprobados if c in subgrafo]
    subgrafo.remove_nodes_from(aprobados_en_grafo)
    return subgrafo


def cursos_disponibles_ahora(grafo_pendiente: nx.DiGraph, cursos_aprobados: Set[str]) -> List[str]:
    """
    Identifica los cursos "fuente": aquellos cuyos prerequisitos ya
    fueron todos aprobados, por lo tanto se pueden inscribir en el
    próximo semestre.
    """
    disponibles = []
    for nodo in grafo_pendiente.nodes:
        prereqs = grafo_pendiente.nodes[nodo].get("prerequisitos", [])
        if all(p in cursos_aprobados for p in prereqs):
            disponibles.append(nodo)
    return disponibles


def orden_topologico(grafo_pendiente: nx.DiGraph) -> List[str]:
    """
    Retorna un orden topológico válido de los cursos pendientes,
    respetando todas las relaciones de prerequisito.

    Lanza networkx.NetworkXUnfeasible si el grafo tiene ciclos, lo
    cual indicaría un error de datos en la malla curricular (un curso
    que depende, directa o indirectamente, de sí mismo).
    """
    return list(nx.topological_sort(grafo_pendiente))


def validar_acíclico(grafo: nx.DiGraph) -> bool:
    """Verifica que la malla curricular no tenga ciclos de prerequisitos."""
    return nx.is_directed_acyclic_graph(grafo)
