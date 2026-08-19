#!/usr/bin/env python3
"""
test_algoritmo.py

Script de consola independiente para probar `calcular_ruta_optima`
(ver ruta_optima.py) directamente sobre las mallas curriculares reales,
ANTES de integrar el algoritmo a cualquier API o frontend.

Uso:
    python3 test_algoritmo.py

Requisitos:
    - networkx instalado (pip install networkx)
    - ruta_optima.py en el mismo directorio (o en el PYTHONPATH)
    - una carpeta "data/" junto a este script con los JSON de mallas
      curriculares (formato: carrera, carrera_id, pensum, vigente_desde,
      fuente, total_cursos, cursos: [...])
"""

import json
import os
import sys
import unicodedata

from ruta_optima import calcular_ruta_optima, RutaOptimaError

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
LIMITE_CREDITOS_DEFECTO = 25


# ---------------------------------------------------------------------
# Utilidades de carga y presentación
# ---------------------------------------------------------------------

def normalizar_texto(texto: str) -> str:
    """minúsculas y sin acentos, para comparar nombres de curso sin líos."""
    texto = texto.strip().lower()
    texto = unicodedata.normalize("NFD", texto)
    return "".join(ch for ch in texto if unicodedata.category(ch) != "Mn")


def listar_archivos_malla() -> list:
    if not os.path.isdir(DATA_DIR):
        print(f"\n[ERROR] No se encontró la carpeta de datos en: {DATA_DIR}")
        print("Coloca los JSON de las mallas curriculares en una carpeta 'data/' "
              "junto a este script.\n")
        sys.exit(1)

    archivos = sorted(f for f in os.listdir(DATA_DIR) if f.endswith(".json"))
    if not archivos:
        print(f"\n[ERROR] No hay archivos .json dentro de {DATA_DIR}\n")
        sys.exit(1)
    return archivos


def elegir_malla(archivos: list) -> str:
    print("\nMallas curriculares disponibles:\n")
    for i, nombre_archivo in enumerate(archivos, start=1):
        print(f"  [{i}] {nombre_archivo}")

    while True:
        eleccion = input(f"\nElige el número de la carrera a analizar (1-{len(archivos)}): ").strip()
        if eleccion.isdigit() and 1 <= int(eleccion) <= len(archivos):
            return archivos[int(eleccion) - 1]
        print("Entrada inválida, intenta de nuevo.")


def cargar_malla_como_diccionario(ruta_archivo: str) -> dict:
    """
    Convierte el JSON real (con "cursos" como lista) al formato de
    diccionario código -> curso que espera calcular_ruta_optima.
    """
    with open(ruta_archivo, "r", encoding="utf-8") as f:
        datos = json.load(f)

    malla = {}
    for curso in datos.get("cursos", []):
        codigo = str(curso["codigo"]).strip().upper()
        malla[codigo] = {
            "codigo": codigo,
            "nombre": curso["nombre"],
            "creditos": curso["creditos"],
            "semestre": curso["semestre"],
            "prerequisitos": [str(p).strip().upper() for p in curso.get("prerequisitos", [])],
            "obligatorio": curso.get("obligatorio", True),
        }
    return malla, datos.get("carrera", "?")


def encontrar_codigo_matematica_basica_1(malla: dict) -> str:
    """
    Busca en semestre 1 un curso obligatorio cuyo nombre sugiera
    "Matemática Básica 1" (con o sin acentos, variantes de redacción).
    Si no lo encuentra, cae de vuelta al primer curso obligatorio de
    semestre 1 como aproximación razonable.
    """
    candidatos_semestre_1 = [
        c for c in malla.values() if c.get("obligatorio", True) and c.get("semestre") == 1
    ]

    for curso in candidatos_semestre_1:
        nombre_norm = normalizar_texto(curso["nombre"])
        if "matematica basica 1" in nombre_norm or "matematica basica i" in nombre_norm:
            return curso["codigo"]

    if candidatos_semestre_1:
        print(
            "  (No se encontró un curso llamado exactamente 'Matemática Básica 1'; "
            f"se usará '{candidatos_semestre_1[0]['nombre']}' como aproximación de "
            "primer semestre para el caso de prueba.)"
        )
        return candidatos_semestre_1[0]["codigo"]

    return None


