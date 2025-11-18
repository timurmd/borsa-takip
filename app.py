import streamlit as st
import pandas as pd
import yfinance as yf
from datetime import datetime
import os

# --- AYARLAR ---
st.set_page_config(layout="wide", page_title="Portföy v16.2")
DATA_FILE = "portfolio_transactions.csv"

# --- DOSYA KONTROL ---
if not os.path.exists(DATA_FILE):
    cols = ["Tarih", "Tur", "Islem", "Sembol", "Adet", "Fiyat", "Komisyon", "Toplam"]
    df = pd.DataFrame(columns=cols)
    df.to_csv(DATA_FILE, index=False)
else:
    # Eski dosya varsa sütun kontrolü
    df_temp = pd.read_csv(DATA_FILE)
    if "Tur" not in df_temp.columns:
        df_temp["Tur"] = "Hisse"
        df_temp.to_csv(DATA_FILE, index=False)

# --- RENK FONKSİYONU ---
def renk_belirle(val):
    color = 'white'
    if isinstance(val, (int, float)):
        if val > 0: color = '#2ecc71'
        elif val < 0: color = '#e74c3c'
    return f'color: {color}; font-weight: bold;'

# --- FİYAT ÇEKME ---
def get_stock_price(symbol):
    try:
        symbol = symbol.upper()
        if not symbol.endswith(".IS"):
            symbol = f"{symbol}.IS"
        ticker = yf.Ticker(symbol)
        val = ticker.fast_info['last_price']
        return val if val is not None else 0.0
    except:
        return 0.0

def save_db(df):
    df.to_csv(DATA_FILE, index=False)

# --- ARAYÜZ ---
st.title("💰 Kişisel Portföy")

tab1, tab2, tab3 = st.tabs(["➕ EKLE", "📊 PORTFÖY", "📋 GEÇMİŞ"])

# --- TAB 1: EKLEME ---
with tab1:
    col1, col2 = st.columns(2)
    with col1:
        st.subheader("Yeni İşlem")
        with st.form("entry_form", clear_on_submit=True):
            v_tur = st.radio("Tür", ["Hisse Senedi", "Yatırım Fonu"], horizontal=True)
            
            c1, c2 = st.columns(2)
            tarih = c1.date_input("Tarih", datetime.now())
            kod = c2.text_input("Kod").upper()
            
            yon = st.radio("Yön", ["Alış", "Satış"], horizontal=True)
            
            c3, c4, c5 = st.columns(3)
            adet = c3.number_input("Adet", min_value=1, step=1, format="%d")
            fiyat = c4.number_input("Fiyat", min_value=0.0, format="%.6f")
            kom = c5.number_input("Komisyon", min_value=0.0, format="%.2f")
            
            if st.form_submit_button("KAYDET"):
                if kod and fiyat > 0:
                    df = pd.read_csv(DATA_FILE)
                    
                    # Hesaplama
                    tutar = adet * fiyat
                    toplam = 0.0
                    if yon == "Alış":
                        toplam = tutar + kom
                    else:
                        toplam = tutar - kom
                    
                    # Kısa atamalar (Hata olmasın diye)
                    yeni = {}
                    yeni["Tarih"] = tarih.strftime("%Y-%m-%d")
                    yeni["Tur"] = "Hisse" if v_tur == "Hisse Senedi" else "Fon"
                    yeni["Islem"] = yon
                    yeni["Sembol"] = kod
                    yeni["Adet"] = adet
                    yeni["Fiyat"] = fiyat
                    yeni["Komisyon"] = kom
                    yeni["Toplam"] = toplam
                    
                    df_yeni = pd.DataFrame([yeni])
                    df = pd.concat([df, df_yeni], ignore_index=True)
                    save_db(df)
                    st.success("Kaydedildi!")
                    st.rerun()

    with col2:
        st.subheader("Silme")
        df_sil = pd.read_csv(DATA_FILE)
        if not df_sil.empty:
            st.dataframe(df_sil.tail(3))
            sil_id = st.selectbox("Sil ID:", df_sil.index.sort_values(ascending=False))
            if st.button("Sil"):
                df_sil = df_sil.drop(sil_id)
                save_db(df_sil)
                st.success("Silindi.")
                st.rerun()

