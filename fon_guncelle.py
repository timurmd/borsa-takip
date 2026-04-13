import re
import time
import requests
import gspread
from bs4 import BeautifulSoup
from google.oauth2.service_account import Credentials

SHEET_ID = "1_isL5_B9EiyLppqdP4xML9N4_pLdvgNYIei70H5yiew"
SHEET_NAME = "Fiyatlar"
JSON_FILE = "service_account.json"

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

MAX_RETRY = 3
REQUEST_DELAY_SECONDS = 2
REQUEST_TIMEOUT_SECONDS = 30


def safe_float(val):
    if val is None or val == "":
        return 0.0
    if isinstance(val, (int, float)):
        return float(val)
    val_str = str(val).strip()
    if "." in val_str and "," in val_str:
        val_str = val_str.replace(".", "")
    val_str = val_str.replace(",", ".")
    try:
        return float(val_str)
    except:
        return 0.0


def init_connection():
    creds = Credentials.from_service_account_file(JSON_FILE, scopes=SCOPES)
    return gspread.authorize(creds)


def create_session():
    session = requests.Session()
    session.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "Accept-Language": "tr-TR,tr;q=0.9,en-US;q=0.8,en;q=0.7",
        "Cache-Control": "no-cache",
        "Pragma": "no-cache",
        "Referer": "https://www.tefas.gov.tr/",
    })
    return session


def is_blocked_response(html):
    markers = [
        "Please enable JavaScript",
        "support ID",
        "Access Denied",
        "Forbidden",
        "captcha",
        "robot",
        "human",
    ]
    html_lower = html.lower()
    return any(m.lower() in html_lower for m in markers)


def html_to_text(html):
    soup = BeautifulSoup(html, "html.parser")
    return " ".join(soup.get_text(" ", strip=True).split())


def extract_value_after_label(text, label):
    escaped_label = re.escape(label)
    pattern = rf"{escaped_label}\s*%?\s*(-?\d{{1,3}}(?:\.\d{{3}})*,\d+|-?\d+,\d+|-?\d+)"
    match = re.search(pattern, text, flags=re.IGNORECASE)
    if not match:
        return None
    return match.group(1)


def normalize_number(value):
    if not value:
        return "0"
    return str(value).replace("%", "").replace(" ", "").replace(".", "")


def fetch_fund_data(session, fund_code):
    fund_code = str(fund_code or "").strip().upper()
    if not fund_code:
        return ("0", "0")

    url = f"https://www.tefas.gov.tr/FonAnaliz.aspx?FonKod={fund_code}"

    for attempt in range(1, MAX_RETRY + 1):
        try:
            response = session.get(url, timeout=REQUEST_TIMEOUT_SECONDS)
            html = response.text

            if response.status_code != 200:
                print(f"[WARN] {fund_code} HTTP {response.status_code}")
                time.sleep(2)
                continue

            if is_blocked_response(html):
                print(f"[BLOCKED] {fund_code}")
                return ("BLOCKED", "BLOCKED")

            text = html_to_text(html)
            price = extract_value_after_label(text, "Son Fiyat (TL)")
            daily_return = extract_value_after_label(text, "Günlük Getiri (%)")

            if price:
                return (
                    normalize_number(price),
                    normalize_number(daily_return) if daily_return else "0"
                )

            print(f"[WARN] {fund_code} parse edilemedi")
        except Exception as e:
            print(f"[WARN] {fund_code} hata: {e}")

        if attempt < MAX_RETRY:
            time.sleep(2)

    return ("0", "0")


def update_prices():
    client = init_connection()
    sheet = client.open_by_key(SHEET_ID).worksheet(SHEET_NAME)
    rows = sheet.get_all_values()

    if len(rows) < 2:
        print("Güncellenecek veri yok.")
        return

    session = create_session()
    updates = []
    updated_count = 0
    blocked_count = 0

    for row in rows[1:]:
        symbol = str(row[0]).strip().upper() if len(row) > 0 else ""
        old_price = row[1] if len(row) > 1 and row[1] else "0"
        old_pct = row[2] if len(row) > 2 and row[2] else "0"
        new_row = [old_price, old_pct]

        if symbol:
            price, pct = fetch_fund_data(session, symbol)

            if price == "BLOCKED":
                blocked_count += 1
                print(f"[BLOCKED] {symbol} eski değer korundu")
            elif price != "0":
                new_row = [price, pct]
                updated_count += 1
                print(f"[OK] {symbol} fiyat={price} gunluk={pct}")
            else:
                print(f"[FAIL] {symbol} veri alınamadı")

            time.sleep(REQUEST_DELAY_SECONDS)

        updates.append(new_row)

    if updates:
        sheet.update(f"B2:C{len(updates)+1}", updates, value_input_option="RAW")

    print(f"Bitti. Güncellenen={updated_count}, Engellenen={blocked_count}")


if __name__ == "__main__":
    update_prices()
