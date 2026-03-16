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
    div[data-testid="stMetricValue"] { color: #2B6CB0; font-weight: bold; }
    .risk-toggle { background-color: #FFFFFF; padding: 15px; border-radius: 8px; box-shadow: 0 2px 4px rgba(0,0,0,0.05); margin-bottom: 20px; border-left: 5px solid #1A365D; }
    div[data-testid="stFormSubmitButton"] button, .action-btn { background-color: #1A365D !important; color: #FFFFFF !important; border: none !important; font-weight: bold !important; padding: 10px 24px !important; border-radius: 6px !important; }
    [data-testid="stSidebarNav"] span, [data-testid="stSidebarNav"] div { color: #FFFFFF !important; font-weight: 600; }
    [data-testid="stSidebarNav"] svg { stroke: #FFFFFF !important; fill: #FFFFFF !important; }
</style>
""", unsafe_allow_html=True)

# --- MOTORE ESTRAZIONE DATI BNP (Versione Ultra-Stabilizzata) ---
@st.cache_data(ttl=900)
def fetch_live_certificates():
    url = "https://investimenti.bnpparibas.it/apiv2/api/v1/productlist/"
    headers = {"accept": "application/json", "clientid": "1", "content-type": "application/json", "languageid": "it", "user-agent": "Mozilla/5.0"}
    payload = {
        "clientId": 1, "languageId": "it", "countryId": "", "sortPreference": [], "filterSelections": [],
        "derivativeTypeIds": [7, 9, 23, 24, 580, 581], "productGroupIds": [7],
        "offset": 0, "limit": 5000, "resolveSubPreset": True, "resolveOnlySelectedPresets": False, "allowLeverageGrouping": False
    }
    try:
        response = requests.post(url, headers=headers, json=payload, timeout=15)
        data = response.json()
        items = data.get('products', data.get('data', []))
        if not items and isinstance(data, dict):
            list_keys = [k for k in data.keys() if isinstance(data[k], list)]
            if list_keys: items = data[max(list_keys, key=lambda k: len(data[k]))]
        if not items: return pd.DataFrame()
        
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
            elif 'barrier' in cl: col_mapping[c] = 'Distanza Barriera %'
            elif 'assetclassid' in cl or 'assetclass.id' in cl: col_mapping[c] = 'Categoria_ID'

        df = df.rename(columns=col_mapping)
        df = df.loc[:, ~df.columns.duplicated()].copy()
        
        if 'Categoria_ID' in df.columns:
            asset_map = {1: 'Azioni', 2: 'Indici', 3: 'Valute', 4: 'Materie prime', 5: 'Tassi di interesse', 11: 'ETF', 14: 'Volatility'}
            df['Classe'] = pd.to_numeric(df['Categoria_ID'], errors='coerce').map(asset_map).fillna('Altro')
        
        for col in ['Strike', 'Multiplo', 'Lettera', 'Denaro', 'Leva', 'Distanza Barriera %']:
            if col in df.columns: df[col] = pd.to_numeric(df[col], errors='coerce')
        
        tipo_cols = [c for c in df.columns if df[c].astype(str).str.contains('Short', case=False, na=False).any()]
        if tipo_cols: df = df[df[tipo_cols[0]].astype(str).str.contains('Short', case=False, na=False)]
        
        return df.dropna(subset=['Strike', 'Lettera'])
    except Exception:
        return pd.DataFrame()

# --- SIDEBAR ---
st.sidebar.header("📉 Attriti di Mercato")
ui_spread = st.sidebar.number_input("Bid-Ask Spread (%)", value=0.5, step=0.1) / 100
ui_comm = st.sidebar.number_input("Commissioni (%)", value=0.1, step=0.05) / 100
ui_div = st.sidebar.number_input("Dividend Yield (%)", value=1.5, step=0.1) / 100

st.title("🏦 Turbo Hedge Quant (v5.6)")
is_real_ratio = st.toggle("🛡️ **Hedge Ratio Netto (Risk Manager)**", value=True)

tab1, tab2, tab3, tab4 = st.tabs(["🎯 Setup & Matrice", "📈 Backtest Storico", "🔍 Database Live", "🤖 Advisor Strategico"])

# --- TAB 1: SETUP ---
with tab1:
    with st.form("input_form"):
        col1, col2, col3 = st.columns(3)
        with col1:
            st.markdown("### ⚙️ Derivato")
            cert = st.session_state.get('selected_cert')
            if cert: st.info(f"ISIN: {cert['isin']}")
            p_iniziale = st.number_input("Prezzo Lettera (€)", value=cert['prezzo'] if cert else 7.64, step=0.01)
            strike = st.number_input("Strike", value=cert['strike'] if cert else 7505.97, step=0.01)
            cambio = st.number_input("Cambio", value=1.15, step=0.01)
            multiplo = st.number_input("Multiplo", value=cert['multiplo'] if cert else 0.01, format="%.4f")
            euribor = st.number_input("Euribor 12M", value=0.02456, format="%.5f")
        with col2:
            st.markdown("### 📉 Mercato")
            v_iniziale = st.number_input("Spot", value=6670.75, step=0.01)
            v_ipotetico = st.number_input("Target", value=6000.0, step=0.01)
            giorni = st.number_input("Giorni", value=60, step=1)
        with col3:
            st.markdown("### 💼 Portafoglio")
            ptf = st.number_input("Capitale (€)", value=200000.0, step=1000.0)
            beta = st.number_input("Beta", value=1.00, step=0.05)
        st.divider()
        tipo_c = st.radio("Ottimizzazione", ["Auto", "Manuale"], horizontal=True)
        n_custom = st.number_input("Qtà", value=1000, step=10) if tipo_c == "Manuale" else None
        if st.form_submit_button("🔥 Calcola"):
            params = TurboParameters(p_iniziale, strike, cambio, multiplo, euribor, v_iniziale, v_ipotetico, giorni, ptf, beta, ui_div, ui_spread, ui_comm)
            res = DeterministicTurboCalculator(params).calculate_all()
            if n_custom:
                res['n_turbo'] = float(n_custom)
                res['capitale'] = ptf + (res['n_turbo'] * p_iniziale * (1 + ui_spread + ui_comm))
                res['valore_copertura_simulata'] = res['n_turbo'] * res['prezzo_futuro'] * (1 - ui_spread - ui_comm)
                res['totale_simulato'] = res['valore_ptf_simulato'] + res['valore_copertura_simulata']
                res['percentuale'] = (res['totale_simulato'] - res['capitale']) / res['capitale']
            st.session_state['res'], st.session_state['params'], st.session_state['barriera_calcolata'] = res, params, res['barriera']

    if 'res' in st.session_state:
        res, params = st.session_state['res'], st.session_state['params']
        st.divider()
        c1, c2, c3 = st.columns([1, 1, 1.3])
        with c1:
            st.markdown("<div style='background-color:#2c5282; padding:10px; color:white; border-radius:5px;'>TURBO</div>", unsafe_allow_html=True)
            st.markdown(f"Strike: {params.strike:.2f}<br/>Fair Value: {res['fair_value']:.4f}€", unsafe_allow_html=True)
        with c2:
            st.markdown("<div style='background-color:#2c5282; padding:10px; color:white; border-radius:5px;'>INDICE</div>", unsafe_allow_html=True)
            st.markdown(f"Spot: {params.valore_iniziale:.2f}<br/>Barriera: {res['barriera']:.2f}", unsafe_allow_html=True)
        with c3:
            st.markdown(f"<div style='text-align:right;'><b>Qtà: {res['n_turbo']:,.0f}</b><br/><h3>{res['totale_simulato']:,.2f} €</h3></div>", unsafe_allow_html=True)
            perf = res['percentuale']*100
            st.markdown(f"<div style='background-color:{'#E8F5E9' if perf>=0 else '#FFEBEE'}; text-align:center; padding:10px; border:2px solid {'#2E7D32' if perf>=0 else '#C62828'};'><b>{perf:+.2f}% Perf. Netta</b></div>", unsafe_allow_html=True)
        
        st.divider()
        st.markdown("### 🌡️ Matrice Sensitività")
        var_list = [-0.2, -0.1, -0.05, 0, 0.05, 0.1, 0.2]
        t_steps = sorted(list(set([0, int(params.giorni/2), params.giorni])))
        matrix = []
        for t in t_steps:
            row = []
            for v in var_list:
                s = params.valore_iniziale * (1 + v)
                if s >= res['barriera']: row.append(0.0)
                else: row.append(max(0, (params.strike-s)/params.cambio*params.multiplo) + max(0, res['premio']-(res['premio']/(params.giorni or 1)*t)))
            matrix.append(row)
        df_sens = pd.DataFrame(matrix, columns=[f"{v*100:+.0f}%" for v in var_list], index=[f"T+{t}gg" for t in t_steps])
        st.dataframe(df_sens.style.format("{:.3f}€").background_gradient(cmap='RdYlGn', axis=None, vmin=0.0), use_container_width=True)

# --- TAB 2: BACKTEST ---
with tab2:
    st.markdown("### 🕰️ Backtest e Report PDF")
    if 'barriera_calcolata' not in st.session_state: st.warning("Esegui il Tab 1.")
    else:
        with st.expander("Parametri", expanded=True):
            b1, b2, b3 = st.columns(3)
            t_ptf = b1.text_input("Ticker Ptf", "SPY")
            t_idx = b2.text_input("Ticker Indice", "^GSPC")
            t_fx = b3.text_input("FX", "")
        if st.button("🚀 Avvia"):
            df_bt, msg, diag = run_historical_backtest(t_ptf, t_idx, t_fx, datetime.date(2023,1,1), datetime.date.today(), st.session_state['barriera_calcolata'])
            if df_bt is not None:
                st.divider()
                if diag['color'] == 'error': st.error(f"**{diag['title']}**\n\n{diag['body']}\n\nAzione: {diag['action']}")
                else: st.success(f"**{diag['title']}**\n\n{diag['body']}\n\nAzione: {diag['action']}")
                st.line_chart(df_bt.set_index('Date')['Ptf_Close'])
                st.download_button("📄 Scarica Report PDF", data=generate_pdf_report(df_bt, t_ptf, t_idx, t_fx, st.session_state['barriera_calcolata'], diag), file_name=f"Report_{t_ptf}.pdf")
            else: st.error(msg)

# --- TAB 3: DATABASE ---
with tab3:
    st.markdown("### 🔍 Database Live")
    df_raw = fetch_live_certificates()
    if df_raw.empty: st.error("Nessun dato disponibile.")
    else:
        c1, c2 = st.columns(2)
        scelta_s = c1.selectbox("Sottostante", ["Tutti"] + sorted([str(x) for x in df_raw['Sottostante'].unique()]))
        scelta_c = c2.selectbox("Classe", ["Tutte"] + sorted([str(x) for x in df_raw['Classe'].unique()]))
        df_f = df_raw.copy()
        if scelta_s != "Tutti": df_f = df_f[df_f['Sottostante'] == scelta_s]
        if scelta_c != "Tutte": df_f = df_f[df_f['Classe'] == scelta_c]
        sel = st.dataframe(df_f, use_container_width=True, hide_index=True, on_select="rerun", selection_mode="single-row")
        if len(sel.selection.rows) > 0:
            row = df_f.iloc[sel.selection.rows[0]]
            st.session_state['selected_cert'] = {"isin": row['ISIN'], "strike": row['Strike'], "multiplo": row['Multiplo'], "prezzo": row['Lettera']}
            st.success(f"Agganciato {row['ISIN']}")

# --- TAB 4: ADVISOR (FIXED KEYERROR) ---
with tab4:
    st.markdown("### 🤖 Advisor Strategico")
    with st.form("adv_form"):
        c1, c2 = st.columns(2)
        v_p = c1.number_input("Portafoglio (€)", value=200000)
        v_b = c1.number_input("Beta", value=1.0)
        v_bud = c2.number_input("Budget (€)", value=5000)
        v_dist = c2.slider("Distanza Barriera Min (%)", 2, 30, 10)
        if st.form_submit_button("🔍 Scouting"):
            l_target = (v_p * v_b) / v_bud
            st.info(f"Leva Target: **{l_target:.1f}**")
            df_l = fetch_live_certificates()
            if not df_l.empty:
                # Fallback sicuro per la colonna Distanza
                col_dist = 'Distanza Barriera %' if 'Distanza Barriera %' in df_l.columns else None
                
                df_res = df_l.copy()
                if col_dist:
                    df_res = df_res[df_res[col_dist] >= v_dist]
                
                df_res['Diff_Leva'] = (df_res['Leva'] - l_target).abs()
                matches = df_res.sort_values('Diff_Leva').head(5)
                
                if matches.empty: st.warning("Nessun match. Modifica i filtri.")
                else: st.dataframe(matches, use_container_width=True)
