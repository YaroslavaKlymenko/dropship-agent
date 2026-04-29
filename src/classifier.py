"""Business logic layer: classify incoming emails and execute intent handlers."""

import json

from src import db
from src import gmail_client as gmail
from src import sheets_client
from src.llm.base import LLMClient

_RESPONSE_SYSTEM_PROMPT = """\
Ти — менеджер інтернет-магазину My-Art (my-art.com.ua), що продає товари для творчості \
(алмазна мозаїка, вишивка тощо). Пишеш відповіді партнерам-гуртовикам у невимушеному, \
але діловому стилі — як жива людина, а не бот.

ВІТАННЯ — СУВОРІ ПРАВИЛА:
Перевір поле "email_body" у наданих даних. Знайди підпис у кінці листа.

Правило 1 — є особисте ім'я (українське або слов'янське: Олена, Марія, Петро, Іван, \
Ірина, Наталя, Оксана, Андрій, Юлія тощо):
→ використай його у кличному відмінку: "Доброго дня, Олено!" / "Доброго дня, Петре!"
Таблиця кличного відмінку: Олена→Олено, Марія→Маріє, Ірина→Ірино, Наталя→Наталю, \
Оксана→Оксано, Юлія→Юліє, Петро→Петре, Іван→Іване, Андрій→Андрію, Олег→Олеже.

Правило 2 — підпис містить ЛИШЕ назву компанії (Crafts Shop, HobbyLand, ArtShop, \
"команда Все Так", "магазин X" тощо) або підпису немає взагалі:
→ використай: "Доброго дня!" — БЕЗ будь-якого імені чи назви компанії.

ЗАБОРОНЕНО: "Доброго дня, Crafts Shop!", "Доброго дня, Все Так!", \
"Доброго дня, [Ім'я]!" якщо це назва компанії, а не особисте ім'я.

Приклади:
• "Дякую, Олена з Все Так" → "Доброго дня, Олено!"
• "З повагою, команда Все Так" → "Доброго дня!"
• Лист без підпису, тільки питання → "Доброго дня!"
• "Дякую, Петро" → "Доброго дня, Петре!"

СТИЛЬ:
- Розмовний тон, без маркованих списків і технічних міток ("Назва:", "Артикул:", "Ціна:").
- Інформацію про товари вплітай у звичайні речення.
- Один короткий абзац на тему, не більше.
- Ціни форматуй як "850 грн" (без десяткових нулів: 850, а не 850.0).
- Варіюй фразування наявності: "є в наявності", "є на складі", "доступний".
- Варіюй прощання: "Гарного дня!", "Чекаємо на замовлення!", "Якщо є питання — пишіть!"
- Підпис варіюй: "Команда My-Art" або "З повагою, My-Art" — чергуй.
- Відповідай ТІЛЬКИ тілом листа — без теми, без зайвих коментарів.

НАЯВНІСТЬ (stock_inquiry):
- Є в наявності: "Так, [назва] (арт. [SKU]) є в наявності — зараз [N] штук на складі. \
Вартість [ціна] грн."
- Немає в базі: "На жаль, артикул [SKU] зараз відсутній у нашому каталозі — \
можливо, мали на увазі інший?"
- available_qty == 0: "На жаль, [назва] наразі немає в наявності — очікуємо поповнення."

РЕЗЕРВУВАННЯ (reserve):
- Підтвердження: "Зарезервували для вас [назва] — [N] штук. \
Чекаємо підтвердження протягом 48 годин."
- Нестача: "На жаль, [назва] є лише [M] штук, а не [N] — уточніть, чи підходить така кількість."
"""


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def generate_response_text(prompt: str, context: dict, llm: LLMClient) -> str:
    """Generate a Ukrainian email body via the LLM.

    Args:
        prompt: Task description, e.g. "Generate stock availability response".
        context: Data dict to embed in the user message (products, quantities, …).
        llm: LLM client instance.

    Returns:
        Plain-text email body signed by 'команда My-Art'.
    """
    context_str = json.dumps(context, ensure_ascii=False, indent=2)
    user_message = f"{prompt}\n\nДані:\n{context_str}"
    return llm.generate_text(_RESPONSE_SYSTEM_PROMPT, user_message)


