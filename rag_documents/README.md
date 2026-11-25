# rag_documents/: corpus del RAG

Este README **no se indexa** (el cargador ignora `README.md`). Describe qué hay, quién lo puede consultar y qué falta.
Tipos de archivo que se indexan: `.pdf` (PyMuPDF, con OCR en páginas escaneadas), `.md`, `.txt` y `.csv` (como texto).

## Documentos y audiencia

La **audiencia** decide quién recupera cada documento: el cliente solo ve los `publico`; el colaborador ve todos.
Se define en `src/rag_store.py` (`DOCS_PUBLICOS`); cualquier archivo nuevo es `interno` hasta que se agregue ahí.

| Archivo                                                                               | Contenido                                                                                                                                 | Tipo                         | Idioma  | Audiencia |
| ------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------- | ------- | --------- |
| `aviso_privacidad_banamex.md`                                                         | Aviso de privacidad integral para clientes de Banamex                                                                                     | Oficial (texto copiado)      | Español | publico   |
| `LFPDPPP.pdf`                                                                         | Ley Federal de Protección de Datos Personales en Posesión de los Particulares, **nueva ley 2025** (últ. reforma DOF 14-11-2025), 24 págs. | Oficial                      | Español | publico   |
| `LIC.pdf`                                                                             | Ley de Instituciones de Crédito (secreto bancario, art. 142; identificación, art. 115), 321 págs.                                         | Oficial                      | Español | publico   |
| `banamex_contexto_publico.md`                                                         | Contexto público de Banamex (separación de Citi, 2026)                                                                                    | Síntesis de fuentes públicas | Español | publico   |
| `glosario_gobierno_datos.md`                                                          | Definiciones de gobierno de datos                                                                                                         | Equipo                       | Español | publico   |
| `politica_calidad_datos_sintetica.md`                                                 | Política interna de calidad: clasificación, roles, reglas **DQ-01 a DQ-11**, remediación                                                  | **Sintético (equipo)**       | Español | interno   |
| `catalogo_datos_sintetico.csv`                                                        | Catálogo por columna: clasificación, Data Owner, Steward, retención y regla DQ                                                            | **Sintético (equipo)**       | Español | interno   |
| `marco_regulatorio_datos_bancarios_mx.md`                                             | LIC, Código de Comercio, LFPDPPP, CNBV/CUB aplicados a datos                                                                              | Síntesis de fuentes públicas | Español | interno   |
| `trazabilidad_politica_vs_marco_regulatorio.md`                                       | Qué artículo respalda cada punto de la política                                                                                           | Equipo                       | Español | interno   |
| `bcbs239_principios_resumen.md`                                                       | Resumen de los 14 principios BCBS 239                                                                                                     | Síntesis                     | Español | interno   |
| `201301-guidelines-principles-effective-risk-data-aggregation-and-risk-reporting.pdf` | **BCBS 239 original** (Comité de Basilea, 2013), 28 págs.                                                                                 | Oficial                      | Inglés  | interno   |
| `The Government Data Quality Framework - GOV.UK.pdf`                                  | Marco de calidad de datos del gobierno británico                                                                                          | Oficial                      | Inglés  | interno   |
| `The Government Data Quality Framework_ guidance - GOV.UK.pdf`                        | Guía de aplicación del marco anterior (complementa, no duplica)                                                                           | Oficial                      | Inglés  | interno   |
| `onsdataqualitypolicy.pdf`                                                            | Política de calidad de datos de la ONS (Reino Unido)                                                                                      | Oficial                      | Inglés  | interno   |

Consistencia verificada:

- Las reglas DQ del catálogo y de la política usan la **misma numeración** que las reglas que ejecuta el sistema (`run_governance_checks`).
- La LFPDPPP es la ley de 2025: sus artículos **no** coinciden con la ley de 2010 (p. ej. consentimiento = art. 7, ARCO = art. 21, transferencias = art. 36).
- Los documentos en inglés funcionan con preguntas en español porque los embeddings (bge-m3) son multilingües.

## Lo que falta (recomendado para el flujo de clientes)

Banamex no publica su política interna de gobierno de datos, por eso la política y el catálogo son **sintéticos** y lo dicen.
Para que los clientes puedan comparar sus contratos contra información oficial, conviene agregar:

1. **Contratos de adhesión de Banamex** (tarjeta de crédito, crédito personal) del **RECA de Condusef**.
2. Comisiones, CAT y penalizaciones publicadas por Banamex.
3. Reglas de Banxico sobre tarjetas de crédito (pago mínimo).
4. **Circular Única de Bancos** (CNBV), artículos de control interno y seguridad de la información.

Al agregar un archivo: si debe verlo el cliente, añádelo a `DOCS_PUBLICOS` en `src/rag_store.py`; luego re-indexa.

## Cómo re-indexar

```powershell
.\run.ps1 ingest        # equivale a: python src/ingest_governance.py --reset
```

La LIC (321 págs.) es ~75% del corpus: la primera indexación con bge-m3 tarda de 5 a 15 minutos.
