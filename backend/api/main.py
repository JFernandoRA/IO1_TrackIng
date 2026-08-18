"""
TrackIng - Sistema Inteligente de Rutas Académicas Curriculares
Punto de entrada principal de la API (FastAPI).

En Vercel, este módulo se despliega como una función serverless de
Python: cada invocación reutiliza la instancia de `app` mientras la
función se mantenga "caliente", y `config.cargar_malla()` cachea la
malla curricular en memoria para evitar releerla en cada petición.
"""

import logging

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from routers import horario_router, malla_router, ruta_router

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("trackIng")

app = FastAPI(
    title="TrackIng API",
    description="Sistema Inteligente de Rutas Académicas Curriculares - API para planificación académica de estudiantes de ingeniería USAC",
    version="1.0.0",
)

# CORS: en producción se recomienda restringir allow_origins al dominio real del frontend.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(Exception)
async def manejador_errores_generico(request: Request, exc: Exception):
    """Captura cualquier excepción no manejada y responde con un JSON consistente en vez de un 500 crudo."""
    logger.exception("Error no manejado procesando %s %s", request.method, request.url)
    return JSONResponse(
        status_code=500,
        content={"detail": "Ocurrió un error interno inesperado en el servidor"},
    )


app.include_router(malla_router.router, prefix="/api")
app.include_router(ruta_router.router, prefix="/api")
app.include_router(horario_router.router, prefix="/api")


@app.get("/api/health", tags=["Sistema"], summary="Health check")
def health_check():
    return {"status": "ok", "servicio": "TrackIng API"}
