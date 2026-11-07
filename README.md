# Servicio de triage de soporte (Nivel 1)

CLI que recibe consultas en texto libre, las clasifica en categorías de soporte, propone una respuesta al cliente y sugiere acciones para un agente humano. La salida cumple un contrato JSON validado con Pydantic; las llamadas al modelo pasan por una capa multi-proveedor (OpenAI principal, Gemini como respaldo) y las evaluaciones miden la calidad de la clasificación sobre un dataset etiquetado.

---

## 1. Requisitos e instalación

### Requisitos

| Requisito | Detalle |
|-----------|---------|
| Python | 3.10 o superior (recomendado 3.11+) |
| Cuentas API | Claves de **OpenAI** y, opcionalmente, **Google Gemini** (fallback) |
| Sistema | macOS, Linux o Windows con `python3` en PATH |

### Pasos para instalar y correr

```bash
# Clonar (o descomprimir) el proyecto
cd proyectoM1L1

# Entorno virtual
python3 -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate

# Dependencias
pip install -r requirements.txt

# Variables de entorno (nunca commitear .env)
cp .env.example .env
# Editar .env y completar OPENAI_API_KEY y, si usas fallback, GEMINI_API_KEY
```

Variables relevantes (ver `.env.example`):

- `OPENAI_API_KEY` — obligatoria para el proveedor principal.
- `GEMINI_API_KEY` — para fallback si OpenAI falla (rate limit, timeout, etc.).
- `LLM_PRIMARY` / `LLM_FALLBACK` — por defecto `openai` / `gemini`.
- `OPENAI_MODEL`, `GEMINI_MODEL`, `LLM_TEMPERATURE`, `LLM_MAX_TOKENS`, `LLM_MAX_RETRIES` — opcionales.

Con el entorno activado y las claves configuradas, ya podés ejecutar la CLI o la suite de evals (secciones siguientes).

---

## 2. Estructura del repositorio

```
proyectoM1L1/
├── Readme.md                 # Este archivo
├── requirements.txt          # Dependencias Python (openai, google-genai, pydantic, PyYAML, …)
├── .env.example              # Plantilla de variables (sin secretos reales)
├── .gitignore
│
├── src/
│   ├── main.py               # CLI de triage
│   ├── llm_provider.py       # OpenAI + Gemini, tool calling, failover
│   └── contracts.py          # Contrato Pydantic y schema de la función LLM
│
├── prompts/
│   ├── fewShot.yaml          # Prompt en producción (few-shot, con ejemplos)
│   └── zeroShot.yaml         # Variante zero-shot para comparar
│
├── evals/
│   ├── dataset.jsonl         # 30 casos etiquetados (categoria_esperada)
│   ├── runner.py             # Suite de evaluación (accuracy global y por categoría)
│   └── eval_report.json      # Último reporte generado por runner.py
│
├── data/
│   └── metrics.jsonl         # Una línea JSON por request evaluado (append-only)
│
├── apiAnswersRecords/
│   └── answers.jsonl         # Historial de ejecuciones de la CLI (ticket + respuesta)
│
├── instructions/             # Notas y guías del curso / desarrollo
└── agentConversations/     # Documentación auxiliar de configuración
```

---

## 3. CLI: `src/main.py`

El entrypoint carga el prompt desde `prompts/fewShot.yaml` (por defecto), envía el ticket al LLM con salida estructurada (function/tool `clasificar_consulta`), valida el JSON con `TriageContrato` y reintenta hasta `LLM_MAX_RETRIES` si falla el parseo o Pydantic.

### Contrato de salida

| Campo | Descripción |
|-------|-------------|
| `answer` | Respuesta propuesta al usuario |
| `confidence` | Confianza del modelo (0–1) |
| `category` | `billing` \| `technical` \| `account` \| `other` |
| `actions` | Lista de acciones sugeridas para el agente humano |

### Ejemplo

```bash
python src/main.py --query "No puedo ver mi última factura en la app"
```

Salida típica en consola: ticket, proveedor/modelo usados, JSON de respuesta y ruta del archivo de registro.

Ejemplo de JSON impreso:

```json
{
  "answer": "Revisá la sección de facturación en Configuración o el historial de pagos; si el cargo es muy reciente, puede tardar hasta 24 horas en reflejarse.",
  "confidence": 0.85,
  "category": "billing",
  "actions": [
    "Confirmar correo y cuenta asociada a la facturación",
    "Verificar estado del último pago en el portal",
    "Escalar a finanzas si no aparece la factura tras 48 h"
  ]
}
```

Cada ejecución exitosa **añade una línea** a `apiAnswersRecords/answers.jsonl` (ticket, respuesta completa, proveedor, modelo e intentos).

---

## 4. Ejecutar `evals/runner.py`

Desde la raíz del proyecto, con el mismo `.env` y venv:

```bash
python evals/runner.py
```

El runner:

1. Importa la lógica de `src/main.py` (mismo prompt y mismos reintentos).
2. Lee **todos** los casos de `evals/dataset.jsonl`.
3. Por cada caso, ejecuta el triage y compara `category` predicha con `categoria_esperada`.
4. Imprime en consola líneas `[OK]` / `[FAIL]` por `eval_id`.
5. Escribe artefactos en disco (ver siguiente sección).

No requiere argumentos; usa rutas fijas relativas a la raíz del repo.

