import streamlit as st
import pandas as pd
import numpy as np
import requests
import datetime
from calculator import TurboParameters, DeterministicTurboCalculator
from charts import generate_scenario_data, plot_payoff_profile, plot_pl_waterfall
from stress_test import run_stress_test
from backtest import run_historical_backtest, generate_pdf_report

# --- STATO DELLA SESSIONE ---
if 'selected_cert' not in st.session_state:
    st.session_state['selected_cert'] = None
if 'ideal_params' not in st.session_state:
    st.session_state['ideal_params'] = None

st.set_page_config(page_title="Turbo Hedge Quant", layout="wide", page_icon="🏦")

# --- INIEZIONE CSS CORPORATE ---
st.markdown("""
<style>
    .stApp { background-color: #F4F7F6; }
    h1, h2, h3 { color: #1A365D; font-family: 'Helvetica Neue', sans-serif; }
    div[data-testid="stForm"] { background-color: #FFFFFF; border-radius: 10px; padding: 20px; box-shadow: 0 4px 6px rgba(0,0,0,0.05); border: none; }
    .stTabs [data-baseweb="tab-list"] { background-color: transparent; }
    .stTabs [data-baseweb="tab"] { background-color: #E2E8F0; border-radius: 8px 8px 0 0; border: none; }
    .stTabs [aria-selected="true"] { background-color: #1A365D !important; color: white !important; }
    .risk-toggle { background-color: #FFFFFF; padding: 15px; border-radius: 8px; box-shadow: 0 2px 4px rgba(0,0,0,0.05); margin-bottom: 20px; border-left: 5px solid #1A365D; }
    div[data-testid="stFormSubmitButton"] button, .action-btn { background-color: #1A365D !important; color: #FFFFFF !important; border: none !important; font-weight: bold !important; padding: 10px 24px !important; border-radius: 6px !important; }
</style>
""", unsafe_allow_html=True)

# --- MOTORE ESTRAZIONE DATI BNP ---
@st.cache_data(ttl=900)
def fetch_live_certificates():
    url = "https://investimenti.bnpparibas.it/apiv2/api/v1/productlist/"
    headers = {"accept": "application/json", "clientid": "1", "content-type": "application/json", "languageid": "it", "user-agent": "Mozilla/5.0"}
    payload = {"clientId": 1, "languageId": "it", "countryId": "", "sortPreference": [], "filterSelections": [], "derivativeTypeIds": [7, 9, 23, 24, 580, 581], "productGroupIds": [7], "offset": 0, "limit": 5000, "resolveSubPreset": True, "resolveOnlySelectedPresets": False, "allowLeverageGrouping": False}
    try:
        response = requests.post(url, headers=headers, json=payload, timeout=15)
        data = response.json()
        items = data.get('products', data.get('data', []))
        df = pd.json_normalize(items)
        col_mapping = {}
        for c in sorted(df.columns, key=len):
            cl = c.lower()
            if 'isin' in cl and 'underlying' not in cl: col_mapping[c] = 'ISIN'
            elif ('underlyingname' in cl or 'underlying.name' in cl) and 'short' not in cl: col_mapping[c] = 'Sottostante'
            elif 'strike' in cl: col_mapping[c] = 'Strike'
            elif 'ratio' in cl or 'multiplier' in cl: col_mapping[c] = 'Multiplo'
            elif cl == 'ask' or cl.endswith('.ask'): col_mapping[c] = 'Lettera'
            elif cl == 'bid' or cl.endswith('.bid'): col_mapping[c] = 'Denaro'
            elif 'leverage' in cl: col_mapping[c] = 'Leva'
            elif 'distancetobarrier' in cl: col_mapping[c] = 'Distanza Barriera %'
            elif 'assetclassid' in cl: col_mapping[c] = 'Categoria_ID'
        df.rename(columns=col_mapping, inplace=True)
        df = df.loc[:, ~df.columns.duplicated()] 
        df = df[df['ISIN'].notna()]
        # Filtro Short forzato
        tipo_cols = [c for c in df.columns if df[c].astype(str).str.contains('Short', case=False, na=False).any()]
        if tipo_cols: df = df[df[tipo_cols[0]].astype(str).str.contains('Short', case=False, na=False)]
        
        asset_map = {1: 'Azioni', 2: 'Indici', 3: 'Valute', 4: 'Materie prime', 5: 'Tassi di interesse', 11: 'ETF', 14: 'Volatility'}
        if 'Categoria_ID' in df.columns:
            df['Classe'] = pd.to_numeric(df['Categoria_ID'], errors='coerce').map(asset_map).fillna('Altro')
        
        for col in ['Strike', 'Multiplo', 'Lettera', 'Denaro', 'Leva', 'Distanza Barriera %']:
            if col in df.columns: df[col] = pd.to_numeric(df[col], errors='coerce')
        return df.dropna(subset=['Strike', 'Lettera'])
    except: return pd.DataFrame()

