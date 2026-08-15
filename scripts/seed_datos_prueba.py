"""
Siembra la base con los proveedores REALES del negocio y, opcionalmente, con
datos de prueba para el resto del sistema (clientes, productos, ventas,
compras, cuenta corriente, promociones, movimientos sin factura y pedidos de
la tienda online).

Las dos partes están separadas a propósito:

  * PROVEEDORES_REALES son los 13 proveedores con los que el negocio trabaja
    de verdad, tal como los pasó Celes en `plantillas/Plantilla_Carga_Datos.xlsx`.
    Esa parte se puede correr en producción.
  * Todo lo demás es inventado, para poder probar y mostrar las pantallas.
    Esa parte NO va a producción.

Uso (siempre desde la raíz del proyecto, no desde adentro de scripts/):
    python scripts/seed_datos_prueba.py                 # proveedores reales + datos de prueba
    python scripts/seed_datos_prueba.py --solo-proveedores
    python scripts/seed_datos_prueba.py --solo-autos    # sólo los autos, sin borrar nada
    python scripts/seed_datos_prueba.py --reemplazar    # borra los datos y vuelve a sembrar

`--solo-autos` es el único que se puede correr sobre una base con datos ya
cargados sin riesgo: es puramente aditivo e idempotente. Sirve para una base
sembrada con una versión de este script anterior a los autos, donde el filtro
"Auto" de /productos queda vacío.

Sin `--reemplazar` es seguro correrlo más de una vez: los proveedores se
actualizan en vez de duplicarse, y los datos de prueba se saltean si ya hay
productos cargados (mismo criterio que `db.seed_demo_data()`).

No toca `categorias`/`subcategorias` (las siembra la migración de Supabase) ni
`usuarios` (dependen de las cuentas de Supabase Auth).
"""
import argparse
import os
import random
import re
import sys
from datetime import datetime, time, timedelta
from decimal import Decimal

# database.py vive en el paquete core/, en la raíz del proyecto (un nivel
# arriba de scripts/).
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Lee DATABASE_URL de un .env si lo hay, igual que hace core/app.py. Sin esto
# había que pasar la cadena de conexión en la línea de comandos, y apuntar a
# una base que no sea la local significaba dejar la contraseña escrita en el
# historial del shell.
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:  # el .env es una comodidad, no un requisito
    pass

from core import database as db


def url_segura(url):
    """La cadena de conexión sin la contraseña, para poder imprimirla.

    Contra la base local da igual (la contraseña es 'postgres'), pero este
    script se corre también contra producción, y ahí la cadena lleva la
    contraseña real de la base: mostrarla la deja escrita en la terminal y en
    cualquier log que la capture.
    """
    return re.sub(r"://([^:/@]+):[^@]*@", r"://\1:***@", url or "")


def es_base_local(url):
    return bool(re.search(r"@(127\.0\.0\.1|localhost|\[::1\])[:/]", url or ""))

# ---------------------------------------------------------------------------
# PARTE 1 — proveedores reales
# ---------------------------------------------------------------------------
# Copiados TAL CUAL de la hoja PROVEEDORES de la planilla: no se corrigen
# nombres de calle ni ortografía, porque adivinar un dato real es peor que
# dejarlo como vino (se edita después desde /proveedores si hace falta).
#
# Dos datos siguen incompletos en la planilla y no se inventan acá:
#   * Miguel Angel Sen-Sei: el CUIT "20-2208807-03" tiene 10 dígitos, le falta
#     uno. Se carga literal para no perder el dato parcial.
#   * Omar: sin CUIT ni email.
# (nombre, telefono, email, direccion, cuit)
PROVEEDORES_REALES = [
    ("Roncal Repuestos S.A", "42316344", "administracion@roncalrepuesto.ar",
     "av.Hipolito Yrigoyen 10253", "30-53361668-9"),
    ("Eine s.r.l", "46570935", "ventas@einefrenos.com",
     "Ingeniero Pereyra 3660", "30-71600039-3"),
    ("Icepar", "4581-4777", "info@icepar-sa.com.ar",
     "anasco 2216", "33-51966896-0"),
    ("Michelli", "11-1527376216", "",
     "Pringuel 139 caba", "30-53587655-6"),
    ("Distrisuper", "0810-666-450", "pedidosba@distrisuper.com",
     "el talar", "33-71561343-9"),
    ("Miguel Angel Sen-Sei", "", "",
     "pje magallanes 766", "20-2208807-03"),
    ("Papierttei", "4440850", "ventasbsas@papierttri.com",
     "m cervantes 1643", "30-70869119-0"),
    ("RM", "4667-1890", "ventas@autopiezasrm.com",
     "roque sanz Pena 1654 san miguel", "20-08269340-9"),
    ("Rio", "", "",
     "rio de janeiro 3650 castelar", "30-71420817-5"),
    ("Rodamitre", "113980-7075", "ventas@rodamitre.com.ar",
     "caboto 1129 caba", "30-71893479-2"),
    ("Deboto", "4574-0200", "distribuidoradevoto@fibertel.com.ar",
     "av. Mosconi 3493", "20-25696013-4"),
    ("Zerbini", "", "zerbini@zsc.com.ar",
     "martin de gaiza 801", "30-71778736-2"),
    ("Omar", "116881-2182", "",
     "Lomas del mirador", ""),
]

# ---------------------------------------------------------------------------
# PARTE 2 — datos de prueba (inventados)
# ---------------------------------------------------------------------------
# (nombre, telefono, email, direccion, cuit_dni, tipo_cliente, condicion_iva)
CLIENTES = [
    ("Taller Los Hermanos", "11-4623-8890", "loshermanos.taller@gmail.com",
     "Av. Rivadavia 18450, Morón", "30-71045512-4", "mecanico", "responsable_inscripto"),
    ("Repuestera del Oeste SRL", "11-4451-2210", "compras@repuesteradeloeste.com.ar",
     "Brandsen 1120, Merlo", "30-70998877-1", "mecanico", "responsable_inscripto"),
    ("Mecánica Sardi", "11-6644-7788", "sardimecanica@hotmail.com",
     "Soler 340, Ituzaingó", "20-24556677-8", "mecanico", "monotributista"),
    ("Juan Pérez", "11-5541-2233", "juanperez84@gmail.com",
     "Las Heras 2210, Castelar", "20-30111222-3", "particular", "consumidor_final"),
    ("María Gómez", "11-5578-9911", "mariagomez@hotmail.com",
     "Zufriategui 890, Ituzaingó", "27-28999123-4", "particular", "consumidor_final"),
    ("Carlos Fernández", "11-3390-4455", "", "Olivera 155, Haedo",
     "", "particular", "consumidor_final"),
    ("Transporte Cargas del Oeste", "11-4488-1200", "administracion@cargasoeste.com.ar",
     "Ruta 7 Km 32, Moreno", "30-65432198-7", "particular", "responsable_inscripto"),
    ("Remiseria San Ignacio", "11-6120-3344", "remiseriasanignacio@gmail.com",
     "San Ignacio 2040, Ituzaingó", "30-71223344-5", "particular", "monotributista"),
    ("Lucía Ramírez", "11-2233-8877", "luciaramirez@gmail.com",
     "Mansilla 415, Padua", "27-35998877-2", "particular", "consumidor_final"),
    ("Gustavo Ibáñez", "11-7788-3322", "", "Pringles 90, Ituzaingó",
     "20-33445566-9", "particular", "consumidor_final"),
]

