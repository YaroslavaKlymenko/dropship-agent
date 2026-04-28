"""Groq LLM client implementation."""

import json
import os

from dotenv import load_dotenv
from groq import Groq

from .base import CLASSIFICATION_PROMPT, LLMClient, format_email_for_prompt

load_dotenv()

_MODEL = "llama-3.3-70b-versatile"
_FALLBACK = {"intent": "other", "product_skus": [], "quantity": None, "language": "en", "confidence": 0.0}


class GroqLLMClient(LLMClient):
    """LLM client backed by Groq (Llama 3.3 70B)."""

    def __init__(self) -> None:
        api_key = os.getenv("GROQ_API_KEY")
        self._client = Groq(api_key=api_key)

    def classify_email(self, subject: str, body: str) -> dict:
        """Classify an email using Groq's Llama model.

        Args:
            subject: Email subject line.
            body: Email body text.

        Returns:
            Classification dict (see LLMClient.classify_email).
        """
        prompt = format_email_for_prompt(subject, body)
        try:
            response = self._client.chat.completions.create(
                model=_MODEL,
                messages=[
                    {"role": "system", "content": CLASSIFICATION_PROMPT},
                    {"role": "user", "content": prompt},
                ],
                response_format={"type": "json_object"},
                temperature=0.1,
            )
            return json.loads(response.choices[0].message.content)
        except json.JSONDecodeError as e:
            print(f"[GroqLLMClient] JSON parse error: {e}")
            return _FALLBACK.copy()
        except Exception as e:
            print(f"[GroqLLMClient] Error: {e}")
            return _FALLBACK.copy()

    def generate_text(self, system_prompt: str, user_message: str) -> str:
        """Generate free-form text using Groq's Llama model.

        Args:
            system_prompt: Instructions / role description for the model.
            user_message: The actual task or context.

        Returns:
            Generated text string, or empty string on failure.
        """
        try:
            response = self._client.chat.completions.create(
                model=_MODEL,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_message},
                ],
                temperature=0.4,
            )
            return response.choices[0].message.content or ""
        except Exception as e:
            print(f"[GroqLLMClient.generate_text] Error: {e}")
            return ""
