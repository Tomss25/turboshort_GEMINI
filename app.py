import streamlit as st
import pandas as pd
import numpy as np
import requests
import datetime
from calculator import TurboParameters, DeterministicTurboCalculator
from charts import generate_scenario_data, plot_payoff_profile, plot_pl_waterfall
from backtest import run_historical_backtest, generate_pdf_report

# --- STATO DELLA SESSIONE ---
if 'selected_cert' not in st.session_state:
    st.session_state['selected_cert'] = None

st.set_page_config(page_title="Turbo Hedge Quant", layout="wide", page_icon="🏦")

# --- INIEZIONE CSS CORPORATE AVANZATA ---
st.markdown("""
<style>
    .stApp { background-color: #F4F7F6; }
    h1, h2, h3 { color: #1A365D; font-family: 'Helvetica Neue', sans-serif; }
    div[data-testid="stForm"] { background-color: #FFFFFF; border-radius: 10px; padding: 20px; box-shadow: 0 4px 6px rgba(0,0,0,0.05); border: none; }
    .stTabs [data-baseweb="tab-list"] { background-color: transparent; }
    .stTabs [data-baseweb="tab"] { background-color: #E2E8F0; border-radius: 8px 8px 0 0; border: none; }
    .stTabs [aria-selected="true"] { background-color: #1A365D !important; color: white !important; }
    .excel-table { width: 100%; border-collapse: collapse; font-size: 14px; margin-bottom: 20px; }
    .excel-table td { padding: 8px 12px; border: 1px solid #dee2e6; }
    .excel-header { background-color: #2c5282; color: white; font-weight: bold; text-align: center; }
    .excel-label { background-color: #f8f9fa; color: #6c757d; font-weight: 500; width: 60%; }
    .excel-value { text-align: right; font-weight: bold; color: #1A365D; }
    [data-testid="stSidebar"] { background-color: #1A365D !important; }
    [data-testid="stSidebarNav"] span, [data-testid="stSidebarNav"] div { color: #FFFFFF !important; font-weight: 600; }
    
    /* Pulsante Bordeaux */
    div[data-testid="stFormSubmitButton"] button, .action-btn { background-color: #800020 !important; color: #FFFFFF !important; border: none !important; font-weight: bold !important; padding: 10px 24px !important; border-radius: 6px !important; }
    div[data-testid="stFormSubmitButton"] button:hover, .action-btn:hover { background-color: #5c0017 !important; color: #FFFFFF !important; }
</style>
""", unsafe_allow_html=True)

# --- MOTORE BNP ANTI-CRASH ---
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
        
        asset_map = {1: 'Azioni', 2: 'Indici', 3: 'Valute', 4: 'Materie prime', 5: 'Tassi di interesse', 11: 'ETF', 14: 'Volatility'}
        if 'Categoria_ID' in df.columns:
            df['Classe'] = pd.to_numeric(df['Categoria_ID'], errors='coerce').map(asset_map).fillna('Altro')
        
        for col in ['Strike', 'Multiplo', 'Lettera', 'Denaro', 'Leva', 'Distanza Barriera %']:
            if col in df.columns: df[col] = pd.to_numeric(df[col], errors='coerce')
        
        tipo_cols = [c for c in df.columns if df[c].astype(str).str.contains('Short', case=False, na=False).any()]
        if tipo_cols: df = df[df[tipo_cols[0]].astype(str).str.contains('Short', case=False, na=False)]
        
        return df.dropna(subset=['Strike', 'Lettera'])
    except Exception:
        return pd.DataFrame()

# --- SIDEBAR ---
st.sidebar.markdown("<h2 style='color: white;'>📉 Attriti di Mercato</h2>", unsafe_allow_html=True)
ui_spread = st.sidebar.number_input("Bid-Ask Spread (%)", value=0.5, step=0.1) / 100
ui_comm = st.sidebar.number_input("Commissioni (%)", value=0.1, step=0.05) / 100
ui_div = st.sidebar.number_input("Dividend Yield (%)", value=1.5, step=0.1) / 100

st.title("🏦 Dashboard Copertura Istituzionale (v6.4)")
is_real_ratio = st.toggle("🛡️ **Hedge Ratio Netto (Risk Manager)**", value=True)

