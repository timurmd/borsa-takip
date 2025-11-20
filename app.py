import streamlit as st
import pandas as pd
import yfinance as yf
from datetime import datetime
import os
import warnings
import gspread
from google.oauth2.service_account import Credentials

# Uyarıları sustur
warnings.simplefilter(action='ignore', category=FutureWarning)

# --- AYARLAR ---
st.set_page_config(layout="wide", page_title="Portfoy v20")

# 👇👇👇 BURAYI DOLDURMAYI UNUTMAYIN 👇👇👇
SHEET_ID = "1_isL5_B9EiyLppqdP4xML9N4_pLdvgNYIei70H5yiew" 
# 👆👆👆 --------------------------------- 👆👆👆

DATA_FILE = "portfolio_transactions.csv"
JSON_FILE = "service_account.json"

# --- AKILLI SAYI DÖNÜŞTÜRÜCÜ (YENİ) ---
def safe_float(val):
    """Virgüllü veya noktalı sayıyı Python formatına çevirir"""
    if val is None or val == "":
        return 0.0
    if isinstance(val, (int, float)):
        return float(val)
    
    # String ise temizle
    val_str = str(val).strip()
    # Virgülü noktaya çevir
    val_str = val_str.replace(",", ".")
    try:
        return float(val_str)
    except:
        return 0.0

# --- GOOGLE SHEETS BAĞLANTISI ---
@st.cache_resource
def init_connection():
    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive"
    ]
    
    if os.path.exists(JSON_FILE):
        creds = Credentials.from_service_account_file(JSON_FILE, scopes=scopes)
    else:
        try:
            info = dict(st.secrets["gcp_service_account"])
            if "private_key" in info:
                info["private_key"] = info["private_key"].replace("\\n", "\n")
            creds = Credentials.from_service_account_info(info, scopes=scopes)
        except Exception as e:
            st.error(f"Anahtar Hatası: {e}")
            st.stop()
            
    client = gspread.authorize(creds)
    return client

# Veri Çekme
def get_data():
    client = init_connection()
    try:
        sheet = client.open_by_key(SHEET_ID).worksheet("Islemler")
        data = sheet.get_all_records()
        df = pd.DataFrame(data)
        
        # Verileri çekerken sayıları düzeltelim
        cols_to_fix = ["Adet", "Fiyat", "Komisyon", "Toplam"]
        for col in cols_to_fix:
            if col in df.columns:
                df[col] = df[col].apply(safe_float)
                
        return df
    except Exception as e:
        st.error(f"Bağlantı Hatası: {e}")
        st.stop()

# Veri Kaydetme
def save_transaction(yeni_veri):
    client = init_connection()
    sheet = client.open_by_key(SHEET_ID).worksheet("Islemler")
    
    # Kaydederken de string olarak gönderip Google'ın anlamasını sağlayalım
    # Google Sheets'e sayı gönderirken bazen float yerine string (noktalı) göndermek daha güvenlidir
    row = [
        yeni_veri["Tarih"], yeni_veri["Tur"], yeni_veri["Islem"], 
        yeni_veri["Sembol"], 
        yeni_veri["Adet"], 
        float(yeni_veri["Fiyat"]), # Python float olarak gönder
        float(yeni_veri["Komisyon"]), 
        float(yeni_veri["Toplam"])
    ]
    sheet.append_row(row)
    
    try:
        price_sheet = client.open_by_key(SHEET_ID).worksheet("Fiyatlar")
        existing = price_sheet.col_values(1)
        if yeni_veri["Sembol"] not in existing:
            price_sheet.append_row([yeni_veri["Sembol"], 0, ""])
    except:
        pass 

# Fon Fiyatlarını Al
def get_fund_prices_from_sheet():
    client = init_connection()
    try:
        sheet = client.open_by_key(SHEET_ID).worksheet("Fiyatlar")
        data = sheet.get_all_records()
        # Fiyatları çekerken de safe_float kullanalım
        fiyat_dict = {str(row["Sembol"]): safe_float(row["Fiyat"]) for row in data}
        return fiyat_dict
    except:
        return {}

# --- DİĞER FONKSİYONLAR ---
@st.cache_data(ttl=300)
def get_stock_price(symbol):
    try:
        symbol = symbol.upper()
        if not symbol.endswith(".IS"): symbol = symbol + ".IS"
        ticker = yf.Ticker(symbol)
        val = ticker.fast_info['last_price']
        return val if val is not None else 0.0
    except:
        return 0.0

def renk(val):
    if val > 0: return 'color: #2ecc71; font-weight: bold;'
    if val < 0: return 'color: #e74c3c; font-weight: bold;'
    return 'color: white;'

# --- ARAYÜZ ---
st.title("☁️ Bulut Portföy")

try:
    df = get_data()
except:
    st.stop()

tab1, tab2, tab3 = st.tabs(["➕ İŞLEM EKLE", "📊 PORTFÖY", "📋 GEÇMİŞ"])

# --- TAB 1 ---
with tab1:
    with st.form("ekle_form", clear_on_submit=True):
        c1, c2 = st.columns(2)
        tur = c1.radio("Tür", ["Hisse Senedi", "Yatırım Fonu"], horizontal=True)
        yon = c2.radio("Yön", ["Alış", "Satış"], horizontal=True)
        
        col_a, col_b = st.columns(2)
        tarih = col_a.date_input("Tarih", datetime.now())
        kod = col_b.text_input("Kod").upper()
        
        c3, c4, c5 = st.columns(3)
        adet = c3.number_input("Adet", min_value=1, step=1)
        fiyat = c4.number_input("Fiyat", min_value=0.0, format="%.6f")
        kom = c5.number_input("Komisyon", min_value=0.