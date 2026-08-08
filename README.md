# Repuestos San Ignacio — Sistema de gestión

Sistema centralizado para el negocio: clientes, stock, ventas, compras a
proveedores, facturación electrónica, tienda online y un panel de
analítica. Reemplaza el Excel que se usaba antes como fuente única de datos.

Esta es la guía rápida de instalación y uso. Para el detalle completo:

- **[docs/DOCUMENTACION_FUNCIONAL.md](docs/DOCUMENTACION_FUNCIONAL.md)** —
  qué hace cada pantalla, qué reemplaza del proceso viejo y qué tiempo
  ahorra. Para cualquiera que use el sistema, no hace falta saber programar.
- **[docs/DOCUMENTACION_TECNICA.md](docs/DOCUMENTACION_TECNICA.md)** —
  arquitectura, qué hace cada módulo, esquema de base de datos,
  configuración y despliegue. Para quien programa o mantiene el sistema.
- **[CLAUDE.md](CLAUDE.md)** — memoria técnica detallada del proyecto
  (decisiones tomadas y por qué, historial de cambios).

## Cómo correrlo (una sola vez para instalar)

1. Instalar [Python 3.10 o superior](https://www.python.org/downloads/).
2. Abrir una terminal en esta carpeta (`frenos_embragues_app`).
3. Instalar las dependencias:

   ```
   pip install -r requirements.txt
   ```

## Cómo usarlo (cada vez que quieran abrir el sistema)

1. En la terminal, dentro de esta carpeta:

   ```
   python app.py
   ```

2. Abrir el navegador en `http://127.0.0.1:5050`.
3. Para cerrar, volver a la terminal y presionar `Ctrl + C`.

La primera vez que se ejecuta, el sistema crea `data.db` (la base de datos)
con **datos de ejemplo** para ver cómo funciona el panel de analítica, y un
usuario `admin` con una contraseña generada al azar guardada en
`credenciales_iniciales.txt` (ábranlo, anoten la contraseña, y bórrenlo
cuando ya no la necesiten). En el primer ingreso el sistema pide elegir una
contraseña nueva.

Si en algún momento quieren empezar de cero, basta con borrar `data.db` y
volver a correr `python app.py`.

## Cargar los datos reales del negocio

En `plantillas/Plantilla_Carga_Datos.xlsx` está la planilla para cargar
clientes, productos, proveedores y —si quieren traer el historial— ventas
históricas. La primera hoja tiene las instrucciones completas. Cuando esté
completa:

```
python scripts/importar_datos.py
```

Se puede correr las veces que haga falta: si un producto o cliente ya
existe, lo actualiza en vez de duplicarlo. Para borrar todo y cargar desde
cero: `python scripts/importar_datos.py --reemplazar`.

Ver `docs/DOCUMENTACION_TECNICA.md` (sección 6) para el resto de las
herramientas de carga masiva (limpieza de listas de precios de
proveedores, carga de stock real por proveedor, etc.).

## Configuración (facturación electrónica, tienda online, mail)

Copiar `.env.example` a un archivo nuevo llamado `.env` y completar lo que
corresponda — cada variable está documentada ahí mismo. Sin completar nada,
el sistema funciona igual: la facturación electrónica, el cobro online y el
envío de comprobantes por mail simplemente avisan que no están configurados
todavía, sin romper ninguna venta. El `.env` nunca se sube al repositorio
ni se comparte por chat.

## Desplegar con Docker

```
docker compose up --build
```

Ver `docs/DOCUMENTACION_TECNICA.md` (sección 9) y la sección
"Dockerización" de `CLAUDE.md` para el detalle sobre volúmenes persistentes
y qué chequear antes de elegir un hosting.

## Compartir el sistema entre varias personas

Hoy el sistema corre en una sola computadora, y las demás personas de esa
misma red Wi-Fi/local pueden acceder desde su navegador usando la IP de esa
computadora en vez de `127.0.0.1` (por ejemplo `http://192.168.0.15:5050`).
Para que sea accesible desde cualquier lado, el siguiente paso es alojarlo
en un hosting (ver "Desplegar con Docker" arriba).

## Respaldo de la información

Toda la información vive en `data.db`. Conviene copiar ese archivo a Google
Drive, Dropbox o un pendrive con frecuencia (por ejemplo, al cerrar el
local) para tener respaldo.

## Estructura del proyecto

```
frenos_embragues_app/
├── app.py                     # punto de entrada (python app.py)
├── core/                      # el sistema en sí (ver docs/DOCUMENTACION_TECNICA.md)
├── scripts/                   # herramientas de carga masiva, se corren a mano
├── plantillas/                # Excels que completa el negocio
├── docs/                      # documentación técnica y funcional
├── templates/, static/        # pantallas y estilos
├── Dockerfile, docker-compose.yml
└── data.db                    # se crea solo la primera vez
```

## Próximos pasos sugeridos

Ver la sección "Pendientes / roadmap" en `CLAUDE.md` para la lista completa
y priorizada (hosting, integración con Mercado Libre, analítica más
profunda, etc.).
