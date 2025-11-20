import streamlit as st
import pandas as pd
import yfinance as yf
from datetime import datetime
import os
import warnings
import gspread
from oauth2client.service_account import ServiceAccountCredentials

# Uyarıları sustur
warnings.simplefilter(action='ignore', category=FutureWarning)

# --- AYARLAR ---
st.set_page_config(layout="wide", page_title="Portfoy v17")
DATA_FILE = "portfolio_transactions.csv"
SHEET_NAME = "BorsaPortfoy" # Google Sheets'teki adınızla AYNI OLMALI
JSON_FILE = "service_account.json"

# --- GOOGLE SHEETS BAĞLANTISI (Tamirci Modu) ---
@st.cache_resource
def init_connection():
    scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
    
    # 1. Durum: Bilgisayarınızda (service_account.json var mı?)
    if os.path.exists(JSON_FILE):
        creds = ServiceAccountCredentials.from_json_keyfile_name(JSON_FILE, scope)
    else:
        # 2. Durum: Streamlit Cloud'da (Secrets kullan)
        try:
            # Secrets verisini normal sözlüğe çevir
            creds_dict = dict(st.secrets["gcp_service_account"])
            
            # --- KRİTİK DÜZELTME BURADA ---
            # Private Key içindeki \n karakterleri bozulduysa düzeltiyoruz
            if "private_key" in creds_dict:
                creds_dict["private_key"] = creds_dict["private_key"].replace("\\n", "\n")
            # ------------------------------
            
            creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
        except Exception as e:
            st.error(f"Bağlantı Hatası Detayı: {e}")
            st.stop()
            
    client = gspread.authorize(creds)
    return client

# Veri Çekme
def get_data():
    client = init_connection()
    try:
        sheet = client.open(SHEET_NAME).worksheet("Islemler")
        data = sheet.get_all_records()
        return pd.DataFrame(data)
    except gspread.exceptions.SpreadsheetNotFound:
        st.error(f"'{SHEET_NAME}' adında bir tablo bulunamadı! Google Sheets adını kontrol edin.")
        st.stop()
    except Exception as e:
        # Eğer tablo boşsa veya başka hata varsa boş dön
        return pd.DataFrame()

# Veri Kaydetme
def save_transaction(yeni_veri):
    client = init_connection()
    sheet = client.open(SHEET_NAME).worksheet("Islemler")
    
    # Satır hazırla
    row = [
        yeni_veri["Tarih"], yeni_veri["Tur"], yeni_veri["Islem"], 
        yeni_veri["Sembol"], yeni_veri["Adet"], yeni_veri["Fiyat"], 
        yeni_veri["Komisyon"], yeni_veri["Toplam"]
    ]
    sheet.append_row(row)
    
    # Fiyatlar sayfasına sembol ekle
    try:
        price_sheet = client.open(SHEET_NAME).worksheet("Fiyatlar")
        existing = price_sheet.col_values(1)
        if yeni_veri["Sembol"] not in existing:
            price_sheet.append_row([yeni_veri["Sembol"], 0, ""])
    except:
        pass 

# Fon Fiyatlarını Sheets'ten Al
def get_fund_prices_from_sheet():
    client = init_connection()
    try:
        sheet = client.open(SHEET_NAME).worksheet("Fiyatlar")
        data = sheet.get_all_records()
        fiyat_dict = {str(row["Sembol"]): float(row["Fiyat"]) for row in data if str(row["Fiyat"]).replace('.','',1).isdigit()}
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

# Verileri Getir
try:
    df = get_data()
except Exception as e:
    st.error("Hata oluştu.")
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
        kom = c5.number_input("Komisyon", min_value=0.0, format="%.2f")
        
        if st.form_submit_button("KAYDET"):
            if kod and fiyat > 0:
                tutar = adet * fiyat
                toplam = tutar + kom if yon == "Alış" else tutar - kom
                
                yeni = {
                    "Tarih": tarih.strftime("%Y-%m-%d"),
                    "Tur": "Hisse" if tur == "Hisse Senedi" else "Fon",
                    "Islem": yon, "Sembol": kod, "Adet": adet,
                    "Fiyat": fiyat, "Komisyon": kom, "Toplam": toplam
                }
                
                with st.spinner("Buluta kaydediliyor..."):
                    save_transaction(yeni)
                    st.success("Kaydedildi!")
                    st.cache_data.clear()
                    st.rerun()

