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
st.set_page_config(layout="wide", page_title="Portfoy v65")

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
        if val > 0: c = '#2ecc71' 
        elif val < 0: c = '#e74c3c' 
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

def save_daily_snapshot(tv, tm, dk, net_ana):
    if tv < 100 and tm > 1000:
        return 
    client = init_connection()
    try: 
        try: sheet = client.open_by_key(SHEET_ID).worksheet("Gecmis")
        except: 
            sheet = client.open_by_key(SHEET_ID).add_worksheet("Gecmis", 1000, 5)
            sheet.append_row(["Tarih", "ToplamVarlik", "ToplamMaliyet", "DolarKuru", "NetAnaPara"])
    except: return

    expected_header = ["Tarih", "ToplamVarlik", "ToplamMaliyet", "DolarKuru", "NetAnaPara"]
    current_header = sheet.row_values(1)
    if current_header != expected_header:
        for i, val in enumerate(expected_header):
            sheet.update_cell(1, i+1, val)

    bugun = datetime.now().strftime("%Y-%m-%d")
    dates = sheet.col_values(1)
    
    d = [bugun, str(tv).replace(".", ","), str(tm).replace(".", ","), str(dk).replace(".", ","), str(net_ana).replace(".", ",")]
    
    if bugun not in dates: sheet.append_row(d)
    else:
        idx = dates.index(bugun) + 1
        for i, val in enumerate(d[1:]): sheet.update_cell(idx, i+2, val)

def save_asset_snapshots(liste):
    client = init_connection()
    bugun = datetime.now().strftime("%Y-%m-%d")
    try:
        try: sheet = client.open_by_key(SHEET_ID).worksheet("VarlikKari")
        except: 
            sheet = client.open_by_key(SHEET_ID).add_worksheet("VarlikKari", 1000, 26)
            sheet.append_row(["Tarih"])
        
        headers = sheet.row_values(1)
        if not headers: headers = ["Tarih"]
        
        data_dict = {item["Varlık"]: str(item["K/Z (%)"]).replace(".", ",") for item in liste}
        
        added_header = False
        for sym in data_dict.keys():
            if sym not in headers:
                headers.append(sym)
                added_header = True
                
        if added_header:
            for c_idx, h_val in enumerate(headers):
                sheet.update_cell(1, c_idx + 1, h_val)
                
        dates = sheet.col_values(1)
        row_data = [bugun]
        for h in headers[1:]:
            row_data.append(data_dict.get(h, "0"))
            
        if bugun not in dates:
            sheet.append_row(row_data)
        else:
            r_idx = dates.index(bugun) + 1
            for c_idx, val in enumerate(row_data):
                sheet.update_cell(r_idx, c_idx + 1, val)
    except: pass

def get_asset_history():
    client = init_connection()
    try:
        sheet = client.open_by_key(SHEET_ID).worksheet("VarlikKari")
        raw = sheet.get_all_values()
        if len(raw) < 2: return pd.DataFrame()
        
        actual_cols = raw[0]
        valid_data = []
        for r in raw[1:]:
            r_padded = r + ["0"] * (len(actual_cols) - len(r))
            valid_data.append(r_padded[:len(actual_cols)])

        df = pd.DataFrame(valid_data, columns=actual_cols)
        for c in df.columns:
            if c != "Tarih": df[c] = df[c].apply(safe_float)
            
        df["Tarih"] = pd.to_datetime(df["Tarih"], errors="coerce")
        df = df.dropna(subset=["Tarih"])
        return df.sort_values("Tarih", ascending=True)
    except: return pd.DataFrame()

