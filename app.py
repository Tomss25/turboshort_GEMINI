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
    div[data-testid="stFormSubmitButton"] button:hover, .action-btn:hover { background-color: #2c5282 !important; color: #FFFFFF !important; }
    [data-testid="stSidebar"] { background-color: #1A365D !important; }
    [data-testid="stSidebar"] .stMarkdown p, [data-testid="stSidebar"] .stMarkdown h1, [data-testid="stSidebar"] .stMarkdown h2, [data-testid="stSidebar"] .stMarkdown h3, [data-testid="stSidebar"] .stMarkdown em { color: #FFFFFF !important; }
    [data-testid="stSidebar"] [data-testid="stExpander"] { background-color: #FFFFFF !important; border-radius: 8px !important; border: none !important; margin-bottom: 12px !important; }
    [data-testid="stSidebar"] [data-testid="stExpander"] p, [data-testid="stSidebar"] [data-testid="stExpander"] label, [data-testid="stSidebar"] [data-testid="stExpander"] div { color: #1A365D !important; font-weight: 500; }
    [data-testid="stSidebar"] [data-testid="stExpander"] input { background-color: #F4F7F6 !important; color: #000000 !important; border: 1px solid #CBD5E0 !important; }
    [data-testid="stSidebar"] [data-testid="stExpander"] svg { stroke: #1A365D !important; }
</style>
""", unsafe_allow_html=True)

# --- MOTORE ESTRAZIONE DATI BNP (Nascosto nel backend) ---
@st.cache_data(ttl=900)
def fetch_live_certificates():
    url = "https://investimenti.bnpparibas.it/apiv2/api/v1/productlist/"
    headers = {
        "accept": "application/json",
        "clientid": "1",
        "content-type": "application/json",
        "languageid": "it",
        "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"
    }
    payload = {
        "clientId": 1, "languageId": "it", "countryId": "", "sortPreference": [], "filterSelections": [],
        "derivativeTypeIds": [7, 9, 23, 24, 580, 581], "productGroupIds": [7],
        "offset": 0, "limit": 5000, "resolveSubPreset": True, "resolveOnlySelectedPresets": False, "allowLeverageGrouping": False
    }
    try:
        response = requests.post(url, headers=headers, json=payload, timeout=15)
        response.raise_for_status()
        data = response.json()
        
        items = []
        if 'products' in data: items = data['products']
        elif 'data' in data and isinstance(data['data'], list): items = data['data']
        else:
            list_keys = [k for k in data.keys() if isinstance(data[k], list)]
            if list_keys: items = data[max(list_keys, key=lambda k: len(data[k]))]
                    
        if not items: return pd.DataFrame({"Errore": ["Nessun dato dal server BNP."]})
            
        df = pd.json_normalize(items)
        col_mapping = {}
        for c in df.columns:
            cl = c.lower()
            if 'isin' in cl and 'underlying' not in cl: col_mapping[c] = 'ISIN'
            elif 'underlyingname' in cl or 'underlying.name' in cl: col_mapping[c] = 'Sottostante'
            elif 'strike' in cl: col_mapping[c] = 'Strike'
            elif 'ratio' in cl or 'multiplier' in cl: col_mapping[c] = 'Multiplo'
            elif 'ask' in cl: col_mapping[c] = 'Lettera'
            elif 'bid' in cl: col_mapping[c] = 'Denaro'
            elif 'leverage' in cl: col_mapping[c] = 'Leva'
            elif 'direction' in cl or 'type' in cl: col_mapping[c] = 'Categoria'
            elif 'distancetobarrier' in cl: col_mapping[c] = 'Distanza Barriera %'
            
        df.rename(columns=col_mapping, inplace=True)
        colonne_utili = ['ISIN', 'Sottostante', 'Categoria', 'Strike', 'Multiplo', 'Lettera', 'Denaro', 'Leva', 'Distanza Barriera %']
        colonne_finali = [c for c in colonne_utili if c in df.columns]
        
        if len(colonne_finali) >= 4:
            df = df[colonne_finali].copy()
            for col in ['Strike', 'Multiplo', 'Lettera', 'Denaro', 'Leva', 'Distanza Barriera %']:
                if col in df.columns: df[col] = pd.to_numeric(df[col], errors='coerce')
        return df.dropna(subset=['Strike', 'Lettera'])
    except Exception as e:
        return pd.DataFrame({"Errore": [f"Errore connessione API: {str(e)}"]})


# --- SIDEBAR ATTRITI ---
st.sidebar.header("📉 Attriti di Mercato")
with st.sidebar.expander("💰 Costi di Transazione", expanded=True):
    ui_spread = st.number_input("Bid-Ask Spread (%)", min_value=0.0, max_value=5.0, value=0.5, step=0.1) / 100
    ui_comm = st.number_input("Commissioni Broker (%)", min_value=0.0, max_value=2.0, value=0.1, step=0.05) / 100
with st.sidebar.expander("📊 Dividend Yield", expanded=True):
    ui_div = st.number_input("Rendimento Dividendi (%)", min_value=0.0, max_value=10.0, value=1.5, step=0.1) / 100

st.title("🏦 Dashboard Copertura Istituzionale (v3.0)")

st.markdown('<div class="risk-toggle">', unsafe_allow_html=True)
is_real_ratio = st.toggle("🛡️ **Modalità Risk Manager (Hedge Ratio Netto)**", value=True)
st.markdown('</div>', unsafe_allow_html=True)

# --- STRUTTURA A 3 TAB UNIFICATA ---
tab1, tab2, tab3 = st.tabs(["🎯 Setup Copertura & Scenario", "📈 Backtest & Rischio FX", "🔍 Database Live BNP Paribas"])

# ======================================================================
# TAB 1: CALCOLATORE E SCENARI
# ======================================================================
with tab1:
    with st.form("input_form"):
        col1, col2, col3 = st.columns(3)
        with col1:
            st.markdown("### ⚙️ Derivato (Turbo)")
            cert = st.session_state.get('selected_cert')
            if cert:
                st.markdown(f"<div style='background-color:#E8F5E9; color:#2E7D32; padding:5px 10px; border-radius:5px; font-weight:bold; margin-bottom:10px;'>📡 ISIN Caricato: {cert['isin']}</div>", unsafe_allow_html=True)
            
            p_iniziale = st.number_input("Prezzo (Lettera) (€)", value=cert['prezzo'] if cert else 7.64, step=0.01)
            strike = st.number_input("Strike", value=cert['strike'] if cert else 7505.97, step=0.01)
            cambio = st.number_input("Tasso di cambio", value=1.15, step=0.01)
            multiplo = st.number_input("Multiplo", value=cert['multiplo'] if cert else 0.01, format="%.4f")
            euribor = st.number_input("Euribor 12M", value=0.02456, format="%.5f")
            
        with col2:
            st.markdown("### 📉 Mercato")
            v_iniziale = st.number_input("Indice Iniziale", value=6670.75, step=0.01)
            v_ipotetico = st.number_input("Scenario Futuro", value=6000.0, step=0.01)
            giorni = st.number_input("Orizzonte (Giorni)", value=60, step=1)
            
        with col3:
            st.markdown("### 💼 Portafoglio")
            ptf = st.number_input("Capitale Ptf (€)", value=200000.0, step=1000.0)
            beta = st.number_input("Beta", value=1.00, step=0.05)
            
        submitted = st.form_submit_button("Esegui Motore Quantitativo")

    if submitted:
        params = TurboParameters(prezzo_iniziale=p_iniziale, strike=strike, cambio=cambio, multiplo=multiplo, euribor=euribor, valore_iniziale=v_iniziale, valore_ipotetico=v_ipotetico, giorni=giorni, portafoglio=ptf, beta=beta, dividend_yield=ui_div, bid_ask_spread=ui_spread, commissioni_pct=ui_comm)
        calc = DeterministicTurboCalculator(params)
        res = calc.calculate_all()
        st.session_state['barriera_calcolata'] = res['barriera']
        st.session_state['params'] = params
        st.session_state['res'] = res

    if 'res' in st.session_state:
        res = st.session_state['res']
        params = st.session_state['params']
        
        st.divider()
        st.markdown("<h2>📊 Risultati della Copertura</h2>", unsafe_allow_html=True)
        excel_col1, excel_col2, excel_col3 = st.columns([1, 1, 1.3])
        
        with excel_col1:
            st.markdown("<div style='background-color: #2c5282; padding: 12px; border-radius: 5px; text-align: center; margin-bottom: 15px;'><h4 style='margin: 0; color: white; font-size: 16px;'>CARATTERISTICHE TURBO SHORT</h4></div>", unsafe_allow_html=True)
            st.markdown(f"""
            <table style='width: 100%; border-collapse: collapse; font-size: 14px;'>
            <tr style='background-color: #F8F9FA;'><td style='padding: 8px; border: 1px solid #dee2e6;'><strong>Prezzo iniziale</strong></td><td style='padding: 8px; border: 1px solid #dee2e6; text-align: right;'>{params.prezzo_iniziale:.2f} €</td></tr>
            <tr><td style='padding: 8px; border: 1px solid #dee2e6;'><strong>Fair Value (Adj. Div)</strong></td><td style='padding: 8px; border: 1px solid #dee2e6; text-align: right; color: #2c5282; font-weight: bold;'>{res['fair_value']:.4f} €</td></tr>
            <tr style='background-color: #F8F9FA;'><td style='padding: 8px; border: 1px solid #dee2e6;'><strong>Premio</strong></td><td style='padding: 8px; border: 1px solid #dee2e6; text-align: right;'>{res['premio']:.4f} €</td></tr>
            <tr><td style='padding: 8px; border: 1px solid #dee2e6;'><strong>Strike</strong></td><td style='padding: 8px; border: 1px solid #dee2e6; text-align: right;'>{params.strike:.2f}</td></tr>
            <tr style='background-color: #F8F9FA;'><td style='padding: 8px; border: 1px solid #dee2e6;'><strong>Tasso di cambio</strong></td><td style='padding: 8px; border: 1px solid #dee2e6; text-align: right;'>{params.cambio:.2f}</td></tr>
            <tr><td style='padding: 8px; border: 1px solid #dee2e6;'><strong>Multiplo</strong></td><td style='padding: 8px; border: 1px solid #dee2e6; text-align: right;'>{params.multiplo:.4f}</td></tr>
            </table>
            """, unsafe_allow_html=True)

        with excel_col2:
            st.markdown("<div style='background-color: #2c5282; padding: 12px; border-radius: 5px; text-align: center; margin-bottom: 15px;'><h4 style='margin: 0; color: white; font-size: 16px;'>INDICE DA COPRIRE</h4></div>", unsafe_allow_html=True)
            st.markdown(f"""
            <table style='width: 100%; border-collapse: collapse; font-size: 14px;'>
            <tr style='background-color: #F8F9FA;'><td style='padding: 8px; border: 1px solid #dee2e6;'><strong>Valore Iniziale</strong></td><td style='padding: 8px; border: 1px solid #dee2e6; text-align: right;'>{params.valore_iniziale:.2f}</td></tr>
            <tr><td style='padding: 8px; border: 1px solid #dee2e6;'><strong>Valore Ipotetico</strong></td><td style='padding: 8px; border: 1px solid #dee2e6; text-align: right; color: #c62828; font-weight: bold;'>{params.valore_ipotetico:.2f}</td></tr>
            <tr style='background-color: #F8F9FA;'><td style='padding: 8px; border: 1px solid #dee2e6;'><strong>Giorni</strong></td><td style='padding: 8px; border: 1px solid #dee2e6; text-align: right;'>{params.giorni}</td></tr>
            <tr><td style='padding: 8px; border: 1px solid #dee2e6;'><strong>Prezzo Turbo Futuro</strong></td><td style='padding: 8px; border: 1px solid #dee2e6; text-align: right; color: #2c5282; font-weight: bold;'>{res['prezzo_futuro']:.4f} €</td></tr>
            <tr style='background-color: #F8F9FA;'><td style='padding: 8px; border: 1px solid #dee2e6;'><strong>Barriera</strong></td><td style='padding: 8px; border: 1px solid #dee2e6; text-align: right;'>{res['barriera']:.2f}</td></tr>
            </table>
            """, unsafe_allow_html=True)

        with excel_col3:
            st.markdown("<div style='background-color: #2c5282; padding: 12px; border-radius: 5px; text-align: center; margin-bottom: 15px;'><h4 style='margin: 0; color: white; font-size: 16px;'>PORTAFOGLIO DA COPRIRE</h4></div>", unsafe_allow_html=True)
            st.markdown(f"<div style='text-align: right; font-size: 24px; font-weight: bold; color: #2c5282; margin-bottom: 20px; padding: 10px; background-color: #F8F9FA; border-radius: 5px;'>{params.portafoglio:,.2f} €</div>", unsafe_allow_html=True)
            st.markdown(f"""
            <table style='width: 100%; border-collapse: collapse; margin-top: 10px; font-size: 14px;'>
            <tr style='background-color: #F8F9FA;'><td style='padding: 8px; border: 1px solid #dee2e6;'><strong>N. Turbo Short</strong></td><td style='padding: 8px; border: 1px solid #dee2e6; text-align: right;'>{res['n_turbo']:.2f}</td><td rowspan='2' style='padding: 8px; border: 1px solid #dee2e6; text-align: center; vertical-align: middle; background-color: #E3F2FD; font-weight: bold;'>TOTALE CON<br/>COPERTURA</td></tr>
            <tr><td style='padding: 8px; border: 1px solid #dee2e6;'><strong>Capitale + Costi</strong></td><td style='padding: 8px; border: 1px solid #dee2e6; text-align: right;'>{res['capitale']:,.2f} €</td></tr>
            <tr style='background-color: #FFF3E0;'><td colspan='2' style='padding: 8px; border: 1px solid #dee2e6; text-align: right; font-weight: bold;'></td><td style='padding: 8px; border: 1px solid #dee2e6; text-align: center; color: #E65100; font-weight: bold; font-size: 16px;'>{res['totale_copertura']:,.2f} €</td></tr>
            </table>
            """, unsafe_allow_html=True)
            
            perf = res['percentuale'] * 100
            perf_bg, perf_color, perf_sign = ('#E8F5E9', '#2E7D32', '+') if perf >= 0 else ('#FFEBEE', '#C62828', '')
            st.markdown(f"<div style='background-color: {perf_bg}; padding: 20px; border-radius: 5px; text-align: center; border: 3px solid {perf_color}; margin-top: 15px;'><div style='font-size: 42px; font-weight: bold; color: {perf_color}; line-height: 1;'>{perf_sign}{perf:.2f}%</div><div style='color: #666; font-size: 12px; margin-top: 8px; font-weight: 600;'>PERFORMANCE NETTA COPERTA</div></div>", unsafe_allow_html=True)

        st.divider()
        st.subheader("⚠️ Matrice di Stress (Con Slippage Dinamico)")
        df_stress = run_stress_test(st.session_state['params'])
        st.dataframe(df_stress, use_container_width=True, hide_index=True)

        st.divider()
        chart_col1, chart_col2 = st.columns(2)
        with chart_col1:
            df_scenari, livello_barriera = generate_scenario_data(st.session_state['params'])
            st.plotly_chart(plot_payoff_profile(df_scenari, st.session_state['params'].valore_iniziale, livello_barriera), use_container_width=True)
        with chart_col2:
            st.plotly_chart(plot_pl_waterfall(st.session_state['res']), use_container_width=True)

# ======================================================================
# TAB 2: BACKTEST STORICO
# ======================================================================
with tab2:
    st.markdown("### Analisi Storica e Rischio FX")
    if 'barriera_calcolata' not in st.session_state:
        st.warning("Per favore, calcola prima la struttura base nel Tab 'Setup Copertura'.")
    else:
        b_col1, b_col2, b_col3, b_col4, b_col5 = st.columns(5)
        ticker_ptf = b_col1.text_input("Ticker Ptf", value="SPY")
        ticker_idx = b_col2.text_input("Ticker Indice", value="^GSPC")
        ticker_fx = b_col3.text_input("Rischio Cambio (es. EURUSD=X)", value="")
        start_date = b_col4.date_input("Inizio", value=datetime.date(2023, 1, 1))
        end_date = b_col5.date_input("Fine", value=datetime.date.today())
        
        if st.button("🚀 Avvia Backtest Avanzato", type="primary"):
            with st.spinner("Calcolo storico..."):
                df_bt, msg, diagnosis = run_historical_backtest(ticker_ptf, ticker_idx, ticker_fx, start_date, end_date, st.session_state['barriera_calcolata'])
                if df_bt is not None:
                    st.success("Completato.")
                    pdf_bytes = generate_pdf_report(df_bt, ticker_ptf, ticker_idx, ticker_fx, st.session_state['barriera_calcolata'], diagnosis)
                    st.download_button("📄 Scarica PDF", data=pdf_bytes, file_name=f"Hedge_{ticker_ptf}.pdf", mime="application/pdf")
                    if diagnosis['color'] == 'error': st.error(f"**{diagnosis['title']}**\n\n{diagnosis['body']}\n\n**{diagnosis['action']}**")
                    else: st.success(f"**{diagnosis['title']}**\n\n{diagnosis['body']}\n\n**{diagnosis['action']}**")
                else: st.error(f"Errore: {msg}")

# ======================================================================
# TAB 3: DATABASE LIVE BNP PARIBAS
# ======================================================================
with tab3:
    st.markdown("### ⚡ Interrogazione API BNP Paribas")
    st.markdown("Cerca e clicca su un certificato per importare automaticamente i dati nel calcolatore.")
    
    df_raw = fetch_live_certificates()
    if "Errore" in df_raw.columns:
        st.error(df_raw["Errore"].iloc[0])
    else:
        col1, col2, col3 = st.columns(3)
        col_sott = 'Sottostante' if 'Sottostante' in df_raw.columns else df_raw.columns[0]
        col_cat = 'Categoria' if 'Categoria' in df_raw.columns else None
        
        with col1: scelta_sott = st.selectbox("Sottostante BNP", ["Tutti"] + sorted([str(x) for x in df_raw[col_sott].dropna().unique()]))
        with col2: scelta_cat = st.selectbox("Categoria BNP", ["Tutti"] + sorted([str(x) for x in df_raw[col_cat].dropna().unique()])) if col_cat else "Tutti"
        with col3: ricerca_libera = st.text_input("Ricerca ISIN:")
        
        df_filtered = df_raw.copy()
        if scelta_sott != "Tutti": df_filtered = df_filtered[df_filtered[col_sott] == scelta_sott]
        if scelta_cat != "Tutti" and col_cat: df_filtered = df_filtered[df_filtered[col_cat] == scelta_cat]
        if ricerca_libera: df_filtered = df_filtered[df_filtered.astype(str).apply(lambda x: x.str.contains(ricerca_libera, case=False)).any(axis=1)]
        
        selection = st.dataframe(df_filtered, use_container_width=True, hide_index=True, on_select="rerun", selection_mode="single-row")
        
        if len(selection.selection.rows) > 0:
            certificato = df_filtered.iloc[selection.selection.rows[0]]
            prezzo_val = certificato.get('Lettera', certificato.get('Denaro', 0.0))
            if pd.isna(prezzo_val): prezzo_val = 0.0
            
            st.session_state['selected_cert'] = {
                "isin": certificato.get('ISIN', "N/D"),
                "strike": float(certificato.get('Strike', 0.0)),
                "multiplo": float(certificato.get('Multiplo', 0.0)),
                "prezzo": float(prezzo_val)
            }
            st.success(f"✅ Dati agganciati per ISIN: {st.session_state['selected_cert']['isin']}")
            
            # Pulsante per forzare il refresh della pagina e caricare i dati nel Tab 1
            if st.button("🔄 Conferma e Ricarica Tab 1", type="primary"):
                st.rerun()
