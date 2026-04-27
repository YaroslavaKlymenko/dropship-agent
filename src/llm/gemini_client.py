"""Google Gemini LLM client implementation."""

import json
import os

from dotenv import load_dotenv

from .base import CLASSIFICATION_PROMPT, LLMClient, format_email_for_prompt

load_dotenv()

_MODEL = "gemini-2.0-flash"
_FALLBACK = {"intent": "other", "product_skus": [], "quantity": None, "language": "en", "confidence": 0.0}


class GeminiLLMClient(LLMClient):
    """LLM client backed by Google Gemini 2.0 Flash."""

    def __init__(self) -> None:
        from google import genai
        from google.genai import types

        api_key = os.getenv("GEMINI_API_KEY")
        self._client = genai.Client(api_key=api_key)
        self._types = types

    def classify_email(self, subject: str, body: str) -> dict:
        """Classify an email using Google Gemini.

        Args:
            subject: Email subject line.
            body: Email body text.

        Returns:
            Classification dict (see LLMClient.classify_email).
        """
        prompt = format_email_for_prompt(subject, body)
        try:
            response = self._client.models.generate_content(
                model=_MODEL,
                contents=f"{CLASSIFICATION_PROMPT}\n\n{prompt}",
                config=self._types.GenerateContentConfig(
                    response_mime_type="application/json",
                    temperature=0.1,
                ),
            )
            return json.loads(response.text)
        except json.JSONDecodeError as e:
            print(f"[GeminiLLMClient] JSON parse error: {e}")
            return _FALLBACK.copy()
        except Exception as e:
            print(f"[GeminiLLMClient] Error: {e}")
            return _FALLBACK.copy()
