"""
Sistema de Venta y Validacion de Entradas con Codigos QR — Multi-Evento
=======================================================================
Backend: Flask + Supabase (PostgreSQL serverless)
Deploy: Vercel (funcion serverless)

Este archivo es el entry point de Vercel. Delega todo a app.py en el
root del proyecto para evitar duplicacion de codigo.
"""

import sys
import os

# Agregar el root del proyecto al path para poder importar app.py
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)

from app import app  # noqa: E402,F401

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
