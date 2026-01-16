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
st.set_page_config(layout="wide", page_title="Portfoy v47")

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
        elif val == "BEDAVA": c = '#3498db'
    
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

def save_daily_snapshot(tv, net_ana, dk):
    client = init_connection()
    try: 
        try: sheet = client.open_by_key(SHEET_ID).worksheet("Gecmis")
        except: 
            sheet = client.open_by_key(SHEET_ID).add_worksheet("Gecmis", 1000, 5)
            sheet.append_row(["Tarih", "ToplamVarlik", "NetAnaPara", "DolarKuru"])
    except: return

    bugun = datetime.now().strftime("%Y-%m-%d")
    dates = sheet.col_values(1)
    
    # 4 Sütun Yeterli: Tarih, Varlık(Anlık), NetAnaPara(Risk), Dolar
    d = [bugun, str(tv).replace(".", ","), str(net_ana).replace(".", ","), str(dk).replace(".", ",")]
    
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

def calculate_benchmarks_detailed(df_transactions):
    m = get_historical_market_data()
    if m.empty: return 0, 0, 0, 0, 0
    s_usd_cost = 0 # Dolar Maliyeti (Giren Dolar - Çıkan Dolar)
    s_gold_cost = 0
    
    df_s = df_transactions.sort_values("Tarih")
    for _, r in df_s.iterrows():
        try:
            day = m.loc[m.index.asof(r["Tarih"].date())]
            usd = day['USD']; gold = day['Gram_Gold']
            amt = float(r["Toplam"])
            if r["Islem"] == "Alış": 
                s_usd_cost += amt/usd
                s_gold_cost += amt/gold
            else: 
                s_usd_cost -= amt/usd
                s_gold_cost -= amt/gold
        except: continue
    
    # Şu anki değerler (Eğer hepsini o gün Dolar yapsaydım şu an elimde kaç $ olurdu?)
    # Aslında kullanıcının istediği: "Benim içerideki Net Ana Param kaç Dolar ediyor?"
    return s_usd_cost, s_gold_cost

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

