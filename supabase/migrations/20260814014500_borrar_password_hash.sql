-- Supabase Auth es el único almacén de credenciales desde las migraciones
-- anteriores: ni el login, ni el cambio de contraseña, ni el alta de usuarios
-- leen o escriben esta columna. Se borra para no dejar hashes de contraseñas
-- viejas dando vueltas en la base -- un dato sensible que ya no cumple
-- ninguna función.
ALTER TABLE usuarios DROP COLUMN password_hash;
