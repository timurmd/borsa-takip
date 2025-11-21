import streamlit as st
import pandas as pd
import yfinance as yf
from datetime import datetime, timedelta
import os
import warnings
import gspread
from google.oauth2.service_account import Credentials
import plotly.express as px

# Uyarıları sustur
warnings.simplefilter(action='ignore', category=FutureWarning)

# --- AYARLAR ---
st.set_page_config(layout="wide", page_title="Portfoy v32")

# 👇👇👇 BURAYI DOLDURUN 👇👇👇
SHEET_ID = "1_isL5_B9EiyLppqdP4xML9N4_pLdvgNYIei70H5yiew"
# 👆👆👆 ------------------ 👆👆👆

DATA_FILE = "portfolio_transactions.csv"
JSON_FILE = "service_account.json"

# --- AKILLI SAYI DÖNÜŞTÜRÜCÜ ---
def safe_float(val):
    if val is None or val == "": return 0.0
    if isinstance(val, (int, float)): return float(val)
    val_str = str(val).strip()
    if "." in val_str and "," in val_str:
        val_str = val_str.replace(".", "")
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
        
        df["Tarih"] = pd.to_datetime(df["Tarih"], dayfirst=False, errors='coerce')
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

# --- PİYASA VE KIYASLAMA ---
@st.cache_data(ttl=3600)
def get_historical_market_data():
    end_date = datetime.now()
    start_date = end_date - timedelta(days=365*5)
    
    usd_df = yf.download("USDTRY=X", start=start_date, end=end_date, progress=False)
    usd_df = usd_df['Close'].reset_index()
    usd_df.columns = ['Date', 'USD']
    usd_df['Date'] = pd.to_datetime(usd_df['Date']).dt.date
    
    gold_df = yf.download("GC=F", start=start_date, end=end_date, progress=False)
    gold_df = gold_df['Close'].reset_index()
    gold_df.columns = ['Date', 'Gold_Ounce']
    gold_df['Date'] = pd.to_datetime(gold_df['Date']).dt.date
    
    market = pd.merge(usd_df, gold_df, on='Date', how='outer').sort_values('Date').ffill()
    market['Gram_Gold'] = (market['Gold_Ounce'] * market['USD']) / 31.1035
    market.set_index('Date', inplace=True)
    return market

def calculate_benchmarks(df_transactions):
    market = get_historical_market_data()
    
    shadow_usd_qty = 0 # Toplam biriken Dolar ADEDİ
    shadow_gold_qty = 0
    
    df_sorted = df_transactions.sort_values("Tarih")
    
    for _, row in df_sorted.iterrows():
        t_date = row["Tarih"].date()
        t_tutar = float(row["Toplam"])
        
        try:
            idx = market.index.asof(t_date)
            day_rates = market.loc[idx]
            usd_rate = day_rates['USD']
            gold_rate = day_rates['Gram_Gold']
        except:
            continue
            
        if row["Islem"] == "Alış":
            shadow_usd_qty += t_tutar / usd_rate
            shadow_gold_qty += t_tutar / gold_rate
        elif row["Islem"] == "Satış":
            shadow_usd_qty -= t_tutar / usd_rate
            shadow_gold_qty -= t_tutar / gold_rate
            
    try:
        last_rates = market.iloc[-1]
        current_usd_try_val = shadow_usd_qty * last_rates['USD']
        current_gold_try_val = shadow_gold_qty * last_rates['Gram_Gold']
        # Hem TL karşılıklarını hem de Net Miktarları döndür
        return current_usd_try_val, current_gold_try_val, shadow_usd_qty, shadow_gold_qty
    except:
        return 0, 0, 0, 0

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

@st.cache_data(ttl=3600)
def get_usd_rate():
    try:
        return yf.Ticker("USDTRY=X").fast_info['last_price']
    except:
        return 1.0

def renk(val):
    c = 'white'
    if val > 0: c = '#2ecc71'
    if val < 0: c = '#e74c3c'
    return f'color: {c}; font-weight: bold;'

# --- ARAYÜZ ---
st.title("☁️ Bulut Portföy & Analiz")

# GÜVENLİK
def check_password():
    if "password_correct" not in st.session_state:
        st.text_input("Şifre", type="password", key="password", on_change=password_entered)
        return False
    return st.session_state["password_correct"]

