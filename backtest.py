import yfinance as yf
import pandas as pd
import numpy as np
from fpdf import FPDF

def run_historical_backtest(ticker_ptf: str, ticker_idx: str, start: str, end: str, livello_barriera: float):
    try:
        ptf_data = yf.download(ticker_ptf, start=start, end=end, progress=False)['Close']
        idx_data = yf.download(ticker_idx, start=start, end=end, progress=False)[['Close', 'High']]
        
        if ptf_data.empty or idx_data.empty:
            return None, "Dati non trovati per i ticker specificati.", None

        df = pd.DataFrame({
            'Ptf_Close': ptf_data.squeeze(),
            'Idx_Close': idx_data['Close'].squeeze(),
            'Idx_High': idx_data['High'].squeeze()
        }).dropna()

        df['R_ptf'] = df['Ptf_Close'].pct_change()
        df['R_idx'] = df['Idx_Close'].pct_change()
        cov_60d = df['R_ptf'].rolling(window=60).cov(df['R_idx'])
        var_60d = df['R_idx'].rolling(window=60).var()
        df['Beta_60d'] = (cov_60d / var_60d).fillna(1.0)
        
        df['Peak'] = df['Ptf_Close'].cummax()
        df['Drawdown'] = (df['Ptf_Close'] - df['Peak']) / df['Peak']
        
        df['Knock_Out_Event'] = np.where(df['Idx_High'] >= livello_barriera, 1, 0)
        
        df['Hedge_Signal'] = np.where(df['Drawdown'] < -0.05, 1, 0)
        df['Hedge_Signal'] = np.where((df['Drawdown'] > -0.02) | (df['Knock_Out_Event'] == 1), 0, df['Hedge_Signal'])
        df['Hedge_Signal'] = df['Hedge_Signal'].ffill().fillna(0)
        df['Hedge_Signal'] = np.where(df['Knock_Out_Event'] == 1, 0, df['Hedge_Signal'])

        # --- MOTORE DIAGNOSTICO ---
        giorni_totali = len(df)
        giorni_coperti = df['Hedge_Signal'].sum()
        numero_ko = df['Knock_Out_Event'].sum()
        perc_copertura = (giorni_coperti / giorni_totali) * 100 if giorni_totali > 0 else 0
        
        if numero_ko > 0:
            diag_color = "error"
            diag_title = "FALLIMENTO STRUTTURALE (Rischio Rovina)"
            diag_body = f"La simulazione ha registrato {numero_ko} eventi di Knock-Out sui massimi intraday. Il premio pagato per la copertura è stato interamente bruciato."
            diag_action = "AZIONE CORRETTIVA: Allontana lo Strike. Stai usando una leva troppo aggressiva che non sopravvive al respiro fisiologico di mercato. Sposta la barriera più in alto e accetta un esborso di capitale maggiore."
        elif perc_copertura > 40:
            diag_color = "warning"
            diag_title = "SOTTOEFFICIENZA (Cash Drag e Over-Hedging)"
            diag_body = f"Nessun K.O. registrato, ma il portafoglio è rimasto coperto per il {perc_copertura:.1f}% del tempo. Mantenere derivati aperti così a lungo distrugge le performance a causa del funding spread."
            diag_action = "AZIONE CORRETTIVA: La copertura deve essere chirurgica. Rivedi i trigger sistematici di ingresso (es. copri solo su drawdowns più profondi del -5%)."
        else:
            diag_color = "success"
            diag_title = "ESITO POSITIVO (Copertura Tattica Ottimale)"
            diag_body = f"Nessun Knock-Out registrato. La permanenza a mercato è stata chirurgica ({perc_copertura:.1f}% del tempo), confermando che la barriera è sufficientemente lontana dal rumore di fondo."
            diag_action = "RISOLUZIONE: I parametri strutturali del derivato (Strike e Leva) sono solidi per l'orizzonte e il sottostante scelti."

        diagnosis = {
            "title": diag_title,
            "body": diag_body,
            "action": diag_action,
            "color": diag_color
        }

        return df.reset_index(), "Successo", diagnosis
        
    except Exception as e:
        return None, str(e), None

def generate_pdf_report(df: pd.DataFrame, ticker_ptf: str, ticker_idx: str, barriera: float, diagnosis: dict) -> bytes:
    import tempfile
    import os
    from fpdf import FPDF
    
    giorni_totali = len(df)
    giorni_coperti = df['Hedge_Signal'].sum()
    percentuale_copertura = (giorni_coperti / giorni_totali) * 100
    numero_ko = df['Knock_Out_Event'].sum()
    max_dd = df['Drawdown'].min() * 100
    
    pdf = FPDF()
    pdf.add_page()
    
    pdf.set_font("Helvetica", "B", 16)
    pdf.set_text_color(26, 54, 93)
    pdf.cell(0, 10, "Turbo Hedge Quant - Report di Backtest", ln=True, align="C")
    pdf.ln(10)
    
    pdf.set_font("Helvetica", "", 12)
    pdf.set_text_color(0, 0, 0)
    pdf.cell(0, 8, f"Asset Analizzati: Portafoglio [{ticker_ptf}] vs Indice [{ticker_idx}]", ln=True)
    pdf.cell(0, 8, f"Periodo Analizzato: {df['Date'].dt.date.iloc[0]} -> {df['Date'].dt.date.iloc[-1]}", ln=True)
    pdf.cell(0, 8, f"Livello Barriera Sotto Stress: {barriera:.2f}", ln=True)
    pdf.ln(10)
    
    pdf.set_font("Helvetica", "B", 14)
    pdf.set_text_color(26, 54, 93)
    pdf.cell(0, 10, "Metriche Storiche", ln=True)
    
    pdf.set_font("Helvetica", "", 12)
    pdf.set_text_color(0, 0, 0)
    pdf.cell(0, 8, f"Max Drawdown Storico: {max_dd:.2f}%", ln=True)
    pdf.cell(0, 8, f"Tempo trascorso in copertura: {percentuale_copertura:.1f}% del periodo", ln=True)
    pdf.cell(0, 8, f"Eventi di Knock-Out Registrati (Massimi Intraday): {numero_ko} eventi", ln=True)
    pdf.ln(10)
    
    # Iniezione della Diagnosi nel PDF
    if diagnosis['color'] == 'error':
        pdf.set_text_color(180, 0, 0) # Rosso
    elif diagnosis['color'] == 'warning':
        pdf.set_text_color(200, 100, 0) # Arancione
    else:
        pdf.set_text_color(0, 120, 0) # Verde
        
    pdf.set_font("Helvetica", "B", 14)
    pdf.cell(0, 10, f"DIAGNOSI: {diagnosis['title']}", ln=True)
    pdf.set_text_color(0, 0, 0)
    pdf.set_font("Helvetica", "", 11)
    pdf.multi_cell(0, 6, txt=diagnosis['body'])
    pdf.ln(2)
    pdf.set_font("Helvetica", "B", 11)
    pdf.multi_cell(0, 6, txt=diagnosis['action'])
    
    with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
        tmp_path = tmp.name
        
    pdf.output(tmp_path)
    
    with open(tmp_path, "rb") as f:
        pdf_bytes = f.read()
        
    os.remove(tmp_path)
    return pdf_bytes
