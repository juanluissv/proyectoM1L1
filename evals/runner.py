"""
Evalúa el triage contra evals/dataset.jsonl y registra métricas en data/metrics.jsonl.
"""

from __future__ import annotations

import importlib.util
import json
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
PROVIDER = 'openai'


def load_triage_module():
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


def estimate_cost_usd(prompt_tokens: int, completion_tokens: int) -> float:
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
		response = triage.call_triage(system_prompt, texto)
		latency_s = time.perf_counter() - t0

		usage = response.usage
		prompt_tokens = usage.prompt_tokens if usage else 0
		completion_tokens = usage.completion_tokens if usage else 0
		total_tokens = (
			usage.total_tokens
			if usage and usage.total_tokens is not None
			else prompt_tokens + completion_tokens
		)
		model = getattr(response, 'model', None) or 'gpt-4o-mini'

		try:
			triage_result = triage.parse_tool_response(response)
			predicted = triage_result.category
		except SystemExit as err:
			print(f'[ERROR] {eval_id} fallo al parsear/validar: {err}')
			predicted = '__error__'
			triage_result = None

		is_correct = predicted == expected and triage_result is not None

		total += 1
		if is_correct:
			correct += 1
		by_cat[expected]['n'] += 1
		if is_correct:
			by_cat[expected]['ok'] += 1

		cost_usd = estimate_cost_usd(prompt_tokens, completion_tokens)
		ts = datetime.now(timezone.utc).isoformat()

		metric = {
			'timestamp': ts,
			'provider': PROVIDER,
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
		'provider': PROVIDER,
		'model': 'gpt-4o-mini',
		**accuracy,
	}
	save_report(summary)
	print_accuracy_report(summary)
	print(f'Reporte: {REPORT_PATH}')
	print(f'Métricas por request (append): {METRICS_PATH}')


if __name__ == '__main__':
	run()
