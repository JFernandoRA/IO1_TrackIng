from __future__ import annotations

import json
import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
ARCHIVO_HORARIOS_VACACIONES = "horarios_vacaciones.json"


def cargar_json(ruta: str) -> dict:
    with open(ruta, "r", encoding="utf-8") as archivo:
        return json.load(archivo)


def listar_mallas_disponibles() -> list[str]:
    if not os.path.isdir(DATA_DIR):
        return []
    return sorted(
        archivo for archivo in os.listdir(DATA_DIR)
        if archivo.lower().endswith(".json")
        and archivo.lower() != ARCHIVO_HORARIOS_VACACIONES
    )


def cargar_periodos_vacacionales(cantidad: int = 30) -> list[dict]:
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


def calcular_limite_creditos(promedio: float) -> int:
    if promedio > 85:
        return 42
    if promedio >= 71:
        return 37
    return 32
