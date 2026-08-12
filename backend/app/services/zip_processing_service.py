"""
Procesamiento de los documentos de la DIAN (sección 3, 5, 6).

Acepta cualquier combinación de archivos que el usuario suba: uno o
varios ZIP (la DIAN a veces entrega la descarga partida en varios ZIP
cuando son muchos documentos), y/o archivos XML/PDF sueltos sin
comprimir (cuando el usuario los descargó individualmente, por ejemplo
desde el correo). Todo se junta en una sola lista de pares
(nombre, contenido) y se agrupa igual, sin importar de dónde vino cada
archivo — así un XML dentro de un ZIP y su PDF suelto (o viceversa)
igual se emparejan si comparten el mismo nombre base.

Un archivo individual que falle (ZIP corrupto, XML mal formado) queda
registrado como error y NO detiene el procesamiento del resto — la
sección 30 pide justamente poder seguir procesando lo válido aunque
algunos archivos tengan error.
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
    nombre_origen: Optional[str] = None  # nombre del archivo/zip subido por el usuario, para mensajes de error


def _clave_desde_nombre(nombre: str) -> str:
    """Nombre de archivo sin extensión, en minúsculas, como clave de respaldo
    cuando no se puede determinar CUFE (ej. PDF sin XML asociado)."""
    base = nombre.rsplit("/", 1)[-1]
    base = base.rsplit(".", 1)[0]
    return base.strip().lower()


def extraer_pares_de_zip(nombre_zip: str, contenido_zip: bytes) -> tuple[list[tuple[str, bytes]], list[DocumentoExtraido]]:
    """
    Abre un ZIP y devuelve sus archivos XML/PDF como pares (nombre, bytes),
    listos para agrupar junto con cualquier otro archivo. Si el ZIP no se
    puede abrir (no es un zip válido, está corrupto, etc.) o no contiene
    ningún XML/PDF, se reporta como error en vez de interrumpir toda la
    carga — así el resto de archivos que sí sean válidos se procesan igual.
    """
    pares = []
    errores = []
    try:
        with zipfile.ZipFile(io.BytesIO(contenido_zip)) as zf:
            nombres = [n for n in zf.namelist() if not n.endswith("/")]
            utiles = [n for n in nombres if n.lower().endswith((".xml", ".pdf"))]
            if not utiles:
                errores.append(DocumentoExtraido(
                    clave_agrupacion=_clave_desde_nombre(nombre_zip), nombre_origen=nombre_zip,
                    error=f"El archivo '{nombre_zip}' es un ZIP válido pero no contiene ningún XML ni PDF adentro.",
                ))
            for n in utiles:
                pares.append((n, zf.read(n)))
    except zipfile.BadZipFile:
        errores.append(DocumentoExtraido(
            clave_agrupacion=_clave_desde_nombre(nombre_zip), nombre_origen=nombre_zip,
            error=f"'{nombre_zip}' no es un archivo ZIP válido (puede estar dañado, ser en realidad un "
                  f"RAR/7z renombrado a .zip, o haberse subido incompleto). Vuelve a descargarlo de la DIAN "
                  f"e inténtalo de nuevo, o sube los XML/PDF sueltos sin comprimir.",
        ))
    return pares, errores


def agrupar_documentos(pares: list[tuple[str, bytes]]) -> list[DocumentoExtraido]:
    """Agrupa pares (nombre, contenido) de XML/PDF en documentos — XML manda (sección 5)."""
    documentos: dict[str, DocumentoExtraido] = {}
    errores: list[DocumentoExtraido] = []

    xmls = [(n, c) for n, c in pares if n.lower().endswith(".xml")]
    pdfs = {n: c for n, c in pares if n.lower().endswith(".pdf")}
    pdf_pendientes = {_clave_desde_nombre(n): (n, c) for n, c in pdfs.items()}

    for nombre_xml, contenido in xmls:
        resultado = extraer_factura_xml(contenido)
        clave_archivo = _clave_desde_nombre(nombre_xml)

        if not resultado["ok"]:
            errores.append(DocumentoExtraido(
                clave_agrupacion=clave_archivo, nombre_xml=nombre_xml,
                xml_bytes=contenido, error=resultado["error"], nombre_origen=nombre_xml,
            ))
            continue

        cufe = resultado["campos"].get("cufe") or ""
        clave = cufe.lower() if cufe else clave_archivo

        doc = DocumentoExtraido(
            clave_agrupacion=clave, nombre_xml=nombre_xml, xml_bytes=contenido,
            fuente_extraccion="xml", confianza=100.0, campos=resultado["campos"],
        )
        documentos[clave] = doc

        if clave_archivo in pdf_pendientes:
            nombre_pdf, contenido_pdf = pdf_pendientes.pop(clave_archivo)
            doc.nombre_pdf = nombre_pdf
            doc.pdf_bytes = contenido_pdf

    for clave_archivo, (nombre_pdf, contenido_pdf) in pdf_pendientes.items():
        resultado = extraer_factura_pdf(contenido_pdf)
        documentos[clave_archivo] = DocumentoExtraido(
            clave_agrupacion=clave_archivo, nombre_pdf=nombre_pdf, pdf_bytes=contenido_pdf,
            fuente_extraccion=resultado["fuente"], confianza=resultado["confianza"], campos=resultado["campos"],
        )

    return list(documentos.values()) + errores


def procesar_zip(contenido_zip: bytes) -> list[DocumentoExtraido]:
    """Compatibilidad: procesa un único ZIP (usado también por las pruebas existentes)."""
    pares, errores = extraer_pares_de_zip("documentos.zip", contenido_zip)
    return agrupar_documentos(pares) + errores


def procesar_archivos_mixtos(archivos: list[tuple[str, bytes]]) -> list[DocumentoExtraido]:
    """
    archivos: lista de (nombre_archivo, contenido) tal como los subió el
    usuario — puede incluir varios .zip, varios .xml/.pdf sueltos, o una
    mezcla de ambos. Cualquier extensión no soportada se reporta como
    error sin detener el resto.
    """
    todos_los_pares: list[tuple[str, bytes]] = []
    errores: list[DocumentoExtraido] = []

    for nombre, contenido in archivos:
        ext = nombre.lower().rsplit(".", 1)[-1] if "." in nombre else ""
        if ext == "zip":
            pares, errores_zip = extraer_pares_de_zip(nombre, contenido)
            todos_los_pares.extend(pares)
            errores.extend(errores_zip)
        elif ext in ("xml", "pdf"):
            todos_los_pares.append((nombre, contenido))
        else:
            errores.append(DocumentoExtraido(
                clave_agrupacion=_clave_desde_nombre(nombre), nombre_origen=nombre,
                error=f"'{nombre}' no es un .zip, .xml ni .pdf — se omitió.",
            ))

    return agrupar_documentos(todos_los_pares) + errores
