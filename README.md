# Servicio de triage de soporte (Nivel 1)

Automatización del primer nivel de soporte: el servicio recibe consultas en texto libre, las clasifica, propone una respuesta y sugiere acciones para un agente humano, con calidad medible, costos controlados y mitigación de usos maliciosos.

## Objetivo

Construir un servicio (CLI) que recibe la consulta de un usuario y devuelve una respuesta **estructurada, segura y medida**, validada contra un contrato fijo.

### Contrato de salida (JSON / Pydantic)

| Campo        | Descripción |
|-------------|-------------|
| `answer`    | Respuesta propuesta al usuario |
| `confidence`| Confianza del modelo en la clasificación/respuesta |
| `category`  | Una de: `billing`, `technical`, `account`, `other` |
| `actions`   | Lista de acciones sugeridas para el agente humano |

Cada ejecución registra **tokens** (entrada/salida), **latencia** y **costo estimado (USD)**. El repositorio incluye un **dataset de evaluación etiquetado** y una **suite de evals** ejecutable por comando, con score global y por categoría.

## Requisitos del proyecto

- Al menos **dos proveedores LLM** configurables (p. ej. OpenAI y Gemini/Anthropic).
- **Context engineering** con prompts versionados en YAML; técnica elegida documentada y **justificada con resultados de evals**, no solo opinión.
- Salidas **estructuradas y validadas** (JSON Schema / Pydantic), con **reintentos automáticos** ante parsing inválido.
- **Guardrails**: moderación / detección de prompt injection en entrada y validación de contenido en salida.
- Abstracción **`LLMProvider`** para cambiar de proveedor sin tocar la lógica de negocio.
- Parámetros de llamada (modelo, `temperature`, límites de tokens) configurados de forma deliberada y documentados.

## Estructura del repositorio

```
.
├── README.md
├── .env.example          # Variables documentadas (sin credenciales reales)
├── .env                  # Local, no commitear
├── .gitignore
├── requirements.txt
├── src/
│   ├── main.py           # CLI de triage
│   └── llm_provider.py   # Abstracción multi-proveedor
├── prompts/
│   └── *.yaml            # Prompts versionados (zero-shot, few-shot, CoT, etc.)
├── evals/
│   ├── dataset.jsonl     # ≥30 casos etiquetados
│   └── runner.py         # Suite de evals (script, no framework de tests)
└── data/
    └── metrics.jsonl     # Log append-only por request
```

## Setup

### 1. Clonar el repositorio

```bash
git clone <url-del-repo>
cd proyectoM1L1
```

### 2. Entorno virtual

```bash
python3 -m venv .venv
source .venv/bin/activate   # macOS / Linux
```

### 3. Dependencias

```bash
pip install -r requirements.txt
```

### 4. Variables de entorno

Copiá `.env.example` a `.env` y completá las claves (nunca subas `.env` al repositorio):

```bash
cp .env.example .env
```

Documentá en `.env.example` al menos: proveedor por defecto, API keys, modelo, `temperature` y límites de tokens.

## Uso

### CLI de triage

Acepta una consulta por línea de comandos, aplica guardrails, llama al LLM configurado y devuelve JSON validado.

```bash
python -m src.main --query "No puedo ver mi última factura en la app"
```

Ejemplo de respuesta esperada:

```json
{
  "answer": "Revisá la sección Facturación en Configuración; si el cargo es reciente, puede tardar 24 h en aparecer.",
  "confidence": 0.82,
  "category": "billing",
  "actions": [
    "Verificar ID de cuenta y email de facturación",
    "Comprobar estado del pago en el portal",
    "Escalar a finanzas si el cargo no aparece tras 48 h"
  ]
}
```

Cada request válido debe generar **una línea** en `data/metrics.jsonl`, por ejemplo:

```json
{"timestamp": "2026-10-29T20:00:00Z", "category": "billing", "tokens_prompt": 420, "tokens_completion": 95, "tokens_total": 515, "latency_s": 1.23, "cost_usd": 0.0012}
```

### Suite de evaluaciones

```bash
python evals/runner.py
```

El runner debe reportar **score global** y **por categoría** (`billing`, `technical`, `account`, `other`).

## Context engineering

> Completá esta sección cuando elijas la versión de prompt definitiva y corras las evals.

| Versión (YAML) | Técnica | Notas |
|----------------|---------|--------|
| `prompts/zero_shot.yaml` | Zero-shot | Reglas de seguridad, formato JSON |
| `prompts/few_shot.yaml` | Few-shot | Ejemplos por categoría |
| `prompts/cot.yaml` | Chain-of-thought | Razonamiento antes del JSON |

**Técnica elegida para producción:** _[pendiente — justificar con tabla de resultados abajo]_

**Parámetros de la llamada (y por qué):**

| Parámetro | Valor | Motivo |
|-----------|-------|--------|
| Modelo | _[ej. gpt-4o-mini]_ | _[costo/latencia vs calidad]_ |
| Temperature | _[ej. 0.2]_ | _[menor variabilidad en JSON estructurado]_ |
| Max tokens | _[ej. 1024]_ | _[límite acorde al contrato]_ |

## Resultados de evals

> Actualizá después de ejecutar `evals/runner.py`.

| Métrica | Global | billing | technical | account | other |
|---------|--------|---------|-----------|---------|-------|
| Accuracy / score | — | — | — | — | — |
| Casos en dataset | ≥30 | — | — | — | — |

## Seguridad y guardrails

- **Entrada:** moderación y/o detección de prompt injection / jailbreak antes de enviar al LLM.
- **Salida:** validación Pydantic del contrato; rechazo o reintento si el contenido no cumple políticas.

## Roadmap de desarrollo

1. Crear repositorio en GitHub y archivos base (`README`, `requirements.txt`, `.gitignore`, `.env.example`).
2. Entorno virtual e instalación de dependencias.
3. Cliente OpenAI (y luego segundo proveedor, p. ej. Gemini).
4. Prueba con un ticket simple; dataset de tickets.
5. Contrato Pydantic `{ answer, confidence, category, actions }`.
6. Prompts en YAML (varias versiones: zero-shot, few-shot, CoT, reglas de seguridad).
7. Configurar modelo, temperature y límites de tokens.
8. Suite de evals y registro en `data/metrics.jsonl` (timestamp, texto, categoría, tokens, latencia, costo USD).
9. Documentar técnica de context engineering y resultados en este README.

## Checklist de entrega

- [ ] Al menos una ejecución de la CLI con JSON válido y una línea en `data/metrics.jsonl`.
- [ ] Suite de evals corrida; resultados reflejados en la tabla de este README.
- [ ] ≥2 versiones de prompt comparadas contra el dataset.
- [ ] ≥2 proveedores LLM configurables vía `LLMProvider`.
- [ ] Guardrails de entrada y salida implementados.
- [ ] `.env.example` y `requirements.txt` sin credenciales reales.

## Criterios de evaluación (referencia)

- **Funcionalidad:** multi-proveedor, esquema Pydantic, retry ante parsing, casos borde.
- **Evals:** dataset ≥30 casos, runner automatizado, reporte claro.
- **Prompting:** versionado, comparativa empírica, selección respaldada por datos.
- **Seguridad:** mitigación de injection; validación de salida.
- **Observabilidad:** JSONL con tokens, latencia y costo por request.
- **Código y docs:** modularidad (cliente, validación, guardrails y métricas separados), README ejecutable.

## Licencia

_[Opcional: agregar licencia del curso o del autor]_
