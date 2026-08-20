# -*- coding: utf-8 -*-
"""
test_algoritmo.py
==================
Script de pruebas / demostración para ruta_optima.py.

Diseñado para leer las mallas curriculares reales de la Facultad de
Ingeniería de la USAC (exportadas de redesEstudio), ubicadas en
backend/data/*.json, con la forma:

    {
        "carrera": "Ingeniería en Ciencias y Sistemas",
        "carrera_id": "ingenieriaEnCienciasYSistemas",
        "pensum": "CLAR",
        "vigente_desde": 2025,
        "cursos": [
            {"codigo": "0101", "nombre": "...", "creditos": 9,
             "semestre": 1, "prerequisitos": [], "obligatorio": true},
            ...
        ]
    }

Cualquier archivo .json dentro de data/ (excepto horarios_vacaciones.json)
se trata como una malla curricular seleccionable.

Flujo de main():
  1. Selección interactiva de malla curricular (data/*.json).
  2. Solicita el promedio acumulado del usuario (0-100) y calcula el
     límite de créditos dinámico:
         > 85            -> 42 créditos
         71 - 85         -> 37 créditos
         < 71             -> 32 créditos
  3. Carga automáticamente data/horarios_vacaciones.json.
  4. Inyecta como obligatorios temporales cualquier optativo que sea
     prerequisito de un obligatorio.
  5. Ejecuta 3 casos de prueba secuenciales:
       Caso 1: estudiante nuevo (ruta regular + vacaciones intercaladas)
       Caso 2: estudiante que perdió "Matemática Básica 1" (se busca por
               nombre en la malla elegida, ya que el código varía entre
               carreras) -> confirma reprogramación dinámica, no fija a
               "Semestre_1"
       Caso 3: estudiante con promedio bajo (<71) -> 32 créditos/slot

Cada caso imprime totales de créditos/horas por periodo y corre
verificaciones automáticas de prerequisitos y límites.

Compatible con Windows, Python 3.13 y NetworkX 3.6.1. Sin dependencias
adicionales a las de ruta_optima.py.
"""

from __future__ import annotations

import sys

from ruta_optima import (
    RutaOptimaError,
    calcular_ruta_regular,
    calcular_ruta_vacaciones,
    horas_teoricas_de,
    inyectar_prerequisitos_optativos,
)
from utilidades import (
    buscar_curso_por_nombre,
    calcular_limite_creditos,
    cargar_periodos_vacacionales,
    imprimir_ruta,
    seleccionar_malla_interactiva,
    solicitar_promedio_acumulado,
)


def verificar_prerequisitos(ruta: dict, malla_cursos: list[dict],
                             aprobados_iniciales: set[str] | None = None) -> list[str]:
    """
    Recorre la ruta periodo por periodo y confirma que ningún curso se
    programó sin tener sus prerequisitos satisfechos por periodos
    anteriores (o por lo ya aprobado al inicio).
    """
    por_codigo = {curso["codigo"]: curso for curso in malla_cursos}
    aprobados_acumulado = set(aprobados_iniciales or [])
    violaciones = []

    for clave_periodo, cursos in ruta.items():
        for curso in cursos:
            prereqs = set(por_codigo.get(curso["codigo"], curso).get("prerequisitos", []))
            faltantes = prereqs - aprobados_acumulado
            if faltantes:
                violaciones.append(
                    f"{clave_periodo}: '{curso['codigo']}' programado sin "
                    f"cumplir prerequisitos {sorted(faltantes)}"
                )
        for curso in cursos:
            aprobados_acumulado.add(curso["codigo"])

    return violaciones


def verificar_limite_creditos(ruta: dict, limite_creditos: int) -> list[str]:
    violaciones = []
    for clave_periodo, cursos in ruta.items():
        creditos = sum(curso.get("creditos", 0) for curso in cursos)
        if creditos > limite_creditos:
            violaciones.append(
                f"{clave_periodo}: {creditos} créditos excede el límite de "
                f"{limite_creditos}"
            )
    return violaciones