# (codigo, nombre, categoria, subcategoria, marca, modelo_compatible,
#  costo, venta, stock_actual, stock_minimo, proveedor, codigo_barras)
#
# OJO: `stock_actual` es el stock de HOY, ya neto de todo el historial que
# siembra este script. Las ventas/compras/cargos de abajo son historia: no
# vuelven a mover el stock (si lo hicieran habría que simular el stock
# inicial de cada producto, que para un seed no aporta nada).
PRODUCTOS = [
    ("FR-PAS-001", "Pastillas de freno delanteras", "Frenos", "Pastillas de freno",
     "Cobreq", "VW Gol Trend / Voyage", "9800.00", "17500.00", 5, 6, "Roncal Repuestos S.A", "7791234500011"),
    ("FR-PAS-002", "Pastillas de freno traseras", "Frenos", "Pastillas de freno",
     "Cobreq", "VW Gol Trend / Voyage", "8400.00", "15200.00", 4, 6, "Roncal Repuestos S.A", "7791234500028"),
    ("FR-PAS-003", "Pastillas de freno delanteras", "Frenos", "Pastillas de freno",
     "Wagner Lockheed", "Fiat Cronos / Argo", "11200.00", "19900.00", 15, 5, "Eine s.r.l", "7791234500035"),
    ("FR-PAS-004", "Pastillas de freno delanteras cerámicas", "Frenos", "Pastillas de freno",
     "Ferodo", "Chevrolet Onix / Prisma", "13500.00", "23900.00", 9, 4, "Distrisuper", "7791234500042"),
    ("FR-DIS-001", "Disco de freno delantero ventilado", "Frenos", "Discos de freno",
     "Fremax", "VW Gol Trend", "16800.00", "28900.00", 12, 4, "Eine s.r.l", "7791234500059"),
    ("FR-DIS-002", "Disco de freno trasero macizo", "Frenos", "Discos de freno",
     "Fremax", "Fiat Cronos", "13400.00", "22900.00", 2, 4, "Eine s.r.l", "7791234500066"),
    ("FR-DIS-003", "Disco de freno delantero ventilado", "Frenos", "Discos de freno",
     "TRW", "Ford Ka / Fiesta", "18900.00", "32500.00", 7, 3, "Icepar", "7791234500073"),
    ("FR-CAM-001", "Campana de freno trasera", "Frenos", "Campanas de freno",
     "Cobreq", "Renault Kangoo", "15200.00", "26500.00", 5, 3, "Roncal Repuestos S.A", "7791234500080"),
    ("FR-ZAP-001", "Juego de zapatas de freno", "Frenos", "Zapatas de freno",
     "Cobreq", "VW Gol / Saveiro", "7600.00", "13900.00", 18, 6, "Roncal Repuestos S.A", "7791234500097"),
    ("FR-BOM-001", "Bomba de freno (cilindro maestro)", "Frenos", "Cilindros (bomba freno, cilindros de rueda)",
     "TRW", "Chevrolet Onix", "22400.00", "38900.00", 3, 2, "Icepar", "7791234500103"),
    ("FR-BOM-002", "Bombín de freno trasero", "Frenos", "Cilindros (bomba freno, cilindros de rueda)",
     "Wagner Lockheed", "Fiat Palio / Siena", "6900.00", "12400.00", 14, 5, "Distrisuper", "7791234500110"),
    ("FR-MAN-001", "Manguera flexible de freno delantera", "Frenos", "Mangueras y flexibles",
     "Griffo", "Universal", "4100.00", "7900.00", 26, 8, "Papierttei", "7791234500127"),
    ("FR-CAB-001", "Cable de freno de mano", "Frenos", "Cables de freno (mano)",
     "Griffo", "Peugeot 208", "8200.00", "14500.00", 6, 4, "Papierttei", "7791234500134"),
    ("FR-SEN-001", "Sensor de desgaste de pastillas", "Frenos", "Sensores de desgaste",
     "Bosch", "VW Amarok", "5400.00", "9800.00", 11, 4, "Eine s.r.l", "7791234500141"),
    ("FR-ANT-001", "Kit de seguros antirruido", "Frenos", "Seguros antirruido",
     "Genérico", "Universal", "1800.00", "3600.00", 34, 10, "Zerbini", "7791234500158"),
    ("EMB-KIT-001", "Kit de embrague completo (disco, plato y crapodina)", "Embrague", "Kits de embrague (disco + plato + collarín)",
     "Luk", "VW Gol 1.6", "52000.00", "86900.00", 6, 2, "Rio", "7791234500165"),
    ("EMB-KIT-002", "Kit de embrague completo", "Embrague", "Kits de embrague (disco + plato + collarín)",
     "Sachs", "Fiat Cronos 1.3", "56800.00", "94500.00", 3, 2, "Rio", "7791234500172"),
    ("EMB-KIT-003", "Kit de embrague completo", "Embrague", "Kits de embrague (disco + plato + collarín)",
     "Valeo", "Ford Ka 1.5", "49500.00", "82900.00", 1, 2, "RM", "7791234500189"),
    ("EMB-CRA-001", "Crapodina hidráulica", "Embrague", "Collarines / rulemanes de embrague",
     "Luk", "Chevrolet Onix / Prisma", "23400.00", "39900.00", 8, 3, "RM", "7791234500196"),
    ("EMB-CRA-002", "Collarín de embrague mecánico", "Embrague", "Collarines / rulemanes de embrague",
     "Sachs", "Renault Kangoo", "11800.00", "20900.00", 10, 4, "Michelli", "7791234500202"),
    ("EMB-BOM-001", "Bomba de embrague", "Embrague", "Bombas y cilindros de embrague",
     "Sachs", "Peugeot 208 / 308", "19600.00", "33900.00", 5, 3, "Michelli", "7791234500219"),
    ("EMB-BOM-002", "Cilindro esclavo de embrague", "Embrague", "Bombas y cilindros de embrague",
     "Valeo", "Fiat Toro", "17300.00", "29900.00", 4, 3, "Deboto", "7791234500226"),
    ("EMB-VOL-001", "Volante bimasa", "Embrague", "Volantes bimasa",
     "Luk", "VW Amarok 2.0 TDI", "268000.00", "429000.00", 1, 1, "Rio", "7791234500233"),
    ("COR-001", "Correa de distribución", "Motor", "Correas (distribución, alternador, etc.)",
     "Gates", "VW Gol 1.6", "9800.00", "17200.00", 13, 5, "Deboto", "7791234500240"),
    ("COR-002", "Kit tensor de distribución", "Motor", "Correas (distribución, alternador, etc.)",
     "Gates", "Fiat Cronos 1.3", "26400.00", "44900.00", 4, 3, "Deboto", "7791234500257"),
    ("LIQ-001", "Líquido de frenos DOT 4 (500 ml)", "Frenos", "Líquido de frenos",
     "Bosch", "Universal", "2900.00", "5600.00", 48, 12, "Distrisuper", "7791234500264"),
    ("LIQ-002", "Líquido de frenos DOT 3 (250 ml)", "Frenos", "Líquido de frenos",
     "Wagner Lockheed", "Universal", "1900.00", "3800.00", 30, 10, "Distrisuper", "7791234500271"),
    ("ROD-001", "Maza de rueda delantera con rodamiento", "Suspensión", "Mazas de rueda",
     "SKF", "Chevrolet Onix", "34200.00", "57900.00", 2, 2, "Rodamitre", "7791234500288"),
    ("ROD-002", "Rodamiento de rueda trasera", "Suspensión", "Rodamientos y rulemanes",
     "SKF", "VW Gol Trend", "12600.00", "21900.00", 9, 4, "Rodamitre", "7791234500295"),
    # Encendido y Eléctrico, Suspensión y Dirección son rubros nuevos de la
    # taxonomía v3. Sin al menos un producto en cada uno, esos filtros de
    # /productos aparecen siempre vacíos y no hay con qué probarlos.
    ("ENC-BUJ-001", "Bujía de encendido", "Encendido y Eléctrico", "Bujías",
     "NGK", "VW Gol 1.6", "3200.00", "5900.00", 40, 12, "Distrisuper", "7791234500302"),
    ("ENC-BUJ-002", "Bujía de encendido platino", "Encendido y Eléctrico", "Bujías",
     "Bosch", "Fiat Cronos 1.3", "5800.00", "9900.00", 22, 8, "Distrisuper", "7791234500309"),
    ("ENC-CAB-001", "Juego de cables de bujía", "Encendido y Eléctrico", "Cables de bujía",
     "NGK", "VW Gol 1.6", "11400.00", "19900.00", 7, 3, "Icepar", "7791234500316"),
    ("ENC-BAT-001", "Batería 12V 65Ah", "Encendido y Eléctrico", "Baterías",
     "Moura", "Universal", "89000.00", "142000.00", 4, 2, "Rio", "7791234500323"),
    ("SUS-AMO-001", "Amortiguador delantero", "Suspensión", "Amortiguadores",
     "Monroe", "VW Gol Trend", "38900.00", "64900.00", 6, 3, "Michelli", "7791234500330"),
    ("SUS-BIE-001", "Bieleta estabilizadora delantera", "Suspensión", "Bieletas",
     "VTH", "Fiat Palio / Siena", "7300.00", "13200.00", 16, 6, "Zerbini", "7791234500337"),
    ("DIR-TER-001", "Terminal de dirección", "Dirección", "Terminales / rótulas",
     "VTH", "VW Gol / Saveiro", "9100.00", "16400.00", 11, 4, "Zerbini", "7791234500344"),
]

