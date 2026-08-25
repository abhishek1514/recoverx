"""Optional OpenAI Responses API client for non-authoritative case explanations."""

from __future__ import annotations

import json
from typing import Any

from app.ai.prompts import SYSTEM_PROMPT
from app.ai.schemas import AIExplanation
from app.core.config import Settings, get_settings


class AIUnavailableError(RuntimeError):
    """Raised when AI cannot be used; callers must retain deterministic results."""


class OpenAIExplanationClient:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()

    def generate(self, context: dict[str, Any]) -> AIExplanation:
        if not self.settings.openai_api_key or not self.settings.openai_model:
            raise AIUnavailableError("OpenAI configuration is unavailable")
        try:
            from openai import OpenAI

            client = OpenAI(api_key=self.settings.openai_api_key)
            response = client.responses.create(
                model=self.settings.openai_model,
                instructions=SYSTEM_PROMPT,
                input=json.dumps(context, separators=(",", ":")),
                text={"format": {"type": "json_schema", "name": "recoverx_case_explanation", "schema": AIExplanation.model_json_schema(), "strict": True}},
                max_output_tokens=600,
                store=False,
            )
            return AIExplanation.model_validate_json(response.output_text)
        except AIUnavailableError:
            raise
        except Exception as exc:
            raise AIUnavailableError("OpenAI explanation request failed") from exc