def verificar_limite_vacaciones(ruta: dict, limite_horas_teoricas: float = 4,
                                 max_cursos: int = 3) -> list[str]:
    violaciones = []
    for clave_periodo, cursos in ruta.items():
        horas_teoricas = sum(horas_teoricas_de(curso) for curso in cursos)
        if horas_teoricas > limite_horas_teoricas:
            violaciones.append(
                f"{clave_periodo}: {horas_teoricas} horas teóricas excede el "
                f"límite de {limite_horas_teoricas}"
            )
        if len(cursos) > max_cursos:
            violaciones.append(
                f"{clave_periodo}: {len(cursos)} cursos excede el máximo de "
                f"{max_cursos} por periodo vacacional"
            )
    return violaciones


def imprimir_verificaciones(etiqueta: str, violaciones: list[str]) -> None:
    if violaciones:
        print(f"  [ERROR] {etiqueta}: se encontraron {len(violaciones)} violación(es):")
        for violacion in violaciones:
            print(f"    - {violacion}")
    else:
        print(f"  [OK] {etiqueta}: sin violaciones.")


# ---------------------------------------------------------------------------
# Ruta intercalada (regular + vacaciones), orquestada a nivel de script
# ---------------------------------------------------------------------------

def construir_ruta_intercalada(
    malla_inyectada: list[dict],
    periodos_vacacionales: list[dict],
    limite_creditos: int,
    aprobados_iniciales: set[str] | None = None,
    reprobados_iniciales: set[str] | None = None,
    aplicar_vacaciones_cada_n_semestres: int = 2,
) -> dict:
    """
    Intercala periodos vacacionales dentro de la ruta regular llamando a
    ambas funciones de forma independiente y combinando sus resultados
    (ambas retornan la misma estructura {clave: [cursos]}, por lo que se
    pueden fusionar directamente en un solo diccionario ordenado).
    """
    aprobados = set(aprobados_iniciales or [])
    reprobados = set(reprobados_iniciales or [])
    ruta_combinada: dict[str, list[dict]] = {}

    semestre_num = 0
    vac_idx = 0

    while True:
        pendientes_obligatorios = {
            curso["codigo"] for curso in malla_inyectada
            if curso.get("obligatorio", True)
            and (curso["codigo"] not in aprobados or curso["codigo"] in reprobados)
        }
        if not pendientes_obligatorios:
            break

        semestre_num += 1
        # Se recalcula la ruta regular completa con el estado actual y se
        # toma solo el primer slot resultante: así cada nuevo semestre
        # aprovecha lo que ya se adelantó en vacaciones.
        parcial = calcular_ruta_regular(
            malla_inyectada,
            aprobados=aprobados,
            reprobados=reprobados,
            limite_creditos=limite_creditos,
        )
        primera_clave = next(iter(parcial))
        cursos_semestre = parcial[primera_clave]
        clave_final = f"Semestre_{semestre_num}"
        ruta_combinada[clave_final] = cursos_semestre

        for curso in cursos_semestre:
            aprobados.add(curso["codigo"])
            reprobados.discard(curso["codigo"])

        if (semestre_num % aplicar_vacaciones_cada_n_semestres == 0
                and vac_idx < len(periodos_vacacionales)):
            periodo = periodos_vacacionales[vac_idx]
            vac_idx += 1
            resultado_vac = calcular_ruta_vacaciones(
                malla_inyectada, [periodo], aprobados=aprobados
            )
            clave_vac = next(iter(resultado_vac))
            ruta_combinada[clave_vac] = resultado_vac[clave_vac]
            for curso in resultado_vac[clave_vac]:
                aprobados.add(curso["codigo"])

    return ruta_combinada


# ---------------------------------------------------------------------------
# Casos de prueba
# ---------------------------------------------------------------------------

def caso_1_estudiante_nuevo(malla_inyectada, periodos_vacacionales, limite_creditos):
    print("\n" + "=" * 70)
    print("CASO 1: Estudiante nuevo (ruta regular + vacaciones intercaladas)")
    print("=" * 70)

    try:
        ruta = construir_ruta_intercalada(
            malla_inyectada, periodos_vacacionales, limite_creditos,
            aprobados_iniciales=set(), reprobados_iniciales=set(),
        )
    except RutaOptimaError as error:
        print(f"  [ERROR] No se pudo calcular la ruta: {error}")
        return

    imprimir_ruta(ruta, "Ruta intercalada (regular + vacaciones)")

    violaciones_prereq = verificar_prerequisitos(ruta, malla_inyectada)
    imprimir_verificaciones("Prerequisitos", violaciones_prereq)

    # Los periodos "Semestre_*" respetan limite_creditos; el resto (los
    # periodos vacacionales, cualquiera sea su nombre) respeta el límite
    # de horas teóricas y máximo de cursos.
    claves_semestre = {clave: cursos for clave, cursos in ruta.items()
                        if clave.startswith("Semestre_")}
    claves_vacaciones = {clave: cursos for clave, cursos in ruta.items()
                          if not clave.startswith("Semestre_")}
    imprimir_verificaciones(
        "Límite de créditos (semestres)",
        verificar_limite_creditos(claves_semestre, limite_creditos),
    )
    imprimir_verificaciones(
        "Límite de horas / cursos (vacaciones)",
        verificar_limite_vacaciones(claves_vacaciones),
    )


