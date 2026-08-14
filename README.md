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

   Completar también `SUPABASE_URL`, `SUPABASE_ANON_KEY` y
   `SUPABASE_SERVICE_ROLE_KEY` con los valores que imprimió
   `npx supabase start` (`API URL`, `publishable key` y `secret key`): de ahí
   salen el login y las fotos de producto.

7. Crear el primer usuario admin, una sola vez. Las contraseñas viven en
   Supabase Auth, así que se crea desde **Studio** (la URL del paso 5):

   - **Authentication → Users → Add user**, con **"Auto Confirm User"
     activado**. Sin eso la cuenta queda pendiente de confirmación por mail y
     no puede entrar.
   - Copiar el UUID que queda a la vista y, desde el **SQL Editor**, crear su
     perfil con ese mismo id:

   ```sql
   INSERT INTO usuarios (id, username, email, nombre, rol, activo, debe_cambiar_password)
   VALUES ('PEGAR_EL_UUID_ACA', 'admin', 'el@mismo.email',
           'Nombre y Apellido', 'admin', true, false);
   ```

   Desde ahí en adelante, el resto de los usuarios se dan de alta desde la
   pantalla `/usuarios`. Se entra con el nombre de usuario o con el email,
   indistinto.

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
la base que tiene los datos reales del negocio. Antes de empezar verifica
que la base del puerto sea la de este proyecto y, si no lo es, corta con un
mensaje explicando qué pasó (suele ser otro proyecto de Supabase levantado
que se adueñó del puerto).

Los tests de login y de fotos usan también los servicios de autenticación y
de archivos de Supabase, no solo Postgres — `npx supabase start` los levanta
todos, así que no hay nada extra que hacer. Corren contra esos servicios de
verdad y no contra simulaciones.

Ver "Migración a Postgres" y "Deploy en Vercel" en `CLAUDE.md` para más
detalle sobre cómo está armada.

## Configuración (base de datos, facturación electrónica, tienda online, mail)

Copiar `.env.example` a un archivo nuevo llamado `.env` y completar lo que
corresponda — cada variable está documentada ahí mismo, incluida
`DATABASE_URL` (ver el paso de instalación de más arriba). Sin completar el
resto, el sistema funciona igual: la facturación electrónica, el cobro
online y el envío de comprobantes por mail simplemente avisan que no están
configurados todavía, sin romper ninguna venta. El `.env` nunca se sube al
repositorio ni se comparte por chat.

## Publicarlo en internet (Vercel + Supabase)

El sistema ya está preparado para esto. Los pasos son estos, en orden:

**1. Subir el esquema de la base al proyecto de Supabase**

```
npx supabase link --project-ref <ref-del-proyecto>
npx supabase db push
```

**2. Crear el bucket de las fotos**

En el panel de Supabase: Storage → New bucket → nombre `productos`, marcado
**público**. Es público porque las fotos se muestran en la tienda online, que
no tiene login.

**3. Crear el proyecto en Vercel** y conectarlo a este repositorio. Vercel
detecta Flask solo; `vercel.json` ya fija la región São Paulo (`gru1`), que es
donde está la base — y eso importa: lo que manda la velocidad es la distancia
entre la función y la base, no entre el usuario y la base.

**4. Cargar las variables de entorno en Vercel.** Están todas documentadas en
`.env.example`, separadas en obligatorias y opcionales. Las obligatorias son
seis: `DATABASE_URL`, `SECRET_KEY`, `SESSION_COOKIE_SECURE=1`, `SUPABASE_URL`,
`SUPABASE_ANON_KEY` y `SUPABASE_SERVICE_ROLE_KEY`.

Las de AFIP, Mercado Pago y mail son opcionales: sin ellas el sistema funciona
igual y cada función avisa en pantalla que falta configurarla. Una venta con
tarjeta queda marcada como pendiente de facturar (con botón de reintento), la
venta se registra y el stock baja lo mismo.

**5. Crear el primer usuario administrador.** En el panel de Supabase:
Authentication → Users → Add user, con **"Auto Confirm User" activado** (sin
eso la cuenta queda pendiente de confirmación y no puede entrar). Después, una
sola vez, desde el SQL Editor:

```sql
INSERT INTO usuarios (id, username, email, nombre, rol, activo, debe_cambiar_password)
VALUES ('<el uuid que muestra el panel>', 'celes', '<el mismo email>',
        'Celeste', 'admin', true, false);
```

De ahí en adelante los demás usuarios se dan de alta desde `/usuarios`, sin
volver a tocar ningún panel.

**Cómo se entra:** con el nombre de usuario **o** con el email, indistinto.

### Y el Dockerfile qué

`Dockerfile` y `docker-compose.yml` quedaron de cuando el sistema usaba
SQLite: asumen un volumen de disco local para la base, que ya no existe. Se
conservan solamente como salida hacia un VPS si algún día se quiere dejar
Vercel, pero **no están actualizados** y el camino de despliegue es el de
arriba.

## Compartir el sistema entre varias personas

Una vez desplegado en Vercel, cada persona entra con su propio usuario desde
cualquier lado, sin instalar nada. Los usuarios se dan de alta desde
`/usuarios` (hace falta ser administrador).

Mientras corra solo en una computadora, las demás personas de esa misma red
Wi-Fi pueden entrar usando la IP de esa computadora en vez de `127.0.0.1`
(por ejemplo `http://192.168.0.15:5050`).

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
