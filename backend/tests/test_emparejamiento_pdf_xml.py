import io
import zipfile

from reportlab.pdfgen import canvas

from app.services.zip_processing_service import agrupar_documentos
from tests.test_documentos import _xml


def _pdf_con_cufe(cufe: str) -> bytes:
    buf = io.BytesIO()
    c = canvas.Canvas(buf)
    c.drawString(50, 800, "FACTURA ELECTRÓNICA DE VENTA")
    c.drawString(50, 780, f"Código Único de Factura - CUFE: {cufe}")
    c.drawString(50, 760, "Nit del Emisor: 900608161")
    c.drawString(50, 740, "Total: $100.000")
    c.save()
    return buf.getvalue()


def test_pdf_con_nombre_distinto_se_relaciona_por_cufe_no_duplica():
    """
    Bug real reportado: el XML y el PDF de la MISMA factura, cuando la
    DIAN los nombra distinto (pasa seguido en descargas reales), antes
    creaban dos facturas separadas — una por el XML, otra por el PDF —
    porque el emparejamiento solo miraba el nombre del archivo.
    """
    cufe = "1b1e032ba8a83ad53c81311b91093374cc884dd20aacf6dc3e46e560c59701ec7260e8f4ade0b3e"
    xml_bytes = _xml("FXX001", cufe, "900608161")
    pdf_bytes = _pdf_con_cufe(cufe)

    pares = [
        ("factura_original_xml.xml", xml_bytes),   # nombre distinto a propósito
        ("descarga_correo_adjunto.pdf", pdf_bytes),  # nombre distinto a propósito
    ]

    documentos = agrupar_documentos(pares, nit_empresa="16699962")

    # Debe quedar UN SOLO documento (el del XML, con el PDF adjunto),
    # no dos documentos separados.
    assert len(documentos) == 1
    doc = documentos[0]
    assert doc.fuente_extraccion == "xml"  # el XML manda, nunca el PDF
    assert doc.confianza == 100.0
    assert doc.pdf_bytes == pdf_bytes  # el PDF quedó adjunto al mismo documento


def test_pdf_sin_cufe_coincidente_si_crea_documento_aparte():
    """Un PDF de una factura DISTINTA (sin XML que la acompañe) sigue procesándose normal, como antes."""
    cufe_xml = "a1a2a3a4a5a6a7a8a9b1b2b3b4b5b6b7b8b9c1c2c3c4c5c6c7c8c9d1d2d3d4d5d6d7d8d9e1e2e3e4"
    cufe_pdf_distinto = "f1f2f3f4f5f6f7f8f9a1a2a3a4a5a6a7a8a9b1b2b3b4b5b6b7b8b9c1c2c3c4c5c6c7c8c9d1d2d3d4"
    xml_bytes = _xml("FXX002", cufe_xml, "900608161")
    pdf_bytes = _pdf_con_cufe(cufe_pdf_distinto)

    pares = [
        ("una_factura.xml", xml_bytes),
        ("otra_factura_completamente_distinta.pdf", pdf_bytes),
    ]

    documentos = agrupar_documentos(pares, nit_empresa="16699962")
    assert len(documentos) == 2  # son facturas distintas de verdad, no deben fusionarse