def get_history_data():
    client = init_connection()
    try:
        sheet = client.open_by_key(SHEET_ID).worksheet("Gecmis")
        raw = sheet.get_all_values()
        if len(raw) < 2: return pd.DataFrame()
        
        actual_cols = raw[0]
        valid_data = []
        for r in raw[1:]:
            r_padded = r + ["0"] * (len(actual_cols) - len(r))
            valid_data.append(r_padded[:len(actual_cols)])

        df = pd.DataFrame(valid_data, columns=actual_cols)

        expected_cols = ["ToplamVarlik", "ToplamMaliyet", "DolarKuru", "NetAnaPara"]
        for c in expected_cols:
            if c in df.columns: df[c] = df[c].apply(safe_float)
            else: df[c] = 0.0

        df["Tarih"] = pd.to_datetime(df["Tarih"], errors="coerce")
        df = df.dropna(subset=["Tarih"]) 
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
    
    tl_injected = 0; usd_injected = 0; gold_injected = 0
    df_al = df_transactions[df_transactions["Islem"] == "Alış"]
    df_sat = df_transactions[df_transactions["Islem"] == "Satış"]
    
    for _, r in df_al.iterrows():
        try:
            day = m.loc[m.index.asof(r["Tarih"].date())]
            usd = day['USD']; gold = day['Gram_Gold']; amt = float(r["Toplam"])
            tl_injected += amt
            if usd > 0: usd_injected += amt / usd
            if gold > 0: gold_injected += amt / gold
        except: continue
        
    net_ana_para = df_al["Toplam"].apply(safe_float).sum() - df_sat["Toplam"].apply(safe_float).sum()
    
    if tl_injected > 0 and net_ana_para > 0:
        avg_usd_rate = tl_injected / usd_injected if usd_injected > 0 else 1
        avg_gold_rate = tl_injected / gold_injected if gold_injected > 0 else 1
        usd_eq = net_ana_para / avg_usd_rate; gold_eq = net_ana_para / avg_gold_rate
        
        try:
            last = m.iloc[-1]
            return usd_eq * last['USD'], gold_eq * last['Gram_Gold'], usd_eq, gold_eq
        except: pass
    return 0, 0, 0, 0

def calculate_net_usd_cost(df_transactions):
    m = get_historical_market_data()
    if m.empty: return 0
    net_usd_cost = 0
    df_s = df_transactions.sort_values("Tarih")
    for _, r in df_s.iterrows():
        try:
            day = m.loc[m.index.asof(r["Tarih"].date())]
            usd_rate = day['USD']; amt = float(r["Toplam"])
            if r["Islem"] == "Alış": net_usd_cost += amt / usd_rate
            else: net_usd_cost -= amt / usd_rate
        except: continue
    return net_usd_cost

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

