-- ---------------------------------------------------------------------
-- Los subrubros que faltaban en la taxonomía v3
-- ---------------------------------------------------------------------
-- Al cargar la lista de rubros del negocio (migración anterior,
-- 20260815120000) quedaron sin lugar varias piezas que el local vende de
-- verdad. Se detectaron porque los productos de prueba no tenían dónde
-- caer, pero el hueco no es del seed: una casa de frenos vende campanas y
-- zapatas, y el líquido de frenos se había quedado sin rubro cuando
-- desapareció la categoría "Líquidos" de la taxonomía vieja.
--
-- Van todos DENTRO de los rubros que ya existen -- no se crea ninguno
-- nuevo. Los nombres siguen el estilo de la lista del negocio ("Pastillas
-- de freno", "Discos de freno"), que nombra la pieza y el sistema al que
-- pertenece.
--
-- Sólo agrega. No borra, no renombra y no toca ningún producto.
-- ---------------------------------------------------------------------
INSERT INTO subcategorias (nombre, categoria_id)
SELECT v.subcategoria, c.id
FROM (VALUES
    -- Frenos: todo esto entraba en la taxonomía vieja y se perdió en el camino.
    ('Frenos', 'Campanas de freno'),
    ('Frenos', 'Zapatas de freno'),
    ('Frenos', 'Mangueras y flexibles'),
    ('Frenos', 'Sensores de desgaste'),
    ('Frenos', 'Seguros antirruido'),
    ('Frenos', 'Líquido de frenos'),

    -- Embrague: la lista sólo cubría el kit y los collarines. Una bomba de
    -- embrague o un volante bimasa no son ninguna de las dos cosas.
    ('Embrague', 'Bombas y cilindros de embrague'),
    ('Embrague', 'Volantes bimasa'),

    -- Rodamientos y mazas no quedaron como rubro propio en la lista nueva.
    -- Van en Suspensión, que es el sistema del que forman parte.
    ('Suspensión', 'Mazas de rueda'),
    ('Suspensión', 'Rodamientos y rulemanes')
) AS v(categoria, subcategoria)
JOIN categorias c ON c.nombre = v.categoria
ON CONFLICT (categoria_id, nombre) DO NOTHING;

-- Si alguna ya existía desactivada (por ejemplo porque venía de la
-- taxonomía vieja y la migración anterior la apagó al no estar en la lista),
-- se reactiva: ahora sí es parte de la taxonomía.
UPDATE subcategorias s SET activo = true
FROM categorias c
WHERE c.id = s.categoria_id
  AND s.activo = false
  AND (c.nombre, s.nombre) IN (
      ('Frenos', 'Campanas de freno'), ('Frenos', 'Zapatas de freno'),
      ('Frenos', 'Mangueras y flexibles'), ('Frenos', 'Sensores de desgaste'),
      ('Frenos', 'Seguros antirruido'), ('Frenos', 'Líquido de frenos'),
      ('Embrague', 'Bombas y cilindros de embrague'),
      ('Embrague', 'Volantes bimasa'),
      ('Suspensión', 'Mazas de rueda'),
      ('Suspensión', 'Rodamientos y rulemanes')
  );
