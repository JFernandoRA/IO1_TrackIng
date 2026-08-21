# -*- coding: utf-8 -*-
"""
api/index.py
============
Punto de entrada que usa Vercel para la función serverless de Python.
No reimplementa nada: solo importa la app de FastAPI ya definida en
backend/server.py y la reexporta como `app`.
"""

import os
import sys

BACKEND_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "backend")
sys.path.insert(0, os.path.abspath(BACKEND_DIR))

from server import app  # noqa: E402  (reexportado para que Vercel lo detecte)
