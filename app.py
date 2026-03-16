import streamlit as st
import pandas as pd
import numpy as np
import requests
import datetime
from calculator import TurboParameters, DeterministicTurboCalculator
from charts import generate_scenario_data, plot_payoff_profile, plot_pl_waterfall
from stress_test import run_stress_test
from backtest import run_historical_backtest, generate_pdf_report

# --- CONFIGURAZIONE PAGINA ---
st.set_page_config(page_title="Turbo Hedge Quant", layout="wide", page_icon="🏦")

# --- INIEZIONE CSS PER LAYOUT "ISTITUZIONALE/EXCEL MODERNIZZATO" ---
st.markdown("""
<style>
    /* Sfondo generale grigio chiarissimo professionale */
    .stApp {
        background-color: #F4F7F6;
    }

    /* Stile per i titoli delle sezioni (come i banner blu nell'Excel) */
    .section-header {
        background-color: #d9e1f2; /* Blu molto chiaro istituzionale */
        color: #1A365D; /* Blu scuro professionale */
        padding: 10px 15px;
        border-radius: 5px;
        font-weight: bold;
        text-transform: uppercase;
        font-size: 14px;
        margin-bottom: 15px;
        border-bottom: 2px solid #b4c6e7;
    }

    /* Container bianco per le sezioni input/output */
    .block-container-styled {
        background-color: #FFFFFF;
        padding: 25px;
        border-radius: 10px;
        box-shadow: 0 4px 6px rgba(0,0,0,0.05);
        margin-bottom: 20px;
    }

    /* Stile per i metrics e i valori chiave */
    .stMetric {
        background-color: #f8f9fa;
        padding: 10px;
        border-radius: 5px;
        border: 1px solid #e9ecef;
    }
    
    /* Riduzione padding default di streamlit per un look più compatto stile griglia */
    .block-container {
        padding-top: 2rem;
        padding-bottom: 2rem;
    }
    
    /* Stile specifico per replicare le tabelle Excel */
    .excel-table {
        width: 100%;
        border-collapse: collapse;
        font-size: 14px;
    }
    .excel-table td {
        padding: 8px 12px;
        border: 1px solid #dee2e6;
    }
    .excel-table-label {
        background-color: #f8f9fa;
        font-weight: 500;
        color: #6c757d;
        width: 60%;
    }
    .excel-table-value {
        text-align: right;
        font-weight: bold;
        color: #1A365D;
    }
    .excel-table-header {
        background-color: #2c5282;
        color: white;
        font-weight: bold;
        text-align: center;
        padding: 10px !important;
    }
</style>
""", unsafe_allow_html=True)

# --- MOTORE ESTRAZIONE DATI BNP PARIBAS (Invariato) ---
@st.cache_data(ttl=900) # Cache 15 minuti
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
        "clientId": 1,
        "languageId": "it",
        "countryId": "",
        "sortPreference": [],
        "filterSelections": [],
        "derivativeTypeIds": [7, 9, 23, 24, 580, 581],
        "productGroupIds": [7],
        "offset": 0,
        "limit": 5000,
        "resolveSubPreset": True,
        "resolveOnlySelectedPresets": False,
        "allowLeverageGrouping": False
    }
    try:
        response = requests.post(url, headers=headers, json=payload, timeout=15)
        response.raise_for_status()
        data = response.json()
        
        items = []
        if 'products' in data:
            items = data['products']
        elif 'data' in data and isinstance(data['data'], list):
            items = data['data']
        else:
            list_keys = [k for k in data.keys() if isinstance(data[k], list)]
            if list_keys:
                items = data[max(list_keys, key=lambda k: len(data[k]))]
                    
        if not items:
            return pd.DataFrame({"Errore": ["Nessun dato restituito dall'API."]})
            
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
        if tipo_cols:
            df['Tipo'] = df[tipo_cols[0]]
        else:
            df['Tipo'] = 'Turbo Short' 

        df = df[df['Tipo'].astype(str).str.contains('Short', case=False, na=False)]

        if 'Categoria_ID' in df.columns:
            asset_map = {
                1: 'Azioni',
                2: 'Indici',
                3: 'Valute',
                4: 'Materie prime',
                5: 'Tassi di interesse',
                11: 'ETF',
                14: 'Volatility'
            }
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
                if col in df.columns:
                    df[col] = pd.to_numeric(df[col], errors='coerce')

        return df.dropna(subset=['Strike', 'Lettera'])
    except requests.exceptions.RequestException as e:
        return pd.DataFrame({"Errore Request": [str(e)]})
    except Exception as e:
        return pd.DataFrame({"Errore Generic": [str(e)]})