# Autos compatibles. Sin esto, el filtro "Auto" de /productos aparece vacío y
# parece roto, aunque el resto de la pantalla tenga datos de sobra.
#
# Salen de desarmar los `modelo_compatible` de PRODUCTOS, que vienen escritos
# como los escribe un proveedor ("VW Gol / Saveiro", "Fiat Palio / Siena"):
# ahí hay DOS autos en un solo campo de texto, y separarlos es justamente lo
# que la tabla `vehiculos` vino a resolver.
#
# `motor` es obligatorio por diseño (ver CLAUDE.md): para el repuesto que
# sirve en cualquier motor del mismo auto se usa el valor explícito
# "Todos los motores", en vez de dejarlo vacío y tener que decidir en cada
# consulta si vacío significa "no sé" o "cualquiera".
# (marca_auto, modelo, motor, anio_desde, anio_hasta)
VEHICULOS = [
    ("VW", "Gol Trend", "1.6", 2008, 2019),
    ("VW", "Voyage", "1.6", 2009, 2019),
    ("VW", "Saveiro", "1.6", 2010, 2020),
    ("VW", "Amarok", "2.0 TDI", 2011, None),
    ("Fiat", "Cronos", "1.3", 2018, None),
    ("Fiat", "Argo", "1.3", 2017, None),
    ("Fiat", "Palio", "1.4", 2004, 2016),
    ("Fiat", "Siena", "1.4", 2004, 2016),
    ("Fiat", "Toro", "2.0 diésel", 2016, None),
    ("Chevrolet", "Onix", "1.4", 2012, 2019),
    ("Chevrolet", "Prisma", "1.4", 2013, 2019),
    ("Ford", "Ka", "1.5", 2016, None),
    ("Ford", "Fiesta", "1.6", 2011, 2019),
    ("Renault", "Kangoo", "1.6", 2008, 2018),
    ("Peugeot", "208", "1.6", 2013, None),
    ("Peugeot", "308", "1.6", 2012, 2020),
]

