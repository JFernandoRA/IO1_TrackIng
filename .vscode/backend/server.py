# -*- coding: utf-8 -*-
"""
server.py
=========
Servidor HTTP (FastAPI) para TrackIng.

No reimplementa ninguna lógica académica: reutiliza tal cual las funciones
ya existentes en ruta_optima.py y utilidades.py (las mismas que usa
plan_anual.py en consola), y solo las expone como endpoints HTTP para que
el frontend pueda consumirlas.

Además sirve el frontend estático (carpeta ../frontend) para poder correr
todo con un solo comando.

Ejecutar con:  python server.py
(o bien:       uvicorn server:app --reload)
"""

from __future__ import annotations

import os
import sys

# Asegura que este directorio (backend/) esté en sys.path, sin importar si
# este módulo se ejecuta directamente (python server.py) o se importa como
# paquete (p. ej. "backend.server" en Vercel), para que los imports planos
# de abajo (ruta_optima, utilidades) sigan funcionando en ambos casos.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from ruta_optima import (
    RutaOptimaError,
    calcular_plan_restante,
    inyectar_prerequisitos_optativos,
    sanear_aprobados_por_prerequisitos,
)
from utilidades import (
    DATA_DIR,
    cargar_json,
    cargar_periodos_vacacionales,
    calcular_limite_creditos,
    listar_mallas_disponibles,
)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
FRONTEND_DIR = os.path.join(os.path.dirname(BASE_DIR), "frontend")

app = FastAPI(title="TrackIng API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


class SolicitudPlan(BaseModel):
    archivo: str
    semestre_actual: int
    promedio: float
    modo: str
    cursos_aprobados: list[str] = []


def _cargar_malla_o_404(archivo: str) -> dict:
    ruta = os.path.join(DATA_DIR, archivo)
    if not os.path.isfile(ruta):
        raise HTTPException(status_code=404, detail=f"No existe la malla '{archivo}'.")
    return cargar_json(ruta)


@app.get("/api/health")
def health():
    return {"status": "ok"}


@app.get("/api/carreras")
def listar_carreras():
    resultado = []
    for archivo in listar_mallas_disponibles():
        malla = cargar_json(os.path.join(DATA_DIR, archivo))
        resultado.append({
            "archivo": archivo,
            "carrera_id": malla.get("carrera_id"),
            "nombre": malla.get("carrera"),
            "pensum": malla.get("pensum"),
            "vigente_desde": malla.get("vigente_desde"),
            "total_cursos": malla.get("total_cursos"),
        })
    resultado.sort(key=lambda c: (c["nombre"] or "", c["vigente_desde"] or 0))
    return resultado


@app.get("/api/malla/{archivo}")
def obtener_malla(archivo: str):
    return _cargar_malla_o_404(archivo)


@app.post("/api/plan")
def calcular_plan(solicitud: SolicitudPlan):
    malla = _cargar_malla_o_404(solicitud.archivo)
    cursos = inyectar_prerequisitos_optativos(malla["cursos"])
    por_codigo = {curso["codigo"]: curso for curso in cursos}

    semestre_actual = solicitud.semestre_actual
    aprobados_input = set(solicitud.cursos_aprobados)

    reprobados = {
        codigo for codigo, curso in por_codigo.items()
        if curso.get("obligatorio", True)
        and curso.get("semestre", 0) < semestre_actual
        and codigo not in aprobados_input
    }

    aprobados, removidos_por_arrastre = sanear_aprobados_por_prerequisitos(
        cursos, aprobados_input
    )

    limite_creditos = calcular_limite_creditos(solicitud.promedio)
    periodos_vacacionales = cargar_periodos_vacacionales()

    try:
        plan = calcular_plan_restante(
            cursos,
            periodos_vacacionales,
            semestre_actual=semestre_actual,
            aprobados=aprobados,
            reprobados=reprobados,
            limite_creditos=limite_creditos,
            modo=solicitud.modo,
        )
    except RutaOptimaError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error

    atrasados_iniciales = [
        {"codigo": codigo, "nombre": por_codigo[codigo]["nombre"]}
        for codigo in plan["atrasados_iniciales"]
    ]
    removidos = [
        {"codigo": codigo, "nombre": por_codigo[codigo]["nombre"]}
        for codigo in sorted(removidos_por_arrastre)
        if codigo in por_codigo
    ]

    return {
        "periodos": plan["periodos"],
        "atrasados_iniciales": atrasados_iniciales,
        "removidos_por_arrastre": removidos,
        "duracion_normal_pensum": plan["duracion_normal_pensum"],
        "semestres_cursados": plan["semestres_cursados"],
        "semestre_estimado_cierre": plan["semestre_estimado_cierre"],
        "semestres_extra": plan["semestres_extra"],
        "limite_creditos": limite_creditos,
        "modo": plan["modo"],
    }


if os.path.isdir(FRONTEND_DIR):
    app.mount("/", StaticFiles(directory=FRONTEND_DIR, html=True), name="frontend")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
