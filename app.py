import streamlit as st
import pandas as pd
import yfinance as yf
from datetime import datetime, timedelta
import os
import warnings
import gspread
from google.oauth2.service_account import Credentials
import plotly.express as px
import plotly.graph_objects as go
import requests

warnings.simplefilter(action="ignore", category=FutureWarning)

st.set_page_config(layout="wide", page_title="Portfoy v69")

SHEET_ID = "1_isL5_B9EiyLppqdP4xML9N4_pLdvgNYIei70H5yiew"
JSON_FILE = "service_account.json"

FINTABLES_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36",
    "Accept": "application/json",
}


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


def safe_adet(val):
    """Adet için özel parser — 2.000 gibi binlik ayırıcılı sayıları doğru okur."""
    if val is None or val == "":
        return 0.0
    if isinstance(val, (int, float)):
        return float(val)
    val_str = str(val).strip().replace("\xa0", "").replace(" ", "")
    if "," in val_str:
        # Türkçe format: 2.000,50 → virgül ondalık
        val_str = val_str.replace(".", "").replace(",", ".")
    else:
        # Sadece nokta var — binlik ayırıcı olarak kabul et: 2.000 → 2000
        val_str = val_str.replace(".", "")
    try:
        return float(val_str)
    except:
        return 0.0


def renk(val):
    c = ""
    if isinstance(val, (int, float)):
        if val > 0:
            c = "#2ecc71"
        elif val < 0:
            c = "#e74c3c"
    elif isinstance(val, str):
        if val.startswith("+"):
            c = "#2ecc71"
        elif val.startswith("-"):
            c = "#e74c3c"
        elif val == "BEDAVA":
            c = "#3498db"
    if c:
        return f"color: {c}; font-weight: bold;"
    return ""


def sembol_tur_belirle(sembol):
    return "Fon" if len(sembol.strip()) == 3 else "Hisse"


@st.cache_resource
def init_connection():
    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive",
    ]
    if os.path.exists(JSON_FILE):
        return gspread.authorize(
            Credentials.from_service_account_file(JSON_FILE, scopes=scopes)
        )
    try:
        info = dict(st.secrets["gcp_service_account"])
        if "private_key" in info:
            info["private_key"] = info["private_key"].replace("\\n", "\n")
        return gspread.authorize(
            Credentials.from_service_account_info(info, scopes=scopes)
        )
    except Exception as e:
        st.error(f"Hata: {e}")
        st.stop()


@st.cache_data(ttl=300)
def get_fund_price_fintables(fon_kod):
    try:
        url = f"https://api.fintables.com/funds/{fon_kod.upper()}/price/"
        r = requests.get(url, headers=FINTABLES_HEADERS, timeout=8)
        if r.status_code == 200:
            data = r.json()
            price = float(data.get("price", 0))
            prev_price = float(data.get("prev_price", 0))
            gunluk_pct = ((price - prev_price) / prev_price) * 100 if prev_price > 0 else 0.0
            return price, gunluk_pct
    except Exception as e:
        print(f"[Fintables] {fon_kod} hata: {e}")
    return 0.0, 0.0


def refresh_fund_prices_in_sheet(active_symbols=None):
    client = init_connection()
    sheet = client.open_by_key(SHEET_ID).worksheet("Fiyatlar")
    raw = sheet.get_all_values()
    if len(raw) < 2:
        return {"updated": 0, "failed": 0, "total": 0}
    active_symbols = set(active_symbols or [])
    updates = []
    updated_count = 0
    failed_count = 0
    for row in raw[1:]:
        symbol = str(row[0]).strip().upper() if len(row) > 0 else ""
        old_price = row[1] if len(row) > 1 and row[1] else "0"
        old_pct = row[2] if len(row) > 2 and row[2] else "0"
        new_row = [old_price, old_pct]
        if symbol and symbol in active_symbols:
            price, pct = get_fund_price_fintables(symbol)
            if price > 0:
                new_row = [str(price).replace(".", ","), str(round(pct, 4)).replace(".", ",")]
                updated_count += 1
            else:
                failed_count += 1
        updates.append(new_row)
    if updates:
        sheet.update(f"B2:C{len(updates)+1}", updates, value_input_option="RAW")
    sheet.update("B1:D1", [["Fiyat", "Günlük %", datetime.now().strftime("%Y-%m-%d %H:%M:%S")]])
    return {"updated": updated_count, "failed": failed_count, "total": len(active_symbols)}


# --- NAKİT ---
def get_nakit_data():
    client = init_connection()
    try:
        try:
            sheet = client.open_by_key(SHEET_ID).worksheet("Nakit")
        except:
            sheet = client.open_by_key(SHEET_ID).add_worksheet("Nakit", 1000, 4)
            sheet.append_row(["Tarih", "Aciklama", "Tutar", "Tip"])
            return pd.DataFrame(columns=["Tarih", "Aciklama", "Tutar", "Tip"])
        raw = sheet.get_all_values()
        if len(raw) < 2:
            return pd.DataFrame(columns=["Tarih", "Aciklama", "Tutar", "Tip"])
        df = pd.DataFrame(raw[1:], columns=raw[0])
        df["Tutar"] = df["Tutar"].apply(safe_float)
        df["Tarih"] = pd.to_datetime(df["Tarih"], errors="coerce")
        return df.dropna(subset=["Tarih"]).sort_values("Tarih")
    except:
        return pd.DataFrame(columns=["Tarih", "Aciklama", "Tutar", "Tip"])