# --- INIZIALIZZAZIONE SESSION STATE ---
if 'selected_cert' not in st.session_state:
    st.session_state['selected_cert'] = None

# --- HEADER PRINCIPALE ---
st.markdown("<h1>🏦 Dashboard Copertura Istituzionale (v3.0)</h1>", unsafe_allow_html=True)
st.markdown("<p style='color: #6c757d; font-size: 16px; margin-top:-10px; margin-bottom: 25px;'>Ottimizzazione Quantitativa di Coperture con Certificati Turbo Short</p>", unsafe_allow_html=True)

# --- SIDEBAR (PARAMETRI DEGLI ATTRITI) ---
with st.sidebar:
    st.markdown("<div class='section-header'>📉 Attriti di Mercato</div>", unsafe_allow_html=True)
    st.markdown("<p style='font-size: 13px; color: #6c757d; font-style: italic; margin-top:-10px; margin-bottom: 15px;'>Imposta i costi reali per non invalidare il modello.</p>", unsafe_allow_html=True)
    
    with st.expander("💰 Costi di Transazione", expanded=True):
        # I valori di default corrispondono a quelli del file Excel fornito
        ui_spread = st.number_input("Bid-Ask Spread (%)", min_value=0.0, max_value=5.0, value=0.5, step=0.1, help="Spread percentuale tra prezzo Denaro e Lettera") / 100
        ui_comm = st.number_input("Commissioni Broker (%)", min_value=0.0, max_value=2.0, value=0.1, step=0.05, help="Commissioni di trading percentuali") / 100
        
    with st.expander("📊 Dividend Yield", expanded=True):
        ui_div = st.number_input("Rendimento Dividendi (%)", min_value=0.0, max_value=10.0, value=1.5, step=0.1, help="Rendimento da dividendi stimato del sottostante") / 100

    st.markdown("<br><hr>", unsafe_allow_html=True)
    st.markdown("<p style='font-size: 12px; color: #adb5bd; text-align: center;'>Hedge Quant Model v3.0 | © 2024</p>", unsafe_allow_html=True)

# --- LAYOUT PRINCIPALE A TABS ---
tab1, tab2, tab3 = st.tabs(["🎯 Setup Copertura & Scenari", "📈 Backtest Storico", "🔍 Database Live BNP Paribas"])

