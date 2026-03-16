import yfinance as yf
import pandas as pd
import numpy as np
from fpdf import FPDF

def run_historical_backtest(ticker_ptf: str, ticker_idx: str, start: str, end: str, livello_barriera: float):
    try:
        ptf_data = yf.download(ticker_ptf, start=start, end=end, progress=False)['Close']
        idx_data = yf.download(ticker_idx, start=start, end=end, progress=False)[['Close', 'High']]
        
        if ptf_data.empty or idx_data.empty:
            return None, "Dati non trovati per i ticker specificati."

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

        return df.reset_index(), "Successo"
        
    except Exception as e:
        return None, str(e)

def generate_pdf_report(df: pd.DataFrame, ticker_ptf: str, ticker_idx: str, barriera: float) -> bytes:
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
    pdf.cell(0, 8, f"Periodo: {df['Date'].dt.date.iloc[0]} -> {df['Date'].dt.date.iloc[-1]} ({giorni_totali} giorni di borsa)", ln=True)
    pdf.cell(0, 8, f"Livello Barriera Analizzato: {barriera:.2f}", ln=True)
    pdf.ln(10)
    
    pdf.set_font("Helvetica", "B", 14)
    pdf.set_text_color(26, 54, 93)
    pdf.cell(0, 10, "Metriche di Rischio Storiche", ln=True)
    
    pdf.set_font("Helvetica", "", 12)
    pdf.set_text_color(0, 0, 0)
    pdf.cell(0, 8, f"Max Drawdown Storico: {max_dd:.2f}%", ln=True)
    pdf.cell(0, 8, f"Tempo trascorso in regime di copertura: {percentuale_copertura:.1f}% del tempo", ln=True)
    pdf.cell(0, 8, f"Eventi di Knock-Out Registrati (Massimi Intraday): {numero_ko} eventi", ln=True)
    
    pdf.ln(10)
    pdf.set_font("Helvetica", "I", 10)
    pdf.multi_cell(0, 6, txt="NOTA RISK MANAGER: Un numero elevato di Knock-Out indica che lo strike scelto "
                             "è troppo vicino alla volatilità fisiologica del mercato. Valutare un allontanamento "
                             "della barriera per evitare l'azzeramento frequente del premio.")
    
    return bytes(pdf.output())
