from __future__ import annotations

import sys

from ruta_optima import (
    RutaOptimaError,
    calcular_plan_restante,
    inyectar_prerequisitos_optativos,
    sanear_aprobados_por_prerequisitos,
)
from utilidades import (
    buscar_cursos_por_fragmento,
    cargar_periodos_vacacionales,
    calcular_limite_creditos,
    imprimir_ruta,
    seleccionar_malla_interactiva,
    solicitar_promedio_acumulado,
)

MODOS_MENU = {
    "1": ("avanzar", "Adelantarme (cerrar la carrera antes de tiempo)"),
    "2": ("nivelarse", "Nivelarme / ponerme al día lo más posible sin atrasarme más"),
    "3": ("tiempo_normal", "Mantener el tiempo normal de cierre de la carrera"),
}


# ---------------------------------------------------------------------------
# Entrada de datos del estudiante
# ---------------------------------------------------------------------------

def solicitar_semestre_actual(cursos: list[dict]) -> int:
    semestres_disponibles = sorted({
        curso.get("semestre") for curso in cursos if curso.get("semestre") is not None
    })
    minimo, maximo = semestres_disponibles[0], semestres_disponibles[-1]
    while True:
        entrada = input(
            f"\n¿En qué semestre del pénsum vas actualmente? "
            f"({minimo}-{maximo}): "
        ).strip()
        if entrada.isdigit() and minimo <= int(entrada) <= maximo:
            return int(entrada)
        print("Ingresa un número de semestre válido.")


def _elegir_entre_coincidencias(coincidencias: list[dict], fragmento: str) -> dict | None:
    if len(coincidencias) == 1:
        return coincidencias[0]

    print(f"  Hay varios cursos que coinciden con '{fragmento}':")
    for indice, curso in enumerate(coincidencias, start=1):
        print(f"    {indice}. {curso['codigo']} - {curso['nombre']} "
              f"(semestre {curso.get('semestre', '?')})")
    print(f"    0. Ninguno de estos / cancelar")

    while True:
        seleccion = input(f"  Elige un curso (0-{len(coincidencias)}): ").strip()
        if seleccion.isdigit():
            seleccion_int = int(seleccion)
            if seleccion_int == 0:
                return None
            if 1 <= seleccion_int <= len(coincidencias):
                return coincidencias[seleccion_int - 1]
        print("  Opción inválida.")


def solicitar_cursos_por_nombre(cursos: list[dict], instruccion: str) -> set[str]:
    print(f"\n{instruccion}")
    print("  (Escribe parte del nombre del curso, por ejemplo 'fisica 1'. "
          "Escribe 'listo' cuando termines.)")
    seleccionados: set[str] = set()
    while True:
        entrada = input("  > ").strip()
        if not entrada or entrada.lower() in ("listo", "ninguno", "no"):
            break
        coincidencias = buscar_cursos_por_fragmento(cursos, entrada)
        if not coincidencias:
            print(f"  No se encontró ningún curso con '{entrada}'. Intenta de nuevo.")
            continue
        curso = _elegir_entre_coincidencias(coincidencias, entrada)
        if curso is None:
            continue
        seleccionados.add(curso["codigo"])
        print(f"  Agregado: {curso['codigo']} - {curso['nombre']}")
    return seleccionados


def solicitar_modo() -> str:
    print("\n¿Cuál es tu objetivo para lo que resta de la carrera?")
    for clave, (_modo, descripcion) in MODOS_MENU.items():
        print(f"  {clave}. {descripcion}")
    while True:
        entrada = input("Elige una opción (1-3): ").strip()
        if entrada in MODOS_MENU:
            return MODOS_MENU[entrada][0]
        print("Opción inválida.")


# ---------------------------------------------------------------------------
# Resumen final
# ---------------------------------------------------------------------------

