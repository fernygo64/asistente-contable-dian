"""
Arquitectura de adaptadores de exportación (secciones 20-22).

AccountingExportAdapter es la interfaz común. La lógica de generación
de archivo delimitado es compartida (columnas configurables por
plantilla), pero cada adaptador define sus propios campos obligatorios
y reglas de validación — no se copia una lógica genérica disfrazada de
"soporta cualquier sistema"; SIIGO y World Office son adaptadores
independientes, como pide la especificación, y agregar un tercero
(section 22, "Otros sistemas") es una clase nueva, no tocar las
existentes.
"""
from abc import ABC, abstractmethod


class AccountingExportAdapter(ABC):
    nombre_sistema: str = ""
    campos_obligatorios: list[str] = []

    def validar_plantilla(self, columnas: list[dict]) -> list[str]:
        errores = []
        labels_presentes = {c["label"] for c in columnas}
        faltantes = [c for c in self.campos_obligatorios if c not in labels_presentes]
        if faltantes:
            errores.append(
                f"La plantilla de {self.nombre_sistema} no tiene las columnas obligatorias: {faltantes}. "
                f"Agrégalas a la plantilla antes de exportar."
            )
        return errores

    @abstractmethod
    def validar_negocio(self, filas: list[dict]) -> list[str]:
        """Reglas de validación específicas del sistema contable destino."""
        raise NotImplementedError


class SiigoExportAdapter(AccountingExportAdapter):
    nombre_sistema = "Siigo Pyme"
    campos_obligatorios = ["Fecha", "Cuenta", "Nit", "Debito", "Credito"]

    def validar_negocio(self, filas: list[dict]) -> list[str]:
        errores = []
        for i, fila in enumerate(filas):
            nit = str(fila.get("Nit", "")).strip()
            if nit and not nit.replace("-", "").isdigit():
                errores.append(f"Fila {i + 1}: NIT '{nit}' no parece un NIT válido para Siigo.")
        return errores


class WorldOfficeExportAdapter(AccountingExportAdapter):
    nombre_sistema = "World Office"
    # World Office exige explícitamente el nombre del tercero en el archivo,
    # a diferencia de Siigo (que puede resolverlo internamente por NIT) —
    # esta es una regla de negocio propia de este adaptador, no genérica.
    campos_obligatorios = ["Fecha", "Cuenta", "Nit", "Tercero", "Debito", "Credito"]

    def validar_negocio(self, filas: list[dict]) -> list[str]:
        errores = []
        for i, fila in enumerate(filas):
            if not str(fila.get("Tercero", "")).strip():
                errores.append(f"Fila {i + 1}: World Office requiere el nombre del tercero, viene vacío.")
        return errores


def obtener_adaptador(sistema_contable: str) -> AccountingExportAdapter:
    adaptadores = {
        "siigo_pyme": SiigoExportAdapter,
        "world_office": WorldOfficeExportAdapter,
    }
    clase = adaptadores.get(sistema_contable)
    if not clase:
        raise ValueError(f"Sistema contable no soportado: {sistema_contable}")
    return clase()