# codigo_producto -> autos para los que sirve, como "marca modelo".
# Los productos "Universal" (líquido de frenos, arandelas, batería) no se
# vinculan a propósito: sirven para cualquier auto, y atarlos a los 16 de la
# lista los haría aparecer en todo filtro de auto como si fueran específicos.
VEHICULOS_POR_PRODUCTO = {
    "FR-PAS-001": ["VW Gol Trend", "VW Voyage"],
    "FR-PAS-002": ["VW Gol Trend", "VW Voyage"],
    "FR-PAS-003": ["Fiat Cronos", "Fiat Argo"],
    "FR-PAS-004": ["Chevrolet Onix", "Chevrolet Prisma"],
    "FR-DIS-001": ["VW Gol Trend"],
    "FR-DIS-002": ["Fiat Cronos"],
    "FR-DIS-003": ["Ford Ka", "Ford Fiesta"],
    "FR-CAM-001": ["Renault Kangoo"],
    "FR-ZAP-001": ["VW Gol Trend", "VW Saveiro"],
    "FR-BOM-001": ["Chevrolet Onix"],
    "FR-BOM-002": ["Fiat Palio", "Fiat Siena"],
    "FR-CAB-001": ["Peugeot 208"],
    "FR-SEN-001": ["VW Amarok"],
    "EMB-KIT-001": ["VW Gol Trend"],
    "EMB-KIT-002": ["Fiat Cronos"],
    "EMB-KIT-003": ["Ford Ka"],
    "EMB-CRA-001": ["Chevrolet Onix", "Chevrolet Prisma"],
    "EMB-CRA-002": ["Renault Kangoo"],
    "EMB-BOM-001": ["Peugeot 208", "Peugeot 308"],
    "EMB-BOM-002": ["Fiat Toro"],
    "EMB-VOL-001": ["VW Amarok"],
    "COR-001": ["VW Gol Trend"],
    "COR-002": ["Fiat Cronos"],
    "ROD-001": ["Chevrolet Onix"],
    "ROD-002": ["VW Gol Trend"],
    "ENC-BUJ-001": ["VW Gol Trend"],
    "ENC-BUJ-002": ["Fiat Cronos"],
    "ENC-CAB-001": ["VW Gol Trend"],
    "SUS-AMO-001": ["VW Gol Trend"],
    "SUS-BIE-001": ["Fiat Palio", "Fiat Siena"],
    "DIR-TER-001": ["VW Gol Trend", "VW Saveiro"],
}

# (codigo_producto, proveedor, precio_costo, codigo_del_proveedor)
# Varios productos cotizados por más de un proveedor, para que el comparador
# de precios, la columna "Mejor precio" de /productos y el agrupado de
# /pedidos tengan algo real que mostrar. En varios casos el más barato NO es
# el proveedor de la ficha, que es justamente el caso interesante.
COTIZACIONES = [
    ("FR-PAS-001", "Roncal Repuestos S.A", "9800.00", "RON-4501"),
    ("FR-PAS-001", "Distrisuper", "9350.00", "DS-11204"),
    ("FR-PAS-001", "Icepar", "10100.00", "ICE-8802"),
    ("FR-PAS-003", "Eine s.r.l", "11200.00", "EIN-3310"),
    ("FR-PAS-003", "Distrisuper", "11800.00", "DS-11390"),
    ("FR-DIS-001", "Eine s.r.l", "16800.00", "EIN-2201"),
    ("FR-DIS-001", "Icepar", "17400.00", "ICE-2201"),
    ("FR-DIS-001", "Roncal Repuestos S.A", "16950.00", "RON-2201"),
    ("FR-DIS-002", "Eine s.r.l", "13400.00", "EIN-2208"),
    ("FR-DIS-002", "Icepar", "13100.00", "ICE-2208"),
    ("FR-BOM-001", "Icepar", "22400.00", "ICE-5540"),
    ("FR-BOM-001", "Papierttei", "23200.00", "PAP-5540"),
    ("EMB-KIT-001", "Rio", "52000.00", "RIO-7701"),
    ("EMB-KIT-001", "RM", "50900.00", "RM-7701"),
    ("EMB-KIT-001", "Michelli", "53500.00", "MIC-7701"),
    ("EMB-CRA-001", "RM", "23400.00", "RM-6620"),
    ("EMB-CRA-001", "Rio", "24100.00", "RIO-6620"),
    ("COR-001", "Deboto", "9800.00", "DEV-9010"),
    ("COR-001", "Zerbini", "9600.00", "ZER-9010"),
    ("LIQ-001", "Distrisuper", "2900.00", "DS-0450"),
    ("LIQ-001", "Omar", "2750.00", ""),
    ("ROD-001", "Rodamitre", "34200.00", "RDM-1180"),
    ("ROD-001", "Miguel Angel Sen-Sei", "33500.00", ""),
]

# Tablas que borra --reemplazar. NO incluye categorias/subcategorias (las
# siembra la migración) ni usuarios (su contraparte real vive en Supabase
# Auth, que este script no toca).
TABLAS_DE_DATOS = [
    "promocion_productos", "promociones_aplicadas", "movimientos_no_facturados",
    "cuenta_corriente_movimiento_items", "cuenta_corriente_movimientos",
    "pedido_web_items", "pedidos_web", "compra_items", "compras",
    "venta_items", "ventas", "producto_proveedor", "producto_vehiculos",
    "vehiculos", "productos", "clientes", "proveedores",
]


def _momento(dias_atras, hora=11, minuto=30):
    """Un instante con la zona horaria del negocio, para las columnas
    TIMESTAMPTZ (cuenta corriente, movimientos sin factura). Se arma sobre
    `db.hoy()` y no sobre `datetime.now()` por el mismo motivo de siempre: el
    servidor puede estar en UTC."""
    return datetime.combine(
        db.hoy() - timedelta(days=dias_atras), time(hora, minuto), tzinfo=db.TZ_NEGOCIO
    )


# ---------------------------------------------------------------------------
# Siembra
# ---------------------------------------------------------------------------
def sembrar_proveedores(conn):
    """Carga (o actualiza) los 13 proveedores reales. Devuelve {nombre: id}.

    Idempotente: busca primero por CUIT —el dato que de verdad identifica a un
    proveedor— y recién si no tiene o no matchea, por nombre. Así correrlo dos
    veces actualiza en vez de duplicar, y un proveedor que ya fue cargado a
    mano con otra grafía del nombre se reconoce igual por su CUIT.
    """
    ids = {}
    creados = actualizados = 0
    for nombre, telefono, email, direccion, cuit in PROVEEDORES_REALES:
        existente = None
        if cuit:
            existente = conn.execute(
                "SELECT id FROM proveedores WHERE cuit = %s", (cuit,)
            ).fetchone()
        if not existente:
            existente = conn.execute(
                "SELECT id FROM proveedores WHERE lower(nombre) = lower(%s)", (nombre,)
            ).fetchone()

        if existente:
            conn.execute(
                """UPDATE proveedores
                   SET nombre=%s, telefono=%s, email=%s, direccion=%s, cuit=%s, activo=true
                   WHERE id=%s""",
                (nombre, telefono, email, direccion, cuit, existente["id"]),
            )
            ids[nombre] = existente["id"]
            actualizados += 1
        else:
            fila = conn.execute(
                """INSERT INTO proveedores (nombre, telefono, email, direccion, cuit)
                   VALUES (%s, %s, %s, %s, %s) RETURNING id""",
                (nombre, telefono, email, direccion, cuit),
            ).fetchone()
            ids[nombre] = fila["id"]
            creados += 1

    print(f"Proveedores reales: {creados} creados, {actualizados} actualizados.")
    return ids