def imprimir_resumen(plan: dict, por_codigo: dict[str, dict], semestre_actual: int) -> None:
    print("\n" + "=" * 70)
    print("RESUMEN")
    print("=" * 70)

    atrasados_iniciales = plan["atrasados_iniciales"]

    if not atrasados_iniciales:
        print(f"  Ibas al día con el pénsum hasta el semestre {semestre_actual}: "
              "no había cursos atrasados pendientes al iniciar el plan.")
    else:
        nombres_iniciales = [
            f"{codigo} - {por_codigo[codigo]['nombre']}" for codigo in atrasados_iniciales
        ]
        print(f"  Cursos atrasados (de semestre anterior al {semestre_actual}) "
              "al iniciar el plan:")
        for nombre in nombres_iniciales:
            print(f"    - {nombre}")

    duracion_normal = plan["duracion_normal_pensum"]
    semestre_cierre = plan["semestre_estimado_cierre"]
    semestres_extra = plan["semestres_extra"]

    print(f"\n  Duración normal del pénsum: {duracion_normal} semestres.")
    print(f"  Semestres a cursar desde ahora: {plan['semestres_cursados']} "
          f"(proyecta cierre en el semestre {semestre_cierre}).")

    if semestres_extra == 0:
        print("\n  [OK] Con este plan cierras la carrera dentro del tiempo normal "
              "del pénsum (o antes).")
    else:
        plural = "semestre" if semestres_extra == 1 else "semestres"
        print(f"\n  [!] Con este plan NO alcanzas a cerrar en el tiempo normal: "
              f"necesitarás {semestres_extra} {plural} adicional(es) por encima "
              f"de los {duracion_normal} semestres oficiales del pénsum, dado el "
              "atraso actual y el límite de créditos que te permite tu promedio.")

    modo_legible = {
        "avanzar": "adelantarte y cerrar antes de tiempo",
        "nivelarse": "nivelarte / no atrasarte más",
        "tiempo_normal": "mantener el tiempo normal de cierre",
    }[plan["modo"]]
    print(f"\n  Objetivo elegido: {modo_legible}.")


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

def main() -> None:
    print("=" * 70)
    print("TrackIng - Plan hasta el cierre de la carrera")
    print("=" * 70)

    malla_json, _archivo_malla = seleccionar_malla_interactiva()
    cursos_malla = inyectar_prerequisitos_optativos(malla_json["cursos"])
    por_codigo = {curso["codigo"]: curso for curso in cursos_malla}

    semestre_actual = solicitar_semestre_actual(cursos_malla)

    aprobados = {
        curso["codigo"] for curso in cursos_malla
        if curso.get("obligatorio", True) and curso.get("semestre", 0) < semestre_actual
    }

    reprobados = solicitar_cursos_por_nombre(
        cursos_malla,
        f"¿Hay cursos de semestres anteriores al {semestre_actual} que AÚN NO "
        "has ganado (reprobados o pendientes)? Ej: 'fisica 1'.",
    )
    aprobados -= reprobados

    adelantados = solicitar_cursos_por_nombre(
        cursos_malla,
        "¿Ya llevas ganado algún curso de semestres FUTUROS por adelantado? "
        "(opcional)",
    )
    aprobados |= adelantados
    reprobados -= adelantados

    aprobados, removidos_por_arrastre = sanear_aprobados_por_prerequisitos(
        cursos_malla, aprobados
    )
    if removidos_por_arrastre:
        print("\n[!] Por arrastre de prerequisitos, tampoco tendrías ganados "
              "estos cursos (dependen directa o indirectamente de algo que "
              "aún no ganas), aunque sean de un semestre anterior al actual:")
        for codigo in sorted(removidos_por_arrastre):
            curso = por_codigo.get(codigo, {})
            print(f"    - {codigo} - {curso.get('nombre', '(desconocido)')}")

    promedio = solicitar_promedio_acumulado()
    limite_creditos = calcular_limite_creditos(promedio)
    print(f"\nLímite de créditos por semestre según tu promedio ({promedio:.2f}): "
          f"{limite_creditos} créditos.")

    modo = solicitar_modo()

    periodos_vacacionales = cargar_periodos_vacacionales()

    try:
        plan = calcular_plan_restante(
            cursos_malla,
            periodos_vacacionales,
            semestre_actual=semestre_actual,
            aprobados=aprobados,
            reprobados=reprobados,
            limite_creditos=limite_creditos,
            modo=modo,
        )
    except RutaOptimaError as error:
        print(f"\n[ERROR] No se pudo calcular el plan: {error}")
        return

    imprimir_ruta(plan["periodos"], "Plan hasta el cierre de la carrera")
    imprimir_resumen(plan, por_codigo, semestre_actual)

    print("\n" + "=" * 70)
    print("Fin.")
    print("=" * 70)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit("\nEjecución cancelada por el usuario.")
