-- ---------------------------------------------------------------------
-- Taxonomía v3: los rubros con los que el negocio quiere arrancar de verdad
-- ---------------------------------------------------------------------
-- La taxonomía v2 (la que sembró 20260813145208_esquema_inicial.sql) salió de
-- clasificar automáticamente ~107.000 filas de listas de precios de cinco
-- proveedores. Servía para ordenar esas listas, pero no es como el negocio
-- piensa su propio mostrador: mezclaba Suspensión con Dirección en un solo
-- rubro, no tenía dónde poner una batería ni una bujía, y arrastraba rubros
-- que el negocio no vende (Filtros, Transmisión).
--
-- Esta lista la definió el negocio. Ocho rubros, con las subcategorías
-- escritas tal cual las pidieron -- incluidas las que llevan coma o
-- paréntesis adentro ("Cazoletas, crapodinas", "Cilindros (bomba freno,
-- cilindros de rueda)"). No se "prolijearon" a propósito: son las palabras
-- con las que en el local se nombran las cosas, y el buscador ya normaliza
-- mayúsculas y acentos por su cuenta.
--
-- Toda la migración es idempotente y NO borra datos de productos: los
-- rubros viejos que todavía tengan productos cargados se desactivan en vez
-- de borrarse, así lo ya cargado se sigue viendo y editando.
-- ---------------------------------------------------------------------

-- La taxonomía se declara UNA vez acá y el resto de la migración la
-- consulta. Escribirla de nuevo en cada paso (insertar, reactivar, retirar
-- lo que sobra) es la forma seria de que las tres copias se desincronicen a
-- la primera corrección. La tabla es temporal: se va sola al terminar.
CREATE TEMP TABLE taxonomia_v3 (categoria TEXT NOT NULL, subcategoria TEXT NOT NULL)
ON COMMIT DROP;

INSERT INTO taxonomia_v3 (categoria, subcategoria) VALUES
    ('Frenos', 'Pastillas de freno'),
    ('Frenos', 'Discos de freno'),
    ('Frenos', 'Cintas de freno'),
    ('Frenos', 'Cilindros (bomba freno, cilindros de rueda)'),
    ('Frenos', 'Servofreno'),
    ('Frenos', 'Cables de freno (mano)'),

    ('Suspensión', 'Amortiguadores'),
    ('Suspensión', 'Bieletas'),
    ('Suspensión', 'Barras de torsión y estabilizadoras'),
    ('Suspensión', 'Bujes'),
    ('Suspensión', 'Cazoletas, crapodinas'),
    ('Suspensión', 'Contrapesos, soportes de suspensión'),
    ('Suspensión', 'Resortes / espirales'),

    ('Dirección', 'Brazos de dirección'),
    ('Dirección', 'Cajas de dirección'),
    ('Dirección', 'Columnas de dirección'),
    ('Dirección', 'Terminales / rótulas'),
    ('Dirección', 'Cremalleras'),

    ('Motor', 'Bomba de agua'),
    ('Motor', 'Cadenas de distribución'),
    ('Motor', 'Correas (distribución, alternador, etc.)'),
    ('Motor', 'Juntas y empaquetaduras'),
    ('Motor', 'Retenes'),

    ('Encendido y Eléctrico', 'Baterías'),
    ('Encendido y Eléctrico', 'Bobinas'),
    ('Encendido y Eléctrico', 'Bujías'),
    ('Encendido y Eléctrico', 'Bujías precalentadoras (diesel)'),
    ('Encendido y Eléctrico', 'Cables de bujía'),
    ('Encendido y Eléctrico', 'Motores de arranque / alternadores'),

    ('Embrague', 'Kits de embrague (disco + plato + collarín)'),
    ('Embrague', 'Collarines / rulemanes de embrague'),

    ('Ferretería', 'Arandelas'),
    ('Ferretería', 'Bulones'),
    ('Ferretería', 'Tornillos'),
    ('Ferretería', 'Tuercas'),

    ('Varios', 'Abrazaderas'),
    ('Varios', 'Terminales, conectores varios'),
    ('Varios', 'Repuestos chicos sin categoría propia');