def save_nakit(tarih, aciklama, tutar, tip):
    client = init_connection()
    try:
        try:
            sheet = client.open_by_key(SHEET_ID).worksheet("Nakit")
        except:
            sheet = client.open_by_key(SHEET_ID).add_worksheet("Nakit", 1000, 4)
            sheet.append_row(["Tarih", "Aciklama", "Tutar", "Tip"])
        sheet.append_row([tarih, aciklama, str(tutar).replace(".", ","), tip])
    except Exception as e:
        st.error(f"Nakit kayıt hatası: {e}")


def delete_nakit_row(row_index):
    client = init_connection()
    sheet = client.open_by_key(SHEET_ID).worksheet("Nakit")
    sheet.delete_rows(row_index + 2)


def get_nakit_bakiye(df_nakit):
    if df_nakit.empty:
        return 0.0
    girdi = df_nakit[df_nakit["Tip"] == "Giriş"]["Tutar"].sum()
    cikti = df_nakit[df_nakit["Tip"] == "Çıkış"]["Tutar"].sum()
    return girdi - cikti


# --- ANA VERİ ---
def get_data():
    client = init_connection()
    try:
        sheet = client.open_by_key(SHEET_ID).worksheet("Islemler")
        raw = sheet.get_all_values()
        if len(raw) < 2:
            return pd.DataFrame()
        df = pd.DataFrame(raw[1:], columns=raw[0])
        if "Adet" in df.columns:
            df["Adet"] = df["Adet"].apply(safe_adet)
        for c in ["Fiyat", "Komisyon", "Toplam"]:
            if c in df.columns:
                df[c] = df[c].apply(safe_float)
        df["Tarih"] = pd.to_datetime(df["Tarih"], dayfirst=False, errors="coerce")
        if "Sembol" in df.columns:
            df["Sembol"] = df["Sembol"].astype(str).str.strip().str.upper().str.replace(".IS", "")

        return df
    except:
        return pd.DataFrame()


def save_transaction(veri):
    client = init_connection()
    sheet = client.open_by_key(SHEET_ID).worksheet("Islemler")
    # Sheets'e yazarken Türkçe karakter sorununu önlemek için normalize et
    islem_yaz = "Alis" if veri["Islem"] in ["Alış", "Alis"] else "Satis"
    row = [
        veri["Tarih"], veri["Tur"], islem_yaz, veri["Sembol"], veri["Adet"],
        str(veri["Fiyat"]).replace(".", ","),
        str(veri["Komisyon"]).replace(".", ","),
        str(veri["Toplam"]).replace(".", ",")
    ]
    sheet.append_row(row)
    try:
        p_sheet = client.open_by_key(SHEET_ID).worksheet("Fiyatlar")
        vals = [str(x).strip().upper() for x in p_sheet.col_values(1)]
        if veri["Sembol"] not in vals and veri["Tur"] == "Fon":
            p_sheet.append_row([veri["Sembol"], 0, 0])
    except:
        pass
    # Satışta otomatik nakit girişi
    if veri["Islem"] == "Satış" and float(veri["Toplam"]) > 0:
        save_nakit(veri["Tarih"], f"{veri['Sembol']} satış geliri", float(veri["Toplam"]), "Giriş")


def get_fund_data_from_sheet():
    client = init_connection()
    try:
        sheet = client.open_by_key(SHEET_ID).worksheet("Fiyatlar")
        raw = sheet.get_all_values()
        data_dict = {}
        for row in raw[1:]:
            if len(row) >= 2:
                sym = str(row[0]).strip().upper()
                price = safe_float(row[1])
                change_pct = safe_float(row[2]) if len(row) > 2 else 0.0
                data_dict[sym] = {"fiyat": price, "yuzde": change_pct}
        return data_dict
    except:
        return {}


def save_daily_snapshot(tv, tm, dk, net_ana, nakit):
    if tv < 100 and tm > 1000:
        return
    client = init_connection()
    try:
        try:
            sheet = client.open_by_key(SHEET_ID).worksheet("Gecmis")
        except:
            sheet = client.open_by_key(SHEET_ID).add_worksheet("Gecmis", 1000, 6)
            sheet.append_row(["Tarih", "ToplamVarlik", "ToplamMaliyet", "DolarKuru", "NetAnaPara", "Nakit"])
    except:
        return

    # Nakit sütunu yoksa ekle
    current_header = sheet.row_values(1)
    if "Nakit" not in current_header:
        new_header = current_header + ["Nakit"]
        sheet.update("A1:" + chr(64 + len(new_header)) + "1", [new_header])
        current_header = new_header

    nakit_col = current_header.index("Nakit") + 1

    bugun = datetime.now().strftime("%Y-%m-%d")
    dates = sheet.col_values(1)
    d = [bugun,
         str(tv).replace(".", ","),
         str(tm).replace(".", ","),
         str(dk).replace(".", ","),
         str(net_ana).replace(".", ",")]

    if bugun not in dates:
        sheet.append_row(d + [str(nakit).replace(".", ",")])
    else:
        idx = dates.index(bugun) + 1
        for i, val in enumerate(d[1:]):
            sheet.update_cell(idx, i + 2, val)
        sheet.update_cell(idx, nakit_col, str(nakit).replace(".", ","))