# ---------------------------------------------------------------------------
# Intent handlers
# ---------------------------------------------------------------------------

def handle_stock_inquiry(email_record: dict, classification: dict, llm: LLMClient) -> dict:
    """Handle stock_inquiry intent: check stock and draft a reply.

    Args:
        email_record: Saved email row from the DB.
        classification: LLM classification result dict.
        llm: LLM client instance.

    Returns:
        Result dict (see process_email docstring for structure).
    """
    result: dict = {
        "email_id": email_record["id"],
        "intent": "stock_inquiry",
        "action_taken": "",
        "draft_id": None,
        "reservation_id": None,
        "needs_human_review": False,
        "error": None,
    }
    try:
        skus = classification.get("product_skus") or []

        if not skus:
            body = generate_response_text(
                "Напиши ввічливу відповідь із проханням уточнити, "
                "які саме товари (артикули) цікавлять партнера. "
                "Звернись до відправника на ім'я (якщо є в email_body).",
                {
                    "subject": email_record["subject"],
                    "email_body": email_record.get("body_text", "")[:400],
                },
                llm,
            )
            service = gmail.get_gmail_service()
            draft = gmail.create_draft(
                service,
                to=email_record["from_email"],
                subject=email_record["subject"],
                body=body,
                thread_id=email_record["gmail_thread_id"],
                original_message_id=email_record["gmail_message_id"],
            )
            result["draft_id"] = draft.get("id")
            result["action_taken"] = "No SKUs identified — created clarification draft."
            return result

        stock_info = []
        for sku in skus:
            product = db.get_product_by_sku(sku)
            if not product:
                stock_info.append({
                    "sku": sku,
                    "found_in_db": False,
                    "note": f"артикул {sku} не знайдено в нашій базі",
                })
            else:
                available = db.check_stock(sku)
                stock_info.append({
                    "sku": sku,
                    "found_in_db": True,
                    "name": product["name"],
                    "price": product.get("price"),
                    "available_qty": available,
                })

        body = generate_response_text(
            "Напиши природну відповідь на запит про наявність товарів. "
            "Звернись до відправника на ім'я (якщо є в email_body). "
            "Для кожного товару: якщо found_in_db == false — артикул відсутній у каталозі; "
            "якщо available_qty == 0 — товар закінчився; "
            "інакше — вкажи назву, артикул, кількість і ціну у звичайному реченні. "
            "Не використовуй списки чи мітки типу 'Назва:', 'Ціна:'. "
            "Відповідай ЛИШЕ про товари з наданого списку.",
            {"products": stock_info, "email_body": email_record.get("body_text", "")[:400]},
            llm,
        )

        service = gmail.get_gmail_service()
        draft = gmail.create_draft(
            service,
            to=email_record["from_email"],
            subject=email_record["subject"],
            body=body,
            thread_id=email_record["gmail_thread_id"],
            original_message_id=email_record["gmail_message_id"],
        )
        result["draft_id"] = draft.get("id")
        result["action_taken"] = f"Created stock inquiry draft for SKUs: {skus}"
    except Exception as e:
        result["error"] = str(e)
        result["needs_human_review"] = True
    return result