def password_entered():
    if st.session_state["password"] == st.secrets["app_password"]:
        st.session_state["password_correct"] = True
        del st.session_state["password"]
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

tab1, tab2, tab3 = st.tabs(["➕ EKLE", "📊 PORTFÖY", "📋 GEÇMİŞ"])

# --- TAB 1: EKLEME & SİLME ---
with tab1:
    col_ekle, col_sil = st.columns([2, 1])

    with col_ekle:
        st.subheader("Yeni İşlem")
        giris_yontemi = st.radio("Yöntem:", ["Birim Fiyat", "Toplam Tutar (Net)"], horizontal=True)
        st.markdown("---")

        with st.form("ekle", clear_on_submit=True):
            c1, c2 = st.columns(2)
            tur = c1.radio("Tür", ["Hisse Senedi", "Yatırım Fonu"], horizontal=True)
            yon = c2.radio("Yön", ["Alış", "Satış"], horizontal=True)
            
            ca, cb = st.columns(2)
            tarih = ca.date_input("Tarih", datetime.now())
            kod = cb.text_input("Kod").upper()
            
            adet = st.number_input("Adet", min_value=1, step=1)
            
            fiyat = 0.0
            kom = 0.0
            toplam = 0.0
            
            cc, cd = st.columns(2)
            
            if giris_yontemi == "Birim Fiyat":
                fiyat = cc.number_input("Fiyat", min_value=0.0, format="%.6f")
                kom = cd.number_input("Komisyon", min_value=0.0, format="%.2f")
            else:
                toplam_girilen = cc.number_input("Net Tutar", min_value=0.0, format="%.2f")
            
            if st.form_submit_button("KAYDET"):
                if kod and adet > 0:
                    if giris_yontemi == "Birim Fiyat":
                        if fiyat > 0:
                            raw = adet * fiyat
                            toplam = raw + kom if yon == "Alış" else raw - kom
                        else: st.stop()
                    else:
                        if toplam_girilen > 0:
                            toplam = toplam_girilen
                            fiyat = toplam_girilen / adet
                            kom = 0
                        else: st.stop()
                    
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
                        st.success("Tamam!")
                        st.cache_data.clear()
                        st.rerun()

    with col_sil:
        st.subheader("Silme")
        try:
            df_sil = get_data()
            if not df_sil.empty:
                st.dataframe(df_sil.tail(5)[["Sembol", "Islem", "Toplam"]], use_container_width=True)
                secilen = st.selectbox("Sil ID:", df_sil.index.sort_values(ascending=False))
                if st.button("Sil"):
                    client = init_connection()
                    sheet = client.open_by_key(SHEET_ID).worksheet("Islemler")
                    sheet.delete_rows(int(secilen) + 2)
                    st.success("Silindi!")
                    st.cache_data.clear()
                    st.rerun()
        except: pass