tab1, tab2, tab3, tab4 = st.tabs(["🎯 Setup & Matrice", "📈 Backtest Storico", "🔍 Database Live", "🤖 Advisor Strategico"])

# ======================================================================
# TAB 1: SETUP & RISULTATI 
# ======================================================================
with tab1:
    with st.form("input_form"):
        col1, col2, col3 = st.columns(3)
        with col1:
            st.markdown("### ⚙️ Caratteristiche Turbo SHORT")
            cert = st.session_state.get('selected_cert')
            if cert: st.info(f"ISIN: {cert['isin']}")
            p_iniziale = st.number_input("Prezzo Lettera (€)", value=cert['prezzo'] if cert else 7.64, step=0.01)
            strike = st.number_input("Strike", value=cert['strike'] if cert else 7505.97, step=0.01)
            cambio = st.number_input("Cambio", value=1.15, step=0.01)
            multiplo = st.number_input("Multiplo", value=cert['multiplo'] if cert else 0.01, format="%.4f")
            euribor = st.number_input("Euribor 12M", value=0.02456, format="%.5f")
        with col2:
            st.markdown("### 📉 indice da coprire")
            v_iniziale = st.number_input("Spot", value=6670.75, step=0.01)
            v_ipotetico = st.number_input("Target", value=6000.0, step=0.01)
            giorni = st.number_input("Giorni Hedging", value=60, step=1)
        with col3:
            st.markdown("### 💼 Portafoglio")
            ptf = st.number_input("Capitale Ptf (€)", value=200000.0, step=1000.0)
            beta = st.number_input("Beta", value=1.00, step=0.05)
        st.divider()
        tipo_c = st.radio("Ottimizzazione", ["Auto", "Manuale"], horizontal=True)
        n_custom = st.number_input("Qtà", value=1000, step=10) if tipo_c == "Manuale" else None
        
        if st.form_submit_button("🔥 Calcola"):
            # Validazione input di base per prevenire crash (Es. divisione per zero)
            cambio = max(0.0001, cambio)
            giorni = max(0, giorni)
            
            params = TurboParameters(p_iniziale, strike, cambio, multiplo, euribor, v_iniziale, v_ipotetico, giorni, ptf, beta, ui_div, ui_spread, ui_comm)
            calc = DeterministicTurboCalculator(params)
            res = calc.calculate_all()
            
            # --- FIX MATEMATICO: Override logiche calcolatore base ---
            # 1. Calcolo Prezzo Futuro corretto (sullo Strike, non sulla Barriera)
            valore_intrinseco_futuro = max(0, (params.strike - params.valore_ipotetico) / params.cambio * params.multiplo)
            res['prezzo_futuro'] = valore_intrinseco_futuro + res['premio']
            
            # 2. Unificazione del calcolo Capitale ed Hedge Ratio (Auto vs Manuale)
            if n_custom:
                res['n_turbo'] = float(n_custom)
                
            costo_unitario_acquisto = params.prezzo_iniziale * (1 + ui_spread + ui_comm)
            valore_unitario_vendita = res['prezzo_futuro'] * (1 - ui_spread - ui_comm)
            
            res['capitale'] = params.portafoglio + (res['n_turbo'] * costo_unitario_acquisto)
            res['valore_copertura_simulata'] = res['n_turbo'] * valore_unitario_vendita
            res['totale_simulato'] = res['valore_ptf_simulato'] + res['valore_copertura_simulata']
            res['percentuale'] = (res['totale_simulato'] - res['capitale']) / res['capitale']
            
            perdita_ptf = params.portafoglio - res['valore_ptf_simulato']
            if perdita_ptf > 0:
                gain_lordo = res['n_turbo'] * (res['prezzo_futuro'] - params.prezzo_iniziale)
                gain_netto = res['valore_copertura_simulata'] - (res['n_turbo'] * costo_unitario_acquisto)
                res['hedge_ratio_commerciale'] = gain_lordo / perdita_ptf
                res['hedge_ratio_reale'] = gain_netto / perdita_ptf
            else:
                res['hedge_ratio_commerciale'] = 0.0
                res['hedge_ratio_reale'] = 0.0
                
            st.session_state['res'], st.session_state['params'], st.session_state['barriera_calcolata'] = res, params, res['barriera']

    if 'res' in st.session_state:
        res, params = st.session_state['res'], st.session_state['params']
        st.divider()
        st.markdown("<h2>📊 Risultati della Copertura</h2>", unsafe_allow_html=True)
        c1, c2, c3 = st.columns([1, 1, 1.3])
        
        with c1:
            st.markdown(f"""
            <table class="excel-table">
                <tr><td colspan="2" class="excel-header">CARATTERISTICHE TURBO</td></tr>
                <tr><td class="excel-label">Prezzo Lettera</td><td class="excel-value">{params.prezzo_iniziale:.2f} €</td></tr>
                <tr><td class="excel-label">Fair Value</td><td class="excel-value">{res['fair_value']:.4f} €</td></tr>
                <tr><td class="excel-label">Premio</td><td class="excel-value">{res['premio']:.4f} €</td></tr>
                <tr><td class="excel-label">Strike</td><td class="excel-value">{params.strike:.2f}</td></tr>
            </table>
            """, unsafe_allow_html=True)

        with c2:
            st.markdown(f"""
            <table class="excel-table">
                <tr><td colspan="2" class="excel-header">INDICE DA COPRIRE</td></tr>
                <tr><td class="excel-label">Spot</td><td class="excel-value">{params.valore_iniziale:.2f}</td></tr>
                <tr><td class="excel-label">Target</td><td class="excel-value">{params.valore_ipotetico:.2f}</td></tr>
                <tr><td class="excel-label">Prezzo Futuro</td><td class="excel-value">{res['prezzo_futuro']:.4f} €</td></tr>
                <tr><td class="excel-label">Barriera</td><td class="excel-value">{res['barriera']:.2f}</td></tr>
            </table>
            """, unsafe_allow_html=True)

        with c3:
            st.markdown(f"<div style='text-align:right; font-size:22px;'><b>{params.portafoglio:,.2f} €</b></div>", unsafe_allow_html=True)
            # FIX: L'interfaccia reagisce coerentemente al toggle
            display_hr = res['hedge_ratio_reale'] if is_real_ratio else res['hedge_ratio_commerciale']
            
            st.markdown(f"""
            <table class="excel-table">
                <tr><td class="excel-label">N. Turbo Short</td><td class="excel-value">{res['n_turbo']:,.2f}</td><td rowspan="2" style="background-color:#E3F2FD; font-weight:bold; text-align:center;">COPERTURA<br>REALE</td></tr>
                <tr><td class="excel-label">Capitale + Costi</td><td class="excel-value">{res['capitale']:,.2f} €</td></tr>
                <tr><td colspan="2" style="text-align:right; font-weight:bold;">Hedge Ratio:</td><td style="background-color:#E3F2FD; text-align:center; font-weight:bold;">{(display_hr*100):.1f}%</td></tr>
            </table>
            """, unsafe_allow_html=True)
            perf = res['percentuale']*100
            st.markdown(f"<div style='background-color:{'#E8F5E9' if perf>=0 else '#FFEBEE'}; text-align:center; padding:15px; border:2px solid {'#2E7D32' if perf>=0 else '#C62828'};'><h3>{perf:+.2f}% Perf. Netta</h3></div>", unsafe_allow_html=True)

        # --- SEZIONE COMMENTI ---
        st.markdown("### 📝 Analisi")
        h_ratio = display_hr * 100
        if h_ratio > 98:
            st.success(f"**Copertura Ottimale:** Il sistema ha neutralizzato il {h_ratio:.1f}% del rischio. La performance netta riflette l'efficacia della protezione al netto dei costi di transazione.")
        elif h_ratio > 80:
            st.warning(f"**Sotto-copertura Parziale:** Stai coprendo il {h_ratio:.1f}% del drawdown stimato. Il portafoglio rimane parzialmente esposto a movimenti direzionali.")
        else:
            st.error(f"**Copertura Insufficiente:** L'Hedge Ratio del {h_ratio:.1f}% è troppo basso per garantire protezione strutturale. Considera di aumentare il numero di certificati o cercare una leva maggiore.")

        if perf < -1:
             st.info(f"**Nota sui Costi:** Il trascinamento negativo del {perf:.2f}% è dovuto principalmente al Bid-Ask spread e alle commissioni. In scenari di bassa volatilità, questo rappresenta il 'premio assicurativo' pagato al mercato.")

        st.divider()
        st.markdown("### 🌡️ Matrice di Sensibilità")
        var_list = [-0.2, -0.1, -0.05, 0, 0.05, 0.1, 0.2]
        t_steps = sorted(list(set([0, int(params.giorni/2), params.giorni])))
        matrix = []
        for t in t_steps:
            row = []
            for v in var_list:
                s = params.valore_iniziale * (1 + v)
                if s >= res['barriera']: 
                    row.append(0.0)
                else: 
                    # FIX MATEMATICO: Matrice basata sullo strike e con decadimento appropriato
                    intrinsic = max(0, (params.strike - s) / params.cambio * params.multiplo)
                    decay = res['premio'] * (t / max(1, params.giorni))
                    row.append(intrinsic + max(0, res['premio'] - decay))
            matrix.append(row)
        df_sens = pd.DataFrame(matrix, columns=[f"{v*100:+.0f}%" for v in var_list], index=[f"T+{t}gg" for t in t_steps])
        st.dataframe(df_sens.style.format("{:.3f}€").background_gradient(cmap='RdYlGn', axis=None, vmin=0.0), use_container_width=True)
        
        st.divider()
        df_s, b_l = generate_scenario_data(params, res['n_turbo'])
        st.plotly_chart(plot_payoff_profile(df_s, params.valore_iniziale, b_l), use_container_width=True)
        st.plotly_chart(plot_pl_waterfall(res), use_container_width=True)