# --- TAB 2 ---
with tab2:
    if st.button("🔄 Yenile"):
        st.cache_data.clear()
        st.rerun()

    if df.empty:
        st.info("İşlem yok.")
    else:
        sheet_fiyatlar = get_fund_prices_from_sheet()
        semboller = df["Sembol"].unique()
        liste = []
        
        for s in semboller:
            txs = df[df["Sembol"] == s]
            if txs.empty: continue
            v_tur = txs.iloc[0]["Tur"]
            
            alis = txs[txs["Islem"] == "Alış"]
            satis = txs[txs["Islem"] == "Satış"]
            net_adet = alis["Adet"].sum() - satis["Adet"].sum()
            
            if net_adet > 0:
                t_maliyet = (alis["Adet"] * alis["Fiyat"]).sum() + alis["Komisyon"].sum()
                ort_maliyet = t_maliyet / alis["Adet"].sum()
                eldeki_mal = ort_maliyet * net_adet
                
                guncel = 0.0
                notlar = ""
                
                if v_tur == "Hisse":
                    guncel = get_stock_price(s)
                else:
                    guncel = float(sheet_fiyatlar.get(s, 0))
                    if guncel == 0:
                         guncel = ort_maliyet
                         notlar = "⚠️ Bekleniyor"
                
                liste.append({
                    "Sembol": s, "Tur": v_tur, "Adet": net_adet,
                    "Not": notlar,
                    "Toplam Maliyet": float(eldeki_mal),
                    "Güncel Fiyat": float(guncel)
                })
        
        if liste:
            df_view = pd.DataFrame(liste)
            cfg = {
                "Sembol": st.column_config.TextColumn("Varlık", disabled=True),
                "Not": st.column_config.TextColumn("Durum", disabled=True),
                "Güncel Fiyat": st.column_config.NumberColumn("Fiyat", format="%.4f"),
                "Toplam Maliyet": st.column_config.NumberColumn("Maliyet", format="%.2f", disabled=True),
                "Tur": None, "Adet": None
            }
            
            edited = st.data_editor(df_view, column_config=cfg, use_container_width=True, hide_index=True, key="gs_editor")
            
            res = []
            top_v = 0; top_m = 0
            for i, row in edited.iterrows():
                p_deg = row["Adet"] * row["Güncel Fiyat"]
                m_deg = row["Toplam Maliyet"]
                kar_tl = p_deg - m_deg
                kar_y = (kar_tl / m_deg)*100 if m_deg > 0 else 0
                top_v += p_deg; top_m += m_deg
                res.append({"Varlık": row["Sembol"], "Toplam Maliyet": m_deg, "Piyasa Değeri": p_deg, "K/Z (TL)": kar_tl, "K/Z (%)": kar_y})
            
            st.markdown("### 📊 Durum")
            st_df = pd.DataFrame(res).style.format({
                "Toplam Maliyet": "{:,.2f}", "Piyasa Değeri": "{:,.2f}",
                "K/Z (TL)": "{:+,.2f}", "K/Z (%)": "{:+.2f} %"
            }).map(renk, subset=["K/Z (TL)", "K/Z (%)"])
            st.dataframe(st_df, use_container_width=True, hide_index=True)
            
            st.divider()
            net_k = top_v - top_m
            net_y = (net_k/top_m)*100 if top_m > 0 else 0
            c1, c2, c3, c4 = st.columns(4)
            c1.metric("Varlık", f"{top_v:,.2f}"); c2.metric("Maliyet", f"{top_m:,.2f}")
            c3.metric("Net K/Z", f"{net_k:+,.2f}"); c4.metric("Getiri", f"%{net_y:+.2f}")

# --- TAB 3 ---
with tab3:
    st.dataframe(df, use_container_width=True)