# TEK ve NET ANALİZ FONKSİYONU
def calculate_portfolio_unified(df):
    portfolio = {}
    df = df.sort_values("Tarih")
    
    # Nakit Akışı Takibi
    toplam_giren = 0
    toplam_cikan = 0
    
    for _, row in df.iterrows():
        sym = row["Sembol"]; typ = row["Tur"]; islem = row["Islem"]; qty = row["Adet"]; total = row["Toplam"]
        
        if islem == "Alış": toplam_giren += total
        else: toplam_cikan += total

        if sym not in portfolio: portfolio[sym] = {"Adet": 0, "Maliyet": 0, "NetGiris": 0.0, "Tur": typ}
        
        if islem == "Alış":
            portfolio[sym]["Adet"] += qty
            portfolio[sym]["Maliyet"] += total # Std Maliyet
            portfolio[sym]["NetGiris"] += total # Sıfır Maliyet Hesabı
        elif islem == "Satış":
            if portfolio[sym]["Adet"] > 0:
                avg = portfolio[sym]["Maliyet"] / portfolio[sym]["Adet"]
                portfolio[sym]["Maliyet"] -= (qty * avg)
                portfolio[sym]["Adet"] -= qty
                
                portfolio[sym]["NetGiris"] -= total # Para çıktı
            else:
                portfolio[sym]["Adet"] = 0
                portfolio[sym]["Maliyet"] = 0
                portfolio[sym]["NetGiris"] = 0
                
        if portfolio[sym]["Adet"] <= 0.001: 
            portfolio[sym]["Adet"] = 0
            portfolio[sym]["Maliyet"] = 0
            portfolio[sym]["NetGiris"] = 0
            
    return portfolio, toplam_giren, toplam_cikan

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
        # TEK FONKSİYON, TÜM ANALİZ
        portfolio, t_giren, t_cikan = calculate_portfolio_unified(df)
        fund_data = get_fund_data_from_sheet()
        dolar = get_usd_rate()
        
        # Ana Para Analizi (Nakit Akışı)
        net_ana_para_tl = t_giren - t_cikan
        net_ana_para_usd_maliyeti, _ = calculate_benchmarks_detailed(df)
        
        liste = []
        gunluk_toplam_tl = 0
        
        for sym, data in portfolio.items():
            net = data["Adet"]
            if net > 0:
                em = data["Maliyet"]
                v_tur = data["Tur"]
                risk_kalan = data["NetGiris"]
                
                # Fiyat Bulma
                guncel = 0.0; ref_fiyat = 0.0
                if v_tur == "Hisse":
                    curr_p, prev_p = get_stock_data_full(sym)
                    guncel = curr_p if curr_p else 0
                    ref_fiyat = prev_p if prev_p else guncel
                else:
                    f_info = fund_data.get(sym, {"fiyat": 0, "yuzde": 0})
                    guncel = f_info["fiyat"]
                    pct = f_info["yuzde"]
                    if guncel == 0: guncel = em / net; ref_fiyat = guncel
                    else: ref_fiyat = guncel / (1 + (pct/100))
                
                # Günlük Fark
                gf_tl = (guncel - ref_fiyat) * net
                gf_yuzde = ((guncel - ref_fiyat) / ref_fiyat) * 100 if ref_fiyat > 0 else 0
                gf_metin = f"{gf_tl:+,.0f} (%{gf_yuzde:+.1f})"
                gunluk_toplam_tl += gf_tl

                # Sıfır Maliyet Durumu
                maliyet_durumu = "BEDAVA" if risk_kalan <= 0 else risk_kalan

                liste.append({
                    "Varlık": sym, 
                    "Lot": net,
                    "Ort. Maliyet": em / net,
                    "Fiyat": guncel,
                    "Risk (TL)": maliyet_durumu, # Sütun adı değişti
                    "Toplam Değer": float(net * guncel),
                    "Kar/Zarar": float((net * guncel) - em),
                    "Günlük": gf_metin
                })

        if liste:
            df_v = pd.DataFrame(liste)
            toplam_portfoy_degeri = df_v["Toplam Değer"].sum()
            toplam_maliyet = sum([x["Ort. Maliyet"] * x["Lot"] for x in liste])
            
            # Günlük Snapshot
            save_daily_snapshot(toplam_portfoy_degeri, net_ana_para_tl, dolar)
            
            # --- ÖZET METRİKLERİ (GENİŞ VE AÇIKLAYICI) ---
            # 1. SATIR: PORTFÖY DURUMU
            genel_kar = toplam_portfoy_degeri - net_ana_para_tl
            c1, c2, c3 = st.columns(3)
            c1.metric("💰 Portföy Değeri", f"{toplam_portfoy_degeri:,.0f} ₺", f"${toplam_portfoy_degeri/dolar:,.0f} (Anlık Dolar Karşılığı)")
            c2.metric("📊 Toplam Maliyet", f"{toplam_maliyet:,.0f} ₺", help="Eldeki varlıkların alış maliyeti")
            c3.metric("📈 Genel Kâr (Tüm Zamanlar)", f"{genel_kar:+,.0f} ₺", help="Cebinize giren nakit + eldeki varlıkların kârı")
            
            st.divider()
            
            # 2. SATIR: NAKİT VE RİSK ANALİZİ
            k1, k2, k3 = st.columns(3)
            
            # NET ANA PARA VE DOLAR MALİYETİ
            usd_cost_str = f"${net_ana_para_usd_maliyeti:,.0f}" if net_ana_para_tl > 0 else "RİSKSİZ"
            k1.metric("🛡️ İçerideki Risk (Net Ana Para)", f"{net_ana_para_tl:,.0f} ₺", f"Maliyet: {usd_cost_str}", 
                      help="Cebinizden çıkan net para. Dolar Maliyeti: O tarihlerde dolar alsaydınız kaç dolarınız olurdu?")

            # NAKİT AKIŞI (Sizin aradığınız 240k burada!)
            nakit_durumu = t_cikan # Toplam sistemden çekilen para
            k2.metric("💸 Çekilen Nakit (Satışlar)", f"{nakit_durumu:,.0f} ₺", help="Bugüne kadar satış yapıp kasaya/cebe çektiğiniz toplam para.")
            
            # GÜNLÜK FARK
            k3.metric("📅 Bugün", f"{gunluk_toplam_tl:+,.0f} ₺", help="Bugünkü piyasa hareketinden değişim")
            
            st.divider()

            # --- TABLO ---
            st.subheader("📋 Varlık Listesi")
            
            # Risk Sütunu Formatı
            def format_risk(val):
                if isinstance(val, (int, float)): return f"{val:,.0f}"
                return val # BEDAVA yazısı için

            cfg = {
                "Varlık": st.column_config.TextColumn("Varlık", disabled=True),
                "Lot": st.column_config.NumberColumn("Lot", format="%.0f"),
                "Ort. Maliyet": st.column_config.NumberColumn("Ort. Maliyet", format="%.2f"),
                "Fiyat": st.column_config.NumberColumn("Fiyat", format="%.2f"),
                "Risk (TL)": st.column_config.Column("Kalan Risk", disabled=True),
                "Toplam Değer": st.column_config.NumberColumn("Değer (TL)", format="%.0f"),
                "Kar/Zarar": st.column_config.NumberColumn("K/Z (TL)", format="%.0f"),
                "Günlük": st.column_config.TextColumn("Günlük", disabled=True)
            }
            
            st.dataframe(df_v.style.format({
                "Ort. Maliyet": "{:,.2f}", "Fiyat": "{:,.2f}", "Toplam Değer": "{:,.0f}", 
                "Kar/Zarar": "{:+,.0f}"
            }).format({"Risk (TL)": format_risk}).map(renk, subset=["Kar/Zarar", "Günlük", "Risk (TL)"]), 
            use_container_width=True, hide_index=True, column_config=cfg)