def _sembrar_clientes(conn):
    """Devuelve {nombre: id}."""
    ids = {}
    for nombre, tel, email, direccion, cuit, tipo, condicion in CLIENTES:
        fila = conn.execute(
            """INSERT INTO clientes
               (nombre, telefono, email, direccion, cuit_dni, fecha_alta, tipo_cliente, condicion_iva)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s) RETURNING id""",
            (nombre, tel, email, direccion, cuit, db.hoy() - timedelta(days=200), tipo, condicion),
        ).fetchone()
        ids[nombre] = fila["id"]
    return ids


def _sembrar_productos(conn, proveedores):
    """Devuelve {codigo: fila del producto} para reusar precio e id."""
    productos = {}
    for (codigo, nombre, categoria, subcategoria, marca, modelo, costo, venta,
         stock, minimo, proveedor, codigo_barras) in PRODUCTOS:
        fila = conn.execute(
            """INSERT INTO productos
               (codigo, nombre, categoria, subcategoria, marca, modelo_compatible,
                codigo_barras, precio_costo, precio_venta, stock_actual, stock_minimo, proveedor_id)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
               RETURNING id, precio_venta, precio_costo""",
            (codigo, nombre, categoria, subcategoria, marca, modelo, codigo_barras,
             Decimal(costo), Decimal(venta), stock, minimo, proveedores[proveedor]),
        ).fetchone()
        productos[codigo] = fila
    return productos


def _sembrar_vehiculos(conn, productos):
    """Carga los autos y los vincula a los productos que les sirven.

    Devuelve (autos, vínculos). La clave del diccionario de autos es
    "marca modelo" (sin el motor), que es como los nombra
    VEHICULOS_POR_PRODUCTO: en este catálogo de prueba no hay dos motores
    distintos del mismo auto, así que alcanza para identificarlo.

    Es idempotente y no borra nada, para poder correrlo sobre una base que ya
    tiene datos (que es el caso de `--solo-autos`): el auto que ya existe se
    reusa y el vínculo repetido se ignora.

    `productos` puede venir de la siembra recién hecha o de la base. Un código
    que no esté cargado se saltea en silencio: sobre una base sembrada con una
    versión anterior del script no están todos los productos de PRODUCTOS, y
    frenar por eso dejaría sin vincular a los que sí están.
    """
    autos = {}
    for marca_auto, modelo, motor, desde, hasta in VEHICULOS:
        conn.execute(
            """INSERT INTO vehiculos (marca_auto, modelo, motor, anio_desde, anio_hasta)
               VALUES (%s, %s, %s, %s, %s)
               ON CONFLICT (marca_auto, modelo, motor) DO NOTHING""",
            (marca_auto, modelo, motor, desde, hasta),
        )
        fila = conn.execute(
            "SELECT id FROM vehiculos WHERE marca_auto=%s AND modelo=%s AND motor=%s",
            (marca_auto, modelo, motor),
        ).fetchone()
        autos[f"{marca_auto} {modelo}"] = fila["id"]

    vinculos = 0
    for codigo, nombres in VEHICULOS_POR_PRODUCTO.items():
        if codigo not in productos:
            continue
        for nombre in nombres:
            cur = conn.execute(
                """INSERT INTO producto_vehiculos (producto_id, vehiculo_id)
                   VALUES (%s, %s)
                   ON CONFLICT (producto_id, vehiculo_id) DO NOTHING""",
                (productos[codigo]["id"], autos[nombre]),
            )
            vinculos += cur.rowcount
    return len(autos), vinculos


def sembrar_solo_autos(conn):
    """Carga los autos de ejemplo y los vincula a los productos que YA estén
    en la base, sin tocar nada más.

    Existe para una base que ya tiene datos cargados (el caso real: producción
    quedó sembrada con una versión del script anterior a los autos, así que el
    filtro "Auto" de /productos aparecía vacío). No borra ni modifica ningún
    producto, cliente ni venta: sólo agrega lo que falte.
    """
    productos = {
        fila["codigo"]: fila
        for fila in conn.execute(
            "SELECT id, codigo FROM productos WHERE codigo IS NOT NULL"
        ).fetchall()
    }
    autos, vinculos = _sembrar_vehiculos(conn, productos)
    sin_cargar = [c for c in VEHICULOS_POR_PRODUCTO if c not in productos]
    print(f"Autos de ejemplo: {autos} autos, {vinculos} vínculos nuevos.")
    if sin_cargar:
        print(
            f"  ({len(sin_cargar)} productos de la lista no están en esta base y se "
            f"saltearon: {', '.join(sorted(sin_cargar))})"
        )
    return autos, vinculos


def _sembrar_cotizaciones(conn, productos, proveedores):
    for codigo, proveedor, precio, codigo_proveedor in COTIZACIONES:
        conn.execute(
            """INSERT INTO producto_proveedor
               (producto_id, proveedor_id, precio_costo, codigo_proveedor)
               VALUES (%s, %s, %s, %s)""",
            (productos[codigo]["id"], proveedores[proveedor], Decimal(precio), codigo_proveedor),
        )


def _tipo_comprobante(metodo, condicion_iva, cuit_dni):
    """Misma regla que usa el sistema al registrar una venta: efectivo va con
    remito interno, y cualquier medio electrónico dispara Factura A (receptor
    Responsable Inscripto con CUIT) o Factura B (todo el resto)."""
    if metodo == "Efectivo":
        return "Remito"
    if condicion_iva == "responsable_inscripto" and len(cuit_dni.replace("-", "")) == 11:
        return "Factura A"
    return "Factura B"


