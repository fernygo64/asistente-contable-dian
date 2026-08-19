# Asistente Contable DIAN — Aplicativo funcional (Etapas 1-5)

Backend real (FastAPI + SQLAlchemy + Alembic) + interfaz web funcional
para el asistente contable multiempresa descrito en la especificación.
**Este proyecto es independiente de ContaFlow AI.**

## Requisitos de sistema (además de Python)

```bash
# Ubuntu/Debian — necesario para el respaldo OCR de PDF
apt-get install -y tesseract-ocr tesseract-ocr-spa poppler-utils
```

## Cómo ejecutarlo

```bash
cd backend
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

alembic upgrade head
uvicorn app.main:app --reload
```

Abre **http://127.0.0.1:8000/app/** en el navegador — ahí está la
interfaz completa (empresas, carga de documentos, facturas, partida
doble, plantillas de exportación, auditoría). La documentación
interactiva de la API está en **http://127.0.0.1:8000/docs**.

Para usar PostgreSQL en vez de SQLite, sin cambiar código:
```bash
export DATABASE_URL="postgresql+psycopg2://usuario:clave@localhost:5432/asistente_contable"
pip install psycopg2-binary
alembic upgrade head && uvicorn app.main:app --reload
```

## Cómo correr las pruebas

```bash
pytest -v   # 42 pruebas
```

## El flujo completo, tal como lo pediste, funcionando de verdad

```
DIAN → Excel + ZIP → carga manual → XML tiene prioridad → PDF/OCR de respaldo
→ extracción con % de confianza → relación por CUFE/número/NIT/fecha
→ detección de duplicados → historial de la empresa → sugerencia explicada
→ revisión/corrección humana → partida doble validada (débito=crédito)
→ aprobación → contabilización → plantilla Siigo/World Office → archivo listo
→ auditoría de todo el proceso
```

Verificado con una prueba end-to-end real (peticiones HTTP contra el
servidor corriendo, no solo TestClient): crear empresa → configurar
cuentas → cargar ZIP con XML real (IVA incluido) → generar partida
(balanceada: débito = crédito = $238.000) → contabilizar → exportar →
archivo `.txt` descargado con los valores correctos.

## Qué incluye cada etapa (todas probadas, 42 pruebas automatizadas)

**Etapa 1 — Núcleo multiempresa:** aislamiento total verificado con el
mismo NIT de proveedor en dos empresas dando resultados independientes;
motor de historial y sugerencia explicable (frecuencia + motivo en
lenguaje natural, nunca inventa cuentas); reglas contables; importación
de histórico Excel/CSV con mapeo de columnas configurable; auditoría.

**Etapa 2 — Documentos DIAN:** carga manual de Excel + ZIP; parser
XML-UBL propio (fuente principal, 100% confianza); extracción de PDF
con respaldo OCR real vía Tesseract (probado con PDF de texto y PDF
escaneado); relación por CUFE → número+NIT → NIT+fecha+total; detección
de duplicados; corrección manual sin perder el dato original.

**Etapa 3 — Partida doble:** genera movimientos débito/crédito a partir
de la cuenta de gasto (sugerida o corregida) + las cuentas base de la
empresa (IVA, retenciones, contrapartida Caja/Banco/Proveedores).
Nunca inventa una cuenta faltante — devuelve el error exacto. Nunca
persiste un comprobante descuadrado. Alimenta el historial de
aprendizaje en cada decisión. Respeta Régimen Simple (sin
retefuente/ICA, solo ReteIVA).

**Etapa 4 — Exportación Siigo/World Office:** arquitectura de
adaptadores real (`AccountingExportAdapter` con `SiigoExportAdapter` y
`WorldOfficeExportAdapter` — reglas de validación distintas entre
ambos, no una lógica genérica con otro nombre). Plantillas configurables
por empresa con equivalencia de cuentas propia. Validación obligatoria
antes de generar el archivo (sección 23) — factura sin partida, sin
balance, o plantilla incompleta bloquean la exportación con el detalle
exacto del error. Registro de auditoría de cada exportación.

**Etapa 5 — Interfaz funcional:** una sola página (`frontend/index.html`,
servida por el propio backend en `/app/`) que cubre el flujo completo:
crear/seleccionar empresa, configurar cuentas base, cargar Excel+ZIP,
revisar facturas con filtros por estado, ver la sugerencia explicada,
generar y previsualizar la partida doble, contabilizar, crear
plantillas y generar/descargar el archivo de exportación, y consultar
auditoría.

## Bugs reales encontrados y corregidos durante la construcción

1. Regex de número de factura no reconocía "Número:" en línea separada de "Factura".
2. Separadores de regex no toleraban el error típico de OCR que confunde `:` con `.`.
3. Excel trataba celdas vacías distinto a CSV.
4. Dependencia circular de llaves foráneas Empresa↔CuentaContable que
   habría fallado al migrar en PostgreSQL — corregida con `use_alter=True`.