# ======================================================================
# TAB 1: SETUP COPERTURA (Nuovo Layout Excel-Style)
# ======================================================================
with tab1:
    with st.form("input_form"):
        st.markdown("<div class='section-header'>🛠️ Setup Parametri di Input</div>", unsafe_allow_html=True)
        
        # Replica la struttura a 3 blocchi del file Excel
        col_inp1, col_inp2, col_inp3 = st.columns(3)
        
        # Recupera certificato selezionato dal DB Live (Tab 3)
        cert_data = st.session_state.get('selected_cert')
        isin_placeholder = cert_data['isin'] if cert_data else "Nessuno (Input Manuale)"
        
        with col_inp1:
            st.markdown("<p style='font-weight: bold; color: #1A365D; margin-bottom: 5px;'>Caratteristiche Turbo SHORT</p>", unsafe_allow_html=True)
            st.caption(f"ISIN Selezionato: {isin_placeholder}")
            
            # Valori di default mappati sul file Excel fornito
            p_iniziale = st.number_input("Prezzo Lettera Turbo (€) (C)", value=cert_data['prezzo'] if cert_data else 7.64, step=0.01, format="%.2f", help="Prezzo di acquisto (Lettera)")
            strike = st.number_input("Strike", value=cert_data['strike'] if cert_data else 7505.97, step=0.01, format="%.2f")
            cambio = st.number_input("Tasso di cambio EUR", value=1.15, step=0.01, format="%.2f", help="Tasso EUR/Valuta Sottostante (es. 1.15 per USD)")
            multiplo = st.number_input("Multiplo", value=cert_data['multiplo'] if cert_data else 0.01, step=0.0001, format="%.4f")
            euribor = st.number_input("Euribor 12M", value=0.02456, step=0.00001, format="%.5f", help="Tasso privo di rischio")
            
        with col_inp2:
            st.markdown("<p style='font-weight: bold; color: #1A365D; margin-bottom: 25px;'>INDICE DA COPRIRE</p>", unsafe_allow_html=True)
            v_iniziale = st.number_input("Valore Iniziale Spot", value=6670.75, step=1.0, format="%.2f")
            v_ipotetico = st.number_input("Valore Ipotetico Scadenza", value=6000.0, step=1.0, format="%.2f")
            giorni = st.number_input("Orizzonte Temporale (Giorni)", value=60, step=1)
            
        with col_inp3:
            st.markdown("<p style='font-weight: bold; color: #1A365D; margin-bottom: 25px;'>PORTAFOGLIO DA COPRIRE</p>", unsafe_allow_html=True)
            ptf = st.number_input("Capitale Portafoglio (€)", value=200000.0, step=1000.0, format="%.2f")
            beta = st.number_input("Beta di Portafoglio", value=1.00, step=0.01, format="%.2f")

        st.markdown("<br>", unsafe_allow_html=True)
        submit_btn = st.form_submit_button("🔥 Esegui Motore Quantitativo")

    # --- LOGICA DI CALCOLO E OUTPUT ---
    if submit_btn:
        # 1. Creazione Oggetto Parametri
        params = TurboParameters(
            prezzo_iniziale=p_iniziale,
            strike=strike,
            cambio=cambio,
            multiplo=multiplo,
            euribor=euribor,
            valore_iniziale=v_iniziale,
            valore_ipotetico=v_ipotetico,
            giorni=giorni,
            portafoglio=ptf,
            beta=beta,
            dividend_yield=ui_div,
            bid_ask_spread=ui_spread,
            commissioni_pct=ui_comm
        )

        # 2. Esecuzione Calcolatore Quantitativo
        calc = DeterministicTurboCalculator(params)
        res = calc.calculate_all()
        
        # Salva in session state per le altre tab
        st.session_state['barriera_calcolata'] = res['barriera']
        st.session_state['current_results'] = res
        st.session_state['current_params'] = params

    # Visualizzazione risultati se disponibili
    if 'current_results' in st.session_state:
        res = st.session_state['current_results']
        params = st.session_state['current_params']
        
        st.markdown("<br><hr><br>", unsafe_allow_html=True)
        st.markdown("<div class='section-header'>📊 Risultati Copertura (Layout Excel Modernizzato)</div>", unsafe_allow_html=True)
        
        # Replica il layout a 3 tabelle dell'Excel
        col_out1, col_out2, col_out3 = st.columns([1, 1, 1.3])
        
        with col_out1:
            st.markdown("""
            <table class="excel-table">
                <tr><td colspan="2" class="excel-table-header">Caratteristiche Turbo SHORT</td></tr>
                <tr><td class="excel-table-label">Prezzo iniziale (Lettera)</td><td class="excel-table-value">{:.2f} €</td></tr>
                <tr><td class="excel-table-label">Fair Value (Medio)</td><td class="excel-table-value">{:.4f} €</td></tr>
                <tr><td class="excel-table-label">Premio (Costo Spread)</td><td class="excel-table-value">{:.4f} €</td></tr>
                <tr><td class="excel-table-label">Strike</td><td class="excel-table-value">{:.2f}</td></tr>
                <tr><td class="excel-table-label">Tasso di cambio</td><td class="excel-table-value">{:.2f}</td></tr>
                <tr><td class="excel-table-label">Multiplo</td><td class="excel-table-value">{:.4f}</td></tr>
                <tr><td class="excel-table-label">Euribor 12M</td><td class="excel-table-value">{:.5f}</td></tr>
            </table>
            """.format(params.prezzo_iniziale, res['fair_value'], res['premio'], params.strike, params.cambio, params.multiplo, params.euribor), unsafe_allow_html=True)

        with col_out2:
            st.markdown("""
            <table class="excel-table">
                <tr><td colspan="2" class="excel-table-header">INDICE DA COPRIRE</td></tr>
                <tr><td class="excel-table-label">Valore Iniziale</td><td class="excel-table-value">{:.2f}</td></tr>
                <tr><td class="excel-table-label">Valore Ipotetico</td><td class="excel-table-value">{:.2f}</td></tr>
                <tr><td class="excel-table-label">Giorni</td><td class="excel-table-value">{}</td></tr>
                <tr><td colspan="2" style="border:none; height:15px;"></td></tr>
                <tr><td class="excel-table-label">Prezzo Turbo Short Futuro</td><td class="excel-table-value">{:.4f} €</td></tr>
                <tr><td class="excel-table-label">Barriera Turbo Short</td><td class="excel-table-value">{:.2f}</td></tr>
                <tr><td class="excel-table-label">Leva Turbo Short</td><td class="excel-table-value">{:.2f}</td></tr>
            </table>
            """.format(params.valore_iniziale, params.valore_ipotetico, params.giorni, res['prezzo_futuro'], res['barriera'], res['leva']), unsafe_allow_html=True)

        with col_out3:
            # Replica l'header del portafoglio con valore grande
            st.markdown(f"""
            <div style="background-color: #f8f9fa; border: 1px solid #dee2e6; border-radius: 5px; padding: 10px; margin-bottom: 10px;">
                <div style="color: #6c757d; font-size: 12px; font-weight: bold; text-transform: uppercase;">PORTAFOGLIO DA COPRIRE</div>
                <div style="color: #1A365D; font-size: 28px; font-weight: bold; text-align: right;">{params.portafoglio:,.2f} €</div>
            </div>
            """, unsafe_allow_html=True)
            
            # Tabella Quantità e Capitale
            st.markdown("""
            <table class="excel-table">
                <tr>
                    <td class="excel-table-label" style="width:50%">N. Turbo Short (Qtà Reale Ask)</td>
                    <td class="excel-table-value" style="width:25%">{:,.2f}</td>
                    <td rowspan="2" style="background-color: #e2f0d9; text-align:center; vertical-align:middle; font-weight:bold; color: #1f4e3d; width:25%;">TOTALE CON<br>COPERTURA</td>
                </tr>
                <tr>
                    <td class="excel-table-label">Capitale Investito (Ask + Comm)</td>
                    <td class="excel-table-value">{:,.2f} €</td>
                </tr>
                <tr>
                    <td colspan="2" style="border:none; text-align:right; font-weight:bold; padding-right:20px; color:#1A365D;">Hedge Ratio Reale (Ask):</td>
                    <td style="background-color: #e2f0d9; text-align:center; font-weight:bold; color: #1f4e3d; font-size:16px;">{:.1f}%</td>
                </tr>
            </table>
            """.format(res['n_turbo'], (res['capitale'] - params.portafoglio), (res['hedge_ratio_reale'] * 100)), unsafe_allow_html=True)
            
            st.markdown("<br>", unsafe_allow_html=True)
            
            # Tabella Valore Simulato
            st.markdown("""
            <table class="excel-table">
                <tr><td colspan="2" class="excel-table-header" style="background-color: #5b9bd5;">VALORE PORTAFOGLIO SIMULATO</td></tr>
                <tr><td class="excel-table-label">Sottostante (Drawdown)</td><td class="excel-table-value">{:,.2f} €</td></tr>
                <tr><td class="excel-table-label">Turbo (Performance Netta Bid)</td><td class="excel-table-value">{:,.2f} €</td></tr>
                <tr style="height: 5px;"><td colspan="2" style="border:none;"></td></tr>
                <tr style="background-color: #d9e1f2;"><td class="excel-table-label" style="background-color: transparent; font-weight:bold; color:#1A365D;">TOTALE PORTAFOGLIO COPERTO</td><td class="excel-table-value" style="font-size:16px;">{:,.2f} €</td></tr>
            </table>
            """.format(res['valore_ptf_simulato'], res['valore_copertura_simulata'], res['totale_simulato']), unsafe_allow_html=True)
            
            # Box Performance Netta Grande
            color = "#2E7D32" if res['percentuale'] >= 0 else "#C62828"
            bg_color = "#E8F5E9" if res['percentuale'] >= 0 else "#FFEBEE"
            st.markdown(f"""
            <div style="background-color: {bg_color}; border: 2px solid {color}; border-radius: 5px; padding: 15px; margin-top: 15px; text-align: center;">
                <div style="color: {color}; font-size: 36px; font-weight: bold;">{res['percentuale']*100:+.2f}%</div>
                <div style="color: #6c757d; font-size: 12px; font-weight: bold; text-transform: uppercase;">PERFORMANCE NETTA COPERTURA (Netta Costi)</div>
            </div>
            """, unsafe_allow_html=True)

        # Sezione Analisi Scenari (Grafici) Invariata
        st.markdown("<br><br>", unsafe_allow_html=True)
        st.markdown("<div class='section-header'>🔮 Analisi di Scenario e Payoff</div>", unsafe_allow_html=True)
        df_scenari, livello_barriera = generate_scenario_data(params)
        
        col_graph1, col_graph2 = st.columns(2)
        with col_graph1:
            st.plotly_chart(plot_payoff_profile(df_scenari, params.valore_iniziale, livello_barriera), use_container_width=True)
        with col_graph2:
            st.plotly_chart(plot_pl_waterfall(res), use_container_width=True)

        st.markdown("<br><br>", unsafe_allow_html=True)
        st.markdown("<div class='section-header'>⚠️ Stress Test Matrice (Spread Bid-Ask Dinamico)</div>", unsafe_allow_html=True)
        st.caption("Analisi della sensitività dell'Hedge Ratio Reale al variare dello spread e della volatilità implicita (approssimata).")
        df_stress = run_stress_test(params)
        st.dataframe(df_stress, use_container_width=True, hide_index=True)

