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
st.set_page_config(layout="wide", page_title="Portfoy v29")

# 👇👇👇 BURAYI DOLDURUN 👇👇👇
SHEET_ID = "1_isL5_B9EiyLppqdP4xML9N4_pLdvgNYIei70H5yiew"
# 👆👆👆 ------------------ 👆👆👆

DATA_FILE = "portfolio_transactions.csv"
JSON_FILE = "service_account.json"

# ==========================================
# 🔒 GÜVENLİK DUVARI (LOGIN EKRANI)
# ==========================================
def check_password():
    """Şifre kontrolü yapar"""
    def password_entered():
        if st.session_state["password"] == st.secrets["app_password"]:
            st.session_state["password_correct"] = True
            del st.session_state["password"]  # Şifreyi hafızadan sil
        else:
            st.session_state["password_correct"] = False

    if "password_correct" not in st.session_state:
        # İlk açılışta şifre sor
        st.text_input("Lütfen Şifre Giriniz", type="password", on_change=password_entered, key="password")
        return False
    elif not st.session_state["password_correct"]:
        # Şifre yanlışsa tekrar sor
        st.text_input("Lütfen Şifre Giriniz", type="password", on_change=password_entered, key="password")
        st.error("😕 Şifre yanlış.")
        return False
    else:
        # Şifre doğruysa devam et
        return True

if not check_password():
    st.stop() # Şifre girilmediyse kodun geri kalanını çalıştırma!

# ==========================================
# 🔓 BURADAN SONRASI SADECE ŞİFRE BİLENE GÖRÜNÜR
# ==========================================

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
# Çıkış Yap Butonu (Sidebar'a eklenir)
if st.sidebar.button("🔒 Çıkış Yap"):
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
        giris_yontemi = st.radio("Hesaplama Yöntemi:", 
                                 ["Birim Fiyat ile (Klasik)", "Toplam Tutar ile (Stopaj/Net)"], 
                                 horizontal=True)
        st.markdown("---")

        with st.form("ekle", clear_on_submit=True):
            c1, c2 = st.columns(2)
            tur = c1.radio("Tür", ["Hisse Senedi", "Yatırım Fonu"], horizontal=True)
            yon = c2.radio("Yön", ["Alış", "Satış"], horizontal=True)
            
            ca, cb = st.columns(2)
            tarih = ca.date_input("Tarih", datetime.now())
            kod = cb.text_input("Kod (Örn: TTE)").upper()
            
            adet = st.number_input("Adet (Lot)", min_value=1, step=1)
            
            fiyat = 0.0
            kom = 0.0
            toplam = 0.0
            
            cc, cd = st.columns(2)
            
            if giris_yontemi == "Birim Fiyat ile (Klasik)":
                fiyat = cc.number_input("Birim Fiyat", min_value=0.0, format="%.6f")
                kom = cd.number_input("Komisyon", min_value=0.0, format="%.2f")
            else:
                toplam_girilen = cc.number_input("Hesaba Geçen NET Tutar", min_value=0.0, format="%.2f")
                st.caption("Birim fiyat otomatik hesaplanacaktır.")
            
            if st.form_submit_button("KAYDET"):
                if kod and adet > 0:
                    if giris_yontemi == "Birim Fiyat ile (Klasik)":
                        if fiyat > 0:
                            raw_tutar = adet * fiyat
                            if yon == "Alış": toplam = raw_tutar + kom
                            else: toplam = raw_tutar - kom
                        else:
                            st.error("Fiyat giriniz.")
                            st.stop()
                    else:
                        if toplam_girilen > 0:
                            toplam = toplam_girilen
                            fiyat = toplam_girilen / adet
                            kom = 0
                        else:
                            st.error("Tutar giriniz.")
                            st.stop()
                    
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

    with col_sil:
        st.subheader("Silme")
        try:
            df_sil = get_data()
            if not df_sil.empty:
                st.dataframe(df_sil.tail(5)[["Sembol", "Islem", "Toplam"]], use_container_width=True)
                secilen_index = st.selectbox("Silinecek Satır (Index):", df_sil.index.sort_values(ascending=False))
                
                if st.button("Seçili Satırı Sil"):
                    client = init_connection()
                    sheet = client.open_by_key(SHEET_ID).worksheet("Islemler")
                    sheet.delete_rows(int(secilen_index) + 2)
                    st.success("Silindi!")
                    st.cache_data.clear()
                    st.rerun()
            else:
                st.info("Kayıt yok.")
        except:
            st.error("Silme listesi yüklenemedi.")

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
            cfg["Adet"] = st.column_config.NumberColumn("Adet", format="%.0f", disabled=True)
            cfg["Güncel Fiyat"] = st.column_config.NumberColumn("Fiyat", format="%.4f")
            cfg["Toplam Maliyet"] = st.column_config.NumberColumn("Maliyet", format="%.2f", disabled=True)
            cfg["Tur"] = None
            cfg["Not"] = None 
            
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
            
            df_alis = df[df["Islem"] == "Alış"]
            df_satis = df[df["Islem"] == "Satış"]
            toplam_giren = df_alis["Toplam"].sum()
            toplam_cikan = df_satis["Toplam"].sum()
            net_ana_para = toplam_giren - toplam_cikan
            genel_kar_tl = tv - net_ana_para
            genel_kar_yuzde = 0
            if net_ana_para > 0:
                genel_kar_yuzde = (genel_kar_tl / net_ana_para) * 100
            
            k1, k2, k3, k4, k5 = st.columns(5)
            k1.metric("Portföy", f"{tv:,.2f}")
            k2.metric("Maliyet", f"{tm:,.2f}", help="Eldeki hisselerin maliyeti")
            k3.metric("Anlık K/Z", f"{tv-tm:+,.2f}")
            k4.metric("Net Ana Para", f"{net_ana_para:,.2f}", help="Toplam Giren - Toplam Çıkan")
            k5.metric("GENEL KAR", f"{genel_kar_tl:+,.2f}", delta=f"%{genel_kar_yuzde:+.2f}")

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