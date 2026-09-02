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

La validación de "columnas obligatorias" se hace por ORIGEN de dato
(source), no por el texto de la etiqueta — así funciona sin importar
cómo el usuario haya nombrado sus columnas. Confirmado con archivos
reales de exportación: Siigo Pyme (Movimiento Contable) usa una sola
columna "Débito o Crédito" con indicador D/C + una columna de Valor
(no columnas separadas de débito y crédito), mientras que World Office
sí usa columnas de Débito y Crédito separadas.
"""
from abc import ABC, abstractmethod


class AccountingExportAdapter(ABC):
    nombre_sistema: str = ""
    # Cada elemento es un conjunto de sources donde basta con que UNO
    # de los sub-conjuntos esté completo (para permitir formas
    # alternativas de representar lo mismo, ej. debito+credito por
    # separado vs. debito_credito+valor combinado).
    requisitos_alternativos: list[list[set]] = []

    def validar_plantilla(self, columnas: list[dict]) -> list[str]:
        errores = []
        sources_presentes = {c.get("source") for c in columnas}
        for nombre_requisito, alternativas in self.requisitos_alternativos:
            cumple_alguna = any(alt.issubset(sources_presentes) for alt in alternativas)
            if not cumple_alguna:
                opciones = " o ".join("+".join(sorted(alt)) for alt in alternativas)
                errores.append(
                    f"La plantilla de {self.nombre_sistema} no tiene columnas para '{nombre_requisito}' "
                    f"(agrega una columna con origen: {opciones})."
                )
        return errores

    @abstractmethod
    def validar_negocio(self, filas: list[dict]) -> list[str]:
        """Reglas de validación específicas del sistema contable destino."""
        raise NotImplementedError


class SiigoExportAdapter(AccountingExportAdapter):
    nombre_sistema = "Siigo Pyme"
    # Confirmado con el archivo real "Movimiento Contable": obligatorios
    # son Tipo de Comprobante, Código Comprobante, Cuenta Contable,
    # Débito o Crédito y Valor de la Secuencia. Tipo/Código de comprobante
    # suelen ser valores fijos según la parametrización propia del
    # usuario en Siigo — no se pueden validar estructuralmente aquí.
    requisitos_alternativos = [
        ("cuenta contable", [{"cuenta"}]),
        ("valor del movimiento", [{"debito_credito", "valor"}, {"debito", "credito"}]),
    ]

    def validar_negocio(self, filas: list[dict]) -> list[str]:
        errores = []
        for i, fila in enumerate(filas):
            nit = str(fila.get("Nit", "")).strip()
            if nit and not nit.replace("-", "").isdigit():
                errores.append(f"Fila {i + 1}: NIT '{nit}' no parece un NIT válido para Siigo.")
        return errores


class WorldOfficeExportAdapter(AccountingExportAdapter):
    nombre_sistema = "World Office"
    # Confirmado con el archivo real "WORLD_OFFICE_JUNIO_2026.xlsx": solo
    # trae el NIT del tercero (columnas "Tercero Externo"), sin ninguna
    # columna de nombre — World Office lo resuelve internamente por NIT,
    # igual que Siigo. La suposición anterior (que exigía nombre) era
    # incorrecta y quedó corregida al revisar un archivo real.
    requisitos_alternativos = [
        ("cuenta contable", [{"cuenta"}]),
        ("nit del tercero", [{"nit"}]),
        ("débito y crédito", [{"debito", "credito"}]),
    ]

    def validar_negocio(self, filas: list[dict]) -> list[str]:
        errores = []
        for i, fila in enumerate(filas):
            nit = str(fila.get("Nit", "")).strip()
            if not nit:
                errores.append(f"Fila {i + 1}: World Office requiere el NIT del tercero, viene vacío.")
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
