"""
Extracción de datos desde XML-UBL de facturas electrónicas DIAN.

El XML es SIEMPRE la fuente principal cuando existe (sección 5) porque
contiene información estructurada — nunca se reemplaza por lo que diga
un PDF cuando hay XML disponible.

Misma lógica que el extractor de facturas ya construido (single-file
HTML), portada a Python: búsqueda de elementos por nombre local
(ignorando el prefijo de namespace), porque el prefijo varía entre
proveedores tecnológicos aunque la estructura UBL sea la misma.
"""
from datetime import datetime
from typing import Optional
from xml.etree import ElementTree as ET


def _local(tag: str) -> str:
    return tag.split("}")[-1] if "}" in tag else tag


def _find_all(root, local_name: str):
    return [el for el in root.iter() if _local(el.tag) == local_name]


def _first_child(root, local_name: str):
    for child in list(root):
        if _local(child.tag) == local_name:
            return child
    return None


def _text(root, local_name: str) -> str:
    found = _find_all(root, local_name)
    return found[0].text.strip() if found and found[0].text else ""


def _amount(parent, local_name: str) -> float:
    if parent is None:
        return 0.0
    node = _first_child(parent, local_name)
    if node is None or not node.text:
        return 0.0
    try:
        return float(node.text)
    except ValueError:
        return 0.0


def _desempaquetar_raiz(root):
    """Si el XML viene envuelto en un AttachedDocument con el documento real
    embebido como CDATA, devuelve el documento interno; si no, la raíz tal cual."""
    tag_raiz = _local(root.tag)
    if tag_raiz in ("Invoice", "CreditNote", "DebitNote", "ApplicationResponse"):
        return root, tag_raiz
    for desc in _find_all(root, "Description"):
        if not desc.text:
            continue
        for candidato in ("Invoice", "CreditNote", "DebitNote"):
            if f"<{candidato}" in desc.text or f":{candidato}" in desc.text:
                try:
                    interno = ET.fromstring(desc.text)
                    return interno, _local(interno.tag)
                except ET.ParseError:
                    continue
    return root, tag_raiz


def clasificar_documento_xml(contenido: bytes) -> dict:
    """
    Identifica QUÉ TIPO de documento electrónico es antes de intentar
    extraer datos de factura de él. Esto evita dos errores graves:
    1) Tratar un "Application Response" (acuse de recibo del proceso
       RADIAN — no es una factura, no tiene información contable) como
       si fuera una factura real.
    2) Tratar una Nómina Electrónica Individual (esquema XML totalmente
       distinto al de factura, con datos de empleado/conceptos de
       nómina) con el parser de facturas, lo que produciría datos
       basura o incorrectos.
    Devuelve {"naturaleza": ..., "raiz": nodo_xml_a_usar} donde
    naturaleza es una de: "factura", "nota_credito", "nota_debito",
    "acuse_recibo", "nomina", "desconocido".
    """
    try:
        root = ET.fromstring(contenido)
    except ET.ParseError as e:
        return {"naturaleza": "invalido", "error": f"XML mal formado: {e}", "raiz": None}

    tag_original = _local(root.tag)
    if "nomina" in tag_original.lower() or "payroll" in tag_original.lower():
        return {"naturaleza": "nomina", "error": None, "raiz": root}

    raiz, tag = _desempaquetar_raiz(root)
    mapa = {
        "Invoice": "factura",
        "CreditNote": "nota_credito",
        "DebitNote": "nota_debito",
        "ApplicationResponse": "acuse_recibo",
    }
    naturaleza = mapa.get(tag, "desconocido")
    return {"naturaleza": naturaleza, "error": None, "raiz": raiz}


