from typing import Literal

from pydantic import BaseModel, Field

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
