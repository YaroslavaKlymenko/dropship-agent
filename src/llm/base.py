"""Abstract base class for LLM clients."""

from abc import ABC, abstractmethod

CLASSIFICATION_PROMPT = (
    "You are an email classifier for a dropshipping business operating in Ukraine. "
    "Emails may be in Ukrainian, Polish, or English. "
    "Analyze the email and return ONLY valid JSON with these fields: "
    "intent, product_skus, quantity, language, confidence. "
    "Intent must be one of: reserve, stock_inquiry, price_request, order_status, other. "
    "If no products mentioned, product_skus is []. If no quantity, quantity is null. "
    "For language, return the ISO code: 'uk' for Ukrainian, 'pl' for Polish, 'en' for English. "
    "Ukrainian keyword hints for intent detection: "
    "reserve → 'резерв', 'зарезервувати', 'забронювати'; "
    "stock_inquiry → 'наявність', 'залишок', 'є в наявності'; "
    "price_request → 'ціна', 'прайс', 'вартість'; "
    "order_status → 'статус', 'замовлення', 'де моє'."
)


def format_email_for_prompt(subject: str, body: str) -> str:
    """Format subject and body into a single string for LLM input."""
    return f"Subject: {subject}\n\nBody:\n{body}"


class LLMClient(ABC):
    """Abstract base class for LLM provider clients."""

    @abstractmethod
    def classify_email(self, subject: str, body: str) -> dict:
        """Classify an email and return structured intent data.

        Args:
            subject: Email subject line.
            body: Email body text.

        Returns:
            dict with keys:
                intent (str): one of "reserve", "stock_inquiry",
                    "price_request", "order_status", "other"
                product_skus (list[str]): SKUs mentioned, e.g. ["WH-001"]
                quantity (int | None): quantity requested, or None
                language (str): ISO language code, e.g. "en", "uk", "pl"
                confidence (float): 0.0–1.0
        """
