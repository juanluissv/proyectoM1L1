import argparse
import json
import os
import sys
from pathlib import Path

_SRC = Path(__file__).resolve().parent
if str(_SRC) not in sys.path:
	sys.path.insert(0, str(_SRC))

import yaml
from dotenv import load_dotenv
from pydantic import ValidationError

from contracts import TriageContrato
from llm_provider import (
	GEMINI_MODEL,
	OPENAI_MODEL,
	TriageLLMResponse,
	call_triage,
)

load_dotenv()

ROOT = Path(__file__).resolve().parent.parent
PROMPT_PATH = ROOT / 'prompts' / 'fewShot.yaml'
ANSWERS_PATH = ROOT / 'apiAnswersRecords' / 'answers.jsonl'

LLM_MAX_RETRIES = int(os.getenv('LLM_MAX_RETRIES', '3'))


class TriageParseError(Exception):
	"""JSON o contrato Pydantic inválido en la respuesta del modelo."""


def parse_args():
	parser = argparse.ArgumentParser(
		description='Triage de ticket de soporte (consulta en texto libre)',
	)
	parser.add_argument(
		'--query',
		required=True,
		help='Consulta del usuario, ej: "Me cobraron dos veces la suscripción"',
	)
	return parser.parse_args()


def load_system_prompt():
	with PROMPT_PATH.open(encoding='utf-8') as prompt_file:
		prompt_data = yaml.safe_load(prompt_file)
	return prompt_data['system_prompt'].strip()


def parse_tool_response(response: TriageLLMResponse) -> TriageContrato:
	try:
		args_dict = json.loads(response.tool_arguments_json)
	except json.JSONDecodeError as err:
		raise TriageParseError(
			f'JSON inválido en tool arguments: {err}',
		) from err
	try:
		return TriageContrato.model_validate(args_dict)
	except ValidationError as err:
		raise TriageParseError(
			f'No cumple el contrato Pydantic:\n{err}',
		) from err


def run_triage_with_retries(
	system_prompt: str,
	ticket: str,
	max_retries: int | None = None,
) -> tuple[TriageContrato, TriageLLMResponse, int]:
	"""
	Llama al LLM y valida la salida; reintenta hasta max_retries ante parse/Pydantic.
	"""
	limit = max_retries if max_retries is not None else LLM_MAX_RETRIES
	last_error: TriageParseError | None = None
	last_response: TriageLLMResponse | None = None
	prompt_sum = 0
	completion_sum = 0
	total_sum = 0

	for attempt in range(1, limit + 1):
		response = call_triage(system_prompt, ticket)
		last_response = response
		prompt_sum += response.prompt_tokens
		completion_sum += response.completion_tokens
		total_sum += response.total_tokens
		try:
			triage = parse_tool_response(response)
			aggregated = TriageLLMResponse(
				provider=response.provider,
				model=response.model,
				tool_arguments_json=response.tool_arguments_json,
				prompt_tokens=prompt_sum,
				completion_tokens=completion_sum,
				total_tokens=total_sum,
			)
			if attempt > 1:
				print(
					f'Validación OK en intento {attempt}/{limit}',
					file=sys.stderr,
				)
			return triage, aggregated, attempt
		except TriageParseError as err:
			last_error = err
			print(
				f'Intento {attempt}/{limit} falló validación: {err}',
				file=sys.stderr,
			)

	msg = last_error or 'Error desconocido de validación'
	detail = ''
	if last_response is not None:
		detail = (
			f'\nÚltimo proveedor: {last_response.provider}, '
			f'args: {last_response.tool_arguments_json[:200]}...'
		)
	raise SystemExit(
		f'Error: agotados {limit} reintentos. {msg}{detail}',
	) from last_error


def main():
	args = parse_args()
	ticket = args.query.strip()
	if not ticket:
		raise SystemExit('Error: --query no puede estar vacío.')

	system_prompt = load_system_prompt()
	triage, response, attempts = run_triage_with_retries(system_prompt, ticket)

	record = {
		'ticket': ticket,
		'answer': triage.model_dump(),
		'provider': response.provider,
		'model': response.model,
		'attempts': attempts,
	}
	output_json = json.dumps(triage.model_dump(), ensure_ascii=False)

	print('ticket:', ticket)
	print('proveedor:', response.provider, '| modelo:', response.model)
	if attempts > 1:
		print('intentos:', attempts)
	print('respuesta:', output_json)

	ANSWERS_PATH.parent.mkdir(parents=True, exist_ok=True)
	with ANSWERS_PATH.open('a', encoding='utf-8') as answers_file:
		answers_file.write(json.dumps(record, ensure_ascii=False) + '\n')

	print(f'Respuesta guardada en {ANSWERS_PATH}')


__all__ = [
	'OPENAI_MODEL',
	'GEMINI_MODEL',
	'PROMPT_PATH',
	'LLM_MAX_RETRIES',
	'TriageParseError',
	'call_triage',
	'load_system_prompt',
	'parse_tool_response',
	'run_triage_with_retries',
]


if __name__ == '__main__':
	main()
