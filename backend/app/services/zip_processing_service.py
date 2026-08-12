"""
Procesamiento del ZIP de documentos (sección 3, 5, 6).

Agrupa los archivos del ZIP en "documentos" — cada documento puede tener
XML, PDF, o ambos. Cuando hay ambos, el XML manda: los campos que trae
el XML nunca se sobreescriben con lo que diga el PDF (sección 5). El
PDF solo aporta campos que el XML no tenga (raro) o sirve de única
fuente cuando no hay XML.
"""
import zipfile
import io
from dataclasses import dataclass, field
from typing import Optional

from app.services.xml_extraction_service import extraer_factura_xml
from app.services.pdf_extraction_service import extraer_factura_pdf


@dataclass
class DocumentoExtraido:
    clave_agrupacion: str
    nombre_xml: Optional[str] = None
    nombre_pdf: Optional[str] = None
    xml_bytes: Optional[bytes] = None
    pdf_bytes: Optional[bytes] = None
    fuente_extraccion: str = ""      # "xml" | "pdf_texto" | "pdf_ocr"
    confianza: float = 0.0
    campos: dict = field(default_factory=dict)
    error: Optional[str] = None


def _clave_desde_nombre(nombre: str) -> str:
    """Nombre de archivo sin extensión, en minúsculas, como clave de respaldo
    cuando no se puede determinar CUFE (ej. PDF sin XML asociado)."""
    base = nombre.rsplit("/", 1)[-1]
    base = base.rsplit(".", 1)[0]
    return base.strip().lower()


def procesar_zip(contenido_zip: bytes) -> list[DocumentoExtraido]:
    documentos: dict[str, DocumentoExtraido] = {}
    errores: list[DocumentoExtraido] = []

    with zipfile.ZipFile(io.BytesIO(contenido_zip)) as zf:
        nombres = [n for n in zf.namelist() if not n.endswith("/")]
        xmls = [n for n in nombres if n.lower().endswith(".xml")]
        pdfs = [n for n in nombres if n.lower().endswith(".pdf")]

        # 1) Procesar todos los XML primero — son la fuente principal y
        #    determinan la clave de agrupación real (CUFE).
        pdf_pendientes = {_clave_desde_nombre(n): n for n in pdfs}

        for nombre_xml in xmls:
            contenido = zf.read(nombre_xml)
            resultado = extraer_factura_xml(contenido)
            clave_archivo = _clave_desde_nombre(nombre_xml)

            if not resultado["ok"]:
                errores.append(DocumentoExtraido(
                    clave_agrupacion=clave_archivo, nombre_xml=nombre_xml,
                    xml_bytes=contenido, error=resultado["error"],
                ))
                continue

            cufe = resultado["campos"].get("cufe") or ""
            clave = cufe.lower() if cufe else clave_archivo

            doc = DocumentoExtraido(
                clave_agrupacion=clave,
                nombre_xml=nombre_xml,
                xml_bytes=contenido,
                fuente_extraccion="xml",
                confianza=100.0,
                campos=resultado["campos"],
            )
            documentos[clave] = doc

            # Si hay un PDF con el mismo nombre base, se asocia como
            # complemento (no reemplaza nada del XML) y se retira de
            # pendientes para no procesarlo dos veces.
            if clave_archivo in pdf_pendientes:
                nombre_pdf = pdf_pendientes.pop(clave_archivo)
                doc.nombre_pdf = nombre_pdf
                doc.pdf_bytes = zf.read(nombre_pdf)

        # 2) PDFs que no tienen XML asociado: única fuente disponible.
        for clave_archivo, nombre_pdf in pdf_pendientes.items():
            contenido = zf.read(nombre_pdf)
            resultado = extraer_factura_pdf(contenido)
            documentos[clave_archivo] = DocumentoExtraido(
                clave_agrupacion=clave_archivo,
                nombre_pdf=nombre_pdf,
                pdf_bytes=contenido,
                fuente_extraccion=resultado["fuente"],
                confianza=resultado["confianza"],
                campos=resultado["campos"],
            )

    return list(documentos.values()) + errores
