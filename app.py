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
st.set_page_config(layout="wide", page_title="Portfoy v21")

# 👇👇👇 BURAYI DOLDURUN 👇👇👇
SHEET_ID = "1_isL5_B9EiyLppqdP4xML9N4_pLdvgNYIei70H5yiew"
# 👆👆👆 ------------------ 👆👆👆

DATA_FILE = "portfolio_transactions.csv"
JSON_FILE = "service_account.json"

# --- AKILLI SAYI DÖNÜŞTÜRÜCÜ ---
def safe_float(val):
    if val is None or val == "":
        return 0.0
    if isinstance(val, (int, float)):
        return float(val)
    val_str = str(val).strip()
    val_str = val_str.replace(",", ".")
    try:
        return float(val_str)
    except:
        return 0.0

# --- GOOGLE BAĞLANTISI ---
@st.cache_resource
def init_connection():
    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive"
    ]
    
    if os.path.exists(JSON_FILE):
        creds = Credentials.from_service_account_file(
            JSON_FILE, 
            scopes=scopes
        )
    else:
        try:
            info = dict(st.secrets["gcp_service_account"])
            if "private_key" in info:
                info["private_key"] = info["private_key"].replace("\\n", "\n")
            
            creds = Credentials.from_service_account_info(
                info, 
                scopes=scopes
            )
        except Exception as e:
            st.error(f"Anahtar Hatası: {e}")
            st.stop()
            
    return gspread.authorize(creds)

# --- VERİ İŞLEMLERİ ---
def get_data():
    client = init_connection()
    try:
        sheet = client.open_by_key(SHEET_ID).worksheet("Islemler")
        data = sheet.get_all_records()
        df = pd.DataFrame(data)
        
        # Sayı düzeltme
        cols = ["Adet", "Fiyat", "Komisyon", "Toplam"]
        for c in cols:
            if c in df.columns:
                df[c] = df[c].apply(safe_float)
        return df
    except Exception as e:
        st.error(f"Bağlantı Hatası: {e}")
        st.stop()

def save_transaction(yeni_veri):
    client = init_connection()
    sheet = client.open_by_key(SHEET_ID).worksheet("Islemler")
    
    row = [
        yeni_veri["Tarih"],
        yeni_veri["Tur"],
        yeni_veri["Islem"],
        yeni_veri["Sembol"],
        yeni_veri["Adet"],
        float(yeni_veri["Fiyat"]),
        float(yeni_veri["Komisyon"]),
        float(yeni_veri["Toplam"])
    ]
    sheet.append_row(row)
    
    try:
        p_sheet = client.open_by_key(SHEET_ID).worksheet("Fiyatlar")
        exist = p_sheet.col_values(1)
        if yeni_veri["Sembol"] not in exist:
            p_sheet.append_row([yeni_veri["Sembol"], 0, ""])
    except:
        pass

def get_fund_prices():
    client = init_connection()
    try:
        sheet = client.open_by_key(SHEET_ID).worksheet("Fiyatlar")
        data = sheet.get_all_records()
        return {str(r["Sembol"]): safe_float(r["Fiyat"]) for r in data}
    except:
        return {}

# --- YARDIMCI ---
@st.cache_data(ttl=300)
def get_stock_price(symbol):
    try:
        symbol = symbol.upper()
        if not symbol.endswith(".IS"): symbol = symbol + ".IS"
        val = yf.Ticker(symbol).fast_info['last_price']
        return val if val is not None else 0.0
    except:
        return 0.0

def renk(val):
    c = 'white'
    if val > 0: c = '#2ecc71'
    if val < 0: c = '#e74c3c'
    return f'color: {c}; font-weight: bold;'

# --- ARAYÜZ ---
st.title("☁️ Bulut Portföy")

try:
    df = get_data()
except:
    st.stop()

tab1, tab2, tab3 = st.tabs(["➕ EKLE", "📊 PORTFÖY", "📋 GEÇMİŞ"])

# --- TAB 1 ---
with tab1:
    with st.form("ekle", clear_on_submit=True):
        c1, c2 = st.columns(2)
        tur = c1.radio("Tür", ["Hisse Senedi", "Yatırım Fonu"], horizontal=True)
        yon = c2.radio("Yön", ["Alış", "Satış"], horizontal=True)
        
        ca, cb = st.columns(2)
        tarih = ca.date_input("Tarih", datetime.now())
        kod = cb.text_input("Kod").upper()
        
        cc, cd, ce = st.columns(3)
        adet = cc.number_input("Adet", min_value=1, step=1)
        
        # -- GÜNCELLEME: ALT ALTA YAZDIM Kİ HATA OLMASIN --
        fiyat = cd.number_input(
            "Fiyat", 
            min_value=0.0, 
            format="%.6f"
        )
        kom = ce.number_input(
            "Komisyon", 
            min_value=0.0, 
            format="%.2f"
        )
        # -------------------------------------------------
        
        if st.form_submit_button("KAYDET"):
            if kod and fiyat > 0:
                tutar = adet * fiyat
                toplam = 0.0
                if yon == "Alış":
                    toplam = tutar + kom
                else:
                    toplam = tutar - kom
                
                yeni = {
                    "Tarih": tarih.strftime("%Y-%m-%d"),
                    "Tur": "Hisse" if tur == "Hisse Senedi" else "Fon",