# --- SIDEBAR ---
st.sidebar.header("📉 Attriti")
ui_spread = st.sidebar.number_input("Spread (%)", value=0.5) / 100
ui_comm = st.sidebar.number_input("Comm (%)", value=0.1) / 100
ui_div = st.sidebar.number_input("Dividendi (%)", value=1.5) / 100

st.title("🏦 Hedge Intelligence System (v5.0)")

tab1, tab2, tab3, tab4 = st.tabs(["🎯 Setup & Sensitività", "📈 Backtest", "🔍 Database Live", "🧠 Ricerca Intelligente"])

# ======================================================================
# TAB 4: INTELLIGENCE & MATCHMAKING
# ======================================================================
with tab4:
    st.header("🧠 Calcolo Struttura Ideale")
    st.markdown("Inserisci i parametri del tuo portafoglio e la tua tolleranza al rischio per trovare il certificato perfetto.")
    
    with st.container():
        c1, c2, c3 = st.columns(3)
        cap_ptf = c1.number_input("Capitale da coprire (€)", value=200000.0, step=1000.0, key="iq_cap")
        beta_ptf = c2.number_input("Beta del Portafoglio", value=1.0, step=0.1, key="iq_beta")
        idx_spot = c3.number_input("Livello Corrente Indice", value=6670.0, step=1.0, key="iq_spot")
        
        c4, c5, c6 = st.columns(3)
        buffer = c4.slider("Cuscinetto di Sicurezza (Distanza Barriera %)", 5, 50, 15, help="A che distanza deve essere lo Strike per non essere colpito da rimbalzi?")
        leva_target = c5.select_slider("Profilo Aggressività (Leva)", options=[2, 5, 10, 20, 50], value=10)
        
    if st.button("🔍 Calcola Struttura e Trova Match", type="primary"):
        # Logica IQ: Lo strike ideale è Spot * (1 + Buffer%)
        strike_ideale = idx_spot * (1 + (buffer/100))
        # Esposizione nominale necessaria = Capitale * Beta
        exp_nominale = cap_ptf * beta_ptf
        
        st.session_state['ideal_params'] = {
            "strike": strike_ideale,
            "leva": leva_target,
            "spot": idx_spot
        }
        
        st.subheader("🎯 Parametri Teorici Ottimali")
        m1, m2, m3 = st.columns(3)
        m1.metric("Strike Ideale", f"{strike_ideale:.2f}")
        m2.metric("Leva Consigliata", f"{leva_target}x")
        m3.metric("Esposizione Nominale", f"{exp_nominale:,.0f} €")
        
        # --- ALGORITMO DI MATCHING ---
        df_live = fetch_live_certificates()
        if not df_live.empty:
            # Filtriamo per lo stesso sottostante se possibile o mostriamo i migliori in generale
            # Calcolo dello Score di Matching (Scarto pesato tra Strike e Leva)
            df_live['Score'] = (abs(df_live['Strike'] - strike_ideale) / strike_ideale) + (abs(df_live['Leva'] - leva_target) / leva_target)
            
            matches = df_live.sort_values('Score').head(5)
            
            st.success("✅ Match trovati nel Database BNP Paribas:")
            
            # Mostriamo i risultati con pulsante di selezione rapida
            for idx, row in matches.iterrows():
                with st.expander(f"MATCH #{idx} - ISIN: {row['ISIN']} ({row['Sottostante']})"):
                    col_a, col_b, col_c = st.columns(3)
                    col_a.write(f"**Strike:** {row['Strike']}")
                    col_b.write(f"**Leva:** {row['Leva']}")
                    col_c.write(f"**Distanza Barriera:** {row['Distanza Barriera %']}%")
                    
                    if st.button(f"Aggancia ISIN {row['ISIN']}", key=row['ISIN']):
                        st.session_state['selected_cert'] = {
                            "isin": row['ISIN'],
                            "strike": float(row['Strike']),
                            "multiplo": float(row['Multiplo']),
                            "prezzo": float(row['Lettera'])
                        }
                        st.success(f"Certificato {row['ISIN']} inviato al Setup!")
                        st.balloons()
        else:
            st.error("Impossibile accedere al database live per il matching.")