# ======================================================================
# TAB 2: BACKTEST STORICO (Invariata)
# ======================================================================
with tab2:
    st.markdown("<div class='section-header'>📈 Backtest Storico e Analisi Drawdown</div>", unsafe_allow_html=True)
    
    # Controllo se è stata calcolata una barriera
    if 'barriera_calcolata' not in st.session_state:
        st.warning("⚠️ Per eseguire il backtest, calcola prima una strategia nel Tab 'Setup Copertura'.")
    else:
        barriera_da_testare = st.session_state['barriera_calcolata']
        st.info(f"Livello Knock-Out da testare (calcolato nel Setup): **{barriera_da_testare:.2f}**")
        
        with st.form("backtest_form"):
            col_bt1, col_bt2, col_bt3 = st.columns(3)
            with col_bt1:
                ticker_ptf = st.text_input("Ticker Portafoglio (Yahoo Finance)", value="SPY", help="Es: SPY per S&P500 ETF, EXSA.DE per EuroStoxx50")
            with col_bt2:
                ticker_idx = st.text_input("Ticker Indice Sottostante", value="^GSPC", help="Es: ^GSPC per S&P500, ^STOXX50E per EuroStoxx50")
            with col_bt3:
                ticker_fx = st.text_input("Ticker Tasso di Cambio (Opzionale)", value="", help="Es: EURUSD=X. Lasciare vuoto se non c'è rischio cambio.")
            
            col_bt4, col_bt5, col_bt6 = st.columns(3)
            with col_bt4:
                start_date = st.date_input("Data Inizio", value=datetime.date(2023, 1, 1))
            with col_bt5:
                end_date = st.date_input("Data Fine", value=datetime.date.today())
            
            st.markdown("<br>", unsafe_allow_html=True)
            run_bt = st.form_submit_button("🚀 Avvia Backtest Storico")

        if run_bt:
            with st.spinner("⏳ Download dati storici e calcolo simulazione..."):
                df_backtest, messaggio, diagnosi = run_historical_backtest(
                    ticker_ptf, ticker_idx, ticker_fx, 
                    start_date, end_date, barriera_da_testare
                )
                
                if df_backtest is not None:
                    st.markdown("<br><hr><br>", unsafe_allow_html=True)
                    st.markdown("<div class='section-header'>📊 Risultati Backtest Storico</div>", unsafe_allow_html=True)
                    
                    # Verdetto del Risk Manager (Istituzionale)
                    with st.expander("⚖️ VERDETTO DEL RISK MANAGER", expanded=True):
                        st.markdown(f"""
                        <div style="background-color: {diagnosi['bg_color']}; border-left: 5px solid {diagnosi['color']}; padding: 15px; border-radius: 5px;">
                            <h3 style="color: {diagnosi['color']}; margin-top:0;">{diagnosi['title']}</h3>
                            <p style="color: #1A365D; font-size: 15px; margin-bottom: 5px;">{diagnosi['body']}</p>
                            <p style="color: #6c757d; font-size: 13px; font-style: italic;">Azione suggerita: {diagnosi['action']}</p>
                        </div>
                        """, unsafe_allow_html=True)
                    
                    st.markdown("<br>", unsafe_allow_html=True)
                    
                    # Metriche Chiave
                    m_col1, m_col2, m_col3, m_col4 = st.columns(4)
                    perf_coperta = df_backtest['Ptf_Coperto'].iloc[-1] / df_backtest['Ptf_Coperto'].iloc[0] - 1
                    perf_nuda = df_backtest['Ptf_Nudo'].iloc[-1] / df_backtest['Ptf_Nudo'].iloc[0] - 1
                    
                    with m_col1: st.metric("Performance Coperta", f"{perf_coperta:.2%}")
                    with m_col2: st.metric("Performance Nuda", f"{perf_nuda:.2%}")
                    with m_col3: st.metric("Max Drawdown Coperto", f"{df_backtest['Drawdown_Coperto'].min():.2%}")
                    with m_col4: st.metric("Eventi KO rilevati", diagnosi['ko_events'])
                    
                    # Grafici
                    st.markdown("<br>", unsafe_allow_html=True)
                    col_chart1, col_chart2 = st.columns(2)
                    with col_chart1:
                        st.line_chart(df_backtest.set_index('Date')[['Ptf_Coperto', 'Ptf_Nudo']])
                    with col_chart2:
                        st.area_chart(df_backtest.set_index('Date')[['Drawdown_Coperto', 'Drawdown_Nudo']])
                        
                    # Esportazione PDF
                    st.markdown("<br>", unsafe_allow_html=True)
                    pdf_data = generate_pdf_report(df_backtest, ticker_ptf, ticker_idx, ticker_fx, barriera_da_testare, diagnosi)
                    st.download_button(
                        label="📄 Scarica Report PDF Istituzionale",
                        data=pdf_data,
                        file_name=f"QuantHedge_Report_{ticker_ptf}_{datetime.date.today()}.pdf",
                        mime="application/pdf",
                    )

                else:
                    st.error(f"❌ Errore durante il backtest: {messaggio}")

