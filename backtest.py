import yfinance as yf
import pandas as pd
import numpy as np

def run_historical_backtest(ticker_ptf: str, ticker_idx: str, ticker_fx: str, start: str, end: str, livello_barriera: float):
    try:
        ptf_data = yf.download(ticker_ptf, start=start, end=end, progress=False)['Close']
        idx_data = yf.download(ticker_idx, start=start, end=end, progress=False)[['Close', 'High']]
        
        if ptf_data.empty or idx_data.empty:
            return None, "Dati Portafoglio o Indice non trovati.", None
            
        df = pd.DataFrame({
            'Ptf_Close': ptf_data.squeeze(),
            'Idx_Close': idx_data['Close'].squeeze(),
            'Idx_High': idx_data['High'].squeeze()
        }).dropna()

        # INTEGRAZIONE FX RISK
        if ticker_fx and ticker_fx.strip() != "":
            fx_data = yf.download(ticker_fx, start=start, end=end, progress=False)['Close']
            if not fx_data.empty:
                df = df.join(fx_data.rename('FX_Close'), how='inner')
                # Convertiamo il portafoglio nella valuta base (es. USD a EUR)
                df['Ptf_Base_Currency'] = df['Ptf_Close'] / df['FX_Close']
            else:
                df['Ptf_Base_Currency'] = df['Ptf_Close']
        else:
            df['Ptf_Base_Currency'] = df['Ptf_Close']

        # Beta calcolato sui rendimenti grezzi dell'asset
        df['R_ptf'] = df['Ptf_Close'].pct_change()
        df['R_idx'] = df['Idx_Close'].pct_change()
        cov_60d = df['R_ptf'].rolling(window=60).cov(df['R_idx'])
        var_60d = df['R_idx'].rolling(window=60).var()
        df['Beta_60d'] = (cov_60d / var_60d).fillna(1.0)
        
        # Drawdown calcolato sul portafoglio Depurato dal Cambio (Realtà per l'investitore)
        df['Peak'] = df['Ptf_Base_Currency'].cummax()
        df['Drawdown'] = (df['Ptf_Base_Currency'] - df['Peak']) / df['Peak']
        
        df['Knock_Out_Event'] = np.where(df['Idx_High'] >= livello_barriera, 1, 0)
        
        df['Hedge_Signal'] = np.where(df['Drawdown'] < -0.05, 1, 0)
        df['Hedge_Signal'] = np.where((df['Drawdown'] > -0.02) | (df['Knock_Out_Event'] == 1), 0, df['Hedge_Signal'])
        df['Hedge_Signal'] = df['Hedge_Signal'].ffill().fillna(0)
        df['Hedge_Signal'] = np.where(df['Knock_Out_Event'] == 1, 0, df['Hedge_Signal'])

        # Motore Diagnostico Invariato
        giorni_totali = len(df)
        giorni_coperti = df['Hedge_Signal'].sum()
        numero_ko = df['Knock_Out_Event'].sum()
        perc_copertura = (giorni_coperti / giorni_totali) * 100 if giorni_totali > 0 else 0
        
        if numero_ko > 0:
            diag_color = "error"
            diag_title = "FALLIMENTO STRUTTURALE (Rischio Rovina)"
            diag_body = f"La simulazione ha registrato {numero_ko} eventi di Knock-Out sui massimi intraday."
            diag_action = "AZIONE CORRETTIVA: Allontana lo Strike o controlla se il rischio di cambio sta scatenando finti segnali di copertura."
        elif perc_copertura > 40:
            diag_color = "warning"
            diag_title = "SOTTOEFFICIENZA (Cash Drag)"
            diag_body = f"Portafoglio coperto per il {perc_copertura:.1f}% del tempo. Eccessiva esposizione ai costi del derivato."
            diag_action = "AZIONE CORRETTIVA: Rivedi i trigger sistematici di ingresso."
        else:
            diag_color = "success"
            diag_title = "ESITO POSITIVO (Copertura Tattica Ottimale)"
            diag_body = f"Nessun Knock-Out. Permanenza a mercato chirurgica ({perc_copertura:.1f}% del tempo)."
            diag_action = "RISOLUZIONE: I parametri strutturali sono solidi."

        diagnosis = {
            "title": diag_title, "body": diag_body, "action": diag_action, "color": diag_color
        }

        return df.reset_index(), "Successo", diagnosis
        
    except Exception as e:
        return None, str(e), None

def generate_pdf_report(df: pd.DataFrame, ticker_ptf: str, ticker_idx: str, ticker_fx: str, barriera: float, diagnosis: dict) -> bytes:
    import tempfile
    import os
    from fpdf import FPDF
    
    giorni_totali = len(df)
    giorni_coperti = df['Hedge_Signal'].sum()
    percentuale_copertura = (giorni_coperti / giorni_totali) * 100
    numero_ko = df['Knock_Out_Event'].sum()
    max_dd = df['Drawdown'].min() * 100
    fx_note = f" (Aggiustato per rischio cambio su {ticker_fx})" if ticker_fx else " (Nessun rischio cambio inserito)"
    
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
    pdf.cell(0, 8, f"Max Drawdown Storico{fx_note}: {max_dd:.2f}%", ln=True)
    pdf.cell(0, 8, f"Tempo trascorso in copertura: {percentuale_copertura:.1f}% del periodo", ln=True)
    pdf.cell(0, 8, f"Eventi di Knock-Out Registrati (Massimi Intraday): {numero_ko} eventi", ln=True)
    pdf.ln(10)
    
    if diagnosis['color'] == 'error':
        pdf.set_text_color(180, 0, 0)
    elif diagnosis['color'] == 'warning':
        pdf.set_text_color(200, 100, 0)
    else:
        pdf.set_text_color(0, 120, 0)
        
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