def _sembrar_ventas(conn, clientes, productos, rnd):
    """~60 ventas repartidas en los últimos 5 meses, para que el panel tenga
    histórico y el gráfico por mes muestre varios meses."""
    clientes_db = conn.execute(
        "SELECT id, condicion_iva, COALESCE(cuit_dni, '') AS cuit_dni FROM clientes"
    ).fetchall()
    productos_db = list(productos.values())

    ventas_creadas = 0
    for i in range(60):
        cliente = rnd.choice(clientes_db)
        fecha = db.hoy() - timedelta(days=rnd.randint(0, 150))
        metodo = rnd.choice(
            ["Efectivo", "Efectivo", "Transferencia", "Tarjeta", "Mercado Pago"]
        )
        tipo = _tipo_comprobante(metodo, cliente["condicion_iva"], cliente["cuit_dni"])
        # Sin AFIPSDK_ACCESS_TOKEN el sistema deja las facturas pendientes de
        # emisión, reintentables desde el comprobante: el seed refleja ese
        # mismo estado en vez de inventar un CAE que ARCA nunca emitió.
        estado = "sin_configurar" if tipo.startswith("Factura") else None

        venta_id = conn.execute(
            """INSERT INTO ventas
               (fecha, cliente_id, total, metodo_pago, tipo_comprobante,
                numero_comprobante, facturacion_estado)
               VALUES (%s, %s, 0, %s, %s, %s, %s) RETURNING id""",
            (fecha, cliente["id"], metodo, tipo, f"{1000 + i:06d}", estado),
        ).fetchone()["id"]

        total = Decimal("0")
        for producto in rnd.sample(productos_db, rnd.randint(1, 3)):
            cantidad = rnd.randint(1, 4)
            subtotal = cantidad * producto["precio_venta"]
            total += subtotal
            conn.execute(
                """INSERT INTO venta_items
                   (venta_id, producto_id, cantidad, precio_unitario, subtotal)
                   VALUES (%s, %s, %s, %s, %s)""",
                (venta_id, producto["id"], cantidad, producto["precio_venta"], subtotal),
            )
        conn.execute("UPDATE ventas SET total=%s WHERE id=%s", (total, venta_id))
        ventas_creadas += 1

    ventas_creadas += _sembrar_venta_pago_mixto(conn, clientes, productos)
    return ventas_creadas


def _sembrar_venta_pago_mixto(conn, clientes, productos):
    """Un pago mixto de hoy: parte en efectivo y parte con tarjeta. Son dos
    ventas con el mismo `id_operacion`, que /ventas/dia cuenta como UNA sola
    operación. Sirve para probar justamente ese caso."""
    cliente_id = clientes["Juan Pérez"]
    producto = productos["FR-PAS-001"]
    id_operacion = "OP-MIXTA-001"

    for metodo, tipo, cantidad, numero in [
        ("Efectivo", "Remito", 1, "009001"),
        ("Tarjeta", "Factura B", 1, "009002"),
    ]:
        subtotal = cantidad * producto["precio_venta"]
        venta_id = conn.execute(
            """INSERT INTO ventas
               (fecha, cliente_id, total, metodo_pago, tipo_comprobante,
                numero_comprobante, id_operacion, facturacion_estado)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s) RETURNING id""",
            (db.hoy(), cliente_id, subtotal, metodo, tipo, numero, id_operacion,
             "sin_configurar" if tipo.startswith("Factura") else None),
        ).fetchone()["id"]
        conn.execute(
            """INSERT INTO venta_items
               (venta_id, producto_id, cantidad, precio_unitario, subtotal)
               VALUES (%s, %s, %s, %s, %s)""",
            (venta_id, producto["id"], cantidad, producto["precio_venta"], subtotal),
        )
    return 2


def _sembrar_compras(conn, proveedores, productos):
    """Compras a proveedores reales, con su factura. Igual que las ventas, son
    historia: no vuelven a mover el stock declarado en PRODUCTOS."""
    compras = [
        (95, "Roncal Repuestos S.A", "A-0003-00012845",
         [("FR-PAS-001", 20), ("FR-ZAP-001", 12), ("FR-CAM-001", 6)]),
        (72, "Eine s.r.l", "A-0002-00005512",
         [("FR-DIS-001", 10), ("FR-DIS-002", 8), ("FR-SEN-001", 10)]),
        (44, "Rio", "A-0001-00000987",
         [("EMB-KIT-001", 4), ("EMB-KIT-002", 3)]),
        (21, "Distrisuper", "A-0007-00034120",
         [("LIQ-001", 36), ("LIQ-002", 24), ("FR-BOM-002", 10)]),
        (6, "Rodamitre", "A-0004-00002233",
         [("ROD-001", 5), ("ROD-002", 8)]),
    ]
    for dias_atras, proveedor, numero_factura, items in compras:
        compra_id = conn.execute(
            """INSERT INTO compras (fecha, proveedor_id, total, numero_factura_proveedor)
               VALUES (%s, %s, 0, %s) RETURNING id""",
            (db.hoy() - timedelta(days=dias_atras), proveedores[proveedor], numero_factura),
        ).fetchone()["id"]

        total = Decimal("0")
        for codigo, cantidad in items:
            precio = productos[codigo]["precio_costo"]
            subtotal = cantidad * precio
            total += subtotal
            conn.execute(
                """INSERT INTO compra_items
                   (compra_id, producto_id, cantidad, precio_unitario, subtotal)
                   VALUES (%s, %s, %s, %s, %s)""",
                (compra_id, productos[codigo]["id"], cantidad, precio, subtotal),
            )
        conn.execute("UPDATE compras SET total=%s WHERE id=%s", (total, compra_id))
    return len(compras)


def _cargo_cuenta_corriente(conn, cliente_id, productos, items, dias_atras,
                            observaciones=None, tercero=None):
    """Un cargo con sus productos, igual que los que crea /clientes/<id>/cuenta-corriente.
    `tercero` es (nombre, cuit_dni, condicion_iva) cuando el mecánico compra a
    nombre de otra persona y la factura corresponde a esa otra persona."""
    tercero_nombre, tercero_cuit, tercero_condicion = tercero or (None, None, None)
    monto = sum(cantidad * productos[codigo]["precio_venta"] for codigo, cantidad in items)

    movimiento_id = conn.execute(
        """INSERT INTO cuenta_corriente_movimientos
           (cliente_id, cliente_tercero_nombre, tercero_cuit_dni, tercero_condicion_iva,
            monto, tipo, fecha, observaciones, facturacion_estado)
           VALUES (%s, %s, %s, %s, %s, 'cargo', %s, %s, 'sin_configurar') RETURNING id""",
        (cliente_id, tercero_nombre, tercero_cuit, tercero_condicion, monto,
         _momento(dias_atras), observaciones),
    ).fetchone()["id"]

    for codigo, cantidad in items:
        producto = productos[codigo]
        conn.execute(
            """INSERT INTO cuenta_corriente_movimiento_items
               (movimiento_id, producto_id, cantidad, precio_unitario, subtotal)
               VALUES (%s, %s, %s, %s, %s)""",
            (movimiento_id, producto["id"], cantidad, producto["precio_venta"],
             cantidad * producto["precio_venta"]),
        )
    return monto


