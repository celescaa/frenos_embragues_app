"""Limpia una planilla de stock ya existente y escribe una copia prolija.

Toma LA PLANILLA QUE EL NEGOCIO YA TIENE, no la regenera desde las listas de
precios: regenerarla borraría las cantidades cargadas a mano, que son el único
trabajo humano que no se puede reponer.

Además de limpiar, agrega una hoja REVISAR con los typos de modelo que detectó
y NO aplicó, con una columna SI/NO. Lo que alguien tilde ahí se copia a
ALIAS_MODELO en scripts/nomenclatura.py y a partir de entonces se aplica solo.
Se propone en vez de aplicar porque el parecido se equivoca: sobre las 25
filas de la primera carga real acertó 12 veces y erró 6, y todos los pares
errados son autos que existen los dos (DASTER/MASTER son los dos Renault).

Uso (desde la raíz del proyecto):
    python scripts/normalizar_planilla_stock.py <archivo.xlsx> [salida.xlsx]
"""
import os
import sys

from openpyxl import load_workbook, Workbook

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from scripts import nomenclatura as nom

# Posiciones fijas en la planilla, iguales a las que usa
# cargar_stock_por_proveedor.py.
COL_CODIGO, COL_RUBRO, COL_NOMBRE = 1, 2, 3
COL_MARCA, COL_MODELO, COL_SUBRUBRO = 4, 5, 11


def _hojas_con_datos(wb):
    for ws in wb.worksheets:
        if ws.title.upper() != "INSTRUCCIONES":
            yield ws


def _es_encabezado(fila):
    """El encabezado se busca, no se asume en la fila 1: la hoja SIN
    IDENTIFICAR lleva un aviso arriba de los títulos."""
    return bool(fila) and bool(fila[0]) and str(fila[0]).strip().upper().startswith("CARGAR")


def normalizar(entrada, salida):
    # Primera pasada: el vocabulario sale de los datos reales del archivo, no
    # de una lista escrita a mano.
    wb = load_workbook(entrada, read_only=True, data_only=True)
    textos = []
    for ws in _hojas_con_datos(wb):
        for fila in ws.iter_rows(values_only=True):
            if _es_encabezado(fila) or not fila or not fila[0]:
                continue
            if len(fila) <= COL_MODELO:
                continue
            textos.append(f"{fila[COL_NOMBRE] or ''} {fila[COL_MODELO] or ''}")
    vocabulario = nom.construir_vocabulario(textos)
    wb.close()

    # Segunda pasada: escribir. write_only por el volumen (~202.000 filas):
    # celda por celda no entra en un tiempo razonable.
    wb = load_workbook(entrada, read_only=True, data_only=True)
    salida_wb = Workbook(write_only=True)
    propuestas, total, marcadas = {}, 0, 0

    for ws in _hojas_con_datos(wb):
        hoja = salida_wb.create_sheet(ws.title)
        encabezado_visto = False
        for fila in ws.iter_rows(values_only=True):
            if not encabezado_visto:
                hoja.append(list(fila) if fila else [])
                if _es_encabezado(fila):
                    encabezado_visto = True
                continue
            if not fila or len(fila) <= COL_MODELO or not fila[COL_NOMBRE]:
                hoja.append(list(fila) if fila else [])
                continue

            limpio = nom.normalizar_fila(
                proveedor=ws.title, descripcion=fila[COL_NOMBRE],
                marca=fila[COL_MARCA], rubro=fila[COL_RUBRO],
                subrubro=fila[COL_SUBRUBRO] if len(fila) > COL_SUBRUBRO else "",
                modelo=fila[COL_MODELO], codigo=fila[COL_CODIGO],
            )
            nueva = list(fila)
            nueva[COL_NOMBRE] = limpio["nombre"]
            nueva[COL_MARCA] = limpio["marca"] or None
            nueva[COL_MODELO] = limpio["modelo"] or None
            nueva[COL_RUBRO] = limpio["rubro"]
            if len(nueva) > COL_SUBRUBRO:
                nueva[COL_SUBRUBRO] = limpio["subrubro"] or None
            hoja.append(nueva)
            total += 1
            if limpio["revisar"]:
                marcadas += 1

            for palabra, veces, candidato, veces_c in nom.proponer_alias(
                    limpio["modelo"], vocabulario):
                if palabra in propuestas:
                    continue
                propuestas[palabra] = (
                    veces, candidato, veces_c,
                    f"{fila[COL_CODIGO]} — {limpio['nombre']}")

    hoja = salida_wb.create_sheet("REVISAR")
    hoja.append(["Palabra encontrada", "Apariciones", "Candidato sugerido",
                 "Apariciones del candidato", "Ejemplo", "¿Aplicar? (SI/NO)"])
    for palabra, (veces, candidato, veces_c, ejemplo) in sorted(propuestas.items()):
        hoja.append([palabra, veces, candidato, veces_c, ejemplo, ""])

    salida_wb.save(salida)
    wb.close()
    return {"filas": total, "marcadas": marcadas, "propuestas": len(propuestas)}


def main():
    if len(sys.argv) < 2 or sys.argv[1] in ("-h", "--help"):
        print(__doc__)
        return
    entrada = sys.argv[1]
    salida = sys.argv[2] if len(sys.argv) > 2 else entrada.replace(".xlsx", "_limpia.xlsx")
    print(f"Leyendo {entrada} ...")
    print("(con la planilla completa son dos pasadas sobre 200.000 filas, tarda unos minutos)")
    r = normalizar(entrada, salida)
    print(f"\nListo: {salida}")
    print(f"  {r['filas']} filas normalizadas")
    print(f"  {r['marcadas']} marcadas para revisar (no pude deducir la pieza)")
    print(f"  {r['propuestas']} typos de modelo propuestos en la hoja REVISAR, ninguno aplicado")


if __name__ == "__main__":
    main()
