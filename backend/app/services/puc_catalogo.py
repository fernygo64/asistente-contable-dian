"""
Catálogo base del Plan Único de Cuentas colombiano (Decreto 2650 de 1993).

Subconjunto verificado de las cuentas de uso más común en una pyme —
NO son las ~2.460 cuentas completas del PUC oficial (un catálogo de ese
tamaño reconstruido de memoria arriesgaría códigos equivocados). Cada
empresa puede seguir creando cualquier cuenta propia con
POST /empresas/{id}/cuentas aunque no esté aquí — este catálogo es solo
una ayuda de búsqueda, nunca una limitación.

Estructura de clases confirmada (Decreto 2650): 1 Activo, 2 Pasivo,
3 Patrimonio, 4 Ingresos, 5 Gastos, 6 Costo de ventas,
7 Costos de producción, 8-9 Cuentas de orden.
"""

# (código, nombre, clase, naturaleza)
CATALOGO_PUC_BASE = [
    # ------------------------------------------------------------- Clase 1 — Activo
    ("110505", "Caja general", "Activo", "debito"),
    ("110510", "Cajas menores", "Activo", "debito"),
    ("111005", "Bancos - Moneda nacional", "Activo", "debito"),
    ("112005", "Cuentas de ahorro - Bancos", "Activo", "debito"),
    ("130505", "Clientes nacionales", "Activo", "debito"),
    ("130905", "Cuentas por cobrar a socios y accionistas", "Activo", "debito"),
    ("135505", "Anticipos a proveedores", "Activo", "debito"),
    ("135515", "Anticipo de impuestos y contribuciones o saldos a favor", "Activo", "debito"),
    ("136505", "Cuentas por cobrar a trabajadores", "Activo", "debito"),
    ("138005", "Deudores varios", "Activo", "debito"),
    ("143501", "Inventarios - Mercancías no fabricadas por la empresa", "Activo", "debito"),
    ("152405", "Equipo de oficina", "Activo", "debito"),
    ("152805", "Equipo de computación y comunicación", "Activo", "debito"),
    ("159205", "Depreciación acumulada", "Activo", "credito"),

    # ------------------------------------------------------------- Clase 2 — Pasivo
    ("210505", "Bancos nacionales (obligaciones financieras)", "Pasivo", "credito"),
    ("220501", "Proveedores nacionales", "Pasivo", "credito"),
    ("233505", "Costos y gastos por pagar", "Pasivo", "credito"),
    ("236540", "Retención en la fuente por pagar", "Pasivo", "credito"),
    ("236705", "Retención de IVA por pagar", "Pasivo", "credito"),
    ("236801", "Retención de ICA por pagar", "Pasivo", "credito"),
    ("240801", "IVA generado (por pagar)", "Pasivo", "credito"),
    ("240802", "IVA descontable", "Activo", "debito"),
    ("240815", "Impuesto al consumo (INC) por pagar", "Pasivo", "credito"),
    ("250405", "Salarios por pagar", "Pasivo", "credito"),
    ("250505", "Cesantías consolidadas", "Pasivo", "credito"),
    ("251005", "Intereses sobre cesantías", "Pasivo", "credito"),
    ("251505", "Prima de servicios", "Pasivo", "credito"),
    ("252005", "Vacaciones consolidadas", "Pasivo", "credito"),
    ("261005", "Provisión para obligaciones laborales - Cesantías", "Pasivo", "credito"),

    # ------------------------------------------------------------- Clase 3 — Patrimonio
    ("311505", "Aportes sociales", "Patrimonio", "credito"),
    ("330505", "Reservas obligatorias", "Patrimonio", "credito"),
    ("360505", "Utilidad del ejercicio", "Patrimonio", "credito"),
    ("361005", "Pérdida del ejercicio", "Patrimonio", "debito"),

    # ------------------------------------------------------------- Clase 4 — Ingresos
    ("413501", "Comercio al por mayor y al por menor", "Ingresos", "credito"),
    ("415501", "Actividades inmobiliarias, empresariales y de alquiler", "Ingresos", "credito"),
    ("421005", "Ingresos financieros", "Ingresos", "credito"),
    ("429505", "Ingresos diversos", "Ingresos", "credito"),

    # ------------------------------------------------------------- Clase 5 — Gastos (51 administración)
    ("510506", "Gastos de personal - Sueldos", "Gastos", "debito"),
    ("511005", "Honorarios", "Gastos", "debito"),
    ("511505", "Impuestos", "Gastos", "debito"),
    ("512005", "Arrendamientos", "Gastos", "debito"),
    ("512505", "Contribuciones y afiliaciones", "Gastos", "debito"),
    ("513005", "Seguros", "Gastos", "debito"),
    ("513595", "Servicios - Diversos", "Gastos", "debito"),
    ("513520", "Servicios - Aseo y vigilancia", "Gastos", "debito"),
    ("514005", "Gastos legales", "Gastos", "debito"),
    ("514010", "Mantenimiento y reparaciones", "Gastos", "debito"),
    ("515005", "Adecuación e instalación", "Gastos", "debito"),
    ("515505", "Gastos de viaje", "Gastos", "debito"),
    ("516005", "Depreciaciones", "Gastos", "debito"),
    ("519505", "Diversos - Otros gastos de administración", "Gastos", "debito"),
    ("519530", "Diversos - Papelería y útiles de oficina", "Gastos", "debito"),
    ("522035", "Diversos - Transporte, fletes y acarreos", "Gastos", "debito"),
    ("522515", "Diversos - Combustibles y lubricantes", "Gastos", "debito"),

    # Clase 5 — Gastos (52 ventas, misma estructura reflejada)
    ("520506", "Gastos de personal de ventas - Sueldos", "Gastos", "debito"),
    ("521005", "Honorarios de ventas", "Gastos", "debito"),
    ("523595", "Servicios de ventas - Diversos", "Gastos", "debito"),
    ("529505", "Diversos - Otros gastos de ventas", "Gastos", "debito"),

    # Clase 5 — Gastos (53 no operacionales)
    ("530505", "Gastos financieros - Intereses", "Gastos", "debito"),
    ("539505", "Gastos diversos no operacionales", "Gastos", "debito"),

    # ------------------------------------------------------------- Clase 6 — Costo de ventas
    ("613501", "Costo de ventas - Comercio al por mayor y al por menor", "Costos", "debito"),
    ("623501", "Compras de mercancías", "Costos", "debito"),
]


def sembrar_catalogo_puc(db):
    """Inserta el catálogo base si no existe todavía (idempotente)."""
    from app.models.models import PucCuenta

    existentes = {c.codigo for c in db.query(PucCuenta.codigo).all()}
    nuevas = 0
    for codigo, nombre, clase, naturaleza in CATALOGO_PUC_BASE:
        if codigo in existentes:
            continue
        db.add(PucCuenta(codigo=codigo, nombre=nombre, clase=clase, naturaleza=naturaleza))
        nuevas += 1
    if nuevas:
        db.commit()
    return nuevas
