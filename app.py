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

warnings.simplefilter(action='ignore', category=FutureWarning)

st.set_page_config(layout="wide", page_title="Portfoy v37")

# 👇👇👇 BURAYI DOLDURUN 👇👇👇
SHEET_ID = "1_isL5_B9EiyLppqdP4xML9N4_pLdvgNYIei70H5yiew"
# 👆👆👆 ------------------ 👆👆👆

DATA_FILE = "portfolio_transactions.csv"
JSON_FILE = "service_account.json"

# --- YARDIMCI FONKSİYONLAR ---
def safe_float(val):
    if val is None or val == "": return 0.0
    if isinstance(val, (int, float)): return float(val)
    val_str = str(val).strip()
    if "." in val_str and "," in val_str:
        val_str = val_str.replace(".", "")
    val_str = val_str.replace(",", ".")
    try: return float(val_str)
    except: return 0.0

def renk(val):
    c = 'white'
    if val > 0: c = '#2ecc71'
    if val < 0: c = '#e74c3c'
    return f'color: {c}; font-weight: bold;'

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
        if veri["Sembol"] not in p_sheet.col_values(1): p_sheet.append_row([veri["Sembol"], 0, ""])
    except: pass

def get_fund_prices():
    client = init_connection()
    try:
        sheet = client.open_by_key(SHEET_ID).worksheet("Fiyatlar")
        raw = sheet.get_all_values()
        return {str(r[0]): safe_float(r[1]) for r in raw[1:] if len(r) >= 2}
    except: return {}

# --- GEÇMİŞ KAYIT SİSTEMİ ---
def save_daily_snapshot(toplam_varlik, toplam_maliyet, dolar_kuru):
    client = init_connection()
    try: sheet = client.open_by_key(SHEET_ID).worksheet("Gecmis")
    except: return
    bugun = datetime.now().strftime("%Y-%m-%d")
    dates = sheet.col_values(1)
    val_str = str(toplam_varlik).replace(".", ",")
    mal_str = str(toplam_maliyet).replace(".", ",")
    kur_str = str(dolar_kuru).replace(".", ",")
    if bugun not in dates:
        sheet.append_row([bugun, val_str, mal_str, kur_str])
    else:
        row_idx = dates.index(bugun) + 1
        sheet.update_cell(row_idx, 2, val_str)
        sheet.update_cell(row_idx, 3, mal_str)
        sheet.update_cell(row_idx, 4, kur_str)

def get_history_data():
    client = init_connection()
    try:
        sheet = client.open_by_key(SHEET_ID).worksheet("Gecmis")
        raw = sheet.get_all_values()
        if len(raw) < 2: return pd.DataFrame()
        df = pd.DataFrame(raw[1:], columns=raw[0])
        for c in ["ToplamVarlik", "ToplamMaliyet", "DolarKuru"]:
            if c in df.columns: df[c] = df[c].apply(safe_float)
        df["Tarih"] = pd.to_datetime(df["Tarih"])
        return df.sort_values("Tarih", ascending=True) # Grafikler için eskiden yeniye sırala
    except: return pd.DataFrame()

# --- PİYASA ---
@st.cache_data(ttl=3600)
def get_historical_market_data():
    end_date = datetime.now()
    start_date = end_date - timedelta(days=365*5)
    usd_df = yf.download("USDTRY=X", start=start_date, end=end_date, progress=False)
    if usd_df.empty: return pd.DataFrame()
    usd_df = usd_df['Close'].reset_index(); usd_df.columns = ['Date', 'USD']; usd_df['Date'] = pd.to_datetime(usd_df['Date']).dt.date
    gold_df = yf.download("GC=F", start=start_date, end=end_date, progress=False)
    if gold_df.empty: return pd.DataFrame()
    gold_df = gold_df['Close'].reset_index(); gold_df.columns = ['Date', 'Gold_Ounce']; gold_df['Date'] = pd.to_datetime(gold_df['Date']).dt.date
    market = pd.merge(usd_df, gold_df, on='Date', how='outer').sort_values('Date').ffill()
    market['Gram_Gold'] = (market['Gold_Ounce'] * market['USD']) / 31.1035
    market.set_index('Date', inplace=True)
    return market

def calculate_benchmarks(df_transactions):
    market = get_historical_market_data()
    if market.empty: return 0, 0, 0, 0
    shadow_usd = 0; shadow_gold = 0
    df_sorted = df_transactions.sort_values("Tarih")
    for _, row in df_sorted.iterrows():
        t_date = row["Tarih"].date(); t_tutar = float(row["Toplam"])
        try:
            idx = market.index.asof(t_date); day_rates = market.loc[idx]
            usd = day_rates['USD']; gold = day_rates['Gram_Gold']
        except: continue
        if row["Islem"] == "Alış":
            shadow_usd += t_tutar / usd; shadow_gold += t_tutar / gold
        elif row["Islem"] == "Satış":
            shadow_usd -= t_tutar / usd; shadow_gold -= t_tutar / gold
    try:
        last = market.iloc[-1]
        return shadow_usd * last['USD'], shadow_gold * last['Gram_Gold'], shadow_usd, shadow_gold
    except: return 0, 0, 0, 0

