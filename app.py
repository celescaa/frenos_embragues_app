"""
Punto de entrada de la aplicación. Se mantiene en la raíz a propósito para
no romper los comandos de siempre (`python app.py`), el `CMD` del
Dockerfile (`gunicorn app:app`) ni las instrucciones del README — pero el
código real vive en `core/app.py`, junto con el resto del núcleo del
sistema (database.py, facturacion_afip.py, etc.).
"""
from core.app import app, sembrar_datos_de_ejemplo

if __name__ == "__main__":
    # La siembra de datos de ejemplo va acá y no al importar core.app: en
    # Vercel el módulo se importa en cada arranque en frío, y sembrar ahí le
    # metería datos de mentira a la base del negocio (que recién creada está
    # vacía, justo la condición que dispara la siembra). Este bloque solo
    # corre con `python app.py`, nunca bajo gunicorn ni bajo Vercel.
    sembrar_datos_de_ejemplo()
    app.run(debug=True, port=5050)
