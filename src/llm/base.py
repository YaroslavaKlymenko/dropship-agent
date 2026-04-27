"""Abstract base class for LLM clients."""

from abc import ABC, abstractmethod

CLASSIFICATION_PROMPT = (
    "You are an email classifier for My-Art (my-art.com.ua), a Ukrainian handcraft store "
    "selling diamond embroidery, cross-stitch sets, paint-by-numbers, and frames. "
    "Partners are dropshippers who write primarily in Ukrainian, but also in Polish or English. "
    "Analyze the email and return ONLY valid JSON with these fields: "
    "intent, product_skus, quantity, language, confidence. "
    "Intent must be one of: reserve, stock_inquiry, price_request, order_status, individual_order, other. "
    "If no products mentioned, product_skus is []. If no quantity, quantity is null. "
    "For language, return the ISO code: 'uk' for Ukrainian, 'pl' for Polish, 'en' for English. "
    "Product SKUs look like: TN1283, AR-3221, TNG1619, IND-ZAKAZ, 2933-4030. "
    "Ukrainian keyword hints for intent detection: "
    "reserve → 'резерв', 'зарезервувати', 'забронювати', 'відкласти', 'броня'; "
    "stock_inquiry → 'наявність', 'залишок', 'скільки є', 'є у вас', 'в наявності'; "
    "price_request → 'ціна', 'вартість', 'прайс', 'скільки коштує', 'актуальна ціна'; "
    "order_status → 'статус', 'замовлення', 'де посилка', 'відправили', 'трек'; "
    "individual_order → 'індивідуальне', 'по фото', 'під замовлення', 'своє фото' "
    "(custom diamond embroidery made from a customer's own photo)."
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
                    "price_request", "order_status", "individual_order", "other"
                product_skus (list[str]): SKUs mentioned, e.g. ["WH-001"]
                quantity (int | None): quantity requested, or None
                language (str): ISO language code, e.g. "en", "uk", "pl"
                confidence (float): 0.0–1.0
        """