@st.cache_data(ttl=300)
def get_stock_price(symbol):
    try:
        symbol = symbol.strip().upper()
        if not symbol.endswith(".IS"): symbol = symbol + ".IS"
        v = yf.Ticker(symbol).fast_info['last_price']
        return v if v is not None else 0.0
    except: return 0.0

@st.cache_data(ttl=3600)
def get_usd_rate():
    try: return yf.Ticker("USDTRY=X").fast_info['last_price']
    except: return 1.0

# --- ARAYÜZ ---
st.title("☁️ Bulut Portföy & Analiz")

def check_password():
    if "password_correct" not in st.session_state:
        st.text_input("Şifre", type="password", key="password", on_change=password_entered); return False
    return st.session_state["password_correct"]
def password_entered():
    if st.session_state["password"] == st.secrets["app_password"]:
        st.session_state["password_correct"] = True; del st.session_state["password"]
    else: st.session_state["password_correct"] = False

if not check_password(): st.stop()
if st.sidebar.button("🔒 Çıkış"): del st.session_state["password_correct"]; st.rerun()

try: df = get_data()
except: st.stop()

tab1, tab2, tab3, tab4 = st.tabs(["➕ EKLE", "📊 PORTFÖY", "📈 GİDİŞAT", "📋 GEÇMİŞ"])

# --- TAB 1 ---
with tab1:
    col_ekle, col_sil = st.columns([2, 1])
    with col_ekle:
        st.subheader("İşlem")
        metod = st.radio("Yöntem:", ["Birim Fiyat", "Toplam Tutar"], horizontal=True)
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
                        save_transaction(yeni)
                        st.success("Tamam!"); st.cache_data.clear(); st.rerun()
    with col_sil:
        st.subheader("Sil")
        try:
            df_sil = get_data()
            if not df_sil.empty:
                st.dataframe(df_sil.tail(5)[["Sembol", "Toplam"]], use_container_width=True)
                secilen = st.selectbox("ID:", df_sil.index.sort_values(ascending=False))
                if st.button("Sil"):
                    client = init_connection()
                    client.open_by_key(SHEET_ID).worksheet("Islemler").delete_rows(int(secilen) + 2)
                    st.success("Silindi!"); st.cache_data.clear(); st.rerun()
        except: pass