def save_asset_snapshots(liste):
    client = init_connection()
    bugun = datetime.now().strftime("%Y-%m-%d")
    try:
        try:
            sheet = client.open_by_key(SHEET_ID).worksheet("VarlikKari")
        except:
            sheet = client.open_by_key(SHEET_ID).add_worksheet("VarlikKari", 1000, 26)
            sheet.append_row(["Tarih"])
        headers = sheet.row_values(1)
        if not headers:
            headers = ["Tarih"]
        data_dict = {item["Varlık"]: str(item["K/Z (%)"]).replace(".", ",") for item in liste}
        added_header = False
        for sym in data_dict.keys():
            if sym not in headers:
                headers.append(sym)
                added_header = True
        if added_header:
            for c_idx, h_val in enumerate(headers):
                sheet.update_cell(1, c_idx + 1, h_val)
        dates = sheet.col_values(1)
        row_data = [bugun]
        for h in headers[1:]:
            row_data.append(data_dict.get(h, "0"))
        if bugun not in dates:
            sheet.append_row(row_data)
        else:
            r_idx = dates.index(bugun) + 1
            for c_idx, val in enumerate(row_data):
                sheet.update_cell(r_idx, c_idx + 1, val)
    except:
        pass


def get_asset_history():
    client = init_connection()
    try:
        sheet = client.open_by_key(SHEET_ID).worksheet("VarlikKari")
        raw = sheet.get_all_values()
        if len(raw) < 2:
            return pd.DataFrame()
        actual_cols = raw[0]
        valid_data = []
        for r in raw[1:]:
            r_padded = r + ["0"] * (len(actual_cols) - len(r))
            valid_data.append(r_padded[:len(actual_cols)])
        df = pd.DataFrame(valid_data, columns=actual_cols)
        for c in df.columns:
            if c != "Tarih":
                df[c] = df[c].apply(safe_float)
        df["Tarih"] = pd.to_datetime(df["Tarih"], errors="coerce")
        df = df.dropna(subset=["Tarih"])
        return df.sort_values("Tarih", ascending=True)
    except:
        return pd.DataFrame()


def get_history_data():
    client = init_connection()
    try:
        sheet = client.open_by_key(SHEET_ID).worksheet("Gecmis")
        raw = sheet.get_all_values()
        if len(raw) < 2:
            return pd.DataFrame()
        actual_cols = raw[0]
        valid_data = []
        for r in raw[1:]:
            r_padded = r + ["0"] * (len(actual_cols) - len(r))
            valid_data.append(r_padded[:len(actual_cols)])
        df = pd.DataFrame(valid_data, columns=actual_cols)
        for c in ["ToplamVarlik", "ToplamMaliyet", "DolarKuru", "NetAnaPara", "Nakit"]:
            if c in df.columns:
                df[c] = df[c].apply(safe_float)
            else:
                df[c] = 0.0
        df["Tarih"] = pd.to_datetime(df["Tarih"], errors="coerce")
        df = df.dropna(subset=["Tarih"])
        return df.sort_values("Tarih", ascending=True)
    except:
        return pd.DataFrame()


@st.cache_data(ttl=3600)
def get_historical_market_data():
    end = datetime.now()
    start = end - timedelta(days=365 * 5)
    usd = yf.download("USDTRY=X", start=start, end=end, progress=False)
    gold = yf.download("GC=F", start=start, end=end, progress=False)
    if usd.empty or gold.empty:
        return pd.DataFrame()
    usd = usd["Close"].reset_index()
    usd.columns = ["Date", "USD"]
    usd["Date"] = pd.to_datetime(usd["Date"]).dt.date
    gold = gold["Close"].reset_index()
    gold.columns = ["Date", "Gold_Ounce"]
    gold["Date"] = pd.to_datetime(gold["Date"]).dt.date
    m = pd.merge(usd, gold, on="Date", how="outer").sort_values("Date").ffill()
    m["Gram_Gold"] = (m["Gold_Ounce"] * m["USD"]) / 31.1035
    m.set_index("Date", inplace=True)
    return m


def calculate_benchmarks(df_transactions):
    m = get_historical_market_data()
    if m.empty:
        return 0, 0, 0, 0
    tl_injected = 0
    usd_injected = 0
    gold_injected = 0
    df_al = df_transactions[df_transactions["Islem"] == "Alış"]
    df_sat = df_transactions[df_transactions["Islem"] == "Satış"]
    for _, r in df_al.iterrows():
        try:
            day = m.loc[m.index.asof(r["Tarih"].date())]
            usd = day["USD"]
            gold = day["Gram_Gold"]
            amt = float(r["Toplam"])
            tl_injected += amt
            if usd > 0:
                usd_injected += amt / usd
            if gold > 0:
                gold_injected += amt / gold
        except:
            continue
    net_ana_para = df_al["Toplam"].apply(safe_float).sum() - df_sat["Toplam"].apply(safe_float).sum()
    if tl_injected > 0 and net_ana_para > 0:
        avg_usd_rate = tl_injected / usd_injected if usd_injected > 0 else 1
        avg_gold_rate = tl_injected / gold_injected if gold_injected > 0 else 1
        usd_eq = net_ana_para / avg_usd_rate
        gold_eq = net_ana_para / avg_gold_rate
        try:
            last = m.iloc[-1]
            return usd_eq * last["USD"], gold_eq * last["Gram_Gold"], usd_eq, gold_eq
        except:
            pass
    return 0, 0, 0, 0


@st.cache_data(ttl=300)
def get_stock_data_full(symbol):
    try:
        s = symbol.strip().upper()
        if not s.endswith(".IS"):
            s += ".IS"
        info = yf.Ticker(s).fast_info
        return info["last_price"], info["previous_close"]
    except:
        return 0.0, 0.0


@st.cache_data(ttl=3600)
def get_usd_rate():
    try:
        return yf.Ticker("USDTRY=X").fast_info["last_price"]
    except:
        return 1.0