def extraer_factura_xml(contenido: bytes) -> dict:
    """
    Devuelve un dict con:
      ok: bool
      error: str | None
      campos: dict de datos extraídos
      campos_presentes: list[str] — para el cálculo de confianza
    El XML válido siempre reporta 100% de confianza estructural
    (sección 7) porque, si el parseo tuvo éxito, los campos que trae
    son exactos — no hay "adivinanza" involucrada.
    """
    try:
        root = ET.fromstring(contenido)
    except ET.ParseError as e:
        return {"ok": False, "error": f"XML mal formado: {e}", "campos": {}, "campos_presentes": []}

    invoice_root, _tag = _desempaquetar_raiz(root)

    numero = _text(invoice_root, "ID")
    cufe_nodes = _find_all(invoice_root, "UUID")
    cufe = cufe_nodes[0].text.strip() if cufe_nodes and cufe_nodes[0].text else ""
    fecha = _text(invoice_root, "IssueDate")
    hora = _text(invoice_root, "IssueTime")

    supplier = None
    for sp in _find_all(invoice_root, "AccountingSupplierParty"):
        supplier = sp
        break
    nit_emisor, nombre_emisor, direccion_emisor = "", "", ""
    if supplier is not None:
        party_ids = _find_all(supplier, "PartyIdentification")
        if party_ids:
            id_node = _first_child(party_ids[0], "ID")
            if id_node is not None and id_node.text:
                nit_emisor = id_node.text.strip()
        reg_names = _find_all(supplier, "RegistrationName")
        if reg_names and reg_names[0].text:
            nombre_emisor = reg_names[0].text.strip()
        if not nombre_emisor:
            names = _find_all(supplier, "Name")
            if names and names[0].text:
                nombre_emisor = names[0].text.strip()
        addr = _find_all(supplier, "PostalAddress")
        if addr:
            partes = []
            line = _first_child(addr[0], "AddressLine")
            if line is not None:
                l = _first_child(line, "Line")
                if l is not None and l.text:
                    partes.append(l.text.strip())
            city = _first_child(addr[0], "CityName")
            if city is not None and city.text:
                partes.append(city.text.strip())
            direccion_emisor = ", ".join(p for p in partes if p)

    receptor = None
    for rp in _find_all(invoice_root, "AccountingCustomerParty"):
        receptor = rp
        break
    nit_receptor, nombre_receptor = "", ""
    if receptor is not None:
        party_ids = _find_all(receptor, "PartyIdentification")
        if party_ids:
            id_node = _first_child(party_ids[0], "ID")
            if id_node is not None and id_node.text:
                nit_receptor = id_node.text.strip()
        reg_names = _find_all(receptor, "RegistrationName")
        if reg_names and reg_names[0].text:
            nombre_receptor = reg_names[0].text.strip()

    legal_total = None
    for lt in _find_all(invoice_root, "LegalMonetaryTotal"):
        legal_total = lt
        break
    line_extension = _amount(legal_total, "LineExtensionAmount")
    tax_exclusive = _amount(legal_total, "TaxExclusiveAmount")
    tax_inclusive = _amount(legal_total, "TaxInclusiveAmount")
    payable = _amount(legal_total, "PayableAmount")

    iva_total = rf_total = ri_total = rv_total = inc_total = 0.0
    for tt in _find_all(invoice_root, "TaxTotal"):
        subtotals = _find_all(tt, "TaxSubtotal")
        if not subtotals:
            iva_total += _amount(tt, "TaxAmount")
            continue
        for st in subtotals:
            schemes = _find_all(st, "TaxScheme")
            tax_name = ""
            if schemes:
                name_node = _first_child(schemes[0], "Name")
                if name_node is not None and name_node.text:
                    tax_name = name_node.text.strip().upper()
            amt = _amount(st, "TaxAmount")
            if "IVA" in tax_name or "VAT" in tax_name:
                iva_total += amt
            elif "INC" in tax_name:
                inc_total += amt
            elif "ICA" in tax_name:
                ri_total += amt
            else:
                iva_total += amt

    for wt in _find_all(invoice_root, "WithholdingTaxTotal"):
        for st in _find_all(wt, "TaxSubtotal"):
            schemes = _find_all(st, "TaxScheme")
            tax_name = ""
            if schemes:
                name_node = _first_child(schemes[0], "Name")
                if name_node is not None and name_node.text:
                    tax_name = name_node.text.strip().upper()
            amt = _amount(st, "TaxAmount")
            if "ICA" in tax_name:
                ri_total += amt
            elif "IVA" in tax_name:
                rv_total += amt
            else:
                rf_total += amt

    conceptos = []
    lineas_xml = (_find_all(invoice_root, "InvoiceLine")
                  + _find_all(invoice_root, "CreditNoteLine")
                  + _find_all(invoice_root, "DebitNoteLine"))
    for line in lineas_xml:
        item = None
        for it in _find_all(line, "Item"):
            item = it
            break
        descripcion, codigo = "", ""
        if item is not None:
            d = _first_child(item, "Description")
            if d is not None and d.text:
                descripcion = d.text.strip()
            for sid in _find_all(item, "StandardItemIdentification"):
                idn = _first_child(sid, "ID")
                if idn is not None and idn.text:
                    codigo = idn.text.strip()
                break
        price_amt = 0.0
        for price in _find_all(line, "Price"):
            price_amt = _amount(price, "PriceAmount")
            break
        qty_node = _first_child(line, "InvoicedQuantity")
        conceptos.append({
            "codigo": codigo,
            "descripcion": descripcion or "(sin descripción)",
            "cantidad": float(qty_node.text) if qty_node is not None and qty_node.text else 0.0,
            "valor_unitario": price_amt,
            "subtotal": _amount(line, "LineExtensionAmount"),
        })

    forma_pago = ""
    for pm in _find_all(invoice_root, "PaymentMeans"):
        code = _first_child(pm, "PaymentMeansCode")
        if code is not None and code.text:
            forma_pago = code.text.strip()
        break

    campos = {
        "numero_factura": numero,
        "cufe": cufe,
        "fecha_emision": fecha,
        "hora_emision": hora,
        "nit_emisor": nit_emisor,
        "nombre_emisor": nombre_emisor,
        "direccion_emisor": direccion_emisor,
        "nit_receptor": nit_receptor,
        "nombre_receptor": nombre_receptor,
        "subtotal": line_extension,
        "base_gravable": tax_exclusive,
        "iva": iva_total,
        "inc": inc_total,
        "retenciones": {"retefuente": rf_total, "reteica": ri_total, "reteiva": rv_total},
        "total": tax_inclusive or payable,
        "valor_a_pagar": payable,
        "forma_pago": forma_pago,
        "conceptos": conceptos,
    }
    campos_presentes = [k for k, v in campos.items() if v not in ("", 0, 0.0, [], {}, None)]

    if not numero and not cufe and not conceptos:
        return {"ok": False, "error": "No se reconoció estructura UBL de factura/nota crédito/nota débito en el archivo.",
                "campos": {}, "campos_presentes": []}

    return {"ok": True, "error": None, "campos": campos, "campos_presentes": campos_presentes}