# ======================================================================
# TAB 1, 2, 3 (Codice Precedente Consolidato)
# ======================================================================
with tab1:
    with st.form("input_form"):
        col1, col2, col3 = st.columns(3)
        with col1:
            st.markdown("### ⚙️ Derivato")
            cert = st.session_state.get('selected_cert')
            if cert: st.info(f"ISIN: {cert['isin']}")
            p_iniziale = st.number_input("Prezzo Lettera (€)", value=cert['prezzo'] if cert else 7.64)
            strike = st.number_input("Strike", value=cert['strike'] if cert else 7505.97)
            cambio = st.number_input("Cambio", value=1.15)
            multiplo = st.number_input("Multiplo", value=cert['multiplo'] if cert else 0.01, format="%.4f")
            euribor = st.number_input("Euribor 12M", value=0.02456, format="%.5f")
        with col2:
            st.markdown("### 📉 Mercato")
            v_iniziale = st.number_input("Indice Spot", value=6670.75)
            v_ipotetico = st.number_input("Target Scenario", value=6000.0)
            giorni = st.number_input("Giorni", value=60)
        with col3:
            st.markdown("### 💼 Portafoglio")
            ptf = st.number_input("Capitale (€)", value=200000.0)
            beta = st.number_input("Beta", value=1.0)
        
        st.divider()
        tipo_copertura = st.radio("Ottimizzazione", ["Auto", "Manuale"], horizontal=True)
        n_turbo_manual = st.number_input("Q.tà Manuale", value=1000) if tipo_copertura == "Manuale" else None
        
        submitted = st.form_submit_button("🔥 Calcola")

    if submitted:
        params = TurboParameters(p_iniziale, strike, cambio, multiplo, euribor, v_iniziale, v_ipotetico, giorni, ptf, beta, ui_div, ui_spread, ui_comm)
        calc = DeterministicTurboCalculator(params)
        res = calc.calculate_all()
        if n_turbo_manual: res['n_turbo'] = float(n_turbo_manual) # Override
        st.session_state['res'], st.session_state['params'] = res, params

    if 'res' in st.session_state:
        res, params = st.session_state['res'], st.session_state['params']
        # Grafico Payoff e Matrice (Omesse qui per brevità, ma incluse nel tuo file completo)
        st.write("### Risultato Sintetico")
        st.metric("Hedge Ratio Reale", f"{res['hedge_ratio_reale']*100:.1f}%")
        # [INSERIRE QUI TUTTE LE TABELLE DELLA V4.5]

with tab3:
    st.header("🔍 Database Live")
    df_raw = fetch_live_certificates()
    if not df_raw.empty:
        st.dataframe(df_raw, use_container_width=True)
