"""
Proveedores LLM: OpenAI (principal) y Gemini (fallback).
"""

from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass
from typing import Any

from dotenv import load_dotenv
from google import genai
from google.genai import types as genai_types
from openai import (
	APIConnectionError,
	APITimeoutError,
	InternalServerError,
	OpenAI,
	RateLimitError,
)

from contracts import TOOL_DESCRIPTION, TOOL_NAME, TOOL_SCHEMA

load_dotenv()

OPENAI_MODEL = os.getenv('OPENAI_MODEL', 'gpt-4o-mini')
GEMINI_MODEL = os.getenv('GEMINI_MODEL', 'gemini-2.0-flash')
LLM_TEMPERATURE = float(os.getenv('LLM_TEMPERATURE', '0.2'))
LLM_MAX_TOKENS = int(os.getenv('LLM_MAX_TOKENS', '512'))
LLM_PRIMARY = os.getenv('LLM_PRIMARY', 'openai').lower()
LLM_FALLBACK = os.getenv('LLM_FALLBACK', 'gemini').lower()

OPENAI_FAILOVER_ERRORS = (
	RateLimitError,
	APIConnectionError,
	APITimeoutError,
	InternalServerError,
)


@dataclass
class TriageLLMResponse:
	provider: str
	model: str
	tool_arguments_json: str
	prompt_tokens: int
	completion_tokens: int
	total_tokens: int


def _gemini_schema(schema: dict) -> dict:
	"""Gemini prefiere schema sin metadatos extra de Pydantic."""
	clean = dict(schema)
	clean.pop('title', None)
	return clean


class OpenAITriageProvider:
	def __init__(self):
		self._client = OpenAI(api_key=os.getenv('OPENAI_API_KEY'))

	def call(self, system_prompt: str, ticket: str) -> TriageLLMResponse:
		response = self._client.chat.completions.create(
			model=OPENAI_MODEL,
			temperature=LLM_TEMPERATURE,
			max_tokens=LLM_MAX_TOKENS,
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
		message = response.choices[0].message
		if not message.tool_calls:
			raise RuntimeError(
				f'OpenAI no devolvió tool_calls: {message.content!r}',
			)
		raw_args = message.tool_calls[0].function.arguments
		usage = response.usage
		prompt_tokens = usage.prompt_tokens if usage else 0
		completion_tokens = usage.completion_tokens if usage else 0
		total_tokens = (
			usage.total_tokens
			if usage and usage.total_tokens is not None
			else prompt_tokens + completion_tokens
		)
		model = getattr(response, 'model', None) or OPENAI_MODEL
		return TriageLLMResponse(
			provider='openai',
			model=model,
			tool_arguments_json=raw_args,
			prompt_tokens=prompt_tokens,
			completion_tokens=completion_tokens,
			total_tokens=total_tokens,
		)


class GeminiTriageProvider:
	def __init__(self):
		api_key = os.getenv('GEMINI_API_KEY') or os.getenv('GOOGLE_API_KEY')
		if not api_key:
			raise RuntimeError('Falta GEMINI_API_KEY (o GOOGLE_API_KEY) en .env')
		self._client = genai.Client(api_key=api_key)

	def call(self, system_prompt: str, ticket: str) -> TriageLLMResponse:
		declaration = genai_types.FunctionDeclaration(
			name=TOOL_NAME,
			description=TOOL_DESCRIPTION,
			parameters=_gemini_schema(TOOL_SCHEMA),
		)
		config = genai_types.GenerateContentConfig(
			system_instruction=system_prompt,
			temperature=LLM_TEMPERATURE,
			max_output_tokens=LLM_MAX_TOKENS,
			tools=[genai_types.Tool(function_declarations=[declaration])],
			tool_config=genai_types.ToolConfig(
				function_calling_config=genai_types.FunctionCallingConfig(
					mode='ANY',
					allowed_function_names=[TOOL_NAME],
				),
			),
		)
		response = self._client.models.generate_content(
			model=GEMINI_MODEL,
			contents=f'Ticket: {ticket}',
			config=config,
		)
		raw_args = _extract_gemini_tool_args(response)
		meta = getattr(response, 'usage_metadata', None)
		prompt_tokens = getattr(meta, 'prompt_token_count', 0) or 0
		completion_tokens = getattr(meta, 'candidates_token_count', 0) or 0
		total_tokens = getattr(meta, 'total_token_count', 0) or (
			prompt_tokens + completion_tokens
		)
		return TriageLLMResponse(
			provider='gemini',
			model=GEMINI_MODEL,
			tool_arguments_json=raw_args,
			prompt_tokens=prompt_tokens,
			completion_tokens=completion_tokens,
			total_tokens=total_tokens,
		)


def _extract_gemini_tool_args(response: Any) -> str:
	candidates = getattr(response, 'candidates', None) or []
	for candidate in candidates:
		content = getattr(candidate, 'content', None)
		if not content:
			continue
		parts = getattr(content, 'parts', None) or []
		for part in parts:
			fc = getattr(part, 'function_call', None)
			if not fc:
				continue
			args = getattr(fc, 'args', None)
			if isinstance(args, dict):
				return json.dumps(args, ensure_ascii=False)
			if args is not None:
				return json.dumps(dict(args), ensure_ascii=False)
	raise RuntimeError('Gemini no devolvió function_call en la respuesta')


class TriageRouter:
	"""OpenAI primero; Gemini (u otro) si el principal falla (call2.py)."""

	def __init__(self):
		self._providers: dict[str, OpenAITriageProvider | GeminiTriageProvider] = {}

	def _provider(self, name: str):
		if name not in self._providers:
			if name == 'openai':
				self._providers[name] = OpenAITriageProvider()
			elif name == 'gemini':
				self._providers[name] = GeminiTriageProvider()
			else:
				raise RuntimeError(f'Proveedor desconocido: {name}')
		return self._providers[name]

	def call_triage(self, system_prompt: str, ticket: str) -> TriageLLMResponse:
		if LLM_PRIMARY not in ('openai', 'gemini'):
			raise RuntimeError(f'LLM_PRIMARY desconocido: {LLM_PRIMARY}')
		fallback_name = (
			LLM_FALLBACK
			if LLM_FALLBACK in ('openai', 'gemini')
			and LLM_FALLBACK != LLM_PRIMARY
			else None
		)
		primary = self._provider(LLM_PRIMARY)
		try:
			return primary.call(system_prompt, ticket)
		except OPENAI_FAILOVER_ERRORS as err:
			print(
				f'[{LLM_PRIMARY}] error ({type(err).__name__}): {err}',
				file=sys.stderr,
			)
			if fallback_name is None:
				raise
			print(f'Usando fallback: {fallback_name}', file=sys.stderr)
			return self._provider(fallback_name).call(system_prompt, ticket)
		except RuntimeError as err:
			if fallback_name is None:
				raise
			print(f'[{LLM_PRIMARY}] {err}', file=sys.stderr)
			print(f'Usando fallback: {fallback_name}', file=sys.stderr)
			return self._provider(fallback_name).call(system_prompt, ticket)


_router: TriageRouter | None = None


def get_router() -> TriageRouter:
	global _router
	if _router is None:
		_router = TriageRouter()
	return _router


def call_triage(system_prompt: str, ticket: str) -> TriageLLMResponse:
	return get_router().call_triage(system_prompt, ticket)
