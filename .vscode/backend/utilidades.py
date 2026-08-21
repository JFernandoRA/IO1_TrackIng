# -*- coding: utf-8 -*-
"""
utilidades.py
==============
Funciones de consola compartidas entre test_algoritmo.py y plan_anual.py:
carga de mallas curriculares, selección interactiva, cálculo del límite de
créditos según el promedio, búsqueda de cursos por nombre (los códigos
varían entre carreras) e impresión de rutas.

Se separó de test_algoritmo.py para no duplicar lógica entre el script de
pruebas y el script de planificación anual (plan_anual.py).
"""

from __future__ import annotations

import json
import os
import unicodedata

from ruta_optima import horas_laboratorio_de, horas_teoricas_de

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
ARCHIVO_HORARIOS_VACACIONES = "horarios_vacaciones.json"


# ---------------------------------------------------------------------------
# Carga de datos y selección interactiva de malla
# ---------------------------------------------------------------------------

def cargar_json(ruta: str) -> dict:
    with open(ruta, "r", encoding="utf-8") as archivo:
        return json.load(archivo)


def listar_mallas_disponibles() -> list[str]:
    """Todo *.json en data/ es una malla, excepto horarios_vacaciones.json."""
    if not os.path.isdir(DATA_DIR):
        return []
    return sorted(
        archivo for archivo in os.listdir(DATA_DIR)
        if archivo.lower().endswith(".json")
        and archivo.lower() != ARCHIVO_HORARIOS_VACACIONES
    )


def seleccionar_malla_interactiva() -> tuple[dict, str]:
    """Lista las mallas disponibles en data/ y deja elegir una por número."""
    archivos = listar_mallas_disponibles()

    if not archivos:
        raise SystemExit(
            f"No se encontraron archivos .json de mallas en {DATA_DIR} "
            f"(se excluye '{ARCHIVO_HORARIOS_VACACIONES}'). Coloca al menos "
            "una malla curricular antes de ejecutar el script."
        )

    opciones = [(archivo, cargar_json(os.path.join(DATA_DIR, archivo))) for archivo in archivos]

    print("\nCarreras / mallas curriculares disponibles:")
    for indice, (archivo, malla) in enumerate(opciones, start=1):
        etiqueta = malla.get("carrera", archivo)
        pensum = malla.get("pensum")
        vigente = malla.get("vigente_desde")
        detalle = f" ({pensum}, {vigente})" if pensum or vigente else ""
        print(f"  {indice}. {etiqueta}{detalle}  [{archivo}]")

    while True:
        seleccion = input(f"Selecciona tu carrera (1-{len(opciones)}): ").strip()
        if seleccion.isdigit() and 1 <= int(seleccion) <= len(opciones):
            archivo_elegido, malla = opciones[int(seleccion) - 1]
            break
        print("Opción inválida. Intenta de nuevo.")

    print(f"Carrera seleccionada: {malla.get('carrera', archivo_elegido)}\n")
    return malla, archivo_elegido


def cargar_periodos_vacacionales(cantidad: int = 30) -> list[dict]:
    """
    Carga data/horarios_vacaciones.json y retorna la lista de periodos
    vacacionales a usar en el plan (en orden cronológico).

    Soporta dos esquemas:
    - Nuevo (recomendado): un único catálogo general en la clave
      "periodo" ({"nombre": ..., "cursos_disponibles": [...]}), que se
      reutiliza para cada ciclo de vacaciones que haga falta planificar
      (mismo catálogo de cursos disponible en cualquier vacación, ya que
      la oferta vacacional de la Facultad no cambia de un ciclo a otro).
      Se generan `cantidad` copias etiquetadas "<nombre> (ciclo 1)",
      "(ciclo 2)", etc. — de sobra para cualquier plan, incluso uno que
      cubra toda la carrera restante con varios semestres de atraso.
    - Antiguo: una lista ya armada en la clave "periodos", cada una con
      su propio "nombre" y "cursos_disponibles" (por si en algún momento
      sí se quiere declarar un catálogo distinto por ciclo). En este caso
      se retorna tal cual, sin importar `cantidad`.
    """
    ruta_horarios = os.path.join(DATA_DIR, ARCHIVO_HORARIOS_VACACIONES)
    if not os.path.isfile(ruta_horarios):
        raise SystemExit(
            f"No se encontró '{ARCHIVO_HORARIOS_VACACIONES}' en {DATA_DIR}."
        )
    datos = cargar_json(ruta_horarios)

    if "periodo" in datos:
        periodo_base = datos["periodo"]
        nombre_base = periodo_base.get("nombre", "Vacaciones")
        cursos_disponibles = periodo_base.get("cursos_disponibles", [])
        return [
            {"nombre": f"{nombre_base} (ciclo {i})", "cursos_disponibles": cursos_disponibles}
            for i in range(1, cantidad + 1)
        ]

    return datos.get("periodos", [])


