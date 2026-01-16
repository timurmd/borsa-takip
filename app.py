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
st.set_page_config(layout="wide", page_title="Portfoy v45")

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
        elif val == "BEDAVA": c = '#3498db' # Mavi
    
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

def save_daily_snapshot(tv, tm, dk, net_ana):
    client = init_connection()
    try: 
        try: sheet = client.open_by_key(SHEET_ID).worksheet("Gecmis")
        except: 
            sheet = client.open_by_key(SHEET_ID).add_worksheet("Gecmis", 1000, 5)
            sheet.append_row(["Tarih", "ToplamVarlik", "ToplamMaliyet", "DolarKuru", "NetAnaPara"])
    except: return

    bugun = datetime.now().strftime("%Y-%m-%d")
    dates = sheet.col_values(1)
    
    # 5 Sütun: Tarih, Varlık, Maliyet, Dolar, NetAnaPara
    d = [bugun, str(tv).replace(".", ","), str(tm).replace(".", ","), str(dk).replace(".", ","), str(net_ana).replace(".", ",")]
    
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
        cols = ["ToplamVarlik", "ToplamMaliyet", "DolarKuru", "NetAnaPara"]
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

# 1. STANDART MUHASEBE (Ağırlıklı Ortalama)
def calculate_standard_portfolio(df):
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

# 2. SIFIR MALİYET ANALİZİ (Giren/Çıkan Para)
def calculate_zero_cost_analysis(df):
    portfolio = {}
    df = df.sort_values("Tarih")
    for _, row in df.iterrows():
        sym = row["Sembol"]; typ = row["Tur"]; islem = row["Islem"]; qty = row["Adet"]; total = row["Toplam"]
        if sym not in portfolio: portfolio[sym] = {"Adet": 0, "NetGiris": 0.0, "Tur": typ}
        if islem == "Alış":
            portfolio[sym]["Adet"] += qty; portfolio[sym]["NetGiris"] += total
        elif islem == "Satış":
            portfolio[sym]["Adet"] -= qty; portfolio[sym]["NetGiris"] -= total
        if portfolio[sym]["Adet"] <= 0.001: portfolio[sym]["Adet"] = 0; portfolio[sym]["NetGiris"] = 0 
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
        # İki Mantığı da Çalıştır
        std_portfolio = calculate_standard_portfolio(df)
        zero_cost_portfolio = calculate_zero_cost_analysis(df)
        
        fund_data = get_fund_data_from_sheet()
        dolar = get_usd_rate()
        
        # --- TABLO 1: STANDART GÖRÜNÜM (Detaylı) ---
        liste_std = []
        for sym, data in std_portfolio.items():
            net = data["Adet"]
            if net > 0:
                em = data["Maliyet"]
                v_tur = data["Tur"]
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
                
                # Günlük Fark Hesabı
                gf_tl = (guncel - ref_fiyat) * net
                gf_yuzde = ((guncel - ref_fiyat) / ref_fiyat) * 100 if ref_fiyat > 0 else 0
                gf_metin = f"{gf_tl:+,.2f} (%{gf_yuzde:+.2f})" # Metin formatı

                liste_std.append({
                    "Varlık": sym, "Lot": net,
                    "Ort. Maliyet": em / net,
                    "Anlık Fiyat": float(guncel),
                    "Toplam Değer": float(net * guncel),
                    "Kar/Zarar": float((net * guncel) - em),
                    "Kar %": float(((net * guncel) - em) / em * 100) if em > 0 else 0,
                    "Günlük Fark": gf_metin
                })

        # --- TABLO 2: SIFIR MALİYET ANALİZİ (Özet) ---
        liste_zero = []
        for sym, data in zero_cost_portfolio.items():
            net = data["Adet"]
            if net > 0:
                risk = data["NetGiris"]
                durum = "BEDAVA" if risk <= 0 else risk
                liste_zero.append({
                    "Varlık": sym,
                    "İçerideki Para (Risk)": durum,
                    "Durum": "✅ Bedava" if risk <= 0 else "⚠️ Riskli"
                })

        # GÖRSELLEŞTİRME
        if liste_std:
            df_v = pd.DataFrame(liste_std)
            toplam_v = df_v["Toplam Değer"].sum()
            toplam_m = sum([x["Ort. Maliyet"] * x["Lot"] for x in liste_std])
            
            # Ana Para Hesabı (Genel)
            df_al = df[df["Islem"] == "Alış"]; df_sat = df[df["Islem"] == "Satış"]
            net_ana_para_genel = df_al["Toplam"].sum() - df_sat["Toplam"].sum()

            save_daily_snapshot(toplam_v, toplam_m, dolar, net_ana_para_genel)
            
            alt_usd, alt_gold, _, _ = calculate_benchmarks(df)
            bench_df = pd.DataFrame({
                "Varlık": ["Sizin Portföy", "Dolar Olsaydı", "Altın Olsaydı"],
                "Değer (TL)": [toplam_v, alt_usd, alt_gold], "Renk": ["blue", "green", "gold"]
            })

            # Grafikler
            c1, c2 = st.columns(2)
            with c1: st.plotly_chart(px.pie(df_v, values='Toplam Değer', names='Varlık', hole=0.4), use_container_width=True)
            with c2: st.plotly_chart(px.bar(bench_df, x="Varlık", y="Değer (TL)", color="Varlık", text_auto='.2s', color_discrete_map={"Sizin Portföy": "#3498db", "Dolar Olsaydı": "#2ecc71", "Altın Olsaydı": "#f1c40f"}), use_container_width=True)
            
            # --- 1. ANA TABLO (Detaylı & Düzenli) ---
            st.subheader("📋 Detaylı Portföy Durumu")
            cfg = {
                "Varlık": st.column_config.TextColumn("Varlık", disabled=True),
                "Lot": st.column_config.NumberColumn("Lot", format="%.0f"),
                "Ort. Maliyet": st.column_config.NumberColumn("Ort. Maliyet", format="%.2f"),
                "Anlık Fiyat": st.column_config.NumberColumn("Fiyat", format="%.2f"),
                "Toplam Değer": st.column_config.NumberColumn("Değer (TL)", format="%.2f"),
                "Kar/Zarar": st.column_config.NumberColumn("K/Z (TL)", format="%.2f"),
                "Kar %": st.column_config.NumberColumn("K/Z (%)", format="%.2f"),
                "Günlük Fark": st.column_config.TextColumn("Günlük Fark", disabled=True)
            }
            st.dataframe(df_v.style.format({
                "Ort. Maliyet": "{:,.2f}", "Anlık Fiyat": "{:,.2f}", "Toplam Değer": "{:,.2f}", 
                "Kar/Zarar": "{:+,.2f}", "Kar %": "{:+.2f} %"
            }).map(renk, subset=["Kar/Zarar", "Kar %", "Günlük Fark"]), use_container_width=True, hide_index=True, column_config=cfg)
            
            # --- 2. SIFIR MALİYET TABLOSU (Ekstra) ---
            st.markdown("---")
            st.subheader("🧠 Alternatif Bakış: Sıfır Maliyet Analizi")
            st.caption("Burada sadece cebinizden çıkan net para gösterilir. 'BEDAVA' yazanlar maliyetini tamamen çıkarmış demektir.")
            
            if liste_zero:
                df_z = pd.DataFrame(liste_zero)
                cfg_z = {
                    "İçerideki Para (Risk)": st.column_config.Column("Kalan Risk (TL)", disabled=True)
                }
                # Risk sütununda sayı varsa formatla, yazı varsa (BEDAVA) elleme
                def format_risk(val):
                    if isinstance(val, (int, float)): return f"{val:,.2f}"
                    return val

                st.dataframe(df_z.style.format({"İçerideki Para (Risk)": format_risk})
                             .map(renk, subset=["İçerideki Para (Risk)"]), 
                             use_container_width=True, hide_index=True, column_config=cfg_z)

            st.divider()
            
            # --- ALT METRİKLER (Tam Kadro Geri Döndü) ---
            genel_k = toplam_v - net_ana_para_genel
            genel_ky = (genel_k/net_ana_para_genel)*100 if net_ana_para_genel > 0 else 0
            
            # Günlük Toplamı Hesapla
            gunluk_toplam = 0
            for item in liste_std:
                try: 
                    # "+1.200,00 (%2)" stringinden sayıyı ayıkla
                    val_part = item["Günlük Fark"].split(' ')[0]
                    val_clean = val_part.replace('.', '').replace(',', '.').replace('+', '')
                    gunluk_toplam += float(val_clean)
                except: pass

            k1, k2, k3, k4, k5, k6 = st.columns(6)
            k1.metric("Portföy", f"{toplam_v:,.0f} ₺", f"${toplam_v/dolar:,.0f}", delta_color="off")
            k2.metric("Maliyet", f"{toplam_m:,.0f} ₺")
            k3.metric("Anlık K/Z", f"{toplam_v-toplam_m:+,.0f} ₺") # Unrealized
            k4.metric("Günlük Fark", f"{gunluk_toplam:+,.0f} ₺")
            k5.metric("Net Ana Para", f"{net_ana_para_genel:,.0f} ₺", help="Tüm işlemler sonucu içeride kalan para")
            k6.metric("GENEL KAR", f"{genel_k:+,.0f} ₺", delta=f"%{genel_ky:.1f}", help="Cebinizdeki nakit dahil gerçek kar")

