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

st.set_page_config(layout="wide", page_title="Portfoy v41")

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

# --- RENKLENDİRME (GÜNCELLENDİ: Metinleri de boyar) ---
def renk(val):
    c = ''
    # Sayısal kontrol
    if isinstance(val, (int, float)):
        if val > 0: c = '#2ecc71'
        elif val < 0: c = '#e74c3c'
    # Metin kontrol (Örn: "+100 (%5)")
    elif isinstance(val, str):
        if val.startswith('+'): c = '#2ecc71'
        elif val.startswith('-'): c = '#e74c3c'
        
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

def save_daily_snapshot(tv, tm, dk):
    client = init_connection()
    try: sheet = client.open_by_key(SHEET_ID).worksheet("Gecmis")
    except: return
    bugun = datetime.now().strftime("%Y-%m-%d")
    dates = sheet.col_values(1)
    d = [bugun, str(tv).replace(".", ","), str(tm).replace(".", ","), str(dk).replace(".", ",")]
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
        for c in ["ToplamVarlik", "ToplamMaliyet", "DolarKuru"]:
            if c in df.columns: df[c] = df[c].apply(safe_float)
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

def calculate_portfolio_state(df):
    portfolio = {}
    df = df.sort_values("Tarih")
    for _, row in df.iterrows():
        sym = row["Sembol"]; typ = row["Tur"]; islem = row["Islem"]; qty = row["Adet"]; total = row["Toplam"]
        if sym not in portfolio: portfolio[sym] = {"Adet": 0, "Maliyet": 0, "Tur": typ}
        if islem == "Alış":
            portfolio[sym]["Adet"] += qty; portfolio[sym]["Maliyet"] += total
        elif islem == "Satış":
            if portfolio[sym]["Adet"] > 0:
                avg = portfolio[sym]["Maliyet"] / portfolio[sym]["Adet"]
                portfolio[sym]["Maliyet"] -= (qty * avg); portfolio[sym]["Adet"] -= qty
            else: portfolio[sym]["Adet"] = 0; portfolio[sym]["Maliyet"] = 0
        if portfolio[sym]["Adet"] <= 0.001: portfolio[sym]["Adet"] = 0; portfolio[sym]["Maliyet"] = 0
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
        portfolio_state = calculate_portfolio_state(df)
        fund_data = get_fund_data_from_sheet()
        dolar = get_usd_rate()
        liste = []
        
        for sym, data in portfolio_state.items():
            net = data["Adet"]
            if net > 0:
                em = data["Maliyet"]
                v_tur = data["Tur"]
                guncel = 0.0; ref_fiyat = 0.0
                
                if v_tur == "Hisse":
                    curr_p, prev_p = get_stock_data_full(sym)
                    guncel = curr_p
                    if curr_p is None: guncel = 0
                    if prev_p is None: prev_p = 0
                    ref_fiyat = prev_p # Dünkü kapanış
                else:
                    f_info = fund_data.get(sym, {"fiyat": 0, "yuzde": 0})
                    guncel = f_info["fiyat"]
                    pct = f_info["yuzde"]
                    
                    if guncel == 0: 
                        guncel = em / net
                        ref_fiyat = guncel # Değişim 0 görünsün
                    else:
                        # Dünkü Fiyat = Bugün / (1 + %/100)
                        ref_fiyat = guncel / (1 + (pct/100))
                
                liste.append({
                    "Sembol": sym, "Tur": v_tur, "Adet": net, 
                    "Birim Maliyet": em / net,
                    "Anlık Fiyat": float(guncel),
                    "Ref Fiyat": float(ref_fiyat), # Gizli referans fiyat
                    "Toplam Değer": float(net * guncel),
                    "K/Z (TL)": float((net * guncel) - em),
                    "K/Z (%)": float(((net * guncel) - em) / em * 100) if em > 0 else 0
                })
        
        if liste:
            df_v = pd.DataFrame(liste)
            toplam_v = df_v["Toplam Değer"].sum()
            toplam_m_gosterge = sum([x["Birim Maliyet"] * x["Adet"] for x in liste])
            save_daily_snapshot(toplam_v, toplam_m_gosterge, dolar)
            
            alt_usd, alt_gold, net_usd_ad, net_gold_ad = calculate_benchmarks(df)
            bench_df = pd.DataFrame({
                "Varlık": ["Sizin Portföy", "Dolar Olsaydı", "Altın Olsaydı"],
                "Değer (TL)": [toplam_v, alt_usd, alt_gold], "Renk": ["blue", "green", "gold"]
            })

            col_g1, col_g2 = st.columns(2)
            with col_g1: st.plotly_chart(px.pie(df_v, values='Toplam Değer', names='Sembol', hole=0.4), use_container_width=True)
            with col_g2: st.plotly_chart(px.bar(bench_df, x="Varlık", y="Değer (TL)", color="Varlık", text_auto='.2s', color_discrete_map={"Sizin Portföy": "#3498db", "Dolar Olsaydı": "#2ecc71", "Altın Olsaydı": "#f1c40f"}), use_container_width=True)
            
            cfg = {
                "Sembol": st.column_config.TextColumn("Varlık", disabled=True),
                "Birim Maliyet": st.column_config.NumberColumn("Ort. Maliyet", format="%.4f"),
                "Anlık Fiyat": st.column_config.NumberColumn("Anlık Fiyat", format="%.4f"),
                "Toplam Değer": st.column_config.NumberColumn("Toplam Değer", format="%.2f", disabled=True),
                "K/Z (TL)": st.column_config.NumberColumn("Kar/Zarar", format="%.2f", disabled=True),
                "K/Z (%)": st.column_config.NumberColumn("Kar %", format="%.2f", disabled=True),
                # Birleşik Sütun (Metin)
                "G.Fark (Metin)": st.column_config.TextColumn("Günlük Fark", disabled=True),
                "Tur": None, "Adet": None, "Ref Fiyat": None
            }
            
            edited = st.data_editor(df_v, column_config=cfg, use_container_width=True, hide_index=True, key="gs_edit")
            
            res = []
            tv = 0; tm = 0; tgf = 0
            
            for i, r in edited.iterrows():
                guncel = safe_float(r["Anlık Fiyat"])
                pd_val = r["Adet"] * guncel
                md_val = r["Birim Maliyet"] * r["Adet"]
                
                # Kar Zarar
                ktl = pd_val - md_val
                ky = (ktl/md_val)*100 if md_val > 0 else 0
                
                # Günlük Fark
                ref = r["Ref Fiyat"]
                gf_tl = (guncel - ref) * r["Adet"]
                gf_yuzde = ((guncel - ref) / ref) * 100 if ref > 0 else 0
                
                # Birleşik Metin Oluşturma: "+1.250,00 (%+3,50)"
                # Not: format fonksiyonu ile virgül/nokta ayarı yapıyoruz
                gf_metin = f"{gf_tl:+,.2f} (%{gf_yuzde:+.2f})"
                
                tv += pd_val; tm += md_val; tgf += gf_tl
                
                res.append({
                    "Varlık": r["Sembol"], 
                    "Birim Maliyet": md_val / r["Adet"],
                    "Anlık Fiyat": guncel,
                    "Toplam Değer": pd_val,
                    "K/Z (TL)": ktl, 
                    "K/Z (%)": ky,
                    "G.Fark (Metin)": gf_metin
                })
            
            st.divider()
            
            st.dataframe(
                pd.DataFrame(res).style.format({
                    "Birim Maliyet": "{:,.4f}", "Anlık Fiyat": "{:,.4f}",
                    "Toplam Değer": "{:,.2f}", "K/Z (TL)": "{:+,.2f}", "K/Z (%)": "{:+.2f} %"
                }).map(renk, subset=["K/Z (TL)", "K/Z (%)", "G.Fark (Metin)"]),
                use_container_width=True, hide_index=True
            )
            
            st.divider()
            df_al = df[df["Islem"] == "Alış"]; df_sat = df[df["Islem"] == "Satış"]
            giren = df_alis["Toplam"].sum(); cikan = df_satis["Toplam"].sum()
            net_ana = giren - cikan
            genel_k = tv - net_ana; genel_ky = (genel_k/net_ana)*100 if net_ana > 0 else 0
            
            k1, k2, k3, k4, k5, k6 = st.columns(6)
            k1.metric("Portföy", f"{tv:,.0f} ₺", f"${tv/dolar:,.0f}", delta_color="off")
            k2.metric("Maliyet", f"{tm:,.0f} ₺")
            k3.metric("Anlık K/Z", f"{tv-tm:+,.0f} ₺")
            k4.metric("Günlük Fark", f"{tgf:+,.0f} ₺")
            k5.metric("Net Ana Para", f"{net_ana:,.0f} ₺", f"${net_usd_ad:,.0f}", delta_color="off")
            k6.metric("GENEL KAR", f"{genel_k:+,.0f} ₺", delta=f"%{genel_ky:.1f}")

with tab3:
    st.subheader("📈 Gidişat")
    df_hist = get_history_data()
    if not df_hist.empty:
        df_hist["NetKar"] = df_hist["ToplamVarlik"] - df_hist["ToplamMaliyet"]
        f1 = go.Figure()
        f1.add_trace(go.Scatter(x=df_hist["Tarih"], y=df_hist["ToplamVarlik"], name='Varlık', line=dict(color='#2ecc71')))
        f1.add_trace(go.Scatter(x=df_hist["Tarih"], y=df_hist["ToplamMaliyet"], name='Maliyet', line=dict(color='gray', dash='dot')))
        st.plotly_chart(f1, use_container_width=True)
        f2 = go.Figure()
        f2.add_trace(go.Scatter(x=df_hist["Tarih"], y=df_hist["NetKar"], name='Net Kar', line=dict(color='#3498db')))
        st.plotly_chart(f2, use_container_width=True)
    else: st.info("Veri toplanıyor...")

with tab4:
    st.dataframe(df.sort_index(ascending=False).style.format({"Fiyat": "{:,.4f}", "Toplam": "{:,.2f}", "Komisyon": "{:,.2f}", "Adet": "{:.0f}"}), use_container_width=True)