# ---------------------------------------------------------------------------
# Promedio acumulado -> límite de créditos dinámico
# ---------------------------------------------------------------------------

def solicitar_promedio_acumulado() -> float:
    while True:
        entrada = input("Ingresa tu promedio acumulado (0-100): ").strip()
        try:
            promedio = float(entrada)
        except ValueError:
            print("Debes ingresar un número. Intenta de nuevo.")
            continue
        if 0 <= promedio <= 100:
            return promedio
        print("El promedio debe estar entre 0 y 100. Intenta de nuevo.")


def calcular_limite_creditos(promedio: float) -> int:
    if promedio > 85:
        return 42
    if promedio >= 71:
        return 37
    return 32


# ---------------------------------------------------------------------------
# Búsqueda de cursos por nombre (los códigos varían entre carreras)
# ---------------------------------------------------------------------------

def _normalizar(texto: str) -> str:
    texto = (texto or "").lower().strip()
    return "".join(
        caracter for caracter in unicodedata.normalize("NFKD", texto)
        if not unicodedata.combining(caracter)
    )


def buscar_curso_por_nombre(cursos: list[dict], fragmentos_clave: list[str]) -> dict | None:
    """Primer curso cuyo nombre contenga TODOS los fragmentos (sin acentos/mayúsculas)."""
    fragmentos = [_normalizar(f) for f in fragmentos_clave]
    for curso in cursos:
        nombre = _normalizar(curso.get("nombre", ""))
        if all(fragmento in nombre for fragmento in fragmentos):
            return curso
    return None


def buscar_cursos_por_fragmento(cursos: list[dict], fragmento: str) -> list[dict]:
    """Todos los cursos cuyo nombre contenga el fragmento dado (sin acentos/mayúsculas)."""
    fragmento_normalizado = _normalizar(fragmento)
    if not fragmento_normalizado:
        return []
    return [
        curso for curso in cursos
        if fragmento_normalizado in _normalizar(curso.get("nombre", ""))
    ]


# ---------------------------------------------------------------------------
# Impresión de rutas
# ---------------------------------------------------------------------------

def _totales_periodo(cursos: list[dict]) -> tuple[float, float, float]:
    creditos = sum(curso.get("creditos", 0) for curso in cursos)
    horas_teoricas = sum(horas_teoricas_de(curso) for curso in cursos)
    horas_laboratorio = sum(horas_laboratorio_de(curso) for curso in cursos)
    return creditos, horas_teoricas, horas_laboratorio


def imprimir_ruta(ruta: dict, titulo: str) -> None:
    print(f"\n--- {titulo} ---")
    if not ruta:
        print("  (sin periodos generados)")
        return

    total_creditos_general = 0
    for clave_periodo, cursos in ruta.items():
        creditos, horas_teoricas, horas_laboratorio = _totales_periodo(cursos)
        total_creditos_general += creditos
        print(f"\n  {clave_periodo}  "
              f"[creditos={creditos}, horas_teoricas={horas_teoricas}, "
              f"horas_laboratorio={horas_laboratorio}, cursos={len(cursos)}]")
        if not cursos:
            print("    (sin cursos asignados en este periodo)")
        for curso in cursos:
            marca = "obligatorio" if curso.get("obligatorio", True) else "optativo"
            print(f"    - {curso['codigo']:<6} {curso.get('nombre', ''):<45} "
                  f"cred={curso.get('creditos', 0):<3} "
                  f"teo~={horas_teoricas_de(curso):<4} "
                  f"lab={horas_laboratorio_de(curso):<3} "
                  f"({marca})")
    print(f"\n  Total de créditos planificados: {total_creditos_general}")