# --- TAB 2 ---
with tab2:
    if st.button("🔄 Yenile"): st.cache_data.clear(); st.rerun()
    if df.empty: st.info("Veri yok.")
    else:
        sheet_fiyat = get_fund_prices()
        dolar = get_usd_rate()
        semboller = df["Sembol"].unique(); liste = []
        
        for s in semboller:
            txs = df[df["Sembol"] == s]
            if txs.empty: continue
            v_tur = txs.iloc[0]["Tur"]
            alis = txs[txs["Islem"] == "Alış"]; satis = txs[txs["Islem"] == "Satış"]
            net = alis["Adet"].sum() - satis["Adet"].sum()
            if net > 0:
                tm = (alis["Adet"] * alis["Fiyat"]).sum() + alis["Komisyon"].sum()
                om = tm / alis["Adet"].sum()
                em = om * net
                guncel = 0.0; notlar = ""
                if v_tur == "Hisse": guncel = get_stock_price(s)
                else:
                    guncel = float(sheet_fiyat.get(s, 0))
                    if guncel == 0: guncel = om; notlar = "⚠️"
                liste.append({"Sembol": s, "Tur": v_tur, "Adet": net, "Not": notlar, 
                              "Toplam Maliyet": float(em), "Güncel Fiyat": float(guncel), "Piyasa Değeri": float(net * guncel)})
        
        if liste:
            df_v = pd.DataFrame(liste)
            toplam_v = df_v["Piyasa Değeri"].sum()
            toplam_m = df_v["Toplam Maliyet"].sum()
            save_daily_snapshot(toplam_v, toplam_m, dolar)
            
            alt_usd, alt_gold, net_usd_ad, net_gold_ad = calculate_benchmarks(df)
            bench_df = pd.DataFrame({
                "Varlık": ["Sizin Portföy", "Dolar Olsaydı", "Altın Olsaydı"],
                "Değer (TL)": [toplam_v, alt_usd, alt_gold],
                "Renk": ["blue", "green", "gold"]
            })

            col_g1, col_g2 = st.columns(2)
            with col_g1:
                st.subheader("Dağılım")
                st.plotly_chart(px.pie(df_v, values='Piyasa Değeri', names='Sembol', hole=0.4), use_container_width=True)
            with col_g2:
                st.subheader("Kıyaslama")
                fig_b = px.bar(bench_df, x="Varlık", y="Değer (TL)", color="Varlık", text_auto='.2s',
                               color_discrete_map={"Sizin Portföy": "#3498db", "Dolar Olsaydı": "#2ecc71", "Altın Olsaydı": "#f1c40f"})
                st.plotly_chart(fig_b, use_container_width=True)
            
            cfg = {"Sembol": st.column_config.TextColumn("Varlık"), "Adet": st.column_config.NumberColumn("Adet", format="%.0f"),
                   "Güncel Fiyat": st.column_config.NumberColumn("Fiyat", format="%.4f"), "Toplam Maliyet": st.column_config.NumberColumn("Maliyet", format="%.2f"),
                   "Tur": None, "Not": None, "Piyasa Değeri": None}
            edited = st.data_editor(df_v, column_config=cfg, use_container_width=True, hide_index=True, key="gs_edit")
            
            res = []
            tv = 0; tm = 0
            for i, r in edited.iterrows():
                pd_val = r["Adet"] * safe_float(r["Güncel Fiyat"]); md_val = safe_float(r["Toplam Maliyet"])
                ktl = pd_val - md_val; ky = (ktl/md_val)*100 if md_val > 0 else 0
                tv += pd_val; tm += md_val
                res.append({"Varlık": r["Sembol"], "Toplam Maliyet": md_val, "Değer": pd_val, "K/Z (TL)": ktl, "K/Z (%)": ky})
            
            st.dataframe(pd.DataFrame(res).style.format({"Toplam Maliyet": "{:,.2f}", "Değer": "{:,.2f}", "K/Z (TL)": "{:+,.2f}", "K/Z (%)": "{:+.2f} %"})
                         .map(renk, subset=["K/Z (TL)", "K/Z (%)"]), use_container_width=True, hide_index=True)
            
            st.divider()
            df_al = df[df["Islem"] == "Alış"]; df_sat = df[df["Islem"] == "Satış"]
            net_ana = df_al["Toplam"].sum() - df_sat["Toplam"].sum()
            genel_k = tv - net_ana; genel_ky = (genel_k/net_ana)*100 if net_ana > 0 else 0
            
            k1, k2, k3, k4, k5 = st.columns(5)
            k1.metric("Portföy", f"{tv:,.0f} ₺", f"${tv/dolar:,.0f}", delta_color="off")
            k2.metric("Maliyet", f"{tm:,.0f} ₺")
            k3.metric("Anlık K/Z", f"{tv-tm:+,.0f} ₺")
            k4.metric("Net Ana Para", f"{net_ana:,.0f} ₺", f"${net_usd_ad:,.0f}", delta_color="off")
            k5.metric("GENEL KAR", f"{genel_k:+,.0f} ₺", delta=f"%{genel_ky:.1f}")

# --- TAB 3: GİDİŞAT (YENİLENDİ) ---
with tab3:
    st.subheader("📈 Gidişat Analizi")
    df_hist = get_history_data()
    
    if not df_hist.empty:
        # Net Kar Hesabı (Toplam Varlık - Toplam Maliyet)
        df_hist["NetKar"] = df_hist["ToplamVarlik"] - df_hist["ToplamMaliyet"]
        # Günlük Değişim
        df_hist["GunlukDegisim"] = df_hist["NetKar"].diff().fillna(0)
        
        # 1. Grafik: Toplam Varlık (Zenginleşme)
        fig1 = go.Figure()
        fig1.add_trace(go.Scatter(x=df_hist["Tarih"], y=df_hist["ToplamVarlik"], mode='lines+markers', name='Varlık', line=dict(color='#2ecc71', width=3)))
        fig1.add_trace(go.Scatter(x=df_hist["Tarih"], y=df_hist["ToplamMaliyet"], mode='lines', name='Maliyet', line=dict(color='gray', dash='dot')))
        fig1.update_layout(title="Varlık Gelişimi (Para Girişi Dahil)", hovermode="x unified")
        st.plotly_chart(fig1, use_container_width=True)
        
        # 2. Grafik: Net Kar (Başarı Göstergesi)
        fig2 = go.Figure()
        fig2.add_trace(go.Scatter(x=df_hist["Tarih"], y=df_hist["NetKar"], mode='lines+markers', name='Net Kar', line=dict(color='#3498db', width=3)))
        fig2.update_layout(title="Net Kar Gelişimi (Para Girişinden Bağımsız)", hovermode="x unified")
        st.plotly_chart(fig2, use_container_width=True)
        
        # 3. Grafik: Günlük Değişimler (Bar)
        colors = ['red' if val < 0 else 'green' for val in df_hist["GunlukDegisim"]]
        fig3 = go.Figure()
        fig3.add_trace(go.Bar(x=df_hist["Tarih"], y=df_hist["GunlukDegisim"], marker_color=colors, name="Değişim"))
        fig3.update_layout(title="Günlük Kar/Zarar Değişimi", hovermode="x unified")
        st.plotly_chart(fig3, use_container_width=True)
        
    else: st.info("Veri toplanıyor...")

# --- TAB 4 ---
with tab4:
    st.dataframe(df.sort_index(ascending=False), use_container_width=True)