def _pago_cuenta_corriente(conn, cliente_id, monto, dias_atras, observaciones=None):
    conn.execute(
        """INSERT INTO cuenta_corriente_movimientos
           (cliente_id, monto, tipo, fecha, observaciones)
           VALUES (%s, %s, 'pago', %s, %s)""",
        (cliente_id, Decimal(monto), _momento(dias_atras), observaciones),
    )


def _sembrar_cuenta_corriente(conn, clientes, productos):
    """Tres cuentas en estados distintos: dos con saldo deudor (para que
    /clientes/top-deudores muestre algo) y una saldada."""
    # Taller Los Hermanos: debe una parte.
    _cargo_cuenta_corriente(
        conn, clientes["Taller Los Hermanos"], productos,
        [("EMB-KIT-001", 1), ("FR-PAS-001", 2)], dias_atras=40,
        observaciones="Se lo lleva el Gordo, factura a fin de mes",
    )
    _cargo_cuenta_corriente(
        conn, clientes["Taller Los Hermanos"], productos,
        [("FR-DIS-001", 2), ("LIQ-001", 3)], dias_atras=18,
    )
    _pago_cuenta_corriente(
        conn, clientes["Taller Los Hermanos"], "120000.00", dias_atras=10,
        observaciones="Transferencia a cuenta",
    )

    # Repuestera del Oeste: compra a nombre de un tercero (la factura va al
    # tercero, no al mecánico dueño de la cuenta).
    _cargo_cuenta_corriente(
        conn, clientes["Repuestera del Oeste SRL"], productos,
        [("EMB-KIT-002", 1)], dias_atras=25,
        tercero=("Marta Solís", "27-26558899-1", "consumidor_final"),
        observaciones="Lo retira Marta, facturar a su nombre",
    )
    _pago_cuenta_corriente(
        conn, clientes["Repuestera del Oeste SRL"], "40000.00", dias_atras=12,
    )

    # Mecánica Sardi: saldada, para tener también ese caso.
    monto = _cargo_cuenta_corriente(
        conn, clientes["Mecánica Sardi"], productos,
        [("FR-PAS-003", 2), ("FR-ANT-001", 2)], dias_atras=30,
    )
    _pago_cuenta_corriente(
        conn, clientes["Mecánica Sardi"], monto, dias_atras=9,
        observaciones="Cancela todo",
    )


def _sembrar_promociones(conn, clientes, productos):
    """Una promoción por porcentaje sobre todo el catálogo, otra de monto fijo
    y una tercera limitada a productos puntuales. `aplicar_promociones()` las
    aplica sola en la próxima venta a esos clientes."""
    conn.execute(
        """INSERT INTO promociones_aplicadas
           (cliente_id, porcentaje_o_monto, tipo, alcance, fecha_inicio, fecha_fin, aprobado_por)
           VALUES (%s, %s, 'porcentaje', 'todo', %s, NULL, %s)""",
        (clientes["Taller Los Hermanos"], Decimal("10.00"),
         db.hoy() - timedelta(days=30), "admin"),
    )
    conn.execute(
        """INSERT INTO promociones_aplicadas
           (cliente_id, porcentaje_o_monto, tipo, alcance, fecha_inicio, fecha_fin, aprobado_por)
           VALUES (%s, %s, 'monto_fijo', 'todo', %s, %s, %s)""",
        (clientes["Transporte Cargas del Oeste"], Decimal("15000.00"),
         db.hoy() - timedelta(days=15), db.hoy() + timedelta(days=45), "admin"),
    )
    promocion_id = conn.execute(
        """INSERT INTO promociones_aplicadas
           (cliente_id, porcentaje_o_monto, tipo, alcance, fecha_inicio, fecha_fin, aprobado_por)
           VALUES (%s, %s, 'porcentaje', 'productos_puntuales', %s, NULL, %s) RETURNING id""",
        (clientes["Repuestera del Oeste SRL"], Decimal("15.00"),
         db.hoy() - timedelta(days=7), "admin"),
    ).fetchone()["id"]
    for codigo in ("EMB-KIT-001", "EMB-KIT-002", "EMB-CRA-001"):
        conn.execute(
            "INSERT INTO promocion_productos (promocion_id, producto_id) VALUES (%s, %s)",
            (promocion_id, productos[codigo]["id"]),
        )


def _sembrar_movimientos_no_facturados(conn, productos):
    """Movimientos de stock que no pasaron por una compra/venta formal."""
    movimientos = [
        ("compra", "FR-ANT-001", 10, "1700.00", "Omar", "Compra en efectivo, sin factura", False),
        ("venta", "LIQ-002", 2, "3800.00", "Vecino del taller de al lado", None, False),
        ("compra", "FR-MAN-001", 4, "4000.00", "Rezago de otro local", "Ya cargado también como compra", True),
    ]
    for tipo, codigo, cantidad, precio, contraparte, observaciones, conciliado in movimientos:
        conn.execute(
            """INSERT INTO movimientos_no_facturados
               (fecha, tipo, producto_id, cantidad, precio, contraparte, observaciones, conciliado)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s)""",
            (_momento(5), tipo, productos[codigo]["id"], cantidad, Decimal(precio),
             contraparte, observaciones, conciliado),
        )