5. Uso de `exportacion.id` antes de que la sesión lo generara (faltaba `db.flush()`).

## Qué NO incluye todavía — honestamente

- **Autenticación real.** Se usa un header `X-User` como placeholder
  para "quién hizo qué" en la auditoría. Antes de usar esto con datos
  reales de una empresa (no solo pruebas locales), esto debe
  reemplazarse por JWT + roles (Administrador/Contador/Supervisor/
  Consulta, como pedía la especificación original).
- **Pruebas E2E de navegador** (Playwright/Selenium): la interfaz se
  probó manualmente contra el backend real y mediante el script de
  Python end-to-end de este README, no con un framework de automatización
  de navegador.
- **Cobertura exhaustiva de variantes de Excel DIAN.** El mapeo de
  columnas es configurable y flexible, pero no se probó contra todos
  los formatos posibles que la DIAN pueda entregar — si tu Excel real
  no relaciona bien, el mapeo de columnas es el primer lugar a revisar.
- **Centros de costo** están modelados y con API, pero no integrados
  todavía en la partida doble (la especificación los pedía asociables
  a movimientos — es una extensión directa sobre `Movimiento.centro_costo_id`,
  que ya existe en el modelo, falta exponerlo en la generación de partida).
- **Panel de importación masiva con contadores en tiempo real** (sección
  30) — hoy la carga procesa todo el ZIP en una sola respuesta HTTP;
  para volúmenes muy grandes convendría procesamiento asíncrono con
  colas (Celery/Redis, como ya se usa en ContaFlow AI).

Estos son los puntos honestos donde "funcional" no significa "cada
detalle de las 44 secciones al 100%" — el flujo central que pediste
(DIAN → extracción → sugerencia → partida doble → Siigo/World Office →
archivo listo) está construido, probado y verificado de punta a punta.

## Ejemplos de uso vía API (además de la interfaz en `/app/`)

```bash
# Crear empresa y configurar sus cuentas base
curl -X POST localhost:8000/empresas -H "Content-Type: application/json" \
  -d '{"nit":"900123456","nombre":"Comercializadora XYZ SAS"}'
curl -X PATCH localhost:8000/empresas/$EMPRESA_ID/cuentas-base \
  -H "Content-Type: application/json" -d '{"cuenta_proveedores":"220501","cuenta_iva_descontable":"240802"}'

# Cargar Excel DIAN + ZIP
curl -X POST "localhost:8000/empresas/$EMPRESA_ID/documentos/cargar" \
  -F "zip=@documentos_dian.zip" -F "excel=@reporte_dian.xlsx" \
  -F "mapeo_cufe=CUFE" -F "mapeo_valor_total=Valor Total"

# Generar partida doble y contabilizar
curl -X POST "localhost:8000/empresas/$EMPRESA_ID/documentos/$FACTURA_ID/partida/generar" \
  -H "Content-Type: application/json" -d '{"cuenta_gasto_codigo":"513595","contrapartida":"proveedores"}'
curl -X POST "localhost:8000/empresas/$EMPRESA_ID/documentos/$FACTURA_ID/contabilizar"

# Exportar a Siigo/World Office
curl -X POST "localhost:8000/empresas/$EMPRESA_ID/exportaciones/generar" \
  -H "Content-Type: application/json" \
  -d '{"plantilla_id":"'$PLANTILLA_ID'","factura_ids":["'$FACTURA_ID'"]}' -o exportacion.txt
```

## Desplegarlo en internet (para usarlo desde cualquier navegador, sin instalar nada)

Este proyecto ya trae todo listo para desplegarse:

- `Dockerfile` — construye el servidor con Tesseract/Poppler incluidos (para que el OCR funcione igual que en local).
- `entrypoint.sh` — aplica las migraciones automáticamente y levanta el servidor.
- `render.yaml` — plantilla para desplegar en Render.com de forma casi automática.
- `app/core/config.py` — ya normaliza la URL de PostgreSQL que entregan Render/Heroku/Neon.

**Recomendación:** usa **Render** (servidor) + **Neon** (base de datos). Render solo
"duerme" el servidor tras 15 minutos sin uso (despierta solo en ~1 minuto al
volver a entrar) pero nunca borra tus datos. Su PostgreSQL gratuito propio,
en cambio, se borra a los 30 días si no lo pasas a un plan pago — por eso
se recomienda Neon para la base de datos, que sí es gratis de forma
permanente. La guía completa, paso a paso, está en la conversación donde
se entregó este proyecto.

**Etapa 6 — Autenticación real** (JWT + roles Administrador/Contador/
Supervisor/Consulta), reemplazando el header `X-User` actual. Es lo
único que separa este proyecto de poder usarse con datos reales de más
de una persona a la vez.