def handle_reserve(email_record: dict, classification: dict, llm: LLMClient) -> dict:
    """Handle reserve intent: create reservations and draft a confirmation.

    Args:
        email_record: Saved email row from the DB.
        classification: LLM classification result dict.
        llm: LLM client instance.

    Returns:
        Result dict. needs_human_review is always True for reservations.
    """
    result: dict = {
        "email_id": email_record["id"],
        "intent": "reserve",
        "action_taken": "",
        "draft_id": None,
        "reservation_id": None,
        "needs_human_review": True,
        "error": None,
    }
    try:
        skus = classification.get("product_skus") or []
        requested_qty = classification.get("quantity") or 1
        reserved_items = []
        shortage_items = []
        first_reservation_id: int | None = None

        for sku in skus:
            product = db.get_product_by_sku(sku)
            if not product:
                shortage_items.append({"sku": sku, "reason": "product not found"})
                continue

            # 1. Спочатку перевіряємо Google Sheet
            sheet_result = sheets_client.process_reservation_in_sheet(sku)
            if not sheet_result["success"] and sheet_result.get("reason") == "немає":
                shortage_items.append({
                    "sku": sku,
                    "name": product.get("name", sku),
                    "reason": "недоступний — немає в наявності",
                })
                continue  # не резервуємо в Supabase

            # 2. Перевіряємо Supabase stock
            available = db.check_stock(sku)
            if available >= requested_qty:
                reservation = db.create_reservation(
                    product_id=product["id"],
                    partner_email=email_record["from_email"],
                    quantity=requested_qty,
                    email_id=email_record["id"],
                )
                if reservation:
                    if first_reservation_id is None:
                        first_reservation_id = reservation["id"]
                    reserved_items.append({
                        "sku": sku,
                        "name": product["name"],
                        "quantity": requested_qty,
                    })
                else:
                    shortage_items.append({"sku": sku, "reason": "reservation failed"})
            else:
                shortage_items.append({
                    "sku": sku,
                    "name": product.get("name", sku),
                    "requested": requested_qty,
                    "available": available,
                })

        result["reservation_id"] = first_reservation_id

        body = generate_response_text(
            "Напиши природну відповідь-підтвердження резервування. "
            "Звернись до відправника на ім'я (якщо є в email_body). "
            "Для кожного зарезервованого товару — підтверди природним реченням (назву та кількість). "
            "Якщо є shortage — поясни, чого не вистачає і запропонуй уточнити. "
            "Зазнач, що резервування очікує підтвердження протягом 48 годин. "
            "Не використовуй списки.",
            {
                "reserved": reserved_items,
                "shortage": shortage_items,
                "email_body": email_record.get("body_text", "")[:400],
            },
            llm,
        )

        service = gmail.get_gmail_service()
        draft = gmail.create_draft(
            service,
            to=email_record["from_email"],
            subject=email_record["subject"],
            body=body,
            thread_id=email_record["gmail_thread_id"],
            original_message_id=email_record["gmail_message_id"],
        )
        result["draft_id"] = draft.get("id")
        result["action_taken"] = (
            f"Reserved {reserved_items}; shortages {shortage_items}. Draft created."
        )
    except Exception as e:
        result["error"] = str(e)
    return result


def handle_price_request(email_record: dict, classification: dict, llm: LLMClient) -> dict:
    """Handle price_request intent: send a price list draft.

    Args:
        email_record: Saved email row from the DB.
        classification: LLM classification result dict.
        llm: LLM client instance.

    Returns:
        Result dict. needs_human_review is False (auto-reply candidate).
    """
    result: dict = {
        "email_id": email_record["id"],
        "intent": "price_request",
        "action_taken": "",
        "draft_id": None,
        "reservation_id": None,
        "needs_human_review": False,
        "error": None,
    }
    try:
        skus = classification.get("product_skus") or []

        if not skus:
            body = generate_response_text(
                "Напиши ввічливу відповідь із проханням уточнити, "
                "ціну яких саме товарів (артикулів) цікавить партнера. "
                "Звернись до відправника на ім'я (якщо є в email_body).",
                {
                    "subject": email_record["subject"],
                    "email_body": email_record.get("body_text", "")[:400],
                },
                llm,
            )
            service = gmail.get_gmail_service()
            draft = gmail.create_draft(
                service,
                to=email_record["from_email"],
                subject=email_record["subject"],
                body=body,
                thread_id=email_record["gmail_thread_id"],
                original_message_id=email_record["gmail_message_id"],
            )
            result["draft_id"] = draft.get("id")
            result["action_taken"] = "No SKUs identified — created clarification draft."
            return result

        price_list = []
        for sku in skus:
            product = db.get_product_by_sku(sku)
            if not product:
                price_list.append({
                    "sku": sku,
                    "found_in_db": False,
                    "note": f"артикул {sku} не знайдено в нашій базі",
                })
            else:
                price_list.append({
                    "sku": sku,
                    "found_in_db": True,
                    "name": product["name"],
                    "price": product.get("price"),
                })

        body = generate_response_text(
            "Напиши природну відповідь з цінами на запитані товари. "
            "Звернись до відправника на ім'я (якщо є в email_body). "
            "Вплети назву, артикул і ціну у звичайне речення — без списків і міток. "
            "Якщо found_in_db == false — артикул відсутній у каталозі. "
            "Відповідай ЛИШЕ про товари з наданого списку.",
            {"price_list": price_list, "email_body": email_record.get("body_text", "")[:400]},
            llm,
        )

        service = gmail.get_gmail_service()
        draft = gmail.create_draft(
            service,
            to=email_record["from_email"],
            subject=email_record["subject"],
            body=body,
            thread_id=email_record["gmail_thread_id"],
            original_message_id=email_record["gmail_message_id"],
        )
        result["draft_id"] = draft.get("id")
        result["action_taken"] = f"Created price list draft ({len(price_list)} products)."
    except Exception as e:
        result["error"] = str(e)
        result["needs_human_review"] = True
    return result


