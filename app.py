"""
Punto de entrada de la aplicación. Se mantiene en la raíz a propósito para
no romper los comandos de siempre (`python app.py`), el `CMD` del
Dockerfile (`gunicorn app:app`) ni las instrucciones del README — pero el
código real vive en `core/app.py`, junto con el resto del núcleo del
sistema (database.py, facturacion_afip.py, etc.).
"""
from core.app import app

if __name__ == "__main__":
    app.run(debug=True, port=5050)
