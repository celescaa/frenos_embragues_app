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

El sistema guarda todo en Postgres (no en un archivo local como antes) —
ver "Migración a Postgres" en `CLAUDE.md` para el porqué. Para desarrollo
local, [Supabase](https://supabase.com) da una forma de levantar ese
Postgres en la propia compu con Docker, sin tener que crear una cuenta ni
depender de internet.

1. Instalar [Python 3.10 o superior](https://www.python.org/downloads/).
2. Instalar [Node.js](https://nodejs.org/) (trae `npx`, que se usa para
   correr la CLI de Supabase sin instalarla globalmente) y
   [Docker Desktop](https://www.docker.com/products/docker-desktop/) (la
   CLI de Supabase levanta Postgres en un contenedor).
3. Abrir una terminal en esta carpeta (`frenos_embragues_app`).
4. Instalar las dependencias de Python:

   ```
   pip install -r requirements.txt
   ```

5. Levantar Postgres local:

   ```
   npx supabase start
   ```

   La primera vez descarga las imágenes de Docker (puede tardar unos
   minutos) y después aplica el esquema de `supabase/migrations/`. Al
   terminar imprime varias URLs y claves; la que importa acá es `DB URL`
   (por default `postgresql://postgres:postgres@127.0.0.1:54322/postgres`).
   También imprime la URL de **Studio**, un panel visual para ver/editar
   las tablas sin escribir SQL a mano (`http://127.0.0.1:54323` por
   default).

6. Copiar `.env.example` a un archivo nuevo llamado `.env`. Si se usa la
   URL de Postgres por default de arriba, `DATABASE_URL` puede quedar
   vacía (el sistema ya usa ese valor si no está definida); si se levantó
   en otro puerto o se apunta a otra base, completarla ahí.

7. Crear el primer usuario admin. Todavía no hay una pantalla para esto
   (queda para cuando el login pase a Supabase Auth, ver el Plan 2 en
   `CLAUDE.md`) — se hace a mano, una sola vez:

   ```
   python -c "from werkzeug.security import generate_password_hash; print(generate_password_hash('elegí-una-contraseña'))"
   ```

   Copiar el hash que imprime y pegarlo en un INSERT como este, corrido
   desde el **SQL Editor** de Studio (la URL del paso 5):

   ```sql
   INSERT INTO usuarios (username, password_hash, nombre, rol)
   VALUES ('admin', 'PEGAR_EL_HASH_ACA', 'Nombre y Apellido', 'admin');
   ```

## Cómo usarlo (cada vez que quieran abrir el sistema)

1. Si Postgres local no está levantado, `npx supabase start` (se puede
   dejar corriendo entre sesiones; `npx supabase stop` lo apaga del todo).
2. En la terminal, dentro de esta carpeta:

   ```
   python app.py
   ```

3. Abrir el navegador en `http://127.0.0.1:5050` y entrar con el usuario
   admin creado en la instalación.

4. Para cerrar, volver a la terminal y presionar `Ctrl + C`.

La primera vez que se ejecuta, el sistema carga **datos de ejemplo**
(clientes, productos, ventas) para ver cómo funciona el panel de
analítica, siempre que la base esté vacía — no pisa datos reales ya
cargados.

Si en algún momento quieren empezar de cero: `npx supabase db reset`
vuelve a aplicar el esquema desde cero (borra todo lo que haya en la base
local) — después hay que repetir el paso 7 de arriba para tener un admin
de nuevo.

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

## Correr los tests

Con Postgres local levantado (`npx supabase start`):

```
python -m pytest tests/ -v
```

Por default corren contra el mismo Postgres local de la instalación
(`postgresql://postgres:postgres@127.0.0.1:54322/postgres`); se puede
apuntar a otra base con la variable `DATABASE_URL_TEST`. La suite deja la
base de pruebas limpia (sin datos de ejemplo) al terminar cada test, así
que es segura de correr las veces que haga falta — pero no correrla contra
la base que tiene los datos reales del negocio. Ver "Migración a Postgres"
en `CLAUDE.md` para más detalle sobre cómo está armada.

## Configuración (base de datos, facturación electrónica, tienda online, mail)

Copiar `.env.example` a un archivo nuevo llamado `.env` y completar lo que
corresponda — cada variable está documentada ahí mismo, incluida
`DATABASE_URL` (ver el paso de instalación de más arriba). Sin completar el
resto, el sistema funciona igual: la facturación electrónica, el cobro
online y el envío de comprobantes por mail simplemente avisan que no están
configurados todavía, sin romper ninguna venta. El `.env` nunca se sube al
repositorio ni se comparte por chat.

## Desplegar con Docker

```
docker compose up --build
```

**Desactualizado**: este `Dockerfile`/`docker-compose.yml` se escribieron
para la versión en SQLite (asumen un volumen de disco local para la base)
y todavía no se actualizaron tras la migración a Postgres — ver la nota al
principio de la sección "Dockerización" de `CLAUDE.md`. Además, el plan de
despliegue elegido ya no es este camino sino Vercel + Supabase (ver "Plan
1 de 2" en `CLAUDE.md`), así que puede que este `Dockerfile` quede
directamente reemplazado más adelante en vez de actualizado.

## Compartir el sistema entre varias personas

Hoy el sistema corre en una sola computadora, y las demás personas de esa
misma red Wi-Fi/local pueden acceder desde su navegador usando la IP de esa
computadora en vez de `127.0.0.1` (por ejemplo `http://192.168.0.15:5050`).
Para que sea accesible desde cualquier lado, el siguiente paso es
desplegarlo (ver "Próximos pasos sugeridos" abajo).

## Respaldo de la información

La información vive en Postgres, no en un archivo local (ver "Migración a
Postgres" en `CLAUDE.md`). En producción, alojado en Supabase, los backups
los maneja Supabase según el plan contratado. En desarrollo local, el
Postgres que levanta `npx supabase start` no tiene backups automáticos,
pero tampoco es donde va a vivir el dato real del negocio.

## Estructura del proyecto

```
frenos_embragues_app/
├── app.py                     # punto de entrada (python app.py)
├── core/                      # el sistema en sí (ver docs/DOCUMENTACION_TECNICA.md)
├── scripts/                   # herramientas de carga masiva, se corren a mano
├── plantillas/                # Excels que completa el negocio
├── supabase/                  # esquema de Postgres (migrations/) y config de la CLI
├── tests/                     # suite de pytest (ver "Correr los tests" arriba)
├── docs/                      # documentación técnica y funcional
├── templates/, static/        # pantallas y estilos
└── Dockerfile, docker-compose.yml   # desactualizados, ver "Desplegar con Docker" arriba
```

## Próximos pasos sugeridos

Ver la sección "Pendientes / roadmap" en `CLAUDE.md` para la lista completa
y priorizada (hosting, integración con Mercado Libre, analítica más
profunda, etc.).
