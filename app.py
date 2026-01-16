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

# Uyarıları sustur
warnings.simplefilter(action='ignore', category=FutureWarning)

# --- AYARLAR ---
st.set_page_config(layout="wide", page_title="Portfoy v44")

# 👇👇👇 BURAYI DOLDURUN 👇👇👇
SHEET_ID = "1_isL5_B9EiyLppqdP4xML9N4_pLdvgNYIei70H5yiew"
# 👆👆👆 ------------------ 👆👆👆

DATA_FILE = "portfolio_transactions.csv"
JSON_FILE = "service_account.json"

# --- YARDIMCI ---
def safe_float(val):
    if val is None or val == "": return 0.0
    if isinstance(val, (int, float)): return float(val)
    val_str = str(val).strip()
    if "." in val_str and "," in val_str: val_str = val_str.replace(".", "")
    val_str = val_str.replace(",", ".")
    try: return float(val_str)
    except: return 0.0

# --- RENKLENDİRME ---
def renk(val):
    c = ''
    if isinstance(val, (int, float)):
        if val > 0: c = '#2ecc71' # Yeşil
        elif val < 0: c = '#e74c3c' # Kırmızı
    elif isinstance(val, str):
        if val.startswith('+'): c = '#2ecc71'
        elif val.startswith('-'): c = '#e74c3c'
        elif val == "BEDAVA": c = '#3498db' # Mavi (Sıfır Maliyet)
    
    if c: return f'color: {c}; font-weight: bold;'
    return ''

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
            st.error(f"Hata: {e}")
            st.stop()

# --- VERİ İŞLEMLERİ ---
def get_data():
    client = init_connection()
    try:
        sheet = client.open_by_key(SHEET_ID).worksheet("Islemler")
        raw = sheet.get_all_values()
        if len(raw) < 2: return pd.DataFrame()
        df = pd.DataFrame(raw[1:], columns=raw[0])
        for c in ["Adet", "Fiyat", "Komisyon", "Toplam"]:
            if c in df.columns: df[c] = df[c].apply(safe_float)
        df["Tarih"] = pd.to_datetime(df["Tarih"], dayfirst=False, errors='coerce')
        if "Sembol" in df.columns:
            df["Sembol"] = df["Sembol"].astype(str).str.strip().str.upper().str.replace(".IS", "")
        return df
    except: return pd.DataFrame()

def save_transaction(veri):
    client = init_connection()
    sheet = client.open_by_key(SHEET_ID).worksheet("Islemler")
    row = [
        veri["Tarih"], veri["Tur"], veri["Islem"], veri["Sembol"], veri["Adet"], 
        str(veri["Fiyat"]).replace(".", ","), str(veri["Komisyon"]).replace(".", ","), str(veri["Toplam"]).replace(".", ",")
    ]
    sheet.append_row(row)
    try:
        p_sheet = client.open_by_key(SHEET_ID).worksheet("Fiyatlar")
        vals = [str(x).strip().upper() for x in p_sheet.col_values(1)]
        if veri["Sembol"] not in vals: p_sheet.append_row([veri["Sembol"], 0, 0])
    except: pass

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
    except: return {}

def save_daily_snapshot(tv, net_ana_para, dk):
    client = init_connection()
    try: 
        try: sheet = client.open_by_key(SHEET_ID).worksheet("Gecmis")
        except: 
            sheet = client.open_by_key(SHEET_ID).add_worksheet("Gecmis", 1000, 5)
            sheet.append_row(["Tarih", "ToplamVarlik", "NetAnaPara", "DolarKuru"])
    except: return

    bugun = datetime.now().strftime("%Y-%m-%d")
    dates = sheet.col_values(1)
    
    d = [bugun, str(tv).replace(".", ","), str(net_ana_para).replace(".", ","), str(dk).replace(".", ",")]
    
    if bugun not in dates: sheet.append_row(d)
    else:
        idx = dates.index(bugun) + 1
        for i, val in enumerate(d[1:]): sheet.update_cell(idx, i+2, val)

def get_history_data():
    client = init_connection()
    try:
        sheet = client.open_by_key(SHEET_ID).worksheet("Gecmis")
        raw = sheet.get_all_values()
        if len(raw) < 2: return pd.DataFrame()
        df = pd.DataFrame(raw[1:], columns=raw[0])
        cols = ["ToplamVarlik", "NetAnaPara", "DolarKuru"]
        for c in cols:
            if c in df.columns: df[c] = df[c].apply(safe_float)
            else: df[c] = 0.0
        df["Tarih"] = pd.to_datetime(df["Tarih"])
        return df.sort_values("Tarih", ascending=True)
    except: return pd.DataFrame()

