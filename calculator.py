import math
from dataclasses import dataclass
from typing import Dict, Any

@dataclass
class TurboParameters:
    prezzo_iniziale: float
    strike: float
    cambio: float
    multiplo: float
    euribor: float
    valore_iniziale: float
    valore_ipotetico: float
    giorni: int
    portafoglio: float
    beta: float = 1.0
    spread_emittente: float = 0.0056
    # NUOVI PARAMETRI DI REALTÀ
    dividend_yield: float = 0.015  # Default 1.5%
    bid_ask_spread: float = 0.005  # Default 0.5%
    commissioni_pct: float = 0.001 # Default 0.1%
    stress_slippage: float = 0.0   # Usato solo negli stress test estremi

class DeterministicTurboCalculator:
    def __init__(self, p: TurboParameters):
        self.p = p

    def safe_divide(self, numerator: float, denominator: float) -> float:
        return 0.0 if denominator == 0 else numerator / denominator

    def calculate_all(self) -> Dict[str, Any]:
        # Aggiustamento Strike per Dividendi Continui
        T = self.safe_divide(self.p.giorni, 360)
        strike_adj = self.p.strike * math.exp(-self.p.dividend_yield * T)
        
        fair_value = self.safe_divide((strike_adj - self.p.valore_iniziale) * self.p.multiplo, self.p.cambio)
        fair_value = max(0.0, fair_value)
        premio = max(0.0, self.p.prezzo_iniziale - fair_value)
        
        denominatore_leva = self.safe_divide(self.p.prezzo_iniziale * self.p.cambio, self.p.multiplo)
        leva = self.safe_divide(self.p.valore_iniziale, denominatore_leva)

        tasso_netto = 1 - self.p.euribor + self.p.spread_emittente
        barriera = self.p.strike * math.pow(tasso_netto, T)
        
        # FIX CHIRURGICO: Il valore intrinseco in un Turbo Short si calcola dallo Strike, non dalla Barriera.
        valore_intrinseco_futuro = self.safe_divide((self.p.strike - self.p.valore_ipotetico) * self.p.multiplo, self.p.cambio)
        prezzo_futuro = max(0.0, valore_intrinseco_futuro + premio)

        esposizione_pesata = self.p.portafoglio * self.p.beta
        n_turbo = self.safe_divide(self.safe_divide(esposizione_pesata, leva), self.p.prezzo_iniziale)
        
        # Attrito di Ingresso (Metà spread + commissioni)
        costo_ingresso_pct = (self.p.bid_ask_spread / 2) + self.p.commissioni_pct
        capitale = (n_turbo * self.p.prezzo_iniziale) * (1 + costo_ingresso_pct)
        
        totale_copertura = self.p.portafoglio + capitale
        
        var_indice = self.safe_divide(self.p.valore_ipotetico - self.p.valore_iniziale, self.p.valore_iniziale)
        var_ptf = var_indice * self.p.beta
        valore_ptf_simulato = self.p.portafoglio * (1 + var_ptf)
        
        # Attrito di Uscita (Metà spread + commissioni + slippage di panico)
        costo_uscita_pct = (self.p.bid_ask_spread / 2) + self.p.commissioni_pct + self.p.stress_slippage
        valore_copertura_lorda = prezzo_futuro * n_turbo
        valore_copertura_netta = valore_copertura_lorda * (1 - costo_uscita_pct)
        
        totale_simulato = valore_ptf_simulato + valore_copertura_netta
        percentuale = self.safe_divide(totale_simulato - totale_copertura, totale_copertura)

        pl_portafoglio = valore_ptf_simulato - self.p.portafoglio
        pl_turbo_netto = valore_copertura_netta - capitale
        pl_turbo_lordo = valore_copertura_lorda - (n_turbo * self.p.prezzo_iniziale) # Illusione senza costi
        
        hedge_ratio_reale = self.safe_divide(pl_turbo_netto, abs(pl_portafoglio)) if pl_portafoglio < 0 else 0.0
        hedge_ratio_commerciale = self.safe_divide(pl_turbo_lordo, abs(pl_portafoglio)) if pl_portafoglio < 0 else 0.0

        return {
            "fair_value": fair_value,
            "premio": premio,
            "leva": leva,
            "barriera": barriera,
            "prezzo_futuro": prezzo_futuro,
            "n_turbo": n_turbo,
            "capitale": capitale,
            "totale_copertura": totale_copertura,
            "valore_ptf_simulato": valore_ptf_simulato,
            "valore_copertura_simulata": valore_copertura_netta,
            "totale_simulato": totale_simulato,
            "percentuale": percentuale,
            "pl_portafoglio": pl_portafoglio,
            "pl_turbo_netto": pl_turbo_netto,
            "pl_turbo_lordo": pl_turbo_lordo,
            "hedge_ratio_reale": hedge_ratio_reale,
            "hedge_ratio_commerciale": hedge_ratio_commerciale
        }
