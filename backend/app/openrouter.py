import os
from typing import Any

from pydantic import BaseModel

OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
OPENROUTER_MODEL = "google/gemini-2.5-flash"


def openrouter_api_key() -> str | None:
    """Return only the hackathon provider credential; never fall back to OpenAI."""
    return os.getenv("OPENROUTER_API_KEY")


def structured_response_format(schema: type[BaseModel]) -> dict[str, Any]:
    return {
        "type": "json_schema",
        "json_schema": {
            "name": schema.__name__.lower(),
            "strict": True,
            "schema": schema.model_json_schema(),
        },
    }


OPENROUTER_STRUCTURED_PROVIDER = {"provider": {"require_parameters": True}}