def caso_2_perdio_matematica_basica_1(malla_inyectada, limite_creditos):
    print("\n" + "=" * 70)
    print("CASO 2: Estudiante que perdió 'Matemática Básica 1'")
    print("=" * 70)

    # El código varía entre carreras, así que el curso se busca por
    # nombre dentro de la malla elegida en tiempo de ejecución.
    curso_objetivo = buscar_curso_por_nombre(
        malla_inyectada, ["matematica", "basica", "1"]
    )
    if curso_objetivo is None:
        candidatos_sem1 = [
            c for c in malla_inyectada
            if c.get("semestre") == 1 and c.get("obligatorio", True)
        ]
        if not candidatos_sem1:
            print("  [ERROR] No se encontró un curso de primer semestre en "
                  "esta malla para simular la reprobación.")
            return
        curso_objetivo = candidatos_sem1[0]
        print(f"  (No se encontró 'Matemática Básica 1' por nombre; se usa "
              f"'{curso_objetivo['nombre']}' como sustituto de primer "
              "semestre.)")

    codigo_objetivo = curso_objetivo["codigo"]
    semestre_objetivo = curso_objetivo.get("semestre", 1)
    print(f"  Curso simulado como reprobado: '{codigo_objetivo}' - "
          f"{curso_objetivo['nombre']} (semestre oficial {semestre_objetivo})")

    # El estudiante ya aprobó el resto de cursos obligatorios de ese mismo
    # semestre oficial, pero reprobó el curso objetivo.
    aprobados = {
        c["codigo"] for c in malla_inyectada
        if c.get("semestre") == semestre_objetivo
        and c.get("obligatorio", True)
        and c["codigo"] != codigo_objetivo
    }
    reprobados = {codigo_objetivo}

    try:
        ruta = calcular_ruta_regular(
            malla_inyectada,
            aprobados=aprobados,
            reprobados=reprobados,
            limite_creditos=limite_creditos,
        )
    except RutaOptimaError as error:
        print(f"  [ERROR] No se pudo calcular la ruta: {error}")
        return

    imprimir_ruta(ruta, "Ruta regular con reprogramación dinámica")

    primer_slot_con_objetivo = next(
        (clave for clave, cursos in ruta.items()
         if any(curso["codigo"] == codigo_objetivo for curso in cursos)),
        None,
    )
    if primer_slot_con_objetivo:
        print(f"\n  Verificación de reprogramación: '{codigo_objetivo}' se "
              f"reprogramó en '{primer_slot_con_objetivo}' (el primer slot "
              "futuro con cupo disponible, no un 'Semestre_1' fijo por "
              "pénsum oficial).")
    else:
        print(f"\n  [ERROR] '{codigo_objetivo}' no aparece en la ruta recalculada.")

    violaciones_prereq = verificar_prerequisitos(
        ruta, malla_inyectada, aprobados_iniciales=aprobados
    )
    imprimir_verificaciones("Prerequisitos", violaciones_prereq)
    imprimir_verificaciones(
        "Límite de créditos", verificar_limite_creditos(ruta, limite_creditos)
    )