def calculate_portfolio_unified(df):
    portfolio = {}
    df = df.sort_values("Tarih", kind="mergesort")
    toplam_giren = 0
    toplam_cikan = 0
    for _, row in df.iterrows():
        sym = row["Sembol"]
        typ = row["Tur"]
        islem = row["Islem"]
        qty = float(row["Adet"])
        total = float(row["Toplam"])
        tarih = row["Tarih"]
        islem_norm = islem.strip().lower().replace("ı", "i").replace("ş", "s").replace("ç", "c").replace("ğ", "g").replace("ü", "u").replace("ö", "o")
        is_alis = islem_norm in ["alis", "al"]
        is_satis = islem_norm in ["satis", "sat"]

        if is_alis:
            toplam_giren += total
        else:
            toplam_cikan += total
        if sym not in portfolio:
            portfolio[sym] = {"Adet": 0, "Maliyet": 0, "NetGiris": 0.0, "Tur": typ, "Alimlar": []}
        if is_alis:
            portfolio[sym]["Adet"] += qty
            portfolio[sym]["Maliyet"] += total
            portfolio[sym]["NetGiris"] += total
            portfolio[sym]["Alimlar"].append({"adet": qty, "tarih": tarih})
        elif is_satis:
            if portfolio[sym]["Adet"] > 0:
                avg_cost = portfolio[sym]["Maliyet"] / portfolio[sym]["Adet"]
                portfolio[sym]["Maliyet"] -= (qty * avg_cost)
                portfolio[sym]["Adet"] -= qty
                portfolio[sym]["NetGiris"] -= total
                kalan_satis = qty
                while kalan_satis > 0 and len(portfolio[sym]["Alimlar"]) > 0:
                    ilk_alim = portfolio[sym]["Alimlar"][0]
                    if ilk_alim["adet"] <= kalan_satis:
                        kalan_satis -= ilk_alim["adet"]
                        portfolio[sym]["Alimlar"].pop(0)
                    else:
                        ilk_alim["adet"] -= kalan_satis
                        kalan_satis = 0
            else:
                portfolio[sym]["Adet"] = 0
                portfolio[sym]["Maliyet"] = 0
                portfolio[sym]["NetGiris"] = 0
                portfolio[sym]["Alimlar"] = []
        if portfolio[sym]["Adet"] <= 0.001:
            portfolio[sym]["Adet"] = 0
            portfolio[sym]["Maliyet"] = 0
            portfolio[sym]["NetGiris"] = 0
            portfolio[sym]["Alimlar"] = []
        # Pozisyon devam ediyor ama NetGiris negatife düştüyse sıfırla
        # (kar realizasyonu yapılmış, kalan risk = 0 yani BEDAVA)
        if portfolio[sym]["NetGiris"] < 0:
            portfolio[sym]["NetGiris"] = 0
    return portfolio, toplam_giren, toplam_cikan


def duzeltme_islemi_kaydet(mevcut_portfolio):
    st.markdown("#### 📐 Pozisyon Düzeltme")
    st.caption("Bankadaki güncel durumu gir — sistem farkı otomatik hesaplar ve işlem olarak kaydeder.")
    aktif_hisseler = {
        sym: data for sym, data in mevcut_portfolio.items()
        if data["Adet"] > 0 and data["Tur"] == "Hisse"
    }
    if not aktif_hisseler:
        st.info("Portföyde aktif hisse senedi bulunamadı.")
        return
    sembol_sec = st.selectbox("Hisse Seç", options=sorted(aktif_hisseler.keys()), key="duz_sembol")
    if sembol_sec:
        mevcut_adet = aktif_hisseler[sembol_sec]["Adet"]
        mevcut_maliyet = aktif_hisseler[sembol_sec]["Maliyet"]
        mevcut_ort_maliyet = mevcut_maliyet / mevcut_adet if mevcut_adet > 0 else 0
        st.info(f"**Mevcut kayıt:** {mevcut_adet:.0f} lot @ {mevcut_ort_maliyet:.4f} TL ortalama")
        with st.form("duzeltme_form", clear_on_submit=True):
            col1, col2, col3 = st.columns(3)
            yeni_adet = col1.number_input("Güncel Toplam Adet", min_value=0, step=1, value=int(mevcut_adet))
            yeni_ort_maliyet = col2.number_input("Güncel Ortalama Maliyet (TL)", min_value=0.0, format="%.4f", value=float(mevcut_ort_maliyet))
            duz_tarih = col3.date_input("Tarih", datetime.now())
            if st.form_submit_button("DÜZELT VE KAYDET"):
                yeni_toplam = yeni_adet * yeni_ort_maliyet
                eski_toplam = mevcut_maliyet
                fark_adet = yeni_adet - mevcut_adet
                fark_toplam = yeni_toplam - eski_toplam
                if abs(fark_adet) < 0.001 and abs(fark_toplam) < 0.01:
                    st.warning("Değişiklik yok, kayıt yapılmadı.")
                    return
                tarih_str = duz_tarih.strftime("%Y-%m-%d")
                if fark_adet == 0:
                    sifir = {"Tarih": tarih_str, "Tur": "Hisse", "Islem": "Satış",
                             "Sembol": sembol_sec, "Adet": mevcut_adet, "Fiyat": mevcut_ort_maliyet,
                             "Komisyon": 0, "Toplam": mevcut_maliyet}
                    yeni_r = {"Tarih": tarih_str, "Tur": "Hisse", "Islem": "Alış",
                              "Sembol": sembol_sec, "Adet": yeni_adet, "Fiyat": yeni_ort_maliyet,
                              "Komisyon": 0, "Toplam": yeni_toplam}
                    with st.spinner("Kaydediliyor..."):
                        save_transaction(sifir)
                        save_transaction(yeni_r)
                    st.success(f"✅ Maliyet düzeltmesi kaydedildi: {yeni_adet:.0f} lot @ {yeni_ort_maliyet:.4f} TL")
                else:
                    if fark_adet > 0:
                        islem = "Alış"
                        islem_adet = fark_adet
                        islem_toplam = fark_toplam
                        islem_fiyat = fark_toplam / fark_adet
                    else:
                        islem = "Satış"
                        islem_adet = abs(fark_adet)
                        islem_toplam = abs(fark_toplam)
                        islem_fiyat = islem_toplam / islem_adet
                    veri = {"Tarih": tarih_str, "Tur": "Hisse", "Islem": islem,
                            "Sembol": sembol_sec, "Adet": islem_adet, "Fiyat": islem_fiyat,
                            "Komisyon": 0, "Toplam": islem_toplam}
                    with st.spinner("Kaydediliyor..."):
                        save_transaction(veri)
                    st.success(f"✅ {islem} kaydedildi: {islem_adet:.0f} lot @ {islem_fiyat:.4f} TL")
                st.cache_data.clear()
                st.rerun()


