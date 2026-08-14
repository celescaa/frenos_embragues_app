-- Supabase Auth pasa a ser el almacén de credenciales. La tabla `usuarios`
-- queda como el "perfil": username, nombre, rol, activo, y las tres cosas que
-- Supabase no trae de fábrica (cambio obligatorio de contraseña, intentos
-- fallidos, bloqueo temporal).
--
-- Migración ADITIVA a propósito: password_hash se hace nullable pero NO se
-- borra todavía, así el login actual sigue funcionando hasta que el código
-- pase a Supabase Auth. La columna la borra una migración posterior, recién
-- cuando ya no la lea nadie.

-- El email vive en auth.users, pero se copia acá para poder resolver el login
-- "por usuario o por email" con una sola consulta a nuestra base, sin pedirle
-- a Supabase que liste usuarios en cada intento.
--
-- Nullable por ahora: los usuarios que ya estén cargados no tienen email, y
-- esta migración no puede inventárselo.
ALTER TABLE usuarios ADD COLUMN email TEXT;
ALTER TABLE usuarios ADD CONSTRAINT usuarios_email_key UNIQUE (email);

-- Los usuarios creados vía Supabase Auth no tienen hash propio: su
-- contraseña vive del otro lado.
ALTER TABLE usuarios ALTER COLUMN password_hash DROP NOT NULL;

-- La clave foránea de usuarios.id -> auth.users(id) NO va acá a propósito.
-- Mientras `/usuarios/nuevo` siga creando el perfil por su cuenta (sin crear
-- antes la cuenta en Supabase Auth), esa restricción rechazaría el alta y
-- dejaría la pantalla rota. Se agrega junto con el código que la satisface,
-- en la migración que acompaña la gestión de usuarios.