def imprimir_ruta(resultado: dict) -> None:
    if "advertencia" in resultado:
        print("\n  ⚠ ADVERTENCIA:", resultado["advertencia"])
        print("  Cursos involucrados en el bloqueo:", ", ".join(resultado["cursos_bloqueados"]))
        if resultado.get("ruta_parcial"):
            print("\n  Ruta parcial calculada antes del bloqueo:")
            imprimir_ruta(resultado["ruta_parcial"])
        return

    if not resultado:
        print("\n  ✓ No hay cursos obligatorios pendientes: la ruta ya está completa.")
        return

    for clave_semestre, cursos in resultado.items():
        creditos_totales = sum(c["creditos"] for c in cursos)
        print(f"\n  {clave_semestre}  ({creditos_totales} créditos, {len(cursos)} cursos)")
        for curso in cursos:
            print(f"    - [{curso['codigo']}] {curso['nombre']} "
                  f"({curso['creditos']} cr., semestre oficial {curso['semestre_oficial']})")

    print(f"\n  Total de semestres necesarios: {len(resultado)}")


def contar_optativos(malla: dict) -> int:
    return sum(1 for c in malla.values() if not c.get("obligatorio", True))


# ---------------------------------------------------------------------
# Casos de prueba
# ---------------------------------------------------------------------

def caso_estudiante_nuevo(malla: dict, limite_creditos: int) -> None:
    print("\n" + "=" * 70)
    print("CASO 1: Estudiante nuevo (0 cursos aprobados)")
    print("=" * 70)
    print("Objetivo: validar la ruta base completa desde el primer semestre.")

    resultado = calcular_ruta_optima([], malla, limite_creditos)
    imprimir_ruta(resultado)


def caso_perdio_matematica_1(malla: dict, limite_creditos: int) -> None:
    print("\n" + "=" * 70)
    print("CASO 2: Estudiante que perdió Matemática Básica 1 pero aprobó")
    print("        las demás materias de primer semestre")
    print("=" * 70)
    print("Objetivo: validar que la ruta reordena y respeta el prerequisito")
    print("          faltante en vez de intentar avanzar de forma inválida.")

    codigo_mate1 = encontrar_codigo_matematica_basica_1(malla)
    if codigo_mate1 is None:
        print("\n  (No hay cursos obligatorios de semestre 1 en esta malla; se omite este caso.)")
        return

    aprobados = [
        c["codigo"]
        for c in malla.values()
        if c.get("obligatorio", True) and c.get("semestre") == 1 and c["codigo"] != codigo_mate1
    ]

    print(f"\n  Curso NO aprobado (reprobado): {codigo_mate1} "
          f"({malla[codigo_mate1]['nombre']})")
    print(f"  Cursos aprobados de primer semestre: {', '.join(aprobados) if aprobados else '(ninguno más)'}")

    resultado = calcular_ruta_optima(aprobados, malla, limite_creditos)
    imprimir_ruta(resultado)

    # Verificación visual rápida: el curso reprobado debe seguir
    # apareciendo en la ruta, y cualquier curso que dependa de él NO
    # debería aparecer antes que él.
    if "advertencia" not in resultado:
        semestre_de_mate1 = None
        for clave_semestre, cursos in resultado.items():
            if any(c["codigo"] == codigo_mate1 for c in cursos):
                semestre_de_mate1 = clave_semestre
                break
        if semestre_de_mate1:
            print(f"\n  ✓ Verificación: '{codigo_mate1}' fue reprogramado en {semestre_de_mate1}, "
                  "como corresponde al no estar aprobado.")
        else:
            print(f"\n  ⚠ Verificación: '{codigo_mate1}' no aparece en ningún semestre de la ruta "
                  "(revisar lógica).")


# ---------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------

def main():
    print("TrackIng — banco de pruebas del algoritmo de ruta óptima")
    print("(ejecución local, sin API ni frontend)\n")

    archivos = listar_archivos_malla()
    archivo_elegido = elegir_malla(archivos)
    ruta_completa = os.path.join(DATA_DIR, archivo_elegido)

    try:
        malla, nombre_carrera = cargar_malla_como_diccionario(ruta_completa)
    except (KeyError, json.JSONDecodeError) as e:
        print(f"\n[ERROR] El archivo '{archivo_elegido}' no tiene el formato esperado: {e}")
        sys.exit(1)

    total_obligatorios = sum(1 for c in malla.values() if c.get("obligatorio", True))
    total_optativos = contar_optativos(malla)

    print(f"\nCarrera seleccionada: {nombre_carrera}")
    print(f"Total de cursos en la malla: {len(malla)} "
          f"({total_obligatorios} obligatorios, {total_optativos} optativos)")
    print(f"Límite de créditos por semestre usado en las pruebas: {LIMITE_CREDITOS_DEFECTO}")

    try:
        caso_estudiante_nuevo(malla, LIMITE_CREDITOS_DEFECTO)
        caso_perdio_matematica_1(malla, LIMITE_CREDITOS_DEFECTO)
    except RutaOptimaError as e:
        print(f"\n[ERROR de validación de entrada] {e}")
        sys.exit(1)

    print("\n" + "=" * 70)
    print("Fin de las pruebas.")
    print("=" * 70)


if __name__ == "__main__":
    main()