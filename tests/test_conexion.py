def test_la_base_de_pruebas_responde(db_conn):
    fila = db_conn.execute("SELECT 1 AS uno").fetchone()
    assert fila["uno"] == 1


def test_las_filas_se_acceden_por_nombre(db_conn):
    """El resto del sistema accede a las filas por nombre (venta["fecha"]),
    así que la conexión tiene que devolver diccionarios, no tuplas."""
    fila = db_conn.execute("SELECT 'Frenos' AS categoria").fetchone()
    assert fila["categoria"] == "Frenos"
