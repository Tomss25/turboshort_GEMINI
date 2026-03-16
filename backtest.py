import yfinance as yf
import pandas as pd
import numpy as np

def run_historical_backtest(ticker_ptf: str, ticker_idx: str, start: str, end: str, livello_barriera: float):
    """
    Scarica i dati storici, calcola il Beta Rolling a 60 giorni e valuta la 
    condizione di Knock-Out sfruttando rigorosamente i massimi intraday (High).
    """
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

        # Ritorni e Beta Rolling a 60 giorni
        df['R_ptf'] = df['Ptf_Close'].pct_change()
        df['R_idx'] = df['Idx_Close'].pct_change()
        cov_60d = df['R_ptf'].rolling(window=60).cov(df['R_idx'])
        var_60d = df['R_idx'].rolling(window=60).var()
        df['Beta_60d'] = (cov_60d / var_60d).fillna(1.0)
        
        # Logica Drawdown per trigger
        df['Peak'] = df['Ptf_Close'].cummax()
        df['Drawdown'] = (df['Ptf_Close'] - df['Peak']) / df['Peak']
        
        # Risk Management: Il controllo spietato sul massimo intraday
        # Se l'High supera la barriera, il certificato muore.
        df['Knock_Out_Event'] = np.where(df['Idx_High'] >= livello_barriera, 1, 0)
        
        # Generazione Segnali
        df['Hedge_Signal'] = np.where(df['Drawdown'] < -0.05, 1, 0)
        df['Hedge_Signal'] = np.where((df['Drawdown'] > -0.02) | (df['Knock_Out_Event'] == 1), 0, df['Hedge_Signal'])
        df['Hedge_Signal'] = df['Hedge_Signal'].ffill().fillna(0)
        
        # Forziamo a zero il segnale post-KO nella stessa giornata
        df['Hedge_Signal'] = np.where(df['Knock_Out_Event'] == 1, 0, df['Hedge_Signal'])

        return df.reset_index(), "Successo"
        
    except Exception as e:
        return None, str(e)