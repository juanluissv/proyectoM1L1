"""
Evalúa el triage contra evals/dataset.jsonl y registra métricas en data/metrics.jsonl.
"""

from __future__ import annotations

import importlib.util
import json
import os
import sys
import time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATASET_PATH = ROOT / 'evals' / 'dataset.jsonl'
METRICS_PATH = ROOT / 'data' / 'metrics.jsonl'
REPORT_PATH = ROOT / 'evals' / 'eval_report.json'
MAIN_PATH = ROOT / 'src' / 'main.py'

CATEGORIES = ('account', 'billing', 'other', 'technical')


# Precios gpt-4o-mini (USD por token) — mismo criterio que registroTokens.py
PRICE_PROMPT_PER_TOKEN = 0.15 / 1_000_000
PRICE_COMPLETION_PER_TOKEN = 0.60 / 1_000_000
def load_triage_module():
	src_dir = str(ROOT / 'src')
	if src_dir not in sys.path:
		sys.path.insert(0, src_dir)
	spec = importlib.util.spec_from_file_location('triage_main', MAIN_PATH)
	if spec is None or spec.loader is None:
		raise RuntimeError(f'No se pudo cargar {MAIN_PATH}')
	mod = importlib.util.module_from_spec(spec)
	sys.modules['triage_main'] = mod
	spec.loader.exec_module(mod)
	return mod


def load_dataset():
	cases = []
	with DATASET_PATH.open(encoding='utf-8') as f:
		for line_num, line in enumerate(f, start=1):
			line = line.strip()
			if not line:
				continue
			try:
				cases.append(json.loads(line))
			except json.JSONDecodeError as err:
				raise ValueError(
					f'dataset.jsonl línea {line_num}: JSON inválido: {err}',
				) from err
	return cases


GEMINI_PRICE_PROMPT = 0.10 / 1_000_000
GEMINI_PRICE_COMPLETION = 0.40 / 1_000_000


def estimate_cost_usd(
	provider: str,
	prompt_tokens: int,
	completion_tokens: int,
) -> float:
	if provider == 'gemini':
		return (
			prompt_tokens * GEMINI_PRICE_PROMPT
			+ completion_tokens * GEMINI_PRICE_COMPLETION
		)
	return (
		prompt_tokens * PRICE_PROMPT_PER_TOKEN
		+ completion_tokens * PRICE_COMPLETION_PER_TOKEN
	)


def append_metric(record: dict) -> None:
	METRICS_PATH.parent.mkdir(parents=True, exist_ok=True)
	with METRICS_PATH.open('a', encoding='utf-8') as f:
		f.write(json.dumps(record, ensure_ascii=False) + '\n')


def build_accuracy_report(
	correct: int,
	total: int,
	by_cat: dict,
) -> dict:
	acc_global = correct / total if total else 0.0
	by_category = {}
	for cat in CATEGORIES:
		stats = by_cat.get(cat, {'n': 0, 'ok': 0})
		n = stats['n']
		ok = stats['ok']
		by_category[cat] = {
			'correct': ok,
			'total': n,
			'accuracy': round(ok / n, 4) if n else 0.0,
		}
	return {
		'accuracy_global': {
			'correct': correct,
			'total': total,
			'accuracy': round(acc_global, 4),
		},
		'by_category': by_category,
	}


def save_report(report: dict) -> None:
	REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
	with REPORT_PATH.open('w', encoding='utf-8') as f:
		json.dump(report, f, ensure_ascii=False, indent=2)
		f.write('\n')


def print_accuracy_report(report: dict) -> None:
	g = report['accuracy_global']
	print()
	print('=== Eval report (dataset.jsonl) ===')
	print(
		f"Accuracy global: {g['correct']}/{g['total']} "
		f"= {g['accuracy']:.2%}",
	)
	print('Por categoría:')
	for cat in CATEGORIES:
		c = report['by_category'][cat]
		print(
			f"  {cat}: {c['correct']}/{c['total']} "
			f"= {c['accuracy']:.2%}",
		)


def run() -> None:
	triage = load_triage_module()
	system_prompt = triage.load_system_prompt()

	cases = load_dataset()
	if not cases:
		print('No hay casos en', DATASET_PATH)
		return

	total = 0
	correct = 0
	by_cat = defaultdict(lambda: {'n': 0, 'ok': 0})

	for caso in cases:
		eval_id = caso.get('id', '')
		texto = caso['texto']
		expected = caso['categoria_esperada']

		t0 = time.perf_counter()
		try:
			triage_result, response, attempts = triage.run_triage_with_retries(
				system_prompt,
				texto,
			)
			predicted = triage_result.category
		except SystemExit as err:
			print(f'[ERROR] {eval_id} fallo tras reintentos: {err}')
			predicted = '__error__'
			triage_result = None
			response = None
			attempts = 0
		latency_s = time.perf_counter() - t0

		if response is None:
			prompt_tokens = completion_tokens = total_tokens = 0
			provider = 'unknown'
			model = 'unknown'
		else:
			prompt_tokens = response.prompt_tokens
			completion_tokens = response.completion_tokens
			total_tokens = response.total_tokens
			provider = response.provider
			model = response.model

		is_correct = predicted == expected and triage_result is not None

		total += 1
		if is_correct:
			correct += 1
		by_cat[expected]['n'] += 1
		if is_correct:
			by_cat[expected]['ok'] += 1

		cost_usd = estimate_cost_usd(provider, prompt_tokens, completion_tokens)
		ts = datetime.now(timezone.utc).isoformat()

		metric = {
			'timestamp': ts,
			'provider': provider,
			'model': model,
			'prompt_tokens': prompt_tokens,
			'completion_tokens': completion_tokens,
			'total_tokens': total_tokens,
			'latency_s': round(latency_s, 6),
			'cost_usd': round(cost_usd, 8),
			# contexto del eval (útil para auditar sin romper los campos pedidos)
			'eval_id': eval_id,
			'category_expected': expected,
			'category_predicted': predicted,
			'category_correct': is_correct,
			'attempts': attempts,
		}
		append_metric(metric)
		status = 'OK' if is_correct else 'FAIL'
		print(f'[{status}] {eval_id} esperado={expected} obtenido={predicted}')

	accuracy = build_accuracy_report(correct, total, by_cat)
	summary = {
		'timestamp': datetime.now(timezone.utc).isoformat(),
		'dataset_path': str(DATASET_PATH.relative_to(ROOT)),
		'prompt_path': str(
			getattr(triage, 'PROMPT_PATH', ROOT / 'prompts' / 'fewShot.yaml')
			.relative_to(ROOT),
		),
		'llm_primary': os.getenv('LLM_PRIMARY', 'openai'),
		'llm_fallback': os.getenv('LLM_FALLBACK', 'gemini'),
		'model_openai': getattr(triage, 'OPENAI_MODEL', 'gpt-4o-mini'),
		'model_gemini': getattr(triage, 'GEMINI_MODEL', 'gemini-2.0-flash'),
		**accuracy,
	}
	save_report(summary)
	print_accuracy_report(summary)
	print(f'Reporte: {REPORT_PATH}')
	print(f'Métricas por request (append): {METRICS_PATH}')


if __name__ == '__main__':
	run()
