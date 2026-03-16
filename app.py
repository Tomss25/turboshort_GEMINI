import streamlit as st
from calculator import TurboParameters, DeterministicTurboCalculator
from charts import generate_scenario_data, plot_payoff_profile
from stress_test import run_stress_test
from backtest import run_historical_backtest, generate_pdf_report
import datetime

st.set_page_config(page_title="Turbo Hedge Quant", layout="wide", page_icon="🏦")
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
</style>
""", unsafe_allow_html=True)

st.title("🏦 Dashboard Copertura Istituzionale (v2.0)")

st.markdown('<div class="risk-toggle">', unsafe_allow_html=True)
is_real_ratio = st.toggle(
    "🛡️ **Modalità Risk Manager (Hedge Ratio Netto)**", 
    value=True, 
    help="ATTIVO: Mostra la percentuale di perdita coperta SOTTRAENDO il costo iniziale pagato per il Turbo. DISATTIVO: Mostra la metrica commerciale lorda (pericolosa, sovrastima la protezione)."
)
st.markdown('</div>', unsafe_allow_html=True)

tab1, tab2 = st.tabs(["🎯 Setup Copertura & Stress Test", "📈 Backtest & Reportistica"])

with tab1:
    with st.form("input_form"):
        col1, col2, col3 = st.columns(3)
        with col1:
            st.markdown("### ⚙️ Derivato (Turbo)")
            p_iniziale = st.number_input("Prezzo iniziale (€)", value=7.64, step=0.01)
            strike = st.number_input("Strike", value=7505.97, step=0.01)
            cambio = st.number_input("Tasso di cambio", value=1.15, step=0.01)
            multiplo = st.number_input("Multiplo", value=0.01, format="%.3f")
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
        params = TurboParameters(
            prezzo_iniziale=p_iniziale, strike=strike, cambio=cambio,
            multiplo=multiplo, euribor=euribor, valore_iniziale=v_iniziale,
            valore_ipotetico=v_ipotetico, giorni=giorni, portafoglio=ptf, beta=beta
        )
        calc = DeterministicTurboCalculator(params)
        res = calc.calculate_all()
        
        st.session_state['barriera_calcolata'] = res['barriera']
        st.session_state['params'] = params
        st.session_state['res'] = res

    if 'res' in st.session_state:
        res = st.session_state['res']
        
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Fair Value", f"€ {res['fair_value']:.4f}")
        c2.metric("Barriera K.O.", f"{res['barriera']:.2f}")
        c3.metric("N. Turbo (Beta Adj)", f"{res['n_turbo']:.2f}")
        c4.metric("Capitale Rischio", f"€ {res['capitale']:,.2f}")
        
        st.divider()
        st.markdown("### 📊 Efficacia della Copertura a Scadenza")
        
        r1, r2, r3, r4 = st.columns(4)
        r1.metric("P&L Ptf Nudo", f"€ {res['pl_portafoglio']:,.2f}")
        
        if is_real_ratio:
            r2.metric("P&L Copertura (Netto)", f"€ {res['pl_turbo_netto']:,.2f}")
            hr_val = res['hedge_ratio_reale'] * 100
            label_hr = "Hedge Ratio (Reale)"
        else:
            r2.metric("P&L Copertura (Lordo)", f"€ {res['pl_turbo_lordo']:,.2f}")
            hr_val = res['hedge_ratio_commerciale'] * 100
            label_hr = "Hedge Ratio (Illusorio)"
            
        if res['pl_portafoglio'] >= 0:
            r3.warning("N/A (Indice in rialzo)")
        elif hr_val >= 90:
            r3.success(f"🎯 {label_hr}: {hr_val:.1f}%")
        elif hr_val >= 50:
            r3.warning(f"⚠️ {label_hr}: {hr_val:.1f}%")
        else:
            r3.error(f"🚨 {label_hr}: {hr_val:.1f}%")
            
        color = "normal" if res['percentuale'] >= 0 else "inverse"
        r4.metric("Rendimento Netto Totale", f"{res['percentuale'] * 100:.2f}%", delta_color=color)

        st.divider()
        st.subheader("⚠️ Matrice di Stress Estremo")
        df_stress = run_stress_test(st.session_state['params'])
        st.dataframe(df_stress, use_container_width=True, hide_index=True)

        st.subheader("📉 Payoff Continuo")
        df_scenari, livello_barriera = generate_scenario_data(st.session_state['params'])
        fig = plot_payoff_profile(df_scenari, current_spot=st.session_state['params'].valore_iniziale, barriera=livello_barriera)
        st.plotly_chart(fig, use_container_width=True)

with tab2:
    st.markdown("### Analisi Storica Event-Driven")
    
    if 'barriera_calcolata' not in st.session_state:
        st.warning("Per favore, calcola prima la struttura base nel Tab 1.")
    else:
        b_col1, b_col2, b_col3, b_col4 = st.columns(4)
        ticker_ptf = b_col1.text_input("Ticker Portafoglio", value="SPY")
        ticker_idx = b_col2.text_input("Ticker Indice", value="^GSPC")
        start_date = b_col3.date_input("Inizio", value=datetime.date(2023, 1, 1))
        end_date = b_col4.date_input("Fine", value=datetime.date.today())
        
        if st.button("🚀 Avvia Backtest Quantitativo", type="primary"):
            with st.spinner("Compilazione dati ed esecuzione logiche di Knock-Out..."):
                df_bt, msg = run_historical_backtest(
                    ticker_ptf, ticker_idx, start_date, end_date, st.session_state['barriera_calcolata']
                )
                
                if df_bt is not None:
                    st.success("Analisi completata.")
                    
                    pdf_bytes = generate_pdf_report(df_bt, ticker_ptf, ticker_idx, st.session_state['barriera_calcolata'])
                    
                    st.download_button(
                        label="📄 Scarica Report Risk Management (PDF)",
                        data=pdf_bytes,
                        file_name=f"Hedge_Report_{ticker_ptf}.pdf",
                        mime="application/pdf"
                    )
                    
                    st.line_chart(df_bt.set_index('Date')['Beta_60d'])
                    st.dataframe(df_bt[['Date', 'Ptf_Close', 'Idx_High', 'Drawdown', 'Beta_60d', 'Knock_Out_Event']].tail(30), use_container_width=True)
                else:
                    st.error(f"Errore: {msg}")