# ======================================================================
# TAB 2: BACKTEST STORICO 
# ======================================================================
with tab2:
    st.markdown("### 🕰️ Analisi Storica e Report")
    if 'barriera_calcolata' not in st.session_state: 
        st.warning("Esegui il Tab 1 per calcolare la barriera.")
    else:
        with st.expander("Parametri Backtest", expanded=True):
            b1, b2, b3, b4, b5 = st.columns(5)
            t_ptf_input = b1.text_input("Ticker Ptf (separati da virgola per multi-asset)", "SPY")
            t_idx = b2.text_input("Ticker Indice", "^GSPC")
            t_fx = b3.text_input("FX (es. EURUSD=X)", "")
            start_date = b4.date_input("Data Inizio", value=datetime.date(2023, 1, 1))
            end_date = b5.date_input("Data Fine", value=datetime.date.today())
            
        if st.button("🚀 Avvia Backtest"):
            tickers = [t.strip() for t in t_ptf_input.split(",") if t.strip()]
            for idx, current_ticker in enumerate(tickers):
                st.markdown(f"#### 🔍 Analisi per: **{current_ticker}**")
                df_bt, msg, diag = run_historical_backtest(current_ticker, t_idx, t_fx, start_date, end_date, st.session_state['barriera_calcolata'])
                
                if df_bt is not None:
                    # FIX: Traduzione codici colore semantici in esadecimali
                    color_status = diag.get('color', 'info')
                    if color_status == 'error': bg, tc = '#FFEBEE', '#C62828'
                    elif color_status == 'warning': bg, tc = '#FFF3E0', '#E65100'
                    else: bg, tc = '#E8F5E9', '#2E7D32'

                    st.markdown(f"""<div style="background-color: {bg}; border-left: 5px solid {tc}; padding: 15px; border-radius: 5px; margin-bottom: 15px;">
                        <h3 style="color: {tc}; margin-top:0;">{diag['title']}</h3><p style="color: #1A365D;">{diag['body']}</p><b style="color: #1A365D;">Azione: {diag['action']}</b></div>""", unsafe_allow_html=True)
                    
                    st.line_chart(df_bt.set_index('Date')[['Ptf_Close']])
                    
                    pdf = generate_pdf_report(df_bt, current_ticker, t_idx, t_fx, st.session_state['barriera_calcolata'], diag)
                    st.download_button(f"📄 Scarica Report PDF ({current_ticker})", data=pdf, file_name=f"Quant_Report_{current_ticker}.pdf", key=f"pdf_dl_{current_ticker}_{idx}")
                else: 
                    st.error(f"Errore su {current_ticker}: {msg}")
                st.divider()