def handle_individual_order(email_record: dict, classification: dict, llm: LLMClient) -> dict:
    """Handle individual_order (custom photo) intent.

    Args:
        email_record: Saved email row from the DB.
        classification: LLM classification result dict.
        llm: LLM client instance.

    Returns:
        Result dict. needs_human_review is always True for custom orders.
    """
    result: dict = {
        "email_id": email_record["id"],
        "intent": "individual_order",
        "action_taken": "",
        "draft_id": None,
        "reservation_id": None,
        "needs_human_review": True,
        "error": None,
    }
    try:
        ind_product = db.get_product_by_sku("IND-ZAKAZ")
        base_price = ind_product.get("price", 1200) if ind_product else 1200

        body = generate_response_text(
            "Напиши природну відповідь на запит про індивідуальне замовлення "
            "(алмазна вишивка/мозаїка по фото). "
            "Звернись до відправника на ім'я (якщо є в email_body). "
            "Попроси надіслати фото, бажані розміри та орієнтовний дедлайн. "
            "Природно вкажи базову вартість. Не використовуй списки.",
            {
                "base_price_uah": base_price,
                "product_sku": "IND-ZAKAZ",
                "email_body": email_record.get("body_text", "")[:400],
            },
            llm,
        )

        service = gmail.get_gmail_service()
        draft = gmail.create_draft(
            service,
            to=email_record["from_email"],
            subject=email_record["subject"],
            body=body,
            thread_id=email_record["gmail_thread_id"],
            original_message_id=email_record["gmail_message_id"],
        )
        result["draft_id"] = draft.get("id")
        result["action_taken"] = "Created individual order inquiry draft (needs owner review)."
    except Exception as e:
        result["error"] = str(e)
    return result


def handle_order_status(email_record: dict, classification: dict, llm: LLMClient) -> dict:
    """Handle order_status intent: escalate to owner with a polite holding draft.

    Args:
        email_record: Saved email row from the DB.
        classification: LLM classification result dict.
        llm: LLM client instance.

    Returns:
        Result dict. needs_human_review is always True.
    """
    result: dict = {
        "email_id": email_record["id"],
        "intent": "order_status",
        "action_taken": "",
        "draft_id": None,
        "reservation_id": None,
        "needs_human_review": True,
        "error": None,
    }
    try:
        body = generate_response_text(
            "Напиши коротку ввічливу відповідь: ми перевіряємо статус замовлення "
            "і найближчим часом надамо оновлену інформацію. "
            "Звернись до відправника на ім'я (якщо є в email_body). Не використовуй списки.",
            {
                "subject": email_record["subject"],
                "email_body": email_record.get("body_text", "")[:400],
            },
            llm,
        )

        service = gmail.get_gmail_service()
        draft = gmail.create_draft(
            service,
            to=email_record["from_email"],
            subject=email_record["subject"],
            body=body,
            thread_id=email_record["gmail_thread_id"],
            original_message_id=email_record["gmail_message_id"],
        )
        result["draft_id"] = draft.get("id")
        result["action_taken"] = "Created holding draft; escalated to owner for order status."
    except Exception as e:
        result["error"] = str(e)
    return result