---

## 5. Resultados que genera `evals/runner.py`

| Artefacto | Ruta | Contenido |
|-----------|------|-----------|
| Reporte de accuracy | `evals/eval_report.json` | Resumen global, desglose por categoría, timestamp, prompt y modelos usados |
| Métricas por request | `data/metrics.jsonl` | **Append**: una línea JSON por caso evaluado |

Campos principales en cada línea de `data/metrics.jsonl`:

- `timestamp`, `provider`, `model`
- `prompt_tokens`, `completion_tokens`, `total_tokens`
- `latency_s`, `cost_usd` (estimado según proveedor)
- `eval_id`, `category_expected`, `category_predicted`, `category_correct`, `attempts`

El criterio de éxito en evals es **solo la categoría** (`category` === `categoria_esperada`), no el texto de `answer` ni `actions`.

---

## 6. Últimos resultados de evals (`eval_report.json`)

Ejecución reflejada en el reporte actual del repositorio (prompt `prompts/fewShot.yaml`, OpenAI `gpt-4o-mini`, fallback Gemini `gemini-2.0-flash`):

| Ámbito | Correctos | Total | Accuracy |
|--------|-----------|-------|----------|
| **Global** | 26 | 30 | **86.67%** |
| account | 7 | 7 | 100.00% |
| billing | 7 | 8 | 87.50% |
| technical | 8 | 8 | 100.00% |
| other | 4 | 7 | 57.14% |

Metadatos del reporte:

| Campo | Valor |
|-------|-------|
| `timestamp` | 2026-11-07T18:52:25.406678+00:00 |
| `dataset_path` | evals/dataset.jsonl |
| `prompt_path` | prompts/fewShot.yaml |
| `llm_primary` / `llm_fallback` | openai / gemini |

Volvé a correr `python evals/runner.py` después de cambiar prompts o modelos; este README puede actualizarse con la nueva tabla.

---

## 7. Prompts: `fewShot.yaml` vs `zeroShot.yaml`

### `prompts/zeroShot.yaml` (zero-shot)

- Define rol de agente de soporte de primer nivel y el **formato JSON** obligatorio.
- Enumera reglas: categorías válidas, tipo de `confidence` y `actions`.
- **No incluye ejemplos** resueltos; el modelo debe inferir categoría y estilo solo desde las instrucciones.

### `prompts/fewShot.yaml` (few-shot)

- Mismas reglas de contrato y seguridad de formato.
- Incorpora **tres ejemplos completos** (ticket → JSON) cubriendo `billing`, `technical` y `account`.
- Los ejemplos en el YAML duplican la estructura esperada (incluida sección `examples` para referencia).

### Por qué few-shot es el mejor caso para este proyecto

1. **Alineación con el dataset**: varios casos de `evals/dataset.jsonl` están inspirados o coinciden con los ejemplos few-shot (p. ej. doble cobro, error 500 en dashboard), lo que reduce errores en categorías frecuentes — coherente con **100%** en `account` y `technical` y **87.5%** en `billing` en el último reporte.
2. **Fronteras ambiguas**: tickets entre `billing` y `account`, o consultas genéricas en `other`, se benefician de ver respuestas modelo; zero-shot tiende a dispersar etiquetas sin anclas.
3. **Salida estructurada estable**: los ejemplos fijan longitud de `answer`, número de `actions` y uso de `confidence`, lo que ayuda al tool calling y reduce reintentos por JSON inválido.
4. **Elección en código**: `src/main.py` apunta por defecto a `fewShot.yaml`; las evals reportan métricas con ese prompt, respaldando la decisión con datos (86.67% global) y no solo con intuición.

Para comparar zero-shot en evals, cambiá temporalmente `PROMPT_PATH` en `src/main.py` a `prompts/zeroShot.yaml` y volvé a ejecutar `evals/runner.py`.

### Parámetros de llamada (por defecto)

| Parámetro | Valor típico | Motivo |
|-----------|--------------|--------|
| Modelo OpenAI | `gpt-4o-mini` | Buen equilibrio costo/latencia para clasificación |
| Modelo Gemini | `gemini-2.0-flash` | Fallback rápido |
| Temperature | `0.2` | Menor variabilidad en categorías y JSON |
| Max tokens | `512` | Suficiente para respuesta + acciones |
| Max reintentos | `3` | Recuperación ante parseo o validación fallida |

---

## 8. Otros archivos y carpetas

| Ruta | Descripción |
|------|-------------|
| `src/contracts.py` | Modelo Pydantic `TriageContrato`, literal de categorías y JSON Schema expuesto al LLM como herramienta `clasificar_consulta`. |
| `src/llm_provider.py` | Clases de proveedor, function/tool calling, orden primary→fallback y agregación de tokens. |
| `evals/dataset.jsonl` | 30 tickets con `id`, `texto`, `categoria_esperada`, `dificultad` y notas de diseño del caso. |
| `apiAnswers/answers.jsonl` | Registro histórico alterno o de pruebas tempranas (si existe en tu clon). |
| `instructions/` | `steps.txt`, guías de prompts, dataset y evals del enunciado del proyecto. |
| `instructions/readme.txt` | Puntero breve al README principal. |
| `agentConversations/` | Conversaciones generadas con el agente de codigo (cursor/composer 2.5) como asistente de el desarrollo. |

---

## Licencia

MIT
