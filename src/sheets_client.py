import os
from google.oauth2 import service_account
from googleapiclient.discovery import build

SPREADSHEET_ID = "1jMgBRSx15uk1NZZExyZha0JTlbrax9Z29HqdTmpdlnA"
SHEET_NAME = "My-Art"
SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]

def get_sheets_service():
    creds_path = os.path.join(os.path.dirname(__file__), "..", "dropship-agent-494614-ffbdfd829454.json")
    creds = service_account.Credentials.from_service_account_file(
        creds_path, scopes=SCOPES
    )
    return build("sheets", "v4", credentials=creds)

def find_sku_row(service, sku: str) -> tuple[int, str] | None:
    """
    Шукає SKU в стовпці A.
    Повертає (row_index, availability_value) або None якщо не знайдено.
    """
    result = service.spreadsheets().values().get(
        spreadsheetId=SPREADSHEET_ID,
        range=f"{SHEET_NAME}!A:C"
    ).execute()
    
    rows = result.get("values", [])
    for i, row in enumerate(rows):
        if row and row[0].strip().upper() == sku.strip().upper():
            availability = row[2].strip() if len(row) > 2 else ""
            return (i + 1, availability)  # +1 бо Google Sheets з 1
    return None

def update_availability(service, row_index: int, new_value: str):
    """Оновлює стовпець C (Наявність) для вказаного рядка."""
    service.spreadsheets().values().update(
        spreadsheetId=SPREADSHEET_ID,
        range=f"{SHEET_NAME}!C{row_index}",
        valueInputOption="RAW",
        body={"values": [[new_value]]}
    ).execute()

def process_reservation_in_sheet(sku: str) -> dict:
    """
    Головна функція — викликається після резервації в Supabase.
    Повертає dict з результатом.
    """
    try:
        service = get_sheets_service()
        result = find_sku_row(service, sku)
        
        if result is None:
            return {"success": False, "reason": f"SKU {sku} не знайдено в таблиці"}
        
        row_index, availability = result
        availability_lower = availability.lower()

        
        
        if availability_lower == "немає":
            return {
                "success": False,
                "reason": "немає",
                "sku": sku
            }
        
        elif "1 шт" in availability_lower:
            update_availability(service, row_index, "немає")
            return {
                "success": True,
                "action": "set_to_none",
                "sku": sku,
                "was": availability
            }
        else:  # "в наявності"
            # залишаємо як є, просто підтверджуємо
            return {
                "success": True,
                "action": "kept_available",
                "sku": sku,
                "was": availability
            }
        
    
    
    except Exception as e:
        return {"success": False, "reason": str(e), "sku": sku}


if __name__ == "__main__":
    print("Тест 1 — немає:")
    print(process_reservation_in_sheet("TN015"))
    
    print("Тест 2 — в наявності, 1 шт:")
    print(process_reservation_in_sheet("TN602"))
    
    