with tab3:
    st.subheader("📈 Servet Gelişimi")
    df_hist = get_history_data()
    if not df_hist.empty:
        # GENEL KAR HESABI
        if "NetAnaPara" in df_hist.columns:
             df_hist["GenelKar"] = df_hist["ToplamVarlik"] - df_hist["NetAnaPara"]
        else: df_hist["GenelKar"] = 0
             
        # Grafik: Yeşil (Servet) ve Gri (Risk)
        f1 = go.Figure()
        f1.add_trace(go.Scatter(x=df_hist["Tarih"], y=df_hist["ToplamVarlik"], name='Portföy Değeri', line=dict(color='#2ecc71', width=3)))
        if "NetAnaPara" in df_hist.columns:
            f1.add_trace(go.Scatter(x=df_hist["Tarih"], y=df_hist["NetAnaPara"], name='İçerideki Risk (Ana Para)', line=dict(color='gray', dash='dot')))
        f1.update_layout(title="Portföy vs Risk", hovermode="x unified")
        st.plotly_chart(f1, use_container_width=True)
        
        # Grafik: Kar
        f2 = go.Figure()
        f2.add_trace(go.Scatter(x=df_hist["Tarih"], y=df_hist["GenelKar"], name='NET SERVET KAZANCI', line=dict(color='#3498db', width=3, fill='tozeroy')))
        f2.update_layout(title="Toplam Kazanılan Servet (Cepteki + Portföydeki)", hovermode="x unified")
        st.plotly_chart(f2, use_container_width=True)
    else: st.info("Veri toplanıyor...")

with tab4:
    st.dataframe(df.sort_index(ascending=False).style.format({"Fiyat": "{:,.4f}", "Toplam": "{:,.2f}", "Komisyon": "{:,.2f}", "Adet": "{:.0f}"}), use_container_width=True)