# --- ANA HESAPLAMA MOTORU ---
def calculate_portfolio_unified(df):
    portfolio = {}
    df = df.sort_values("Tarih")
    toplam_giren = 0; toplam_cikan = 0
    
    for _, row in df.iterrows():
        sym = row["Sembol"]; typ = row["Tur"]; islem = row["Islem"]
        qty = float(row["Adet"]); total = float(row["Toplam"]); tarih = row["Tarih"]
        
        if islem == "Alış": toplam_giren += total
        else: toplam_cikan += total

        if sym not in portfolio: 
            portfolio[sym] = {"Adet": 0, "Maliyet": 0, "NetGiris": 0.0, "Tur": typ, "Alimlar": []}
        
        if islem == "Alış":
            portfolio[sym]["Adet"] += qty
            portfolio[sym]["Maliyet"] += total 
            portfolio[sym]["NetGiris"] += total 
            portfolio[sym]["Alimlar"].append({"adet": qty, "tarih": tarih}) 
            
        elif islem == "Satış":
            if portfolio[sym]["Adet"] > 0:
                avg_cost = portfolio[sym]["Maliyet"] / portfolio[sym]["Adet"]
                portfolio[sym]["Maliyet"] -= (qty * avg_cost)
                portfolio[sym]["Adet"] -= qty
                portfolio[sym]["NetGiris"] -= total 
                
                kalan_satis = qty
                while kalan_satis > 0 and len(portfolio[sym]["Alimlar"]) > 0:
                    ilk_alim = portfolio[sym]["Alimlar"][0]
                    if ilk_alim["adet"] <= kalan_satis:
                        kalan_satis -= ilk_alim["adet"]
                        portfolio[sym]["Alimlar"].pop(0) 
                    else:
                        ilk_alim["adet"] -= kalan_satis
                        kalan_satis = 0
            else:
                portfolio[sym]["Adet"] = 0; portfolio[sym]["Maliyet"] = 0; portfolio[sym]["NetGiris"] = 0; portfolio[sym]["Alimlar"] = []
                
        if portfolio[sym]["Adet"] <= 0.001: 
            portfolio[sym]["Adet"] = 0; portfolio[sym]["Maliyet"] = 0; portfolio[sym]["NetGiris"] = 0; portfolio[sym]["Alimlar"] = []
            
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
                    hata = False
                    
                    # DÜZELTME 1: SATIŞ İŞLEMİNDE 0 TL ENGELİ
                    if metod == "Birim Fiyat":
                        if yon == "Satış" and fiyat <= 0:
                            st.error("⚠️ Hata: Satış işlemi için fiyat 0'dan büyük olmalıdır!")
                            hata = True
                        elif fiyat >= 0:
                            raw = adet * fiyat
                            toplam = raw + kom if yon == "Alış" else raw - kom
                        else:
                            hata = True
                    else:
                        if yon == "Satış" and toplam_girilen <= 0:
                            st.error("⚠️ Hata: Satış işlemi için tutar 0'dan büyük olmalıdır!")
                            hata = True
                        elif toplam_girilen >= 0:
                            toplam = toplam_girilen
                            fiyat = (toplam_girilen / adet) if adet > 0 else 0; kom = 0
                        else:
                            hata = True
                    
                    if not hata:
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
        portfolio, t_giren, t_cikan = calculate_portfolio_unified(df)
        fund_data = get_fund_data_from_sheet()
        dolar = get_usd_rate()
        
        net_ana_para_tl = t_giren - t_cikan
        alt_usd, alt_gold, net_ana_para_usd_maliyeti, _ = calculate_benchmarks(df)
        
        liste = []
        gunluk_toplam_tl = 0
        bugun_tarih = datetime.now()
        
        for sym, data in portfolio.items():
            net = data["Adet"]
            if net > 0:
                em = data["Maliyet"]
                v_tur = data["Tur"]
                risk_kalan = data["NetGiris"]
                alimlar = data["Alimlar"]
                
                total_weighted_days = 0
                for alim in alimlar:
                    gun_farki = (bugun_tarih - alim["tarih"]).days
                    gun_farki = max(1, gun_farki) 
                    total_weighted_days += gun_farki * alim["adet"]
                
                ort_gun = int(total_weighted_days / net) if net > 0 else 0

                guncel = 0.0; ref_fiyat = 0.0
                if v_tur == "Hisse":
                    curr_p, prev_p = get_stock_data_full(sym)
                    guncel = curr_p if curr_p else 0
                    ref_fiyat = prev_p if prev_p else guncel
                else:
                    f_info = fund_data.get(sym, {"fiyat": 0, "yuzde": 0})
                    guncel = f_info["fiyat"]
                    pct = f_info["yuzde"]
                    if guncel == 0: guncel = em / net if net > 0 else 0; ref_fiyat = guncel
                    else: ref_fiyat = guncel / (1 + (pct/100))
                
                deger = net * guncel
                kz = deger - em
                kz_yuzde = (kz / em) * 100 if em > 0 else 0

                gf_tl = (guncel - ref_fiyat) * net
                gf_yuzde = ((guncel - ref_fiyat) / ref_fiyat) * 100 if ref_fiyat > 0 else 0
                
                gf_metin = f"{gf_tl:+,.0f} (%{gf_yuzde:+.2f})" 
                gunluk_toplam_tl += gf_tl
                
                maliyet_durumu = "BEDAVA" if risk_kalan <= 0 else risk_kalan

                liste.append({
                    "Varlık": sym, 
                    "Lot": net,
                    "Ort. Maliyet": (em / net) if net > 0 else 0,
                    "Fiyat": guncel,
                    "Kalan Risk (TL)": maliyet_durumu,
                    "Değer (TL)": float(deger),
                    "Ort. Süre": f"{ort_gun} Gün", 
                    "K/Z (TL)": float(kz),
                    "K/Z (%)": float(kz_yuzde),
                    "Günlük Fark": gf_metin
                })

        if liste:
            df_v = pd.DataFrame(liste)
            toplam_portfoy_degeri = df_v["Değer (TL)"].sum()
            toplam_maliyet = sum([x["Ort. Maliyet"] * x["Lot"] for x in liste])
            
            save_daily_snapshot(toplam_portfoy_degeri, toplam_maliyet, dolar, net_ana_para_tl)
            save_asset_snapshots(liste) 
            
            genel_kar = toplam_portfoy_degeri - net_ana_para_tl
            genel_ky = (genel_kar / net_ana_para_tl)*100 if net_ana_para_tl > 0 else 0
            
            bench_df = pd.DataFrame({
                "Varlık": ["Sizin Portföy", "Dolar Olsaydı", "Altın Olsaydı"],
                "Değer (TL)": [toplam_portfoy_degeri, alt_usd, alt_gold], "Renk": ["blue", "green", "gold"]
            })

            # Grafikler
            c1, c2 = st.columns(2)
            with c1: st.plotly_chart(px.pie(df_v, values='Değer (TL)', names='Varlık', hole=0.4), use_container_width=True)
            with c2: st.plotly_chart(px.bar(bench_df, x="Varlık", y="Değer (TL)", color="Varlık", text_auto='.2s', color_discrete_map={"Sizin Portföy": "#3498db", "Dolar Olsaydı": "#2ecc71", "Altın Olsaydı": "#f1c40f"}), use_container_width=True)
            
            # --- GENİŞ KUTUCUK TASARIMI ---
            anlik_kz = toplam_portfoy_degeri - toplam_maliyet
            anlik_ky = (anlik_kz / toplam_maliyet) * 100 if toplam_maliyet > 0 else 0
            
            k1, k2, k3 = st.columns(3)
            k1.metric("Portföy Değeri", f"{toplam_portfoy_degeri:,.0f} ₺", f"${toplam_portfoy_degeri/dolar:,.0f}", delta_color="off")
            k2.metric("Maliyet (Eldeki)", f"{toplam_maliyet:,.0f} ₺")
            k3.metric("Anlık K/Z (Eldeki)", f"{anlik_kz:+,.0f} ₺", f"%{anlik_ky:.1f} (Maliyete Göre)") 
            
            st.divider()
            
            k4, k5, k6 = st.columns(3)
            k4.metric("Günlük Fark", f"{gunluk_toplam_tl:+,.0f} ₺")
            k5.metric("Net Ana Para (Riskli)", f"{net_ana_para_tl:,.0f} ₺", f"Dolar Maliyeti: ${net_ana_para_usd_maliyeti:,.0f}", delta_color="off")
            k6.metric("GENEL KAR", f"{genel_kar:+,.0f} ₺", f"%{genel_ky:.1f} (Ana Paraya Göre)")

            st.divider()

            # TABLO
            st.subheader("📋 Portföy Detayı")
            def format_risk(val):
                if isinstance(val, (int, float)): return f"{val:,.0f}"
                return val
            
            cfg = {
                "Varlık": st.column_config.TextColumn("Varlık", disabled=True),
                "Lot": st.column_config.NumberColumn("Lot", format="%.0f"),
                "Ort. Maliyet": st.column_config.NumberColumn("Ort. Maliyet", format="%.4f"),
                "Fiyat": st.column_config.NumberColumn("Fiyat", format="%.4f"),
                "Kalan Risk (TL)": st.column_config.Column("Kalan Risk", disabled=True),
                "Değer (TL)": st.column_config.NumberColumn("Değer (TL)", format="%.0f"),
                "Ort. Süre": st.column_config.TextColumn("Elde Tutma"),
                "K/Z (TL)": st.column_config.NumberColumn("K/Z (TL)", format="%.0f"),
                "K/Z (%)": st.column_config.NumberColumn("K/Z (%)", format="%.2f"),
                "Günlük Fark": st.column_config.TextColumn("Günlük", disabled=True)
            }
            
            st.dataframe(df_v.style.format({
                "Ort. Maliyet": "{:,.4f}", "Fiyat": "{:,.4f}",
                "Değer (TL)": "{:,.0f}", 
                "K/Z (TL)": "{:+,.0f}", "K/Z (%)": "{:+.2f} %"
            }).format({"Kalan Risk (TL)": format_risk}).map(renk, subset=["K/Z (TL)", "K/Z (%)", "Günlük Fark"]), 
            use_container_width=True, hide_index=True, column_config=cfg)