def _sembrar_pedidos_web(conn, clientes, productos):
    """Dos pedidos de la tienda online: uno ya pagado (con su venta real
    asociada, como la deja el webhook de Mercado Pago) y uno esperando pago."""
    # Pagado: el webhook genera la venta y la enlaza al pedido.
    producto = productos["FR-PAS-004"]
    total = 2 * producto["precio_venta"]
    venta_id = conn.execute(
        """INSERT INTO ventas
           (fecha, cliente_id, total, metodo_pago, tipo_comprobante,
            numero_comprobante, facturacion_estado)
           VALUES (%s, %s, %s, 'Mercado Pago', 'Factura B', '009100', 'sin_configurar')
           RETURNING id""",
        (db.hoy() - timedelta(days=3), clientes["Lucía Ramírez"], total),
    ).fetchone()["id"]
    conn.execute(
        """INSERT INTO venta_items (venta_id, producto_id, cantidad, precio_unitario, subtotal)
           VALUES (%s, %s, 2, %s, %s)""",
        (venta_id, producto["id"], producto["precio_venta"], total),
    )
    pedido_id = conn.execute(
        """INSERT INTO pedidos_web
           (fecha, nombre_cliente, telefono, email, direccion, cuit_dni, total,
            estado, mp_preference_id, mp_payment_id, venta_id)
           VALUES (%s, %s, %s, %s, %s, %s, %s, 'pagado', %s, %s, %s) RETURNING id""",
        (db.hoy() - timedelta(days=3), "Lucía Ramírez", "11-2233-8877",
         "luciaramirez@gmail.com", "Mansilla 415, Padua", "27-35998877-2", total,
         "PREF-DEMO-0001", "PAY-DEMO-0001", venta_id),
    ).fetchone()["id"]
    conn.execute(
        """INSERT INTO pedido_web_items (pedido_id, producto_id, cantidad, precio_unitario, subtotal)
           VALUES (%s, %s, 2, %s, %s)""",
        (pedido_id, producto["id"], producto["precio_venta"], total),
    )

    # Esperando el pago: todavía no hay venta ni stock descontado.
    producto = productos["COR-001"]
    total = producto["precio_venta"]
    pedido_id = conn.execute(
        """INSERT INTO pedidos_web
           (fecha, nombre_cliente, telefono, email, direccion, cuit_dni, total,
            estado, mp_preference_id)
           VALUES (%s, %s, %s, %s, %s, %s, %s, 'pendiente_pago', %s) RETURNING id""",
        (db.hoy(), "Gustavo Ibáñez", "11-7788-3322", "", "Pringles 90, Ituzaingó",
         "20-33445566-9", total, "PREF-DEMO-0002"),
    ).fetchone()["id"]
    conn.execute(
        """INSERT INTO pedido_web_items (pedido_id, producto_id, cantidad, precio_unitario, subtotal)
           VALUES (%s, %s, 1, %s, %s)""",
        (pedido_id, producto["id"], producto["precio_venta"], total),
    )


def _marcar_pedidos_pendientes(conn, productos):
    """Un par de productos ya pedidos al proveedor, esperando que lleguen: es
    el estado que muestra /pedidos en su sección aparte.

    Los otros productos bajo el mínimo (FR-PAS-001, FR-DIS-002, ROD-001) se
    dejan sin marcar a propósito: los tres tienen cotizaciones de más de un
    proveedor y el más barato NO es el de la ficha, así que /pedidos los
    agrupa por el proveedor conveniente, les pone la insignia "mejor precio"
    y calcula el ahorro estimado del pedido."""
    for codigo in ("FR-PAS-002", "EMB-KIT-003"):
        conn.execute(
            """UPDATE productos SET pedido_pendiente=true, fecha_pedido_pendiente=%s
               WHERE id=%s""",
            (db.hoy() - timedelta(days=4), productos[codigo]["id"]),
        )


def sembrar_datos_prueba(conn, proveedores):
    """Todo lo inventado. Asume que los proveedores reales ya están cargados."""
    rnd = random.Random(2026)  # reproducible: la misma corrida da los mismos datos

    clientes = _sembrar_clientes(conn)
    productos = _sembrar_productos(conn, proveedores)
    autos, vinculos = _sembrar_vehiculos(conn, productos)
    _sembrar_cotizaciones(conn, productos, proveedores)
    ventas = _sembrar_ventas(conn, clientes, productos, rnd)
    compras = _sembrar_compras(conn, proveedores, productos)
    _sembrar_cuenta_corriente(conn, clientes, productos)
    _sembrar_promociones(conn, clientes, productos)
    _sembrar_movimientos_no_facturados(conn, productos)
    _sembrar_pedidos_web(conn, clientes, productos)
    _marcar_pedidos_pendientes(conn, productos)

    print(
        f"Datos de prueba: {len(clientes)} clientes, {len(productos)} productos, "
        f"{autos} autos ({vinculos} vínculos), {len(COTIZACIONES)} cotizaciones, "
        f"{ventas} ventas, {compras} compras, cuenta corriente, promociones, "
        "movimientos sin factura y pedidos web."
    )


def hay_datos_de_prueba(conn):
    return conn.execute("SELECT COUNT(*) AS c FROM productos").fetchone()["c"] > 0


def borrar_datos(conn):
    conn.execute(
        "TRUNCATE TABLE " + ", ".join(TABLAS_DE_DATOS) + " RESTART IDENTITY CASCADE"
    )
    print(f"Borradas {len(TABLAS_DE_DATOS)} tablas de datos.")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.strip().splitlines()[0])
    parser.add_argument(
        "--solo-proveedores", action="store_true",
        help="carga únicamente los 13 proveedores reales, sin datos de prueba",
    )
    parser.add_argument(
        "--solo-autos", action="store_true",
        help="carga únicamente los autos de ejemplo y los vincula a los productos "
             "que ya estén cargados; no borra ni modifica nada más",
    )
    parser.add_argument(
        "--reemplazar", action="store_true",
        help="BORRA clientes, productos, ventas, compras y todo el resto antes de sembrar",
    )
    parser.add_argument(
        "--sin-confirmar", action="store_true",
        help="no pide confirmación para --reemplazar (para tests y scripts)",
    )
    args = parser.parse_args(argv)

    destino = url_segura(db.DATABASE_URL)

    # Apuntar sin querer a producción es el accidente caro de este script, y
    # se volvió fácil desde que lee el .env: basta con tener ahí la cadena de
    # producción y olvidarse. Cualquier base que no sea la local pide
    # confirmación, incluso en los modos que no borran nada.
    if not es_base_local(db.DATABASE_URL) and not args.sin_confirmar:
        print(f"OJO: la base NO es local -> {destino}")
        if input("Escribí 'si' para seguir: ").strip().lower() not in ("si", "sí"):
            print("Cancelado, no se tocó nada.")
            return 1

    if args.reemplazar and not args.sin_confirmar:
        print(f"--reemplazar BORRA todos los datos de: {destino}")
        if input("Escribí 'borrar' para confirmar: ").strip().lower() != "borrar":
            print("Cancelado, no se tocó nada.")
            return 1

    conn = db.get_connection()
    try:
        # --solo-autos es puramente aditivo: ni siquiera toca los proveedores.
        if args.solo_autos:
            sembrar_solo_autos(conn)
            conn.commit()
            print("Listo, sobre:", destino)
            return 0

        if args.reemplazar:
            borrar_datos(conn)

        proveedores = sembrar_proveedores(conn)

        if args.solo_proveedores:
            print("--solo-proveedores: no se cargaron datos de prueba.")
        elif hay_datos_de_prueba(conn):
            print(
                "Ya hay productos cargados: no se tocaron los datos de prueba. "
                "Usá --reemplazar si querés volver a empezar de cero."
            )
        else:
            sembrar_datos_prueba(conn, proveedores)

        conn.commit()
    finally:
        conn.close()

    print("Listo, sobre:", destino)
    return 0


if __name__ == "__main__":
    sys.exit(main())