# --- TAB 2: PORTFÖY ---
with tab2:
    df = pd.read_csv(DATA_FILE)
    if not df.empty:
        semboller = df["Sembol"].unique()
        data_rows = []
        
        with st.spinner('Hesaplanıyor...'):
            for s in semboller:
                # Veri filtreleme
                txs = df[df["Sembol"] == s]
                tur = txs.iloc[0]["Tur"]
                
                alis = txs[txs["Islem"] == "Alış"]
                satis = txs[txs["Islem"] == "Satış"]
                
                top_alis = alis["Adet"].sum()
                top_satis = satis["Adet"].sum()
                net_adet = top_alis - top_satis
                
                if net_adet > 0:
                    # --- HATA VEREN KISIM PARÇALANDI ---
                    alis_tutar = (alis["Adet"] * alis["Fiyat"]).sum()
                    alis_kom = alis["Komisyon"].sum()
                    top_maliyet = alis_tutar + alis_kom
                    
                    ort_maliyet = 0
                    if top_alis > 0:
                        ort_maliyet = top_maliyet / top_alis
                    # -----------------------------------
                    
                    eldeki_top_maliyet = ort_maliyet * net_adet
                    
                    guncel = 0.0
                    if tur == "Hisse":
                        guncel = get_stock_price(s)
                    else:
                        guncel = ort_maliyet
                    
                    item = {}
                    item["Tur"] = tur
                    item["Sembol"] = s
                    item["Adet"] = float(net_adet)
                    item["Toplam Maliyet"] = float(eldeki_top_maliyet)
                    item["Güncel Fiyat"] = float(guncel)
                    data_rows.append(item)
        
        if data_rows:
            df_view = pd.DataFrame(data_rows)
            
            st.info("Fon fiyatlarını tablodan elle giriniz.")
            
            # Ayarlar (Hatasız 'None' yöntemi)
            cfg = {
                "Sembol": st.column_config.TextColumn("Varlık", disabled=True),
                "Güncel Fiyat": st.column_config.NumberColumn("Fiyat", format="%.4f", min_value=0),
                "Toplam Maliyet": st.column_config.NumberColumn("Maliyet", format="%.2f", disabled=True),
                "Tur": None,
                "Adet": None
            }

            edited_df = st.data_editor(
                df_view,
                column_config=cfg,
                use_container_width=True,
                hide_index=True,
                key="editor_v16_2"
            )
            
            # Sonuçlar
            sonuc_listesi = []
            t_deger = 0
            t_maliyet = 0
            
            for i, row in edited_df.iterrows():
                p_deg = row["Adet"] * row["Güncel Fiyat"]
                m_deg = row["Toplam Maliyet"]
                
                kar_tl = p_deg - m_deg
                kar_yuzde = 0
                if m_deg > 0:
                    kar_yuzde = (kar_tl / m_deg) * 100
                
                t_deger += p_deg
                t_maliyet += m_deg
                
                r = {}
                r["Varlık"] = row["Sembol"]
                r["Toplam Maliyet"] = m_deg
                r["Piyasa Değeri"] = p_deg
                r["K/Z (TL)"] = kar_tl
                r["K/Z (%)"] = kar_yuzde
                sonuc_listesi.append(r)
            
            if sonuc_listesi:
                st.markdown("### 📊 Durum")
                res_df = pd.DataFrame(sonuc_listesi)
                
                fmt = {
                    "Toplam Maliyet": "{:,.2f}",
                    "Piyasa Değeri": "{:,.2f}",
                    "K/Z (TL)": "{:+,.2f}",
                    "K/Z (%)": "{:+.2f} %"
                }
                
                styler = res_df.style.format(fmt).map(renk_belirle, subset=["K/Z (TL)", "K/Z (%)"])
                st.dataframe(styler, use_container_width=True, hide_index=True)
            
            st.divider()
            genel_kz = t_deger - t_maliyet
            genel_yuzde = 0
            if t_maliyet > 0:
                genel_yuzde = (genel_kz / t_maliyet) * 100
            
            k1, k2, k3, k4 = st.columns(4)
            k1.metric("Varlık", f"{t_deger:,.2f}")
            k2.metric("Maliyet", f"{t_maliyet:,.2f}")
            k3.metric("Net K/Z", f"{genel_kz:+,.2f}", delta=f"{genel_kz:+,.2f}")
            k4.metric("Getiri", f"% {genel_yuzde:+.2f}", delta=f"% {genel_yuzde:+.2f}")
            
    else:
        st.warning("İşlem yok.")

# --- TAB 3: GEÇMİŞ ---
with tab3:
    st.dataframe(pd.read_csv(DATA_FILE).sort_index(ascending=False))