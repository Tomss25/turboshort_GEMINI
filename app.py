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
    [data-testid="stSidebarNav"] span, [data-testid="stSidebarNav"] div { color: #FFFFFF !important; font-weight: 600; }
    [data-testid="stSidebarNav"] svg { stroke: #FFFFFF !important; fill: #FFFFFF !important; }
</style>
""", unsafe_allow_html=True)

# --- MOTORE ESTRAZIONE DATI BNP ---
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
            elif 'valuationdate' in cl or 'maturitydate' in cl: col_mapping[c] = 'Scadenza'
            elif 'assetclassid' in cl or 'assetclass.id' in cl: col_mapping[c] = 'Categoria_ID'

        df.rename(columns=col_mapping, inplace=True)
        df = df.loc[:, ~df.columns.duplicated()] 
        
        tipo_cols = [c for c in df.columns if df[c].astype(str).str.contains('Short', case=False, na=False).any()]
        if tipo_cols: df['Tipo'] = df[tipo_cols[0]]
        else: df['Tipo'] = 'Turbo Short' 

        df = df[df['Tipo'].astype(str).str.contains('Short', case=False, na=False)]

        if 'Categoria_ID' in df.columns:
            asset_map = {1: 'Azioni', 2: 'Indici', 3: 'Valute', 4: 'Materie prime', 5: 'Tassi di interesse', 11: 'ETF', 14: 'Volatility'}
            df['Classe'] = pd.to_numeric(df['Categoria_ID'], errors='coerce').map(asset_map).fillna('Altro')
        else:
            df['Classe'] = 'N/D'

        if 'Scadenza' in df.columns:
            df['Scadenza'] = pd.to_datetime(df['Scadenza'], errors='coerce').dt.strftime('%d/%m/%Y').fillna('Open End')
        else:
            df['Scadenza'] = 'Open End'
        
        colonne_utili = ['Sottostante', 'ISIN', 'Tipo', 'Classe', 'Scadenza', 'Strike', 'Multiplo', 'Leva', 'Distanza Barriera %', 'Denaro', 'Lettera']
        colonne_finali = [c for c in colonne_utili if c in df.columns]
        
        if len(colonne_finali) >= 4:
            df = df[colonne_finali].copy()
            for col in ['Strike', 'Multiplo', 'Lettera', 'Denaro', 'Leva', 'Distanza Barriera %']:
                if col in df.columns: df[col] = pd.to_numeric(df[col], errors='coerce')
        return df.dropna(subset=['Strike', 'Lettera'])
    except Exception as e:
        return pd.DataFrame({"Errore": [f"Errore API o Parsing: {str(e)}"]})

# --- SIDEBAR ATTRITI ---
st.sidebar.header("📉 Attriti di Mercato")
with st.sidebar.expander("💰 Costi di Transazione", expanded=True):
    ui_spread = st.number_input("Bid-Ask Spread (%)", min_value=0.0, max_value=5.0, value=0.5, step=0.1) / 100
    ui_comm = st.number_input("Commissioni Broker (%)", min_value=0.0, max_value=2.0, value=0.1, step=0.05) / 100
with st.sidebar.expander("📊 Dividend Yield", expanded=True):
    ui_div = st.number_input("Rendimento Dividendi (%)", min_value=0.0, max_value=10.0, value=1.5, step=0.1) / 100

st.title("🏦 Dashboard Copertura Istituzionale (v5.0)")

st.markdown('<div class="risk-toggle">', unsafe_allow_html=True)
is_real_ratio = st.toggle("🛡️ **Modalità Risk Manager (Hedge Ratio Netto dei Costi)**", value=True)
st.markdown('</div>', unsafe_allow_html=True)

tab1, tab2, tab3, tab4 = st.tabs(["🎯 Setup & Matrice", "📈 Backtest Storico", "🔍 Database Live", "🤖 Advisor Strategico"])

# ======================================================================
# TAB 1: CALCOLATORE E MATRICE
# ======================================================================
with tab1:
    with st.form("input_form"):
        col1, col2, col3 = st.columns(3)
        with col1:
            st.markdown("### ⚙️ Derivato (Turbo)")
            cert = st.session_state.get('selected_cert')
            if cert:
                st.markdown(f"<div style='background-color:#E8F5E9; color:#2E7D32; padding:5px 10px; border-radius:5px; font-weight:bold; margin-bottom:10px;'>📡 ISIN Caricato: {cert['isin']}</div>", unsafe_allow_html=True)
            p_iniziale = st.number_input("Prezzo Lettera (€)", value=cert['prezzo'] if cert else 7.64, step=0.01)
            strike = st.number_input("Strike", value=cert['strike'] if cert else 7505.97, step=0.01)
            cambio = st.number_input("Tasso di cambio EUR", value=1.15, step=0.01)
            multiplo = st.number_input("Multiplo", value=cert['multiplo'] if cert else 0.01, format="%.4f")
            euribor = st.number_input("Euribor 12M", value=0.02456, format="%.5f")
        with col2:
            st.markdown("### 📉 Mercato")
            v_iniziale = st.number_input("Indice Iniziale Spot", value=6670.75, step=0.01)
            v_ipotetico = st.number_input("Scenario Futuro Target", value=6000.0, step=0.01)
            giorni = st.number_input("Orizzonte Hedging (Giorni)", value=60, step=1)
        with col3:
            st.markdown("### 💼 Portafoglio")
            ptf = st.number_input("Capitale Ptf (€)", value=200000.0, step=1000.0)
            beta = st.number_input("Beta", value=1.00, step=0.05)
        st.divider()
        st.markdown("### 🎯 Ottimizzazione Copertura")
        tipo_copertura = st.radio("Strategia di Hedging", ["Auto-Ottimizza (Delta Neutral 100%)", "Manuale (Forza Quantità)"], horizontal=True)
        n_turbo_custom = st.number_input("Numero Certificati", value=1000, step=10) if tipo_copertura == "Manuale (Forza Quantità)" else None
        submitted = st.form_submit_button("🔥 Esegui Motore Quantitativo")

    if submitted:
        params = TurboParameters(prezzo_iniziale=p_iniziale, strike=strike, cambio=cambio, multiplo=multiplo, euribor=euribor, valore_iniziale=v_iniziale, valore_ipotetico=v_ipotetico, giorni=giorni, portafoglio=ptf, beta=beta, dividend_yield=ui_div, bid_ask_spread=ui_spread, commissioni_pct=ui_comm)
        calc = DeterministicTurboCalculator(params)
        res = calc.calculate_all()
        if n_turbo_custom:
            res['n_turbo'] = float(n_turbo_custom)
            res['capitale'] = params.portafoglio + (res['n_turbo'] * params.prezzo_iniziale * (1 + ui_spread + ui_comm))
            res['valore_copertura_simulata'] = res['n_turbo'] * res['prezzo_futuro'] * (1 - ui_spread - ui_comm)
            res['totale_simulato'] = res['valore_ptf_simulato'] + res['valore_copertura_simulata']
            res['percentuale'] = (res['totale_simulato'] - res['capitale']) / res['capitale']
            perdita_ptf = params.portafoglio - res['valore_ptf_simulato']
            res['hedge_ratio_reale'] = (res['valore_copertura_simulata'] - (res['n_turbo'] * params.prezzo_iniziale * (1 + ui_spread + ui_comm))) / perdita_ptf if perdita_ptf > 0 else 0
            res['totale_copertura'] = res['capitale']
        st.session_state['barriera_calcolata'], st.session_state['params'], st.session_state['res'] = res['barriera'], params, res

    if 'res' in st.session_state:
        res, params = st.session_state['res'], st.session_state['params']
        st.divider()
        st.markdown("<h2>📊 Risultati</h2>", unsafe_allow_html=True)
        excel_col1, excel_col2, excel_col3 = st.columns([1, 1, 1.3])
        with excel_col1:
            st.markdown("<div style='background-color: #2c5282; padding: 10px; color: white; border-radius: 5px;'>CARATTERISTICHE TURBO</div>", unsafe_allow_html=True)
            st.markdown(f"<table style='width: 100%; font-size: 14px;'><tr><td>Strike</td><td align='right'>{params.strike:.2f}</td></tr><tr><td>Fair Value</td><td align='right'>{res['fair_value']:.4f} €</td></tr></table>", unsafe_allow_html=True)
        with excel_col2:
            st.markdown("<div style='background-color: #2c5282; padding: 10px; color: white; border-radius: 5px;'>INDICE</div>", unsafe_allow_html=True)
            st.markdown(f"<table style='width: 100%; font-size: 14px;'><tr><td>Spot</td><td align='right'>{params.valore_iniziale:.2f}</td></tr><tr><td>Barriera</td><td align='right'>{res['barriera']:.2f}</td></tr></table>", unsafe_allow_html=True)
        with excel_col3:
            st.markdown(f"<div style='text-align: right; font-size: 24px; font-weight: bold; color: #2c5282;'>{params.portafoglio:,.2f} €</div>", unsafe_allow_html=True)
            st.markdown(f"<table style='width: 100%; font-size: 14px;'><tr><td>N. Turbo</td><td align='right'>{res['n_turbo']:,.0f}</td></tr><tr style='background-color: #FFF3E0;'><td>TOTALE COPERTO</td><td align='right'><b>{res['totale_simulato']:,.2f} €</b></td></tr></table>", unsafe_allow_html=True)
            perf = res['percentuale'] * 100
            st.markdown(f"<div style='background-color: {'#E8F5E9' if perf >= 0 else '#FFEBEE'}; padding: 10px; text-align: center; border: 2px solid {'#2E7D32' if perf >= 0 else '#C62828'}; margin-top: 5px;'><b>{perf:+.2f}% Perf. Netta</b></div>", unsafe_allow_html=True)
        
        st.divider()
        st.markdown("### 🌡️ Matrice di Sensitività")
        var_list = [-0.20, -0.10, -0.05, 0.0, 0.05, 0.10, 0.20]
        col_names = [f"{v*100:+.0f}%" for v in var_list]
        spot_levels = [params.valore_iniziale * (1 + v) for v in var_list]
        t_steps = [0, int(params.giorni/2), params.giorni] if params.giorni > 0 else [0]
        matrix_data = []
        for t in sorted(list(set(t_steps))):
            row = []
            for s in spot_levels:
                if s >= res['barriera']: row.append(0.0)
                else: row.append(max(0, (params.strike - s) / params.cambio * params.multiplo) + max(0, res['premio'] - (res['premio']/params.giorni*t if params.giorni>0 else 0)))
            matrix_data.append(row)
        df_sens = pd.DataFrame(matrix_data, columns=col_names, index=[f"Oggi" if t==0 else f"T+{t} gg" for t in t_steps])
        st.dataframe(df_sens.style.format("{:.3f} €").background_gradient(cmap='RdYlGn', axis=None, vmin=0.0), use_container_width=True)

# ======================================================================
# TAB 2: BACKTEST
# ======================================================================
with tab2:
    st.markdown("### 🕰️ Backtest Storico")
    if 'barriera_calcolata' not in st.session_state: st.warning("Esegui prima il Setup nel Tab 1.")
    else:
        with st.expander("Parametri Backtest", expanded=True):
            b1, b2, b3, b4, b5 = st.columns(5)
            ticker_ptf = b1.text_input("Ticker Ptf", value="SPY")
            ticker_idx = b2.text_input("Ticker Indice", value="^GSPC")
            ticker_fx = b3.text_input("FX (es. EURUSD=X)", value="")
            start_date = b4.date_input("Inizio", value=datetime.date(2023, 1, 1))
            end_date = b5.date_input("Fine", value=datetime.date.today())
        if st.button("🚀 Avvia Backtest"):
            df_bt, msg, diag = run_historical_backtest(ticker_ptf, ticker_idx, ticker_fx, start_date, end_date, st.session_state['barriera_calcolata'])
            if df_bt is not None:
                st.markdown(f"### Verdetto: {diag['title']}")
                c1, c2 = st.columns(2)
                c1.line_chart(df_bt.set_index('Date')['Ptf_Close'])
                c2.area_chart(df_bt.set_index('Date')['Drawdown'])
            else: st.error(msg)

# ======================================================================
# TAB 3: DATABASE LIVE
# ======================================================================
with tab3:
    st.markdown("### 🔍 Database Live BNP Paribas")
    df_raw = fetch_live_certificates()
    if "Errore" in df_raw.columns: st.error(df_raw["Errore"].iloc[0])
    else:
        col1, col2, col3 = st.columns(3)
        with col1: scelta_sott = st.selectbox("Sottostante BNP", ["Tutti"] + sorted([str(x) for x in df_raw['Sottostante'].dropna().unique()]))
        with col2: scelta_cat = st.selectbox("Classe", ["Tutte le categorie", "Azioni", "ETF", "Indici", "Materie prime", "Tassi di interesse", "Valute", "Volatility"])
        with col3: ricerca_libera = st.text_input("Ricerca ISIN:")
        df_filtered = df_raw.copy()
        if scelta_sott != "Tutti": df_filtered = df_filtered[df_filtered['Sottostante'] == scelta_sott]
        if scelta_cat != "Tutte le categorie": df_filtered = df_filtered[df_filtered['Classe'] == scelta_cat]
        if ricerca_libera: df_filtered = df_filtered[df_filtered.astype(str).apply(lambda x: x.str.contains(ricerca_libera, case=False)).any(axis=1)]
        selection = st.dataframe(df_filtered, use_container_width=True, hide_index=True, on_select="rerun", selection_mode="single-row")
        if len(selection.selection.rows) > 0:
            cert = df_filtered.iloc[selection.selection.rows[0]]
            st.session_state['selected_cert'] = {"isin": cert['ISIN'], "strike": float(cert['Strike']), "multiplo": float(cert['Multiplo']), "prezzo": float(cert.get('Lettera', cert.get('Denaro', 0.0)))}
            st.success(f"✅ ISIN {cert['ISIN']} agganciato. Torna al Tab 1.")

# ======================================================================
# TAB 4: ADVISOR STRATEGICO (REVERSE ENGINEERING)
# ======================================================================
with tab4:
    st.markdown("### 🤖 Advisor: Reverse Engineering della Copertura")
    st.markdown("Parti dal tuo portafoglio per trovare il certificato ideale nel database BNP.")
    
    with st.form("advisor_form"):
        adv_col1, adv_col2 = st.columns(2)
        with adv_col1:
            target_ptf = st.number_input("Capitale da proteggere (€)", value=200000, step=1000)
            target_beta = st.number_input("Beta stimato del portafoglio", value=1.0, step=0.1)
        with adv_col2:
            budget_max = st.number_input("Budget massimo per l'acquisto (€)", value=5000, step=500)
            distanza_min = st.slider("Distanza minima dalla barriera (%)", 2, 30, 10)
        
        search_submitted = st.form_submit_button("🔍 Trova Certificati Compatibili")

    if search_submitted:
        # LOGICA QUANT: Calcolo Leva Target
        # Formula: Budget = (Valore * Beta) / Leva  => Leva = (Valore * Beta) / Budget
        leva_ideale = (target_ptf * target_beta) / budget_max
        st.write(f"💡 **Parametri Ideali:** Per coprirti con {budget_max} € ti serve un certificato con **Leva {leva_ideale:.1f}**.")
        
        df_live = fetch_live_certificates()
        if "Errore" not in df_live.columns:
            # Filtro 1: Direzione Short (già filtrato dal motore)
            # Filtro 2: Distanza Barriera
            df_adv = df_live[df_live['Distanza Barriera %'] >= distanza_min].copy()
            
            # Filtro 3: Pertinenza Leva (cerchiamo i più vicini)
            df_adv['Differenza_Leva'] = (df_adv['Leva'] - leva_ideale).abs()
            top_matches = df_adv.sort_values('Differenza_Leva').head(10)
            
            if top_matches.empty:
                st.warning("Nessun certificato trovato con questi parametri. Prova ad alzare il budget o abbassare la distanza minima.")
            else:
                st.markdown("### 🏆 Top 10 Certificati Suggeriti")
                st.markdown("*Ordinati per vicinanza alla leva ideale calcolata.*")
                
                # Visualizzazione risultati
                match_selection = st.dataframe(
                    top_matches[['Sottostante', 'ISIN', 'Leva', 'Distanza Barriera %', 'Strike', 'Lettera']], 
                    use_container_width=True, hide_index=True, on_select="rerun", selection_mode="single-row", key="adv_table"
                )
                
                if len(match_selection.selection.rows) > 0:
                    best_cert = top_matches.iloc[match_selection.selection.rows[0]]
                    st.session_state['selected_cert'] = {
                        "isin": best_cert['ISIN'],
                        "strike": float(best_cert['Strike']),
                        "multiplo": float(best_cert['Multiplo']),
                        "prezzo": float(best_cert['Lettera'])
                    }
                    st.success(f"🎯 **{best_cert['ISIN']}** selezionato! Vai al Tab 1 per il calcolo finale.")
