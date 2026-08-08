# Imagen del sistema de gestión de Repuestos San Ignacio, para poder
# desplegarla en cualquier lado (Render, Railway, Fly.io, un VPS propio,
# etc.) sin depender de la compu del local.
#
# Los datos que tienen que sobrevivir a un redeploy (base de datos, clave de
# sesión, credenciales iniciales, fotos de producto) NO quedan adentro de la
# imagen: viven en /app/data y /app/static/img/productos, pensados para
# montarse como volúmenes (ver docker-compose.yml). Si el hosting elegido
# borra el disco en cada redeploy, esos datos se pierden igual — hace falta
# un volumen persistente de verdad del lado del hosting.
FROM python:3.11-slim

WORKDIR /app

# Las dependencias se instalan en un paso aparte para que Docker cachee esta
# capa y no reinstale todo cada vez que cambia solo el código.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Carpeta de datos persistentes (ver database.py: SI_INSTANCE_DIR). Se crea
# en el build para que exista aunque todavía no se haya montado ningún
# volumen (por ejemplo, la primera vez que se prueba la imagen sin compose).
ENV SI_INSTANCE_DIR=/app/data
RUN mkdir -p /app/data /app/static/img/productos

EXPOSE 5050

# gunicorn en vez del servidor de desarrollo de Flask (app.run/debug=True es
# solo para correr local con `python app.py`, nunca en producción).
CMD ["gunicorn", "--bind", "0.0.0.0:5050", "--workers", "2", "--timeout", "60", "app:app"]