def caso_3_promedio_bajo(malla_inyectada):
    print("\n" + "=" * 70)
    print("CASO 3: Estudiante con promedio bajo (<71 -> 32 créditos por slot)")
    print("=" * 70)

    limite_bajo = calcular_limite_creditos(50.0)  # 50 < 71 -> 32 créditos
    limite_alto = calcular_limite_creditos(90.0)  # referencia para comparar

    try:
        ruta_bajo = calcular_ruta_regular(
            malla_inyectada, aprobados=set(), reprobados=set(),
            limite_creditos=limite_bajo,
        )
        ruta_alto = calcular_ruta_regular(
            malla_inyectada, aprobados=set(), reprobados=set(),
            limite_creditos=limite_alto,
        )
    except RutaOptimaError as error:
        print(f"  [ERROR] No se pudo calcular la ruta: {error}")
        return

    imprimir_ruta(ruta_bajo, f"Ruta regular con límite bajo ({limite_bajo} créditos)")

    print(f"\n  Comparación de semestres necesarios:")
    print(f"    - Límite {limite_bajo} créditos (<71 de promedio): "
          f"{len(ruta_bajo)} semestres")
    print(f"    - Límite {limite_alto} créditos (>85 de promedio, referencia): "
          f"{len(ruta_alto)} semestres")

    if len(ruta_bajo) >= len(ruta_alto):
        print("  [OK] El límite más bajo generó igual o más semestres, "
              "como se esperaba.")
    else:
        print("  [ERROR] El límite más bajo generó menos semestres que el "
              "límite alto; esto no debería ocurrir.")

    violaciones_prereq = verificar_prerequisitos(ruta_bajo, malla_inyectada)
    imprimir_verificaciones("Prerequisitos", violaciones_prereq)

    violaciones_limite = verificar_limite_creditos(ruta_bajo, limite_bajo)
    imprimir_verificaciones(f"Límite de créditos ({limite_bajo})", violaciones_limite)

    # "Óptimo" en este contexto: se revisa cuánto del cupo de cada slot se
    # usa en promedio, como indicador de que no se desperdicia capacidad
    # de forma sistemática.
    print("  Verificación de optimalidad (uso de cupo por slot):")
    total_slots = len(ruta_bajo)
    creditos_usados = sum(
        sum(curso.get("creditos", 0) for curso in cursos)
        for cursos in ruta_bajo.values()
    )
    capacidad_total = total_slots * limite_bajo
    porcentaje_uso = (creditos_usados / capacidad_total * 100) if capacidad_total else 0
    print(f"    - Uso promedio de capacidad por slot: {porcentaje_uso:.1f}% "
          f"({creditos_usados}/{capacidad_total} créditos)")


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

def main() -> None:
    print("=" * 70)
    print("TrackIng - Pruebas de ruta_optima.py")
    print("=" * 70)

    # 1) Selección interactiva de malla curricular (se mantiene intacta).
    malla_json, _archivo_malla = seleccionar_malla_interactiva()
    cursos_malla = malla_json["cursos"]

    # 2) Promedio acumulado -> límite de créditos dinámico.
    promedio = solicitar_promedio_acumulado()
    limite_creditos = calcular_limite_creditos(promedio)
    print(f"\nPromedio ingresado: {promedio:.2f}")
    print(f"Límite de créditos asignado para esta ejecución: {limite_creditos} "
          "créditos por semestre.\n")

    # 3) Carga automática de horarios vacacionales desde data/.
    periodos_vacacionales = cargar_periodos_vacacionales()
    print(f"Periodos vacacionales cargados: "
          f"{[p['nombre'] for p in periodos_vacacionales]}")

    # 4) Inyectar optativos-prerequisito como obligatorios temporales.
    malla_inyectada = inyectar_prerequisitos_optativos(cursos_malla)
    codigos_obligatorios_originales = {
        curso["codigo"] for curso in cursos_malla if curso.get("obligatorio", True)
    }
    codigos_inyectados = {
        curso["codigo"] for curso in malla_inyectada if curso.get("obligatorio", True)
    } - codigos_obligatorios_originales
    if codigos_inyectados:
        print(f"Optativos inyectados como obligatorios temporales "
              f"(son prerequisito de un obligatorio): {sorted(codigos_inyectados)}")
    else:
        print("No hay optativos que deban inyectarse como obligatorios temporales "
              "en esta malla.")

    # 5) Tres casos de prueba secuenciales.
    caso_1_estudiante_nuevo(malla_inyectada, periodos_vacacionales, limite_creditos)
    caso_2_perdio_matematica_basica_1(malla_inyectada, limite_creditos)
    caso_3_promedio_bajo(malla_inyectada)

    print("\n" + "=" * 70)
    print("Fin de las pruebas.")
    print("=" * 70)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit("\nEjecución cancelada por el usuario.")