# --- TAB 2 ---
with tab2:
    if st.button("🔄 Yenile"):
        st.cache_data.clear()
        st.rerun()

    if df.empty:
        st.info("Veri yok.")
    else:
        sheet_fiyat = get_fund_prices()
        dolar_kuru = get_usd_rate()
        
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
                item["Piyasa Değeri"] = float(net * guncel)
                liste.append(item)
        
        if liste:
            df_v = pd.DataFrame(liste)
            
            # --- HESAPLAMALAR ---
            # 1. Kıyaslama Verilerini (Ham Dolar Miktarlarını da) Al
            alt_usd_tl, alt_gold_tl, net_usd_adet, net_gold_adet = calculate_benchmarks(df)
            
            toplam_varlik = df_v["Piyasa Değeri"].sum()
            anlik_portfoy_usd = toplam_varlik / dolar_kuru if dolar_kuru > 0 else 0
            
            # Grafik Verisi
            benchmark_data = pd.DataFrame({
                "Varlık": ["Sizin Portföy", "Dolar Olsaydı", "Altın Olsaydı"],
                "Değer (TL)": [toplam_varlik, alt_usd_tl, alt_gold_tl],
                "Renk": ["blue", "green", "gold"]
            })
            
            col_grafik1, col_grafik2 = st.columns(2)
            
            with col_grafik1:
                st.subheader("Dağılım (Pasta)")
                fig1 = px.pie(df_v, values='Piyasa Değeri', names='Sembol', hole=0.4)
                st.plotly_chart(fig1, use_container_width=True)
            
            with col_grafik2:
                st.subheader("Kıyaslama (Benchmark)")
                fig2 = px.bar(
                    benchmark_data, 
                    x="Varlık", 
                    y="Değer (TL)", 
                    color="Varlık",
                    text_auto='.2s',
                    color_discrete_map={"Sizin Portföy": "#3498db", "Dolar Olsaydı": "#2ecc71", "Altın Olsaydı": "#f1c40f"}
                )
                st.plotly_chart(fig2, use_container_width=True)
            
            # --- TABLO ---
            cfg = {}
            cfg["Sembol"] = st.column_config.TextColumn("Varlık", disabled=True)
            cfg["Adet"] = st.column_config.NumberColumn("Adet", format="%.0f", disabled=True)
            cfg["Güncel Fiyat"] = st.column_config.NumberColumn("Fiyat", format="%.4f")
            cfg["Toplam Maliyet"] = st.column_config.NumberColumn("Maliyet", format="%.2f", disabled=True)
            cfg["Tur"] = None
            cfg["Not"] = None
            cfg["Piyasa Değeri"] = None
            
            edited = st.data_editor(
                df_v, 
                column_config=cfg, 
                use_container_width=True, 
                hide_index=True, 
                key="gs_edit"
            )
            
            res = []
            tv = 0; tm = 0
            for i, r in edited.iterrows():
                pd_val = r["Adet"] * safe_float(r["Güncel Fiyat"])
                md_val = safe_float(r["Toplam Maliyet"])
                ktl = pd_val - md_val
                ky = (ktl/md_val)*100 if md_val > 0 else 0
                tv += pd_val; tm += md_val
                
                satir = {}
                satir["Varlık"] = r["Sembol"]
                satir["Toplam Maliyet"] = md_val
                satir["Değer"] = pd_val
                satir["K/Z (TL)"] = ktl
                satir["K/Z (%)"] = ky
                res.append(satir)
            
            st.divider()
            st.dataframe(
                pd.DataFrame(res).style.format({
                    "Toplam Maliyet": "{:,.2f}", "Değer": "{:,.2f}",
                    "K/Z (TL)": "{:+,.2f}", "K/Z (%)": "{:+.2f} %"
                }).map(renk, subset=["K/Z (TL)", "K/Z (%)"]),
                use_container_width=True, hide_index=True
            )
            
            st.divider()
            
            # Genel Hesaplar
            df_alis = df[df["Islem"] == "Alış"]
            df_satis = df[df["Islem"] == "Satış"]
            giren = df_alis["Toplam"].sum()
            cikan = df_satis["Toplam"].sum()
            net_ana = giren - cikan
            genel_kar = tv - net_ana
            genel_yuzde = (genel_kar / net_ana) * 100 if net_ana > 0 else 0
            
            # GÜNCELLENMİŞ PANEL (DOLARLI)
            k1, k2, k3, k4, k5 = st.columns(5)
            
            # 1. Portföy Değeri (Altında Dolar Karşılığı)
            k1.metric("Portföy", f"{tv:,.0f} ₺", f"${anlik_portfoy_usd:,.0f}", delta_color="off")
            
            # 2. Anlık Maliyet
            k2.metric("Eldeki Maliyet", f"{tm:,.0f} ₺")
            
            # 3. Anlık Kar
            k3.metric("Anlık K/Z", f"{tv-tm:+,.0f} ₺")
            
            # 4. Net Ana Para (Altında Dolar Maliyeti)
            # delta_color="off" gri yapar, "normal" veya "inverse" renkli yapar.
            # Gri yapmak için "off" kullanıyoruz ki artış azalış gibi durmasın.
            k4.metric("Net Ana Para", f"{net_ana:,.0f} ₺", f"${net_usd_adet:,.0f}", delta_color="off", help="Ana paranızın o günkü kurla Dolar karşılığı")
            
            # 5. Genel Kar
            k5.metric("GENEL KAR", f"{genel_kar:+,.0f} ₺", delta=f"%{genel_yuzde:.1f}")

# --- TAB 3 ---
with tab3:
    st.dataframe(
        df.sort_index(ascending=False).style.format({
            "Fiyat": "{:,.4f}", "Toplam": "{:,.2f}",
            "Komisyon": "{:,.2f}", "Adet": "{:.0f}"
        }), 
        use_container_width=True
    )