-- ---------------------------------------------------------------------
-- 1. Los ocho rubros nuevos (y reactivar los que ya existían apagados)
-- ---------------------------------------------------------------------
INSERT INTO categorias (nombre)
SELECT DISTINCT categoria FROM taxonomia_v3
ON CONFLICT (nombre) DO NOTHING;

UPDATE categorias SET activo = true
WHERE nombre IN (SELECT categoria FROM taxonomia_v3) AND activo = false;

-- ---------------------------------------------------------------------
-- 2. Sus subcategorías
-- ---------------------------------------------------------------------
INSERT INTO subcategorias (nombre, categoria_id)
SELECT t.subcategoria, c.id
FROM taxonomia_v3 t
JOIN categorias c ON c.nombre = t.categoria
ON CONFLICT (categoria_id, nombre) DO NOTHING;

UPDATE subcategorias s SET activo = true
FROM categorias c, taxonomia_v3 t
WHERE c.id = s.categoria_id
  AND t.categoria = c.nombre AND t.subcategoria = s.nombre
  AND s.activo = false;

-- ---------------------------------------------------------------------
-- 3. Los dos renombres que son la misma cosa con otro nombre
-- ---------------------------------------------------------------------
-- "Embragues" -> "Embrague" es puro singular/plural, y "Otros" -> "Varios" es
-- el mismo cajón de sastre (el propio negocio lo describió como "repuestos
-- chicos sin categoría propia"). Se mueven los productos ya cargados para no
-- dejarlos apuntando a un rubro que desaparece del desplegable.
--
-- La subcategoría NO se toca: las viejas de Embragues ("Discos y platos",
-- "Volantes bimasa", "Bombas y cilindros") no tienen equivalente exacto en
-- las dos nuevas, y adivinar el destino sería inventar un dato del negocio.
-- El producto conserva el texto que tenía; quien lo edite elige la
-- subcategoría nueva que corresponda.
UPDATE productos SET categoria = 'Embrague' WHERE categoria = 'Embragues';
UPDATE productos SET categoria = 'Varios'   WHERE categoria IN ('Otros', 'Otro');

-- ---------------------------------------------------------------------
-- 4. Retirar lo que quedó fuera de la lista nueva
-- ---------------------------------------------------------------------
-- Mismo criterio que ya usa el sistema para proveedores y autos: lo que no
-- tiene nada cargado se borra, y lo que sí tiene se desactiva (deja de
-- aparecer para elegir, pero no rompe ni esconde lo ya cargado).
--
-- Las subcategorías van primero, porque subcategorias.categoria_id no tiene
-- ON DELETE CASCADE: borrar una categoría con subcategorías vivas falla.
UPDATE subcategorias s SET activo = false
FROM categorias c
WHERE c.id = s.categoria_id
  AND NOT EXISTS (
      SELECT 1 FROM taxonomia_v3 t
      WHERE t.categoria = c.nombre AND t.subcategoria = s.nombre
  );

DELETE FROM subcategorias s
USING categorias c
WHERE c.id = s.categoria_id
  AND s.activo = false
  AND NOT EXISTS (
      SELECT 1 FROM productos p
      WHERE p.subcategoria = s.nombre AND p.categoria = c.nombre
  );

UPDATE categorias SET activo = false
WHERE nombre NOT IN (SELECT categoria FROM taxonomia_v3);

DELETE FROM categorias c
WHERE c.activo = false
  AND NOT EXISTS (SELECT 1 FROM productos p WHERE p.categoria = c.nombre)
  AND NOT EXISTS (SELECT 1 FROM subcategorias s WHERE s.categoria_id = c.id);