# --- ARAYÜZ ---
st.title("☁️ Bulut Portföy & Analiz")


def check_password():
    if "password_correct" not in st.session_state:
        st.text_input("Şifre", type="password", key="pwd", on_change=pwd_entered)
        return False
    return st.session_state["password_correct"]


def pwd_entered():
    pwd_value = st.session_state.get("pwd", "")
    if pwd_value == st.secrets["app_password"]:
        st.session_state["password_correct"] = True
        if "pwd" in st.session_state:
            del st.session_state["pwd"]
    else:
        st.session_state["password_correct"] = False


if not check_password():
    st.stop()

if st.sidebar.button("🔒 Çıkış"):
    del st.session_state["password_correct"]
    st.rerun()

try:
    df = get_data()
except:
    st.stop()

mevcut_semboller = sorted(df["Sembol"].dropna().unique().tolist()) if not df.empty else []

tab1, tab2, tab3, tab4, tab5 = st.tabs(["➕ EKLE", "📊 PORTFÖY", "💵 NAKİT", "📈 GİDİŞAT", "📋 GEÇMİŞ"])

# ================================================================
with tab1:
    mod = st.radio("Mod:", ["Yeni İşlem", "Pozisyon Düzelt"], horizontal=True)
    st.divider()

    if mod == "Yeni İşlem":
        col_ekle, col_sil = st.columns([2, 1])
        with col_ekle:
            st.subheader("İşlem")
            metod = st.radio("Yöntem:", ["Birim Fiyat", "Toplam Tutar"], horizontal=True)
            with st.form("ekle", clear_on_submit=True):
                yon = st.radio("Yön", ["Alış", "Satış"], horizontal=True)
                ca, cb = st.columns(2)
                tarih = ca.date_input("Tarih", datetime.now())
                kod_options = ["— Yeni sembol gir —"] + mevcut_semboller
                kod_sec = cb.selectbox("Sembol Seç / Yeni Gir", kod_options)
                if kod_sec == "— Yeni sembol gir —":
                    kod = st.text_input("Yeni Sembol Kodu").strip().upper()
                else:
                    kod = kod_sec
                if kod:
                    tur_auto = sembol_tur_belirle(kod)
                    st.caption(f"📌 Tür: **{tur_auto}** ({'3 harf = Fon' if tur_auto == 'Fon' else '3 harften fazla = Hisse'})")
                adet = st.number_input("Adet", min_value=1, step=1)
                fiyat = 0.0
                kom = 0.0
                toplam = 0.0
                cc, cd = st.columns(2)
                if metod == "Birim Fiyat":
                    fiyat = cc.number_input("Fiyat", min_value=0.0, format="%.6f")
                    kom = cd.number_input("Komisyon", min_value=0.0, format="%.2f")
                else:
                    toplam_girilen = cc.number_input("Net Tutar", min_value=0.0, format="%.2f")

                if st.form_submit_button("KAYDET"):
                    if kod and adet > 0:
                        hata = False
                        if metod == "Birim Fiyat":
                            if yon == "Satış" and fiyat <= 0:
                                st.error("⚠️ Satış için fiyat 0'dan büyük olmalıdır!")
                                hata = True
                            elif fiyat >= 0:
                                raw_t = adet * fiyat
                                toplam = raw_t + kom if yon == "Alış" else raw_t - kom
                            else:
                                hata = True
                        else:
                            if yon == "Satış" and toplam_girilen <= 0:
                                st.error("⚠️ Satış için tutar 0'dan büyük olmalıdır!")
                                hata = True
                            elif toplam_girilen >= 0:
                                toplam = toplam_girilen
                                fiyat = (toplam_girilen / adet) if adet > 0 else 0
                                kom = 0
                            else:
                                hata = True
                        if not hata:
                            yeni = {
                                "Tarih": tarih.strftime("%Y-%m-%d"),
                                "Tur": sembol_tur_belirle(kod),
                                "Islem": yon, "Sembol": kod, "Adet": adet,
                                "Fiyat": fiyat, "Komisyon": kom, "Toplam": toplam
                            }
                            with st.spinner("Kaydediliyor..."):
                                save_transaction(yeni)
                                st.success("Tamam!")
                                st.cache_data.clear()
                                st.rerun()

        with col_sil:
            st.subheader("Sil")
            try:
                df_sil = get_data()
                if not df_sil.empty:
                    st.dataframe(df_sil.tail(5)[["Sembol", "Islem", "Toplam"]], use_container_width=True)
                    secilen = st.selectbox("ID:", df_sil.index.sort_values(ascending=False))
                    if st.button("Sil"):
                        client = init_connection()
                        client.open_by_key(SHEET_ID).worksheet("Islemler").delete_rows(int(secilen) + 2)
                        st.success("Silindi!")
                        st.cache_data.clear()
                        st.rerun()
            except:
                pass
    else:
        if df.empty:
            st.info("Henüz işlem kaydı yok.")
        else:
            portfolio_tmp, _, _ = calculate_portfolio_unified(df)
            duzeltme_islemi_kaydet(portfolio_tmp)