with tab3:
    st.subheader("📈 Gidişat")
    df_hist = get_history_data()
    if not df_hist.empty:
        # Eski veri desteği (Maliyet sütunu varsa kullan, yoksa hata verme)
        df_hist["GenelKar"] = df_hist["ToplamVarlik"] - df_hist["NetAnaPara"]
        
        f1 = go.Figure()
        f1.add_trace(go.Scatter(x=df_hist["Tarih"], y=df_hist["ToplamVarlik"], name='Servet', line=dict(color='#2ecc71', width=3)))
        if "NetAnaPara" in df_hist.columns:
            f1.add_trace(go.Scatter(x=df_hist["Tarih"], y=df_hist["NetAnaPara"], name='İçerideki Ana Para', line=dict(color='gray', dash='dot')))
        st.plotly_chart(f1, use_container_width=True)
        
        f2 = go.Figure()
        f2.add_trace(go.Scatter(x=df_hist["Tarih"], y=df_hist["GenelKar"], name='Toplam Kar', line=dict(color='#3498db', width=3)))
        st.plotly_chart(f2, use_container_width=True)
        
        st.caption("Not: Grafik verileri 'Gecmis' sayfası silindiği için bugünden itibaren yeniden birikmeye başlamıştır.")
    else: st.info("Veri toplanıyor... (Yarın grafik oluşacak)")

with tab4:
    st.dataframe(df.sort_index(ascending=False).style.format({"Fiyat": "{:,.4f}", "Toplam": "{:,.2f}", "Komisyon": "{:,.2f}", "Adet": "{:.0f}"}), use_container_width=True)