# ======================================================================
# TAB 3: DATABASE LIVE (Parser Robusto)
# ======================================================================
with tab3:
    st.markdown("<div class='section-header'>🔍 Terminale Dati Live BNP Paribas</div>", unsafe_allow_html=True)
    st.markdown("<p style='font-size: 13px; color: #6c757d; font-style: italic; margin-top:-10px; margin-bottom: 15px;'>Seleziona un certificato dalla tabella per caricarlo automaticamente nel motore di calcolo (Tab 1).</p>", unsafe_allow_html=True)
    
    with st.spinner("📡 Interrogazione API BNP Paribas in corso..."):
        df_live = fetch_live_certificates()
        
    if "Errore" in df_live.columns:
        st.error(f"❌ Impossibile recuperare i dati live: {df_live['Errore'].iloc[0]}")
    elif df_live.empty:
        st.warning("⚠️ Nessun certificato Turbo Short trovato.")
    else:
        # Filtri Dinamici
        f_col1, f_col2, f_col3 = st.columns(3)
        with f_col1:
            lista_sottostanti = ["Tutti"] + sorted(df_live['Sottostante'].unique().tolist())
            scelta_sottostate = st.selectbox("Filtra per Sottostante", lista_sottostanti)
        with f_col2:
            categorie_disponibili = ["Tutte le categorie", "Azioni", "ETF", "Indici", "Materie prime", "Tassi di interesse", "Valute", "Volatility"]
            scelta_cat = st.selectbox("Filtra per Classe", categorie_disponibili)
        with f_col3:
            ricerca_isin = st.text_input("Ricerca ISIN veloce").upper()

        # Applicazione Filtri
        df_display = df_live.copy()
        if scelta_sottostate != "Tutti":
            df_display = df_display[df_display['Sottostante'] == scelta_sottostate]
        if scelta_cat != "Tutte le categorie":
            df_display = df_display[df_display['Classe'] == scelta_cat]
        if ricerca_isin:
            df_display = df_display[df_display['ISIN'].str.contains(ricerca_isin, na=False)]

        # Configurazione Tabella Interattiva
        st.markdown("<br>", unsafe_allow_html=True)
        st.caption(f"Visualizzati {len(df_display)} certificati Turbo Short")
        
        # Gestione selezione interattiva
        event = st.dataframe(
            df_display,
            use_container_width=True,
            hide_index=True,
            on_select="rerun",
            selection_mode="single-row"
        )
        
        # Logica di caricamento dati al click
        if event and event.selection and event.selection.rows:
            selected_index = event.selection.rows[0]
            # Recupera i dati reali dal DataFrame filtrato
            cert_selezionato = df_display.iloc[selected_index]
            
            # Gestione prezzo (Lettera se disponibile, altrimenti Denaro)
            prezzo_caricato = cert_selezionato.get('Lettera', cert_selezionato.get('Denaro', 0.0))
            if pd.isna(prezzo_caricato):
                prezzo_caricato = 0.0
            
            # Aggiorna Session State
            st.session_state['selected_cert'] = {
                "isin": cert_selezionato.get('ISIN', "N/D"),
                "strike": float(cert_selezionato.get('Strike', 0.0)),
                "multiplo": float(cert_selezionato.get('Multiplo', 0.0)),
                "prezzo": float(prezzo_caricato)
            }
            st.success(f"✅ Dati per ISIN **{cert_selezionato['ISIN']}** caricati con successo! Vai al Tab 'Setup Copertura' per calcolare.")
            
            # Pulsante per forzare il refresh e vedere i dati nel form input
            if st.button("🔄 Aggiorna Form Input Adesso"):
                st.rerun()

st.markdown("<br><hr>", unsafe_allow_html=True)
st.markdown("<p style='font-size: 12px; color: #adb5bd; text-align: center;'>QuantHedge Pro Dashboard | Uso Strettamente Professionale</p>", unsafe_allow_html=True)