# ================================================================
with tab2:
    if st.button("🔄 Yenile"):
        portfolio_tmp, _, _ = calculate_portfolio_unified(df)
        active_fund_symbols = {
            sym for sym, data in portfolio_tmp.items()
            if data["Adet"] > 0 and data["Tur"] == "Fon"
        }
        if not active_fund_symbols:
            st.info("Güncellenecek aktif fon bulunamadı.")
        else:
            with st.spinner("Fon fiyatları Fintables'tan güncelleniyor..."):
                sonuc = refresh_fund_prices_in_sheet(active_fund_symbols)
            st.cache_data.clear()
            st.cache_resource.clear()
            if sonuc["updated"] > 0:
                st.success(f"✅ {sonuc['updated']} fon güncellendi.")
            else:
                st.warning(f"⚠️ Fiyat alınamadı ({sonuc['failed']} başarısız). Eski fiyatlar korunuyor.")
        st.rerun()

    if df.empty:
        st.info("Veri yok.")
    else:
        portfolio, t_giren, t_cikan = calculate_portfolio_unified(df)
        fund_data = get_fund_data_from_sheet()
        dolar = get_usd_rate()
        df_nakit = get_nakit_data()
        nakit_bakiye = get_nakit_bakiye(df_nakit)

        net_ana_para_tl = t_giren - t_cikan
        alt_usd, alt_gold, net_ana_para_usd_maliyeti, _ = calculate_benchmarks(df)

        liste = []
        gunluk_toplam_tl = 0
        bugun_tarih = datetime.now()

        for sym, data in portfolio.items():
            net = data["Adet"]
            if net > 0:
                em = data["Maliyet"]
                v_tur = data["Tur"]
                risk_kalan = data["NetGiris"]
                alimlar = data["Alimlar"]
                total_weighted_days = 0
                for alim in alimlar:
                    gun_farki = max(1, (bugun_tarih - alim["tarih"]).days)
                    total_weighted_days += gun_farki * alim["adet"]
                ort_gun = int(total_weighted_days / net) if net > 0 else 0
                guncel = 0.0
                ref_fiyat = 0.0
                if v_tur == "Hisse":
                    curr_p, prev_p = get_stock_data_full(sym)
                    guncel = curr_p if curr_p else 0
                    ref_fiyat = prev_p if prev_p else guncel
                else:
                    f_info = fund_data.get(sym, {"fiyat": 0, "yuzde": 0})
                    guncel = f_info["fiyat"]
                    pct = f_info["yuzde"]
                    if guncel == 0:
                        guncel = em / net if net > 0 else 0
                        ref_fiyat = guncel
                    else:
                        ref_fiyat = guncel / (1 + (pct / 100))
                deger = net * guncel
                kz = deger - em
                kz_yuzde = (kz / em) * 100 if em > 0 else 0
                gf_tl = (guncel - ref_fiyat) * net
                gf_yuzde = ((guncel - ref_fiyat) / ref_fiyat) * 100 if ref_fiyat > 0 else 0
                gf_metin = f"{gf_tl:+,.0f} (%{gf_yuzde:+.2f})"
                gunluk_toplam_tl += gf_tl
                maliyet_durumu = "BEDAVA" if risk_kalan <= 0 else risk_kalan
                liste.append({
                    "Varlık": sym, "Lot": net,
                    "Ort. Maliyet": (em / net) if net > 0 else 0,
                    "Fiyat": guncel, "Kalan Risk (TL)": maliyet_durumu,
                    "Değer (TL)": float(deger), "Ort. Süre": f"{ort_gun} Gün",
                    "K/Z (TL)": float(kz), "K/Z (%)": float(kz_yuzde),
                    "Günlük Fark": gf_metin
                })

        if liste:
            df_v = pd.DataFrame(liste)
            toplam_portfoy_degeri = df_v["Değer (TL)"].sum()
            toplam_maliyet = sum([x["Ort. Maliyet"] * x["Lot"] for x in liste])
            toplam_servet = toplam_portfoy_degeri + nakit_bakiye

            save_daily_snapshot(toplam_portfoy_degeri, toplam_maliyet, dolar, net_ana_para_tl, nakit_bakiye)
            save_asset_snapshots(liste)

            # Genel Kar = şu anki portföy + realize edilen karlar - toplam yatırılan
            genel_kar = toplam_portfoy_degeri + t_cikan - t_giren
            genel_ky = (genel_kar / t_giren) * 100 if t_giren > 0 else 0

            pie_df = df_v[["Varlık", "Değer (TL)"]].copy()
            if nakit_bakiye > 0:
                pie_df = pd.concat([pie_df, pd.DataFrame([{"Varlık": "💵 Nakit", "Değer (TL)": nakit_bakiye}])], ignore_index=True)

            fig_pie = px.pie(
                pie_df, values="Değer (TL)", names="Varlık",
                hole=0.45,
            )
            fig_pie.update_traces(
                textposition="outside",
                texttemplate="<b>%{label}</b><br>%{percent:.1%}",
                hovertemplate="<b>%{label}</b><br>%{value:,.0f} ₺<br>%{percent:.1%}<extra></extra>",
                pull=[0.03] * len(pie_df),
            )
            fig_pie.update_layout(
                showlegend=False,
                margin=dict(t=40, b=40, l=40, r=40),
                height=480,
            )
            st.plotly_chart(fig_pie, use_container_width=True)

            anlik_kz = toplam_portfoy_degeri - toplam_maliyet
            anlik_ky = (anlik_kz / toplam_maliyet) * 100 if toplam_maliyet > 0 else 0

            k0, k1, k2, k3 = st.columns(4)
            k0.metric("Toplam Servet", f"{toplam_servet:,.0f} ₺", f"${toplam_servet/dolar:,.0f}", delta_color="off")
            k1.metric("Portföy Değeri", f"{toplam_portfoy_degeri:,.0f} ₺")
            k2.metric("Nakit", f"{nakit_bakiye:,.0f} ₺")
            k3.metric("Anlık K/Z", f"{anlik_kz:+,.0f} ₺", f"%{anlik_ky:.1f}")

            st.divider()

            k4, k5, k6 = st.columns(3)
            k4.metric("Günlük Fark", f"{gunluk_toplam_tl:+,.0f} ₺")
            k5.metric("Borsadaki Maliyet", f"{toplam_maliyet:,.0f} ₺", "Eldeki varlıkların alış maliyeti", delta_color="off")
            k6.metric("GENEL KAR", f"{genel_kar:+,.0f} ₺", f"%{genel_ky:.1f} (Ana Paraya Göre)")

            st.divider()
            st.subheader("📋 Portföy Detayı")

            def format_risk(val):
                if isinstance(val, (int, float)):
                    return f"{val:,.0f}"
                return val

            cfg = {
                "Varlık": st.column_config.TextColumn("Varlık", disabled=True),
                "Lot": st.column_config.NumberColumn("Lot", format="%.0f"),
                "Ort. Maliyet": st.column_config.NumberColumn("Ort. Maliyet", format="%.4f"),
                "Fiyat": st.column_config.NumberColumn("Fiyat", format="%.4f"),
                "Kalan Risk (TL)": st.column_config.Column("Kalan Risk", disabled=True),
                "Değer (TL)": st.column_config.NumberColumn("Değer (TL)", format="%.0f"),
                "Ort. Süre": st.column_config.TextColumn("Elde Tutma"),
                "K/Z (TL)": st.column_config.NumberColumn("K/Z (TL)", format="%.0f"),
                "K/Z (%)": st.column_config.NumberColumn("K/Z (%)", format="%.2f"),
                "Günlük Fark": st.column_config.TextColumn("Günlük", disabled=True)
            }

            st.dataframe(
                df_v.style.format({
                    "Ort. Maliyet": "{:,.4f}", "Fiyat": "{:,.4f}",
                    "Değer (TL)": "{:,.0f}", "K/Z (TL)": "{:+,.0f}", "K/Z (%)": "{:+.2f} %"
                }).format({"Kalan Risk (TL)": format_risk}).map(renk, subset=["K/Z (TL)", "K/Z (%)", "Günlük Fark"]),
                use_container_width=True, hide_index=True, column_config=cfg
            )