with tab3:
    st.subheader("📈 Gidişat")
    
    # 1. Genel Portföy Gidişatı
    df_hist = get_history_data()
    if not df_hist.empty:
        df_hist["GenelKar"] = df_hist["ToplamVarlik"] - df_hist["NetAnaPara"]
        df_hist["AnlikKar"] = df_hist.apply(lambda r: r["ToplamVarlik"] - r["ToplamMaliyet"] if r["ToplamMaliyet"] > 100 else 0, axis=1)
        
        f1 = go.Figure()
        f1.add_trace(go.Scatter(x=df_hist["Tarih"], y=df_hist["ToplamVarlik"], name='Toplam Servet', line=dict(color='#2ecc71', width=3)))
        f1.add_trace(go.Scatter(x=df_hist["Tarih"], y=df_hist["NetAnaPara"], name='İçerideki Ana Para', line=dict(color='gray', dash='dot')))
        f1.update_layout(title="Toplam Varlık vs Ana Para", hovermode="x unified")
        st.plotly_chart(f1, use_container_width=True)
        
        st.divider()
        
        f2 = go.Figure()
        f2.add_trace(go.Scatter(x=df_hist["Tarih"], y=df_hist["GenelKar"], name='GENEL KÂR (Cepteki Dahil)', line=dict(color='#3498db', width=3)))
        f2.add_trace(go.Scatter(x=df_hist["Tarih"], y=df_hist["AnlikKar"], name='ANLIK KÂR (Sadece Eldekiler)', line=dict(color='#f1c40f', width=2, dash='dash')))
        f2.update_layout(title="Kâr Analizi: Genel vs Anlık", hovermode="x unified")
        st.plotly_chart(f2, use_container_width=True)
    else: st.info("Genel veri toplanıyor...")
    
    st.divider()

    # 2. DÜZELTME 2: Varlık Bazında Kâr Gidişatı (Sadece aktif olanları gösterir)
    df_assets = get_asset_history()
    if not df_assets.empty and len(df_assets.columns) > 1:
        st.subheader("📊 Varlık Bazında Kâr/Zarar (%) Gidişatı")
        st.info("💡 Not: Grafik bugünden itibaren her gün varlıkların kapanış performansını işleyerek ilerleyecektir. Tamamen satılan varlıklar grafikten otomatik gizlenir.")
        
        # Sadece güncel olarak elimizde olan sembolleri grafiğe dahil ediyoruz
        portfolio_gidisat, _, _ = calculate_portfolio_unified(df)
        aktif_semboller = [sym for sym, d in portfolio_gidisat.items() if d["Adet"] > 0]
        
        gosterilecek_kolonlar = ["Tarih"] + [c for c in df_assets.columns if c in aktif_semboller]
        
        if len(gosterilecek_kolonlar) > 1:
            df_assets_aktif = df_assets[gosterilecek_kolonlar]
            df_melted = df_assets_aktif.melt(id_vars=["Tarih"], var_name="Varlık", value_name="K/Z (%)")
            
            f3 = px.line(df_melted, x="Tarih", y="K/Z (%)", color="Varlık", markers=True)
            f3.add_hline(y=0, line_dash="dash", line_color="red") 
            f3.update_layout(hovermode="x unified", yaxis_title="Kâr / Zarar (%)")
            st.plotly_chart(f3, use_container_width=True)
        else:
            st.warning("Grafiği çizilecek aktif varlık bulunamadı.")

with tab4:
    st.dataframe(df.sort_index(ascending=False).style.format({"Fiyat": "{:,.4f}", "Toplam": "{:,.2f}", "Komisyon": "{:,.2f}", "Adet": "{:.0f}"}), use_container_width=True)
