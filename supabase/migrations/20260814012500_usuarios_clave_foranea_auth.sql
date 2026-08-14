-- Cierra la migración a Supabase Auth: el id del perfil pasa a ser el mismo
-- id de la cuenta, con la base garantizándolo.
--
-- Va acá y no en la migración anterior a propósito: hasta que `/usuarios/nuevo`
-- no creaba la cuenta ANTES del perfil, esta restricción habría rechazado toda
-- alta de usuario y dejado esa pantalla rota. Ahora el código la satisface.

-- Se saca el default: a partir de acá el id siempre lo provee auth.users.
-- Dejar gen_random_uuid() invitaría a crear un perfil con un id inventado que
-- la clave foránea rechazaría después con un error mucho menos claro.
ALTER TABLE usuarios ALTER COLUMN id DROP DEFAULT;

-- ON DELETE CASCADE: borrar la cuenta se lleva el perfil. Al revés no puede
-- pasar (no queremos una cuenta viva sin perfil: sería alguien que puede
-- autenticarse pero no tiene rol), y por eso el borrado de usuarios del
-- sistema empieza por la cuenta y deja que la base arrastre el perfil.
ALTER TABLE usuarios
    ADD CONSTRAINT usuarios_id_fkey
    FOREIGN KEY (id) REFERENCES auth.users(id) ON DELETE CASCADE;
