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
st.set_page_config(layout="wide", page_title="Portfoy v22")

# 👇👇👇 BURAYI DOLDURUN (Tırnakların arasına ID yapıştırın) 👇👇👇
SHEET_ID = "1_isL5_B9EiyLppqdP4xML9N4_pLdvgNYIei70H5yiew"
# 👆👆👆 -------------------------------------------------- 👆👆👆

DATA_FILE = "portfolio_transactions.csv"
JSON_FILE = "service_account.json"

# --- AKILLI SAYI DÖNÜŞTÜRÜCÜ ---
def safe_float(val):
    if val is None or val == "":
        return 0.0
    if isinstance(val, (int, float)):
        return float(val)
    try:
        val_str = str(val).strip().replace(",", ".")
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
        return gspread.authorize(Credentials.from_service_account_file(JSON_FILE, scopes=scopes))
    else:
        try:
            info = dict(st.secrets["gcp_service_account"])
            if "private_key" in info:
                info["private_key"] = info["private_key"].replace("\\n", "\n")
            return gspread.authorize(Credentials.from_service_account_info(info, scopes=scopes))
        except Exception as e:
            st.error(f"Anahtar Hatası: {e}")
            st.stop()

# --- VERİ İŞLEMLERİ ---
def get_data():
    client = init_connection()
    try:
        sheet = client.open_by_key(SHEET_ID).worksheet("Islemler")
        df = pd.DataFrame(sheet.get_all_records())
        cols = ["Adet", "Fiyat", "Komisyon", "Toplam"]
        for c in cols:
            if c in df.columns:
                df[c] = df[c].apply(safe_float)
        return df
    except Exception as e:
        st.error(f"Bağlantı Hatası: {e}")
        st.stop()

def save_transaction(veri):
    client = init_connection()
    sheet = client.open_by_key(SHEET_ID).worksheet("Islemler")
    
    row = [
        veri["Tarih"], veri["Tur"], veri["Islem"], 
        veri["Sembol"], veri["Adet"], 
        float(veri["Fiyat"]), float(veri["Komisyon"]), float(veri["Toplam"])
    ]
    sheet.append_row(row)
    
    try:
        p_sheet = client.open_by_key(SHEET_ID).worksheet("Fiyatlar")
        if veri["Sembol"] not in p_sheet.col_values(1):
            p_sheet.append_row([veri["Sembol"], 0, ""])
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
        fiyat = cd.number_input("Fiyat", min_value=0.0, format="%.6f")
        kom = ce.number_input("Komisyon", min_value=0.0, format="%.2f")
        
        if st.form_submit_button("KAYDET"):
            if kod and fiyat > 0:
                # Hesaplama
                tutar = adet * fiyat
                toplam = 0.0
                if yon == "Alış":
                    toplam = tutar + kom
                else:
                    toplam = tutar - kom
                
                # --- YENİ YAPI: SATIR SATIR TANIMLAMA (HATA VERMEZ) ---
                yeni = {}
                yeni["Tarih"] = tarih.strftime("%Y-%m-%d")
                if tur == "Hisse Senedi":
                    yeni["Tur"] = "Hisse"
                else:
                    yeni["Tur"] = "Fon"
                yeni["Islem"] = yon
                yeni["Sembol"] = kod
                yeni["Adet"] = adet
                yeni["Fiyat"] = fiyat
                yeni["Komisyon"] = kom
                yeni["Toplam"] = toplam
                # ------------------------------------------------------
                
                with st.spinner("Kaydediliyor..."):
                    save_transaction(yeni)
                    st.success("Tamamlandı!")
                    st.cache_data.clear()
                    st.rerun()

# --- TAB 2 ---
with tab2:
    if st.button("🔄 Yenile"):
        st.cache_data.clear()
        st.rerun()

    if df.empty:
        st.info("Veri yok.")
    else:
        sheet_fiyat = get_fund_prices()
        semboller = df["Sembol"].unique()
        liste = []
        
        for s in semboller:
            txs = df[df["Sembol"] == s]
            if txs.empty: continue
            v_tur = txs.iloc[0]["Tur"]
            
            alis = txs[txs["Islem"] == "Alış"]
            satis = txs[txs["Islem"] == "Satış"]
            net = alis["Adet"].sum() - satis["Adet"].sum()
            
            if net > 0:
                tm = (alis["Adet"] * alis["Fiyat"]).sum() + alis["Komisyon"].sum()
                om = tm / alis["Adet"].sum()
                em = om * net
                
                guncel = 0.0
                notlar = ""
                
                if v_tur == "Hisse":
                    guncel = get_stock_price(s)
                else:
                    guncel = float(sheet_fiyat.get(s, 0))
                    if guncel == 0:
                        guncel = om
                        notlar = "⚠️"
                
                # Liste Ekleme (Satır satır)
                item = {}
                item["Sembol"] = s
                item["Tur"] = v_tur
                item["Adet"] = net
                item["Not"] = notlar
                item["Toplam Maliyet"] = float(em)
                item["Güncel Fiyat"] = float(guncel)
                liste.append(item)
        
        if liste:
            df_v = pd.DataFrame(liste)
            
            # Ayarlar (Sözlük yapısı)
            cfg = {}
            cfg["Sembol"] = st.column_config.TextColumn("Varlık", disabled=True)
            cfg["Not"] = st.column_config.TextColumn("D", disabled=True)
            cfg["Güncel Fiyat"] = st.column_config.NumberColumn("Fiyat", format="%.4f")
            cfg["Toplam Maliyet"] = st.column_config.NumberColumn("Maliyet", format="%.2f", disabled=True)
            cfg["Tur"] = None
            cfg["Adet"] = None
            
            edited = st.data_editor(
                df_v, 
                column_config=cfg, 
                use_container_width=True, 
                hide_index=True, 
                key="gs_edit"
            )
            
            res = []
            tv = 0
            tm = 0
            for i, r in edited.iterrows():
                pd_val = r["Adet"] * safe_float(r["Güncel Fiyat"])
                md_val = safe_float(r["Toplam Maliyet"])
                ktl = pd_val - md_val
                ky = (ktl/md_val)*100 if md_val > 0 else 0
                tv += pd_val
                tm += md_val
                
                # Sonuç listesi (Satır satır)
                satir = {}
                satir["Varlık"] = r["Sembol"]
                satir["Toplam Maliyet"] = md_val
                satir["Değer"] = pd_val
                satir["K/Z (TL)"] = ktl
                satir["K/Z (%)"] = ky
                res.append(satir)
            
            st.markdown("### 📊 Durum")
            rdf = pd.DataFrame(res)
            fmt = {
                "Toplam Maliyet": "{:,.2f}", "Değer": "{:,.2f}",
                "K/Z (TL)": "{:+,.2f}", "K/Z (%)": "{:+.2f} %"
            }
            st.dataframe(
                rdf.style.format(fmt).map(renk, subset=["K/Z (TL)", "K/Z (%)"]),
                use_container_width=True,
                hide_index=True
            )
            
            st.divider()
            nk = tv - tm
            ny = (nk/tm)*100 if tm > 0 else 0
            k1, k2, k3, k4 = st.columns(4)
            k1.metric("Varlık", f"{tv:,.2f}")
            k2.metric("Maliyet", f"{tm:,.2f}")
            k3.metric("Net K/Z", f"{nk:+,.2f}")
            k4.metric("Getiri", f"%{ny:+.2f}")

# --- TAB 3 ---
with tab3:
    st.dataframe(df, use_container_width=True)