# ================================================================
with tab3:
    st.subheader("💵 Nakit Takibi")
    df_nakit = get_nakit_data()
    nakit_bakiye = get_nakit_bakiye(df_nakit)

    renk_bakiye = "#2ecc71" if nakit_bakiye >= 0 else "#e74c3c"
    st.markdown(f"""
    <div style="background:#1e1e1e;border-radius:12px;padding:20px 28px;display:inline-block;margin-bottom:16px;">
        <div style="color:#aaa;font-size:14px;">Güncel Nakit Bakiye</div>
        <div style="color:{renk_bakiye};font-size:32px;font-weight:bold;">{nakit_bakiye:,.0f} ₺</div>
    </div>
    """, unsafe_allow_html=True)

    col_giris, _ = st.columns([2, 1])
    with col_giris:
        with st.form("nakit_form", clear_on_submit=True):
            st.markdown("**Yeni Hareket Ekle**")
            nc1, nc2 = st.columns(2)
            n_tarih = nc1.date_input("Tarih", datetime.now(), key="n_tarih")
            n_tip = nc2.radio("Tip", ["Giriş", "Çıkış"], horizontal=True)
            n_tutar = st.number_input("Tutar (₺)", min_value=0.0, format="%.2f")
            n_aciklama = st.text_input("Açıklama (opsiyonel)", placeholder="Maaş, harcama, fon satışı...")
            if st.form_submit_button("EKLE"):
                if n_tutar > 0:
                    with st.spinner("Kaydediliyor..."):
                        save_nakit(n_tarih.strftime("%Y-%m-%d"), n_aciklama, n_tutar, n_tip)
                        st.success("Tamam!")
                        st.cache_data.clear()
                        st.rerun()
                else:
                    st.error("Tutar 0'dan büyük olmalıdır.")

    st.divider()

    if not df_nakit.empty:
        df_nakit_sorted = df_nakit.sort_values("Tarih").copy()
        df_nakit_sorted["NetTutar"] = df_nakit_sorted.apply(
            lambda r: r["Tutar"] if r["Tip"] == "Giriş" else -r["Tutar"], axis=1
        )
        df_nakit_sorted["Bakiye"] = df_nakit_sorted["NetTutar"].cumsum()

        fg = go.Figure()
        fg.add_trace(go.Scatter(
            x=df_nakit_sorted["Tarih"], y=df_nakit_sorted["Bakiye"],
            name="Nakit Bakiye", line=dict(color="#f1c40f", width=3),
            fill="tozeroy", fillcolor="rgba(241,196,15,0.1)"
        ))
        fg.update_layout(title="Nakit Bakiye Gidişatı", hovermode="x unified", height=300)
        st.plotly_chart(fg, use_container_width=True)

        st.divider()
        st.subheader("📋 Nakit Hareketleri")

        df_goster = df_nakit_sorted[["Tarih", "Aciklama", "Tip", "Tutar"]].copy()
        df_goster = df_goster.sort_values("Tarih", ascending=False)
        df_goster["Tarih"] = df_goster["Tarih"].dt.strftime("%Y-%m-%d")

        col_tablo, col_sil2 = st.columns([3, 1])
        with col_tablo:
            st.dataframe(
                df_goster.style.format({"Tutar": "{:,.2f} ₺"}).map(
                    lambda v: "color:#2ecc71;font-weight:bold" if v == "Giriş" else "color:#e74c3c;font-weight:bold",
                    subset=["Tip"]
                ),
                use_container_width=True, hide_index=True
            )
        with col_sil2:
            st.markdown("**Satır Sil**")
            sil_idx = st.selectbox("ID:", df_nakit.index.sort_values(ascending=False), key="nakit_sil")
            if st.button("Sil", key="nakit_sil_btn"):
                delete_nakit_row(int(sil_idx))
                st.success("Silindi!")
                st.cache_data.clear()
                st.rerun()
    else:
        st.info("Henüz nakit hareketi girilmemiş.")