# --- PİYASA ---
@st.cache_data(ttl=3600)
def get_historical_market_data():
    end = datetime.now(); start = end - timedelta(days=365*5)
    usd = yf.download("USDTRY=X", start=start, end=end, progress=False)
    gold = yf.download("GC=F", start=start, end=end, progress=False)
    if usd.empty or gold.empty: return pd.DataFrame()
    usd = usd['Close'].reset_index(); usd.columns=['Date','USD']; usd['Date']=pd.to_datetime(usd['Date']).dt.date
    gold = gold['Close'].reset_index(); gold.columns=['Date','Gold_Ounce']; gold['Date']=pd.to_datetime(gold['Date']).dt.date
    m = pd.merge(usd, gold, on='Date', how='outer').sort_values('Date').ffill()
    m['Gram_Gold'] = (m['Gold_Ounce']*m['USD'])/31.1035
    m.set_index('Date', inplace=True)
    return m

def calculate_benchmarks(df_transactions):
    m = get_historical_market_data()
    if m.empty: return 0, 0, 0, 0
    s_usd = 0; s_gold = 0
    df_s = df_transactions.sort_values("Tarih")
    for _, r in df_s.iterrows():
        try:
            day = m.loc[m.index.asof(r["Tarih"].date())]
            usd = day['USD']; gold = day['Gram_Gold']
            amt = float(r["Toplam"])
            if r["Islem"] == "Alış": s_usd+=amt/usd; s_gold+=amt/gold
            else: s_usd-=amt/usd; s_gold-=amt/gold
        except: continue
    try:
        last = m.iloc[-1]
        return s_usd*last['USD'], s_gold*last['Gram_Gold'], s_usd, s_gold
    except: return 0,0,0,0

@st.cache_data(ttl=300)
def get_stock_data_full(symbol):
    try:
        s = symbol.strip().upper()
        if not s.endswith(".IS"): s += ".IS"
        info = yf.Ticker(s).fast_info
        return info['last_price'], info['previous_close']
    except: return 0.0, 0.0

@st.cache_data(ttl=3600)
def get_usd_rate():
    try: return yf.Ticker("USDTRY=X").fast_info['last_price']
    except: return 1.0

# --- SIFIR MALİYET MOTORU ---
def calculate_zero_cost_portfolio(df):
    """
    Bu fonksiyon her hisse için:
    (Toplam Alış Parası - Toplam Satış Parası) hesabı yapar.
    Eğer sonuç negatifse (Satış > Alış), o hissenin maliyeti 0 kabul edilir.
    """
    portfolio = {}
    df = df.sort_values("Tarih")
    
    for _, row in df.iterrows():
        sym = row["Sembol"]; typ = row["Tur"]; islem = row["Islem"]; qty = row["Adet"]; total = row["Toplam"]
        
        if sym not in portfolio: 
            portfolio[sym] = {"Adet": 0, "NetGiris": 0.0, "Tur": typ}
        
        if islem == "Alış":
            portfolio[sym]["Adet"] += qty
            portfolio[sym]["NetGiris"] += total # Kasadan para çıktı (Yatırım)
        elif islem == "Satış":
            portfolio[sym]["Adet"] -= qty
            portfolio[sym]["NetGiris"] -= total # Kasaya para girdi (Geri Dönüş)
            
        # Eğer adet sıfırlandıysa defteri temizle
        if portfolio[sym]["Adet"] <= 0.001:
            portfolio[sym]["Adet"] = 0
            portfolio[sym]["NetGiris"] = 0 

    return portfolio

# --- ARAYÜZ ---
st.title("☁️ Bulut Portföy & Analiz")

def check_password():
    if "password_correct" not in st.session_state:
        st.text_input("Şifre", type="password", key="pwd", on_change=pwd_entered); return False
    return st.session_state["password_correct"]
def pwd_entered():
    if st.session_state["pwd"] == st.secrets["app_password"]:
        st.session_state["password_correct"] = True; del st.session_state["pwd"]
    else: st.session_state["password_correct"] = False

if not check_password(): st.stop()
if st.sidebar.button("🔒 Çıkış"): del st.session_state["password_correct"]; st.rerun()

try: df = get_data()
except: st.stop()

tab1, tab2, tab3, tab4 = st.tabs(["➕ EKLE", "📊 PORTFÖY", "📈 GİDİŞAT", "📋 GEÇMİŞ"])

