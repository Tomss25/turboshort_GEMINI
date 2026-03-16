import streamlit as st
from calculator import TurboParameters, DeterministicTurboCalculator
from charts import generate_scenario_data, plot_payoff_profile
from stress_test import run_stress_test
from backtest import run_historical_backtest
import datetime

st.set_page_config(page_title="Turbo Hedge Quant", layout="wide")
st.title("📊 Turbo Hedge Quant Dashboard v2.0")

tab1, tab2 = st.tabs(["🎯 Dimensionamento Copertura", "📈 Backtesting Storico"])

with tab1:
    with st.form("input_form"):
        col1, col2, col3 = st.columns(3)
        
        with col1:
            st.markdown("**Caratteristiche Turbo**")
            p_iniziale = st.number_input("Prezzo iniziale (€)", value=7.64, step=0.01)
            strike = st.number_input("Strike", value=7505.97, step=0.01)
            cambio = st.number_input("Tasso di cambio", value=1.15, step=0.01)
            multiplo = st.number_input("Multiplo", value=0.01, format="%.3f")
            euribor = st.number_input("Euribor 12M", value=0.02456, format="%.5f")
            
        with col2:
            st.markdown("**Indice**")
            v_iniziale = st.number_input("Valore Iniziale", value=6670.75, step=0.01)
            v_ipotetico = st.number_input("Valore Ipotetico", value=6000.0, step=0.01)
            giorni = st.number_input("Giorni", value=60, step=1)
            
        with col3:
            st.markdown("**Portafoglio**")
            ptf = st.number_input("Portafoglio (€)", value=200000.0, step=1000.0)
            beta = st.number_input("Beta Portafoglio", value=1.00, step=0.05)
            
        submitted = st.form_submit_button("Esegui Calcolo", type="primary")

    if submitted:
        params = TurboParameters(
            prezzo_iniziale=p_iniziale, strike=strike, cambio=cambio,
            multiplo=multiplo, euribor=euribor, valore_iniziale=v_iniziale,
            valore_ipotetico=v_ipotetico, giorni=giorni, portafoglio=ptf, beta=beta
        )
        
        calc = DeterministicTurboCalculator(params)
        res = calc.calculate_all()
        
        st.session_state['barriera_calcolata'] = res['barriera']
        
        st.divider()
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Fair Value", f"€ {res['fair_value']:.4f}")
        c2.metric("Barriera Turbo", f"{res['barriera']:.2f}")
        c3.metric("N. Turbo (Beta Adj)", f"{res['n_turbo']:.2f}")
        c4.metric("Capitale Investito", f"€ {res['capitale']:,.2f}")
        
        st.divider()
        st.subheader("Risultato Simulato a Scadenza")
        r1, r2, r3 = st.columns(3)
        r1.metric("Valore Ptf Simulato", f"€ {res['valore_ptf_simulato']:,.2f}")
        r2.metric("Valore Copertura", f"€ {res['valore_copertura_simulata']:,.2f}")
        color = "normal" if res['percentuale'] >= 0 else "inverse"
        r3.metric("Performance Netta", f"{res['percentuale'] * 100:.2f}%", delta_color=color)

        st.divider()
        mostra_rischio = st.checkbox(
            "🔍 Mostra Metriche Avanzate di Rischio (Hedge Ratio Reale)", 
            value=False,
            help="Attivando questa spunta il tool smette di lusingarti e calcola l'efficacia reale della tua copertura. Rivela l'esatta percentuale di perdita neutralizzata."
        )
        if mostra_rischio:
            adv1, adv2, adv3 = st.columns(3)
            adv1.metric("Perdita Ptf", f"€ {res['pl_portafoglio']:,.2f}")
            adv2.metric("Guadagno Turbo Netto", f"€ {res['pl_turbo']:,.2f}")
            hr = res['hedge_ratio'] * 100
            if res['pl_portafoglio'] >= 0:
                adv3.warning("N/A (Indice in rialzo)")
            elif hr >= 90:
                adv3.success(f"🎯 Hedge Ratio: {hr:.1f}%")
            elif hr >= 50:
                adv3.warning(f"⚠️ Hedge Ratio: {hr:.1f}% (Sottocoperto)")
            else:
                adv3.error(f"🚨 Hedge Ratio: {hr:.1f}% (Inefficace)")

        st.divider()
        st.subheader("⚠️ Stress Test Discreto Estremo")
        df_stress = run_stress_test(params)
        st.dataframe(df_stress, use_container_width=True, hide_index=True)

        st.divider()
        st.subheader("📉 Payoff Continuo a Scadenza")
        df_scenari, livello_barriera = generate_scenario_data(params)
        fig = plot_payoff_profile(df_scenari, current_spot=params.valore_iniziale, barriera=livello_barriera)
        st.plotly_chart(fig, use_container_width=True)

with tab2:
    st.markdown("### Simulazione Storica e Beta Rolling (60g)")
    st.info("Valutazione del rischio su base storica. Verifica i Knock-Out sfruttando i massimi intraday.")
    
    if 'barriera_calcolata' not in st.session_state:
        st.warning("Per favore, calcola prima la barriera nel Tab 1.")
    else:
        b_col1, b_col2, b_col3, b_col4 = st.columns(4)
        ticker_ptf = b_col1.text_input("Ticker Portafoglio", value="SPY")
        ticker_idx = b_col2.text_input("Ticker Indice", value="^GSPC")
        start_date = b_col3.date_input("Inizio", value=datetime.date(2023, 1, 1))
        end_date = b_col4.date_input("Fine", value=datetime.date.today())
        
        if st.button("Esegui Backtest Veloce", type="primary"):
            with st.spinner("Estrazione dati, calcolo covarianze e stress barriera..."):
                df_bt, msg = run_historical_backtest(
                    ticker_ptf, ticker_idx, start_date, end_date, st.session_state['barriera_calcolata']
                )
                
                if df_bt is not None:
                    st.success("Analisi quantitativa completata.")
                    st.write("**Evoluzione del Beta Dinamico**")
                    st.line_chart(df_bt.set_index('Date')['Beta_60d'])
                    st.write("**Log Rischi (Controlla colonna Knock_Out_Event)**")
                    st.dataframe(df_bt[['Date', 'Ptf_Close', 'Idx_High', 'Drawdown', 'Beta_60d', 'Hedge_Signal', 'Knock_Out_Event']].tail(30), use_container_width=True)
                else:
                    st.error(f"Errore: {msg}")