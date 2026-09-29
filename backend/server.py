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
    excluir_cursos,
    inyectar_prerequisitos_optativos,
    sanear_aprobados_por_prerequisitos,
    seleccionar_cursos_objetivo,
    tipo_de_curso,
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
    cursos_excluidos: list[str] = []
    cursos_solo_vacaciones: list[str] = []
    cursos_solo_semestre: list[str] = []
    incluir_idiomas: bool = False
    iniciar_en_vacaciones: bool = False


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
    cursos_malla = [{**curso, "tipo": tipo_de_curso(curso)} for curso in malla["cursos"]]
    por_codigo_malla = {curso["codigo"]: curso for curso in cursos_malla}

    semestre_actual = solicitud.semestre_actual
    excluidos_input = set(solicitud.cursos_excluidos)
    aprobados_input = set(solicitud.cursos_aprobados) - excluidos_input
    periodos_vacacionales = cargar_periodos_vacacionales()

    # "No quiero llevarlo en semestre" -> solo vacaciones;
    # "no quiero llevarlo en vacaciones" -> solo semestre.
    solo_vacaciones = set(solicitud.cursos_solo_vacaciones) - excluidos_input - aprobados_input
    solo_semestre = set(solicitud.cursos_solo_semestre) - excluidos_input - aprobados_input
    solo_vacaciones -= solo_semestre  # ambos a la vez = curso descartado
    ambos = set(solicitud.cursos_solo_vacaciones) & set(solicitud.cursos_solo_semestre)
    excluidos_input |= ambos - aprobados_input

    # Un curso reservado para vacaciones debe estar en la oferta vacacional.
    oferta_vacacional = set()
    if periodos_vacacionales:
        for entrada in periodos_vacacionales[0].get("cursos_disponibles", []):
            oferta_vacacional.add(entrada["codigo"] if isinstance(entrada, dict) else entrada)
    sin_oferta_vacacional = {c for c in solo_vacaciones if c not in oferta_vacacional}
    solo_vacaciones -= sin_oferta_vacacional
    excluidos_input |= sin_oferta_vacacional

    duracion_normal = max(
        (c.get("semestre", 0) for c in cursos_malla if c.get("obligatorio", True)),
        default=semestre_actual,
    )

    aprobados, removidos_por_arrastre = sanear_aprobados_por_prerequisitos(
        cursos_malla, aprobados_input
    )

    # Cursos que el estudiante no quiere llevar (y lo que depende de ellos).
    cursos_filtrados, excluidos_efectivos = excluir_cursos(
        cursos_malla, excluidos_input, aprobados
    )
    excluidos_por_arrastre = excluidos_efectivos - excluidos_input
    excluidos_obligatorios = sorted(
        c for c in excluidos_efectivos
        if por_codigo_malla[c].get("obligatorio", True)
    )

    solo_vacaciones -= excluidos_efectivos
    solo_semestre -= excluidos_efectivos

    # Un curso con restricción de periodo es un curso que sí quiere llevar:
    # si era optativo, se incluye en el plan (con sus prerequisitos).
    cursos_filtrados = [
        {**c, "obligatorio": True} if c["codigo"] in (solo_vacaciones | solo_semestre) else c
        for c in cursos_filtrados
    ]

    cursos = inyectar_prerequisitos_optativos(cursos_filtrados)
    por_codigo = {curso["codigo"]: curso for curso in cursos}

    reprobados = {
        codigo for codigo, curso in por_codigo.items()
        if curso.get("obligatorio", True)
        and curso.get("semestre", 0) < semestre_actual
        and codigo not in aprobados
    }

    # Optativos / social humanística / idiomas que hacen falta para cerrar.
    cursos, objetivo = seleccionar_cursos_objetivo(
        cursos, aprobados, incluir_idiomas=solicitud.incluir_idiomas
    )

    limite_creditos = calcular_limite_creditos(solicitud.promedio)

    try:
        plan = calcular_plan_restante(
            cursos,
            periodos_vacacionales,
            semestre_actual=semestre_actual,
            aprobados=aprobados,
            reprobados=reprobados,
            limite_creditos=limite_creditos,
            modo=solicitud.modo,
            iniciar_en_vacaciones=solicitud.iniciar_en_vacaciones,
            duracion_normal_pensum=duracion_normal,
            solo_vacaciones=solo_vacaciones,
            solo_semestre=solo_semestre,
        )
    except RutaOptimaError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error

    atrasados_iniciales = [
        {"codigo": codigo, "nombre": por_codigo[codigo]["nombre"]}
        for codigo in plan["atrasados_iniciales"]
        if codigo in reprobados
    ]
    removidos = [
        {"codigo": codigo, "nombre": por_codigo[codigo]["nombre"]}
        for codigo in sorted(removidos_por_arrastre)
        if codigo in por_codigo
    ]

    def _nombrar(codigos):
        return [
            {"codigo": c, "nombre": por_codigo_malla[c]["nombre"]}
            for c in sorted(codigos) if c in por_codigo_malla
        ]

    return {
        "periodos": plan["periodos"],
        "objetivo_creditos": objetivo,
        "excluidos_por_arrastre": _nombrar(excluidos_por_arrastre),
        "sin_oferta_vacacional": _nombrar(sin_oferta_vacacional),
        "excluidos_obligatorios": _nombrar(excluidos_obligatorios),
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