def handle_other(email_record: dict, classification: dict, llm: LLMClient) -> dict:
    """Handle unknown intent: summarize for owner, no draft created.

    Args:
        email_record: Saved email row from the DB.
        classification: LLM classification result dict.
        llm: LLM client instance.

    Returns:
        Result dict. needs_human_review is always True, draft_id is None.
    """
    result: dict = {
        "email_id": email_record["id"],
        "intent": "other",
        "action_taken": "",
        "draft_id": None,
        "reservation_id": None,
        "needs_human_review": True,
        "error": None,
    }
    try:
        summary = generate_response_text(
            "Зроби короткий підсумок цього листа для власника магазину (2-3 речення). "
            "Вкажи, про що запитує партнер і чи потрібна термінова реакція.",
            {
                "from": email_record["from_email"],
                "subject": email_record["subject"],
                "body_preview": email_record.get("body_text", "")[:500],
            },
            llm,
        )
        result["action_taken"] = f"Escalated to owner. Summary: {summary}"
    except Exception as e:
        result["error"] = str(e)
    return result


# ---------------------------------------------------------------------------
# Dispatch table
# ---------------------------------------------------------------------------

_HANDLERS = {
    "stock_inquiry": handle_stock_inquiry,
    "reserve": handle_reserve,
    "price_request": handle_price_request,
    "individual_order": handle_individual_order,
    "order_status": handle_order_status,
    "other": handle_other,
}


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def process_email(email_record: dict) -> dict:
    """Classify an email and execute the matching intent handler.

    Args:
        email_record: A saved email row from the DB (keys: id, gmail_message_id,
            gmail_thread_id, from_email, subject, body_text, received_at).

    Returns:
        Result dict with keys:
            email_id (int): DB row id of the processed email.
            intent (str): Classified intent.
            action_taken (str): Human-readable description of the action.
            draft_id (str | None): Gmail draft ID if a draft was created.
            reservation_id (int | None): DB reservation ID if one was created.
            needs_human_review (bool): Whether the owner must review before sending.
            error (str | None): Error message if something went wrong.
    """
    from src.llm.factory import get_llm_client

    base_result: dict = {
        "email_id": email_record.get("id"),
        "intent": "other",
        "action_taken": "",
        "draft_id": None,
        "reservation_id": None,
        "needs_human_review": True,
        "error": None,
    }

    try:
        llm = get_llm_client()
        classification = llm.classify_email(
            subject=email_record.get("subject", ""),
            body=email_record.get("body_text", ""),
        )
        intent = classification.get("intent", "other")
        handler = _HANDLERS.get(intent, handle_other)
        return handler(email_record, classification, llm)
    except Exception as e:
        base_result["error"] = str(e)
        return base_result


# ---------------------------------------------------------------------------
# __main__ — smoke test: stock inquiry for TN1283 only
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import json as _json

    # Simulates the dict that db.save_email() returns after storing a real email.
    # gmail_message_id / gmail_thread_id are fake — the Gmail client will log a
    # warning when it cannot fetch the RFC Message-ID and when the thread is not
    # found, then fall back to a standalone draft.  That is expected in local tests.
    sample_email = {
        "id": 1,
        "gmail_message_id": "test-msg-001",
        "gmail_thread_id": "test-thread-001",
        "from_email": "klymenko0105@gmail.com",
        "subject": "Наявність TN1283",
        "body_text": (
            "Доброго дня!\n"
            "Підкажіть, будь ласка, чи є у вас в наявності TN1283?\n"
            "Дякую!"
        ),
        "received_at": "2026-04-28T10:00:00+03:00",
    }

    print("=" * 60)
    print("Test: stock_inquiry for TN1283 only")
    print("Expected: response mentions ONLY TN1283, not other products")
    print("Expected: draft has Re: prefix and threading headers")
    print("Note: fake IDs → warnings about Message-ID/thread are normal")
    print("=" * 60)

    result = process_email(sample_email)
    print(_json.dumps(result, ensure_ascii=False, indent=2))

    if result.get("draft_id"):
        print(f"\nDraft created: {result['draft_id']}")
        print(f"Intent:        {result['intent']}")
        print(f"Action:        {result['action_taken']}")
    else:
        print("\nNo draft created (check error field above).")