# ================================================================
with tab4:
    st.subheader("📈 Gidişat")
    df_hist = get_history_data()
    if not df_hist.empty:
        df_hist["GenelKar"] = df_hist["ToplamVarlik"] - df_hist["NetAnaPara"]
        df_hist["AnlikKar"] = df_hist.apply(
            lambda r: r["ToplamVarlik"] - r["ToplamMaliyet"] if r["ToplamMaliyet"] > 100 else 0, axis=1
        )
        df_hist["ToplamServet"] = df_hist["ToplamVarlik"] + df_hist["Nakit"]

        # Nakit verisi olan günleri ayır
        df_nakit_var = df_hist[df_hist["Nakit"] > 0].copy()

        f1 = go.Figure()
        f1.add_trace(go.Scatter(x=df_hist["Tarih"], y=df_hist["ToplamVarlik"],
                                name="Portföy Değeri", line=dict(color="#3498db", width=2)))
        if not df_nakit_var.empty:
            f1.add_trace(go.Scatter(x=df_nakit_var["Tarih"], y=df_nakit_var["ToplamServet"],
                                    name="Toplam Servet (Nakit Dahil)", line=dict(color="#2ecc71", width=3)))
        f1.add_trace(go.Scatter(x=df_hist["Tarih"], y=df_hist["NetAnaPara"],
                                name="İçerideki Ana Para", line=dict(color="gray", dash="dot")))
        f1.update_layout(title="Toplam Servet vs Portföy vs Ana Para", hovermode="x unified")
        st.plotly_chart(f1, use_container_width=True)

        st.divider()

        f2 = go.Figure()
        f2.add_trace(go.Scatter(x=df_hist["Tarih"], y=df_hist["GenelKar"],
                                name="GENEL KÂR (Cepteki Dahil)", line=dict(color="#3498db", width=3)))
        f2.add_trace(go.Scatter(x=df_hist["Tarih"], y=df_hist["AnlikKar"],
                                name="ANLIK KÂR (Sadece Eldekiler)", line=dict(color="#f1c40f", width=2, dash="dash")))
        f2.update_layout(title="Kâr Analizi: Genel vs Anlık", hovermode="x unified")
        st.plotly_chart(f2, use_container_width=True)
    else:
        st.info("Genel veri toplanıyor...")

    st.divider()

    df_assets = get_asset_history()
    if not df_assets.empty and len(df_assets.columns) > 1:
        st.subheader("📊 Varlık Bazında Kâr/Zarar (%) Gidişatı")
        st.info("💡 Not: Grafik bugünden itibaren her gün varlıkların kapanış performansını işleyerek ilerleyecektir.")
        portfolio_gidisat, _, _ = calculate_portfolio_unified(df)
        aktif_semboller = [sym for sym, d in portfolio_gidisat.items() if d["Adet"] > 0]
        gosterilecek_kolonlar = ["Tarih"] + [c for c in df_assets.columns if c in aktif_semboller]
        if len(gosterilecek_kolonlar) > 1:
            df_assets_aktif = df_assets[gosterilecek_kolonlar]
            df_melted = df_assets_aktif.melt(id_vars=["Tarih"], var_name="Varlık", value_name="K/Z (%)")
            f3 = px.line(df_melted, x="Tarih", y="K/Z (%)", color="Varlık", markers=True)
            f3.add_hline(y=0, line_dash="dash", line_color="red")
            f3.update_layout(hovermode="x unified", yaxis_title="Kâr / Zarar (%)")
            st.plotly_chart(f3, use_container_width=True)
        else:
            st.warning("Grafiği çizilecek aktif varlık bulunamadı.")

# ================================================================
with tab5:
    st.dataframe(
        df.sort_index(ascending=False).style.format({
            "Fiyat": "{:,.4f}", "Toplam": "{:,.2f}",
            "Komisyon": "{:,.2f}", "Adet": "{:.0f}"
        }),
        use_container_width=True
    )
