"""Supabase database client for My-Art dropshipping agent."""

import os

from dotenv import load_dotenv
from supabase import Client, create_client

load_dotenv()

_client: Client | None = None


def get_client() -> Client:
    """Return a shared Supabase client, creating it on first call.

    Reads SUPABASE_URL and SUPABASE_SERVICE_KEY from environment.
    """
    global _client
    if _client is None:
        url = os.getenv("SUPABASE_URL", "")
        key = os.getenv("SUPABASE_SERVICE_KEY", "")
        _client = create_client(url, key)
    return _client


def get_product_by_sku(sku: str) -> dict | None:
    """Fetch a product row by SKU.

    Args:
        sku: Product SKU, e.g. "TN1283".

    Returns:
        Product dict, or None if not found.
    """
    try:
        result = get_client().table("products").select("*").eq("sku", sku).single().execute()
        return result.data
    except Exception as e:
        print(f"[db.get_product_by_sku] Error fetching SKU {sku!r}: {e}")
        return None


def check_stock(sku: str) -> int:
    """Return available stock for a SKU (stock_qty - reserved_qty).

    Args:
        sku: Product SKU, e.g. "TNG1619".

    Returns:
        Available quantity, or 0 if the product is not found.
    """
    try:
        result = (
            get_client()
            .table("products")
            .select("stock_qty, reserved_qty")
            .eq("sku", sku)
            .single()
            .execute()
        )
        if not result.data:
            return 0
        return result.data["stock_qty"] - result.data["reserved_qty"]
    except Exception as e:
        print(f"[db.check_stock] Error checking stock for SKU {sku!r}: {e}")
        return 0


def get_partner_by_email(email: str) -> dict | None:
    """Fetch a partner row by email address.

    Args:
        email: Partner email address, e.g. "olena@crafts-shop.ua".

    Returns:
        Partner dict, or None if not found.
    """
    try:
        result = (
            get_client()
            .table("partners")
            .select("*")
            .eq("email", email)
            .single()
            .execute()
        )
        return result.data
    except Exception as e:
        print(f"[db.get_partner_by_email] Error fetching partner {email!r}: {e}")
        return None


def save_email(email_data: dict) -> dict | None:
    """Insert an email record, skipping if gmail_message_id already exists.

    Args:
        email_data: Dict with keys: gmail_message_id, gmail_thread_id,
            from_email, to_email, subject, body_text, received_at.

    Returns:
        Inserted row dict, or None if skipped/failed.
    """
    try:
        result = (
            get_client()
            .table("emails")
            .insert(email_data, returning="representation")
            .execute()
        )
        return result.data[0] if result.data else None
    except Exception as e:
        error_str = str(e)
        if "duplicate" in error_str.lower() or "unique" in error_str.lower():
            # gmail_message_id already exists — skip silently
            return None
        print(f"[db.save_email] Error saving email: {e}")
        return None


def create_reservation(
    product_id: int,
    partner_email: str,
    quantity: int,
    email_id: int,
) -> dict | None:
    """Create a reservation and increment the product's reserved_qty.

    Inserts a row into reservations with status="pending", then updates
    products.reserved_qty += quantity.

    Args:
        product_id: ID of the product to reserve.
        partner_email: Email address of the requesting partner.
        quantity: Number of units to reserve.
        email_id: ID of the source email record.

    Returns:
        Inserted reservation dict, or None on failure.
    """
    try:
        db = get_client()

        reservation = (
            db.table("reservations")
            .insert(
                {
                    "product_id": product_id,
                    "partner_email": partner_email,
                    "quantity": quantity,
                    "email_id": email_id,
                    "status": "pending",
                },
                returning="representation",
            )
            .execute()
        )

        db.rpc(
            "increment_reserved_qty",
            {"p_product_id": product_id, "p_quantity": quantity},
        ).execute()

        return reservation.data[0] if reservation.data else None
    except Exception as e:
        print(f"[db.create_reservation] Error creating reservation: {e}")
        return None


if __name__ == "__main__":
    db = get_client()

    print("=== First 3 products ===")
    try:
        rows = db.table("products").select("sku, name, price, stock_qty").limit(3).execute()
        for p in rows.data:
            print(f"  {p['sku']} | {p['name']} | {p['price']} | stock: {p['stock_qty']}")
    except Exception as e:
        print(f"  Error: {e}")

    print("\n=== get_product_by_sku('TN1283') ===")
    product = get_product_by_sku("TN1283")
    if product:
        print(f"  name: {product.get('name')}, stock: {product.get('stock_qty')}")
    else:
        print("  Not found")

    print("\n=== check_stock('TNG1619') ===")
    available = check_stock("TNG1619")
    print(f"  Available: {available}")

    print("\n=== get_partner_by_email('olena@crafts-shop.ua') ===")
    partner = get_partner_by_email("olena@crafts-shop.ua")
    if partner:
        print(f"  company_name: {partner.get('company_name')}")
    else:
        print("  Not found")