with tab1:
    col_ekle, col_sil = st.columns([2, 1])
    with col_ekle:
        st.subheader("Yeni İşlem")
        metod = st.radio("Yöntem:", ["Birim Fiyat", "Toplam Tutar"], horizontal=True)
        st.markdown("---")
        with st.form("ekle", clear_on_submit=True):
            c1, c2 = st.columns(2)
            tur = c1.radio("Tür", ["Hisse Senedi", "Yatırım Fonu"], horizontal=True)
            yon = c2.radio("Yön", ["Alış", "Satış"], horizontal=True)
            ca, cb = st.columns(2)
            tarih = ca.date_input("Tarih", datetime.now())
            kod = cb.text_input("Kod").upper()
            adet = st.number_input("Adet", min_value=1, step=1)
            fiyat = 0.0; kom = 0.0; toplam = 0.0
            cc, cd = st.columns(2)
            if metod == "Birim Fiyat":
                fiyat = cc.number_input("Fiyat", min_value=0.0, format="%.6f")
                kom = cd.number_input("Komisyon", min_value=0.0, format="%.2f")
            else:
                toplam_girilen = cc.number_input("Net Tutar", min_value=0.0, format="%.2f")
            
            if st.form_submit_button("KAYDET"):
                if kod and adet > 0:
                    if metod == "Birim Fiyat":
                        if fiyat > 0:
                            raw = adet * fiyat
                            toplam = raw + kom if yon == "Alış" else raw - kom
                        else: st.stop()
                    else:
                        if toplam_girilen > 0:
                            toplam = toplam_girilen
                            fiyat = toplam_girilen / adet; kom = 0
                        else: st.stop()
                    yeni = {"Tarih": tarih.strftime("%Y-%m-%d"), "Tur": "Hisse" if tur == "Hisse Senedi" else "Fon",
                            "Islem": yon, "Sembol": kod, "Adet": adet, "Fiyat": fiyat, "Komisyon": kom, "Toplam": toplam}
                    with st.spinner("Kaydediliyor..."):
                        save_transaction(yeni); st.success("Tamam!"); st.cache_data.clear(); st.rerun()
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
                    st.success("Silindi!"); st.cache_data.clear(); st.rerun()
        except: pass

