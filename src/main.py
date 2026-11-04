import argparse
import json
from pathlib import Path
from typing import Literal
import os
import yaml
from dotenv import load_dotenv
from openai import OpenAI
from pydantic import BaseModel, Field, ValidationError

load_dotenv()

client = OpenAI(api_key=os.getenv('OPENAI_API_KEY'))

ROOT = Path(__file__).resolve().parent.parent
PROMPT_PATH = ROOT / 'prompts' / 'fewShot.yaml'
ANSWERS_PATH = ROOT / 'apiAnswersRecords' / 'answers.jsonl'


TOOL_NAME = 'clasificar_consulta'
TOOL_DESCRIPTION = (
	'Clasifica el ticket de soporte y devuelve respuesta, confianza, '
	'categoría y acciones sugeridas para el agente humano.'
)
CategoriaValida = Literal['billing', 'technical', 'account', 'other']

class TriageContrato(BaseModel):
	answer: str = Field(min_length=1)
	confidence: float = Field(ge=0.0, le=1.0)
	category: CategoriaValida
	actions: list[str] = Field(min_length=1)

TOOL_SCHEMA = TriageContrato.model_json_schema()


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


def call_triage(system_prompt: str, ticket: str):
	return client.chat.completions.create(
		model='gpt-4o-mini',
		messages=[
			{'role': 'system', 'content': system_prompt},
			{'role': 'user', 'content': f'Ticket: {ticket}'},
		],
		tools=[{
			'type': 'function',
			'function': {
				'name': TOOL_NAME,
				'description': TOOL_DESCRIPTION,
				'parameters': TOOL_SCHEMA,
			},
		}],
		tool_choice={
			'type': 'function',
			'function': {'name': TOOL_NAME},
		},
	)


def parse_tool_response(response) -> TriageContrato:
	message = response.choices[0].message
	if not message.tool_calls:
		raise SystemExit(
			'Error: el modelo no devolvió tool_calls. '
			f'Contenido: {message.content!r}',
		)

	raw_args = message.tool_calls[0].function.arguments
	try:
		args_dict = json.loads(raw_args)
	except json.JSONDecodeError as err:
		raise SystemExit(f'Error: JSON inválido en tool arguments: {err}') from err

	try:
		return TriageContrato.model_validate(args_dict)
	except ValidationError as err:
		raise SystemExit(f'Error: no cumple el contrato Pydantic:\n{err}') from err


def main():
	args = parse_args()
	ticket = args.query.strip()
	if not ticket:
		raise SystemExit('Error: --query no puede estar vacío.')

	system_prompt = load_system_prompt()
	response = call_triage(system_prompt, ticket)
	triage = parse_tool_response(response)

	record = {'ticket': ticket, 'answer': triage.model_dump()}
	output_json = json.dumps(triage.model_dump(), ensure_ascii=False)

	print('ticket:', ticket)
	print('respuesta:', output_json)

	ANSWERS_PATH.parent.mkdir(parents=True, exist_ok=True)
	with ANSWERS_PATH.open('a', encoding='utf-8') as answers_file:
		answers_file.write(json.dumps(record, ensure_ascii=False) + '\n')

	print(f'Respuesta guardada en {ANSWERS_PATH}')


if __name__ == '__main__':
	main()