# ======================================================================
# TAB 3: DATABASE LIVE 
# ======================================================================
with tab3:
    st.markdown("### 🔍 Live Terminal BNP Paribas")
    df_raw = fetch_live_certificates()
    if df_raw.empty: 
        st.error("Nessun dato.")
    else:
        c1, c2, c3, c4 = st.columns(4)
        scelta_s = c1.selectbox("Sottostante", ["Tutti"] + sorted([str(x) for x in df_raw['Sottostante'].unique()]))
        scelta_c = c2.selectbox("Classe", ["Tutte"] + sorted([str(x) for x in df_raw['Classe'].unique()]))
        min_leva = c3.number_input("Leva Minima", value=1.0, step=1.0)
        max_leva = c4.number_input("Leva Massima", value=100.0, step=1.0)
        
        df_f = df_raw.copy()
        if scelta_s != "Tutti": df_f = df_f[df_f['Sottostante'] == scelta_s]
        if scelta_c != "Tutte": df_f = df_f[df_f['Classe'] == scelta_c]
        
        df_f = df_f[(df_f['Leva'] >= min_leva) & (df_f['Leva'] <= max_leva)]
        
        sel = st.dataframe(df_f, use_container_width=True, hide_index=True, on_select="rerun", selection_mode="single-row")
        if len(sel.selection.rows) > 0:
            row = df_f.iloc[sel.selection.rows[0]]
            st.session_state['selected_cert'] = {"isin": row['ISIN'], "strike": row['Strike'], "multiplo": row['Multiplo'], "prezzo": row['Lettera']}
            st.success(f"✅ ISIN {row['ISIN']} caricato."); st.button("Aggiorna ora")