with tab2:
    if st.button("🔄 Yenile"): st.cache_data.clear(); st.rerun()
    if df.empty: st.info("Veri yok.")
    else:
        # SIFIR MALİYET MANTIĞI
        portfolio_state = calculate_zero_cost_portfolio(df)
        fund_data = get_fund_data_from_sheet()
        dolar = get_usd_rate()
        liste = []
        
        toplam_risk = 0.0 # İçeride kalan net para
        
        for sym, data in portfolio_state.items():
            net = data["Adet"]
            if net > 0:
                net_giris = data["NetGiris"] # Bu hisse için hala içeride ne kadar paramız var?
                v_tur = data["Tur"]
                guncel = 0.0; ref_fiyat = 0.0
                
                # Fiyat Çekme
                if v_tur == "Hisse":
                    curr_p, prev_p = get_stock_data_full(sym)
                    guncel = curr_p; ref_fiyat = prev_p if prev_p else curr_p
                else:
                    f_info = fund_data.get(sym, {"fiyat": 0, "yuzde": 0})
                    guncel = f_info["fiyat"]
                    pct = f_info["yuzde"]
                    if guncel == 0 and net > 0: guncel = net_giris / net # Fiyat yoksa maliyetten uydur
                    ref_fiyat = guncel / (1 + (pct/100)) if guncel else 0
                
                toplam_deger = net * guncel
                
                # --- SIFIR MALİYET HESABI ---
                if net_giris <= 0:
                    # Satışlar maliyeti çıkarmış, hatta kar edilmiş.
                    # Bu artık BEDAVA hısse.
                    maliyet_gorunum = "BEDAVA" # Tabloda yazı yazacak
                    kar_zarar = toplam_deger # Tamamı kâr
                    risk = 0 # Bu hissede risk kalmadı
                else:
                    maliyet_gorunum = net_giris # Kalan maliyet
                    kar_zarar = toplam_deger - net_giris
                    risk = net_giris
                    toplam_risk += risk

                # Günlük Fark
                gf_tl = (guncel - ref_fiyat) * net
                gf_yuzde = ((guncel - ref_fiyat) / ref_fiyat) * 100 if ref_fiyat > 0 else 0
                gf_metin = f"{gf_tl:+,.0f} (%{gf_yuzde:+.1f})"

                liste.append({
                    "Varlık": sym, 
                    "Lot": int(net) if net % 1 == 0 else float(f"{net:.2f}"), 
                    "Fiyat": guncel,
                    "Kalan Ana Para": maliyet_gorunum, # Sadeleştirilmiş Maliyet
                    "Toplam Değer": toplam_deger,
                    "Net Kâr": kar_zarar,
                    "Günlük": gf_metin
                })
        
        # --- ANA PARA HESABI (Genel) ---
        df_al = df[df["Islem"] == "Alış"]; df_sat = df[df["Islem"] == "Satış"]
        net_ana_para_genel = df_al["Toplam"].sum() - df_sat["Toplam"].sum()
        
        if liste:
            df_v = pd.DataFrame(liste)
            toplam_portfoy_degeri = df_v["Toplam Değer"].sum()
            
            # Günlük kayıt
            save_daily_snapshot(toplam_portfoy_degeri, net_ana_para_genel, dolar)
            
            # Benchmark
            alt_usd, alt_gold, net_usd_ad, net_gold_ad = calculate_benchmarks(df)
            bench_df = pd.DataFrame({
                "Varlık": ["Sizin Portföy", "Dolar Olsaydı", "Altın Olsaydı"],
                "Değer (TL)": [toplam_portfoy_degeri, alt_usd, alt_gold], "Renk": ["blue", "green", "gold"]
            })

            # GRAFİKLER
            c1, c2 = st.columns(2)
            with c1: st.plotly_chart(px.pie(df_v, values='Toplam Değer', names='Varlık', hole=0.4), use_container_width=True)
            with c2: st.plotly_chart(px.bar(bench_df, x="Varlık", y="Değer (TL)", color="Varlık", text_auto='.2s', color_discrete_map={"Sizin Portföy": "#3498db", "Dolar Olsaydı": "#2ecc71", "Altın Olsaydı": "#f1c40f"}), use_container_width=True)
            
            # --- SADELEŞTİRİLMİŞ TABLO ---
            cfg = {
                "Varlık": st.column_config.TextColumn("Varlık", disabled=True),
                "Lot": st.column_config.NumberColumn("Lot", format="%d"), # Sade sayı
                "Fiyat": st.column_config.NumberColumn("Fiyat", format="%.2f"),
                "Kalan Ana Para": st.column_config.Column("Kalan Risk (TL)", disabled=True), # Hem sayı hem yazı olabilir
                "Toplam Değer": st.column_config.NumberColumn("Değer (TL)", format="%.0f"),
                "Net Kâr": st.column_config.NumberColumn("Net Kâr", format="%+d"),
                "Günlük": st.column_config.TextColumn("Günlük", disabled=True)
            }
            
            st.dataframe(df_v.style.format({
                "Fiyat": "{:,.2f}", "Toplam Değer": "{:,.0f}", "Net Kâr": "{:+,.0f}"
            }).map(renk, subset=["Net Kâr", "Günlük", "Kalan Ana Para"]), use_container_width=True, hide_index=True, column_config=cfg)
            
            st.divider()
            
            genel_k = toplam_portfoy_degeri - net_ana_para_genel
            genel_ky = (genel_k/net_ana_para_genel)*100 if net_ana_para_genel > 0 else 0
            
            k1, k2, k3, k4, k5 = st.columns(5)
            k1.metric("Portföy", f"{toplam_portfoy_degeri:,.0f} ₺", f"${toplam_portfoy_degeri/dolar:,.0f}", delta_color="off")
            k2.metric("İçerideki Risk", f"{net_ana_para_genel:,.0f} ₺", help="Cebinizden çıkan ve henüz dönmeyen net para")
            k3.metric("GENEL KAR", f"{genel_k:+,.0f} ₺", delta=f"%{genel_ky:.1f}")
            # Günlük farkı toplam olarak hesaplayalım (Görsel amaçlı)
            gunluk_toplam = 0
            for item in liste:
                try: gunluk_toplam += float(item["Günlük"].split(' ')[0].replace('.', '').replace(',','.'))
                except: pass
            k4.metric("Bugün", f"{gunluk_toplam:+,.0f} ₺")

with tab3:
    st.subheader("📈 Gidişat")
    df_hist = get_history_data()
    if not df_hist.empty:
        if "NetAnaPara" in df_hist.columns:
             df_hist["GenelKar"] = df_hist["ToplamVarlik"] - df_hist["NetAnaPara"]
        else:
             df_hist["GenelKar"] = df_hist["ToplamVarlik"] # Veri yoksa geçici çözüm
        
        f1 = go.Figure()
        f1.add_trace(go.Scatter(x=df_hist["Tarih"], y=df_hist["ToplamVarlik"], name='Servet', line=dict(color='#2ecc71', width=3)))
        if "NetAnaPara" in df_hist.columns:
            f1.add_trace(go.Scatter(x=df_hist["Tarih"], y=df_hist["NetAnaPara"], name='İçerideki Ana Para', line=dict(color='gray', dash='dot')))
        st.plotly_chart(f1, use_container_width=True)
        
        f2 = go.Figure()
        f2.add_trace(go.Scatter(x=df_hist["Tarih"], y=df_hist["GenelKar"], name='Net Kâr (Gerçekleşen Dahil)', line=dict(color='#3498db', width=3)))
        st.plotly_chart(f2, use_container_width=True)
    else: st.info("Veri toplanıyor...")

with tab4:
    st.dataframe(df.sort_index(ascending=False).style.format({"Fiyat": "{:,.4f}", "Toplam": "{:,.2f}", "Komisyon": "{:,.2f}", "Adet": "{:.0f}"}), use_container_width=True)