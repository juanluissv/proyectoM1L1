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
DATASET_PATH = ROOT / 'evals' / 'dataset.jsonl'
ANSWERS_PATH = ROOT / 'evals' / 'answers.jsonl'

with PROMPT_PATH.open(encoding='utf-8') as prompt_file:
	prompt_data = yaml.safe_load(prompt_file)

SYSTEM_PROMPT = prompt_data['system_prompt'].strip()

tickets = []
with DATASET_PATH.open(encoding='utf-8') as dataset_file:
	for line in dataset_file:
		line = line.strip()
		if not line:
			continue
		tickets.append(json.loads(line)['ticket'])

print('================== tickets del dataset ==================')

answer_records = []

for ticket in tickets:
	response = client.chat.completions.create(
		model='gpt-4o-mini',
		messages=[
			{'role': 'system', 'content': SYSTEM_PROMPT},
			{'role': 'user', 'content': f'Ticket: {ticket}'},
		],
		response_format={'type': 'json_object'},
	)

	raw_content = response.choices[0].message.content
	parsed_answer = json.loads(raw_content)

	answer_records.append({
		'ticket': ticket,
		'answer': parsed_answer,
	})

	print('ticket:', ticket)
	print('respuesta:', raw_content)
	print()

with ANSWERS_PATH.open('w', encoding='utf-8') as answers_file:
	for record in answer_records:
		answers_file.write(json.dumps(record, ensure_ascii=False) + '\n')

print(f'Guardadas {len(answer_records)} respuestas en {ANSWERS_PATH}')
