import argparse
import json
import os
from pathlib import Path

import yaml
from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()

client = OpenAI(api_key=os.getenv('OPENAI_API_KEY'))

ROOT = Path(__file__).resolve().parent.parent
PROMPT_PATH = ROOT / 'prompts' / 'prompt1.yaml'
ANSWERS_PATH = ROOT / 'apiAnswersRecords' / 'answers.jsonl'


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


def main():
	args = parse_args()
	ticket = args.query.strip()
	if not ticket:
		raise SystemExit('Error: --query no puede estar vacío.')

	system_prompt = load_system_prompt()

	response = client.chat.completions.create(
		model='gpt-4o-mini',
		messages=[
			{'role': 'system', 'content': system_prompt},
			{'role': 'user', 'content': f'Ticket: {ticket}'},
		],
		response_format={'type': 'json_object'},
	)

	raw_content = response.choices[0].message.content
	parsed_answer = json.loads(raw_content)

	record = {'ticket': ticket, 'answer': parsed_answer}

	print('ticket:', ticket)
	print('respuesta:', raw_content)

	ANSWERS_PATH.parent.mkdir(parents=True, exist_ok=True)
	with ANSWERS_PATH.open('a', encoding='utf-8') as answers_file:
		answers_file.write(json.dumps(record, ensure_ascii=False) + '\n')

	print(f'Respuesta guardada en {ANSWERS_PATH}')


if __name__ == '__main__':
	main()
