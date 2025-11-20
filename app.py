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
st.set_page_config(layout="wide", page_title="Portfoy v25")

# 👇👇👇 BURAYI DOLDURUN 👇👇👇
SHEET_ID = "1_isL5_B9EiyLppqdP4xML9N4_pLdvgNYIei70H5yiew"
# 👆👆👆 ------------------ 👆👆👆

DATA_FILE = "portfolio_transactions.csv"
JSON_FILE = "service_account.json"

# --- AKILLI SAYI DÖNÜŞTÜRÜCÜ ---
def safe_float(val):
    if val is None or val == "": return 0.0
    val_str = str(val).strip()
    # 1.234.567,89 formatı için noktaları sil
    if "." in val_str and "," in val_str:
        val_str = val_str.replace(".", "")
    # Virgülü noktaya çevir
    val_str = val_str.replace(",", ".")
    try:
        return float(val_str)
    except:
        return 0.0

# --- GOOGLE BAĞLANTISI ---
@st.cache_resource
def init_connection():
    scopes = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
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
        raw_data = sheet.get_all_values()
        if len(raw_data) < 2: return pd.DataFrame()
        
        header = raw_data[0]
        rows = raw_data[1:]
        df = pd.DataFrame(rows, columns=header)
        
        cols = ["Adet", "Fiyat", "Komisyon", "Toplam"]
        for c in cols:
            if c in df.columns:
                df[c] = df[c].apply(safe_float)
        return df
    except:
        return pd.DataFrame()

def save_transaction(veri):
    client = init_connection()
    sheet = client.open_by_key(SHEET_ID).worksheet("Islemler")
    
    row = [
        veri["Tarih"], veri["Tur"], veri["Islem"], 
        veri["Sembol"], veri["Adet"], 
        str(veri["Fiyat"]).replace(".", ","),
        str(veri["Komisyon"]).replace(".", ","),
        str(veri["Toplam"]).replace(".", ",")
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
        raw_data = sheet.get_all_values()
        fiyat_dict = {}
        for row in raw_data[1:]:
            if len(row) >= 2:
                sembol = str(row[0])
                fiyat_dict[sembol] = safe_float(row[1])
        return fiyat_dict
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
                tutar = adet * fiyat
                toplam = 0.0
                if yon == "Alış":
                    toplam = tutar + kom
                else:
                    toplam = tutar - kom
                
                yeni = {}
                yeni["Tarih"] = tarih.strftime("%Y-%m-%d")
                yeni["Tur"] = "Hisse" if tur == "Hisse Senedi" else "Fon"
                yeni["Islem"] = yon
                yeni["Sembol"] = kod
                yeni["Adet"] = adet
                yeni["Fiyat"] = fiyat
                yeni["Komisyon"] = kom
                yeni["Toplam"] = toplam
                
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
            # Anlık Durum Değişkenleri
            top_v = 0
            top_m = 0
            
            for i, r in edited.iterrows():
                pd_val = r["Adet"] * safe_float(r["Güncel Fiyat"])
                md_val = safe_float(r["Toplam Maliyet"])
                ktl = pd_val - md_val
                ky = (ktl/md_val)*100 if md_val > 0 else 0
                
                top_v += pd_val
                top_m += md_val
                
                satir = {}
                satir["Varlık"] = r["Sembol"]
                satir["Toplam Maliyet"] = md_val
                satir["Değer"] = pd_val
                satir["K/Z (TL)"] = ktl
                satir["K/Z (%)"] = ky
                res.append(satir)
            
            st.markdown("### 📊 Portföy Detayı")
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
            
            # --- GELİŞMİŞ ANA PARA HESABI ---
            # 1. Tüm zamanlarda cepten çıkan toplam para (Alışlar)
            toplam_giren = df[df["Islem"] == "Alış"]["Toplam"].sum()
            
            # 2. Cebe geri giren toplam para (Satışlar)
            toplam_cikan = df[df["Islem"] == "Satış"]["Toplam"].sum()
            
            # 3. Net İçerideki Ana Para
            net_ana_para = toplam_giren - toplam_cikan
            
            # 4. Gerçekleşmiş + Gerçekleşmemiş Genel Kar
            genel_kar_tl = top_v - net_ana_para
            
            genel_kar_yuzde = 0
            if net_ana_para > 0:
                genel_kar_yuzde = (genel_kar_tl / net_ana_para) * 100
            
            # --- GÖSTERGE PANELİ ---
            # 5 Kolonlu yapı
            k1, k2, k3, k4, k5 = st.columns(5)
            
            k1.metric("Portföy Değeri", f"{top_v:,.2f}", help="Şu anki varlıklarınızın toplam değeri")
            k2.metric("Mevcut Maliyet", f"{top_m:,.2f}", help="Sadece elinizde kalan hisselerin maliyeti")
            
            # Anlık Kar (Sadece eldekiler)
            anlik_kar = top_v - top_m
            k3.metric("Anlık K/Z", f"{anlik_kar:+,.2f}", delta=None)
            
            # Genel Durum
            k4.metric("Net Ana Para", f"{net_ana_para:,.2f}", help="Toplam yatırdığınız eksi çektiğiniz para")
            k5.metric("GENEL TOPLAM KAR", f"{genel_kar_tl:+,.2f}", delta=f"%{genel_kar_yuzde:+.2f}", help="Geçmiş karlar dahil toplam durum")

# --- TAB 3 ---
with tab3:
    st.dataframe(
        df.sort_index(ascending=False).style.format({
            "Fiyat": "{:,.4f}",
            "Toplam": "{:,.2f}",
            "Komisyon": "{:,.2f}",
            "Adet": "{:.0f}"
        }), 
        use_container_width=True
    )