# ======================================================================
# TAB 4: ADVISOR 
# ======================================================================
with tab4:
    st.markdown("### 🤖 Advisor Strategico: Match Portafoglio")
    st.markdown("Imposta i vincoli di capitale e di budget per estrarre dal mercato i certificati matematicamente ottimali.")
    
    st.markdown("#### 1️⃣ Definisci i Parametri di Hedging")
    with st.form("adv_form"):
        c1, c2, c3, c4 = st.columns(4)
        v_p = c1.number_input("Valore Portafoglio (€)", value=200000.0, step=1000.0)
        v_b = c2.number_input("Beta", value=1.0, step=0.1)
        v_bud = c3.number_input("Budget Copertura (€)", value=5000.0, step=500.0)
        v_dist = c4.number_input("Distanza Barriera Min (%)", value=10.0, step=1.0)
        submit_adv = st.form_submit_button("🔍 Cerca Certificati Ottimali")
        
    if submit_adv:
        l_target = (v_p * v_b) / max(1.0, v_bud)
        st.markdown("#### 2️⃣ Risultato Ottimizzazione")
        st.metric(label="🎯 Leva Target Calcolata", value=f"{l_target:.2f}x", help="Rapporto matematico necessario tra capitale da proteggere e budget allocato.")
        
        df_l = fetch_live_certificates()
        if not df_l.empty:
            col_d = 'Distanza Barriera %' if 'Distanza Barriera %' in df_l.columns else None
            df_res = df_l.copy()
            if col_d: df_res = df_res[df_res[col_d] >= v_dist]
            df_res['Diff_Leva'] = (df_res['Leva'] - l_target).abs()
            matches = df_res.sort_values('Diff_Leva').head(10)
            
            if matches.empty: 
                st.warning("Nessun certificato sul mercato rispetta questi parametri. Prova a incrementare il budget o ridurre la distanza dalla barriera.")
            else:
                st.markdown("##### 🏆 Migliori Soluzioni di Mercato (Ordinati per vicinanza alla Leva Target)")
                st.dataframe(matches[['Sottostante', 'ISIN', 'Leva', 'Distanza Barriera %', 'Strike', 'Lettera']], use_container_width=True)
                st.info("👆 Copia l'ISIN desiderato o vai nella tab 'Database Live' per caricarlo nel motore di Setup.")
