"""Factory for creating the appropriate LLM client."""

import json
import os

from dotenv import load_dotenv

from .base import LLMClient

load_dotenv()


def get_llm_client() -> LLMClient:
    """Return an LLM client based on the LLM_PROVIDER environment variable.

    Returns:
        GroqLLMClient if LLM_PROVIDER=groq, GeminiLLMClient if LLM_PROVIDER=gemini.

    Raises:
        ValueError: If LLM_PROVIDER is missing or unsupported.
    """
    provider = os.getenv("LLM_PROVIDER", "").strip().lower()

    if provider == "groq":
        from .groq_client import GroqLLMClient
        return GroqLLMClient()
    elif provider == "gemini":
        from .gemini_client import GeminiLLMClient
        return GeminiLLMClient()
    else:
        raise ValueError(
            f"Unsupported or missing LLM_PROVIDER: {repr(provider)}. "
            "Set LLM_PROVIDER to 'groq' or 'gemini' in your .env file."
        )


if __name__ == "__main__":
    provider = os.getenv("LLM_PROVIDER", "").strip().lower()
    print(f"Using LLM provider: {provider}")

    client = get_llm_client()

    result = client.classify_email(
        subject="Reservation request",
        body=(
            "Hi, could you reserve 10 units of WH-001 for our next "
            "shipment? Best regards, John from Retail Shop UK"
        ),
    )

    print(json.dumps(result, indent=2))
