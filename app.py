import streamlit as st
from calculator import TurboParameters, DeterministicTurboCalculator
from charts import generate_scenario_data, plot_payoff_profile
from stress_test import run_stress_test
from backtest import run_historical_backtest, generate_pdf_report
import datetime

st.set_page_config(page_title="Turbo Hedge Quant", layout="wide", page_icon="🏦")

# --- INIEZIONE CSS CORPORATE & PULSANTE BLUE NAVY ---
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
    
    /* STILE PULSANTE BLUE NAVY */
    div[data-testid="stFormSubmitButton"] button {
        background-color: #1A365D !important;
        color: #FFFFFF !important;
        border: none !important;
        font-weight: bold !important;
        padding: 10px 24px !important;
        border-radius: 6px !important;
    }
    div[data-testid="stFormSubmitButton"] button:hover {
        background-color: #2c5282 !important;
        color: #FFFFFF !important;
    }
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

tab1, tab2 = st.tabs(["🎯 Setup Copertura & Scenario", "📈 Backtest & Reportistica"])

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
        params = st.session_state['params']
        
        st.divider()
        st.markdown(f"<h2>📊 Risultati della Copertura</h2>", unsafe_allow_html=True)
        
        excel_col1, excel_col2, excel_col3 = st.columns([1, 1, 1.3])
        
        # --- COLONNA 1: CARATTERISTICHE TURBO ---
        with excel_col1:
            st.markdown("""
            <div style='background-color: #2c5282; padding: 12px; border-radius: 5px; text-align: center; margin-bottom: 15px;'>
            <h4 style='margin: 0; color: white; font-size: 16px;'>CARATTERISTICHE TURBO SHORT</h4>
            </div>
            """, unsafe_allow_html=True)
            
            st.markdown(f"""
            <table style='width: 100%; border-collapse: collapse; font-size: 14px;'>
            <tr style='background-color: #F8F9FA;'>
                <td style='padding: 8px; border: 1px solid #dee2e6;'><strong>Prezzo iniziale</strong></td>
                <td style='padding: 8px; border: 1px solid #dee2e6; text-align: right;'>{params.prezzo_iniziale:.2f} €</td>
            </tr>
            <tr>
                <td style='padding: 8px; border: 1px solid #dee2e6;'><strong>Fair Value</strong></td>
                <td style='padding: 8px; border: 1px solid #dee2e6; text-align: right; color: #2c5282; font-weight: bold;'>{res['fair_value']:.4f} €</td>
            </tr>
            <tr style='background-color: #F8F9FA;'>
                <td style='padding: 8px; border: 1px solid #dee2e6;'><strong>Premio</strong></td>
                <td style='padding: 8px; border: 1px solid #dee2e6; text-align: right;'>{res['premio']:.4f} €</td>
            </tr>
            <tr>
                <td style='padding: 8px; border: 1px solid #dee2e6;'><strong>Strike</strong></td>
                <td style='padding: 8px; border: 1px solid #dee2e6; text-align: right;'>{params.strike:.2f}</td>
            </tr>
            <tr style='background-color: #F8F9FA;'>
                <td style='padding: 8px; border: 1px solid #dee2e6;'><strong>Tasso di cambio</strong></td>
                <td style='padding: 8px; border: 1px solid #dee2e6; text-align: right;'>{params.cambio:.2f}</td>
            </tr>
            <tr>
                <td style='padding: 8px; border: 1px solid #dee2e6;'><strong>Multiplo</strong></td>
                <td style='padding: 8px; border: 1px solid #dee2e6; text-align: right;'>{params.multiplo:.3f}</td>
            </tr>
            <tr style='height: 20px;'><td colspan='2' style='border: none;'></td></tr>
            <tr style='background-color: #F8F9FA;'>
                <td style='padding: 8px; border: 1px solid #dee2e6;'><strong>Euribor 12M</strong></td>
                <td style='padding: 8px; border: 1px solid #dee2e6; text-align: right;'>{params.euribor:.5f}</td>
            </tr>
            </table>
            """, unsafe_allow_html=True)

        # --- COLONNA 2: INDICE ---
        with excel_col2:
            st.markdown("""
            <div style='background-color: #2c5282; padding: 12px; border-radius: 5px; text-align: center; margin-bottom: 15px;'>
            <h4 style='margin: 0; color: white; font-size: 16px;'>INDICE DA COPRIRE</h4>
            </div>
            """, unsafe_allow_html=True)
            
            st.markdown(f"""
            <table style='width: 100%; border-collapse: collapse; font-size: 14px;'>
            <tr style='background-color: #F8F9FA;'>
                <td style='padding: 8px; border: 1px solid #dee2e6;'><strong>Valore Iniziale</strong></td>
                <td style='padding: 8px; border: 1px solid #dee2e6; text-align: right;'>{params.valore_iniziale:.2f}</td>
            </tr>
            <tr>
                <td style='padding: 8px; border: 1px solid #dee2e6;'><strong>Valore Ipotetico</strong></td>
                <td style='padding: 8px; border: 1px solid #dee2e6; text-align: right; color: #c62828; font-weight: bold;'>{params.valore_ipotetico:.2f}</td>
            </tr>
            <tr style='background-color: #F8F9FA;'>
                <td style='padding: 8px; border: 1px solid #dee2e6;'><strong>Giorni</strong></td>
                <td style='padding: 8px; border: 1px solid #dee2e6; text-align: right;'>{params.giorni}</td>
            </tr>
            <tr style='height: 20px;'><td colspan='2' style='border: none;'></td></tr>
            <tr>
                <td style='padding: 8px; border: 1px solid #dee2e6;'><strong>Prezzo Turbo Short</strong></td>
                <td style='padding: 8px; border: 1px solid #dee2e6; text-align: right; color: #2c5282; font-weight: bold;'>{res['prezzo_futuro']:.4f} €</td>
            </tr>
            <tr style='background-color: #F8F9FA;'>
                <td style='padding: 8px; border: 1px solid #dee2e6;'><strong>Barriera Turbo Short</strong></td>
                <td style='padding: 8px; border: 1px solid #dee2e6; text-align: right;'>{res['barriera']:.2f}</td>
            </tr>
            <tr>
                <td style='padding: 8px; border: 1px solid #dee2e6;'><strong>Leva Turbo Short</strong></td>
                <td style='padding: 8px; border: 1px solid #dee2e6; text-align: right;'>{res['leva']:.2f}</td>
            </tr>
            </table>
            """, unsafe_allow_html=True)

        # --- COLONNA 3: PORTAFOGLIO & PERFORMANCE ---
        with excel_col3:
            st.markdown("""
            <div style='background-color: #2c5282; padding: 12px; border-radius: 5px; text-align: center; margin-bottom: 15px;'>
            <h4 style='margin: 0; color: white; font-size: 16px;'>PORTAFOGLIO DA COPRIRE</h4>
            </div>
            """, unsafe_allow_html=True)
            
            st.markdown(f"""
            <div style='text-align: right; font-size: 24px; font-weight: bold; color: #2c5282; margin-bottom: 20px; padding: 10px; background-color: #F8F9FA; border-radius: 5px;'>
            {params.portafoglio:,.2f} €
            </div>
            """, unsafe_allow_html=True)
            
            st.markdown(f"""
            <table style='width: 100%; border-collapse: collapse; margin-top: 10px; font-size: 14px;'>
            <tr style='background-color: #F8F9FA;'>
                <td style='padding: 8px; border: 1px solid #dee2e6;'><strong>N. Turbo Short</strong></td>
                <td style='padding: 8px; border: 1px solid #dee2e6; text-align: right;'>{res['n_turbo']:.2f}</td>
                <td rowspan='2' style='padding: 8px; border: 1px solid #dee2e6; text-align: center; vertical-align: middle; background-color: #E3F2FD; font-weight: bold;'>TOTALE CON<br/>COPERTURA</td>
            </tr>
            <tr>
                <td style='padding: 8px; border: 1px solid #dee2e6;'><strong>Capitale</strong></td>
                <td style='padding: 8px; border: 1px solid #dee2e6; text-align: right;'>{res['capitale']:,.2f} €</td>
            </tr>
            <tr style='background-color: #FFF3E0;'>
                <td colspan='2' style='padding: 8px; border: 1px solid #dee2e6; text-align: right; font-weight: bold;'></td>
                <td style='padding: 8px; border: 1px solid #dee2e6; text-align: center; color: #E65100; font-weight: bold; font-size: 16px;'>{res['totale_copertura']:,.2f} €</td>
            </tr>
            </table>
            """, unsafe_allow_html=True)
            
            st.markdown("""
            <div style='background-color: #E3F2FD; padding: 10px; border-radius: 5px; text-align: center; margin-top: 20px; margin-bottom: 10px;'>
            <strong style='color: #0D47A1;'>VALORE PORTAFOGLIO SIMULATO</strong>
            </div>
            """, unsafe_allow_html=True)
            
            st.markdown(f"""
            <table style='width: 100%; border-collapse: collapse; font-size: 14px;'>
            <tr style='background-color: #F8F9FA;'>
                <td style='padding: 8px; border: 1px solid #dee2e6;'></td>
                <td style='padding: 8px; border: 1px solid #dee2e6; text-align: right; font-weight: bold;'>VALORE COPERTURA</td>
            </tr>
            <tr>
                <td style='padding: 8px; border: 1px solid #dee2e6;'><strong>Portafoglio</strong></td>
                <td style='padding: 8px; border: 1px solid #dee2e6; text-align: right;'>{res['valore_ptf_simulato']:,.2f} €</td>
            </tr>
            <tr style='background-color: #F8F9FA;'>
                <td style='padding: 8px; border: 1px solid #dee2e6;'><strong>Turbo (netto)</strong></td>
                <td style='padding: 8px; border: 1px solid #dee2e6; text-align: right; color: #2E7D32; font-weight: bold;'>{res['valore_copertura_simulata']:,.2f} €</td>
            </tr>
            <tr style='height: 10px;'><td colspan='2' style='border: none;'></td></tr>
            <tr style='background-color: #E3F2FD;'>
                <td style='padding: 8px; border: 1px solid #dee2e6;'><strong>TOTALE</strong></td>
                <td style='padding: 8px; border: 1px solid #dee2e6; text-align: right; font-weight: bold; font-size: 16px;'>{res['totale_simulato']:,.2f} €</td>
            </tr>
            </table>
            """, unsafe_allow_html=True)
            
            perf = res['percentuale'] * 100
            perf_bg = '#E8F5E9' if perf >= 0 else '#FFEBEE'
            perf_color = '#2E7D32' if perf >= 0 else '#C62828'
            perf_sign = '+' if perf >= 0 else ''
            
            st.markdown(f"""
            <div style='background-color: {perf_bg}; padding: 20px; border-radius: 5px; text-align: center; border: 3px solid {perf_color}; margin-top: 15px;'>
            <div style='font-size: 42px; font-weight: bold; color: {perf_color}; line-height: 1;'>{perf_sign}{perf:.2f}%</div>
            <div style='color: #666; font-size: 12px; margin-top: 8px; font-weight: 600;'>PERFORMANCE COPERTA</div>
            </div>
            """, unsafe_allow_html=True)

        # --- DIAGNOSI E COMMENTO RISK MANAGER ---
        st.divider()
        
        # Logica del verdetto sul singolo scenario calcolato
        hr_val = (res['hedge_ratio_reale'] if is_real_ratio else res['hedge_ratio_commerciale']) * 100
        label_hr = "Hedge Ratio (Reale)" if is_real_ratio else "Hedge Ratio (Commerciale/Lordo)"
        
        col_diag1, col_diag2 = st.columns([1, 2])
        
        with col_diag1:
            st.metric(label=f"🛡️ {label_hr}", value=f"{hr_val:.1f}%")
            if not is_real_ratio:
                st.caption("⚠️ *Stai visualizzando il rapporto lordo che ignora i costi. Passa alla modalità Risk Manager in alto.*")
                
        with col_diag2:
            is_ko = params.valore_ipotetico >= res['barriera']
            
            if is_ko:
                st.error("**🚨 VERDETTO: KNOCK-OUT (Rischio Rovina)**\n\nNello scenario ipotizzato l'indice ha sfondato la barriera. Il certificato è stato annullato, l'intero premio pagato è stato bruciato e il portafoglio è rimasto totalmente scoperto alla discesa. **Consiglio:** Questo strike è troppo aggressivo per questo scenario di stress. Scegli un Turbo con strike più alto.")
            elif res['pl_portafoglio'] >= 0:
                st.info("**ℹ️ VERDETTO: CASH DRAG (Mercato in Rialzo)**\n\nL'indice è salito o rimasto stabile. Il portafoglio è in profitto, ma la copertura ha operato come un'assicurazione a perdere, erodendo la performance netta a causa del deprezzamento del derivato. **Consiglio:** Accettabile se l'hedge era puramente difensivo.")
            elif hr_val >= 90:
                st.success(f"**✅ VERDETTO: COPERTURA OTTIMALE**\n\nLa struttura è chirurgica. Il guadagno netto del derivato neutralizza con successo il {hr_val:.1f}% della perdita del portafoglio senza avvicinarsi criticamente alla barriera. **Consiglio:** Configurazione raccomandata per questo scenario.")
            elif hr_val >= 50:
                st.warning(f"**⚠️ VERDETTO: SOTTOCOPERTURA**\n\nLa struttura assorbe solo il {hr_val:.1f}% della perdita. O hai investito troppo poco capitale, o l'effetto del decadimento temporale (Time Decay) sta mangiando i profitti del derivato. **Consiglio:** Aumenta il capitale allocato all'hedge o usa uno strumento con leva maggiore.")
            else:
                st.error(f"**❌ VERDETTO: COPERTURA INEFFICACE**\n\nStai coprendo solo il {hr_val:.1f}%. I costi e il decadimento del derivato superano i benefici direzionali. **Consiglio:** La strategia attuale sta bruciando liquidità senza offrire reale protezione. Ricalibra leva e capitale.")

        # --- SEZIONI GRAFICHE E STRESS TEST ---
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
                df_bt, msg, diagnosis = run_historical_backtest(
                    ticker_ptf, ticker_idx, start_date, end_date, st.session_state['barriera_calcolata']
                )
                
                if df_bt is not None:
                    st.success("Analisi completata.")
                    
                    pdf_bytes = generate_pdf_report(
                        df_bt, ticker_ptf, ticker_idx, st.session_state['barriera_calcolata'], diagnosis
                    )
                    
                    st.download_button(
                        label="📄 Scarica Report Risk Management (PDF)",
                        data=pdf_bytes,
                        file_name=f"Hedge_Report_{ticker_ptf}.pdf",
                        mime="application/pdf"
                    )
                    
                    st.line_chart(df_bt.set_index('Date')['Beta_60d'])
                    st.dataframe(df_bt[['Date', 'Ptf_Close', 'Idx_High', 'Drawdown', 'Beta_60d', 'Knock_Out_Event']].tail(30), use_container_width=True)
                    
                    st.divider()
                    st.markdown("### Verdetto Storico del Risk Manager")
                    if diagnosis['color'] == 'error':
                        st.error(f"**🚨 {diagnosis['title']}**\n\n{diagnosis['body']}\n\n**{diagnosis['action']}**")
                    elif diagnosis['color'] == 'warning':
                        st.warning(f"**⚠️ {diagnosis['title']}**\n\n{diagnosis['body']}\n\n**{diagnosis['action']}**")
                    else:
                        st.success(f"**✅ {diagnosis['title']}**\n\n{diagnosis['body']}\n\n**{diagnosis['action']}**")
                else:
                    st.error(f"Errore: {msg}")
