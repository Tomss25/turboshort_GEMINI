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
    spread: float = 0.0056

class DeterministicTurboCalculator:
    def __init__(self, p: TurboParameters):
        self.p = p

    def safe_divide(self, numerator: float, denominator: float) -> float:
        return 0.0 if denominator == 0 else numerator / denominator

    def calculate_all(self) -> Dict[str, Any]:
        # 1. Caratteristiche Turbo
        fair_value = self.safe_divide((self.p.strike - self.p.valore_iniziale) * self.p.multiplo, self.p.cambio)
        fair_value = max(0.0, fair_value)
        premio = max(0.0, self.p.prezzo_iniziale - fair_value)
        
        denominatore_leva = self.safe_divide(self.p.prezzo_iniziale * self.p.cambio, self.p.multiplo)
        leva = self.safe_divide(self.p.valore_iniziale, denominatore_leva)

        # 2. Barriera e Prezzo Futuro
        tasso_netto = 1 - self.p.euribor + self.p.spread
        barriera = self.p.strike * math.pow(tasso_netto, self.safe_divide(self.p.giorni, 360))
        
        valore_intrinseco_futuro = self.safe_divide((barriera - self.p.valore_ipotetico) * self.p.multiplo, self.p.cambio)
        prezzo_futuro = max(0.0, valore_intrinseco_futuro + premio)

        # 3. Dimensionamento pesato per il Beta
        esposizione_pesata = self.p.portafoglio * self.p.beta
        n_turbo = self.safe_divide(self.safe_divide(esposizione_pesata, leva), self.p.prezzo_iniziale)
        capitale = n_turbo * self.p.prezzo_iniziale
        totale_copertura = self.p.portafoglio + capitale
        
        # Simulazione Ptf pesata col Beta
        var_indice = self.safe_divide(self.p.valore_ipotetico - self.p.valore_iniziale, self.p.valore_iniziale)
        var_ptf = var_indice * self.p.beta
        valore_ptf_simulato = self.p.portafoglio * (1 + var_ptf)
        
        valore_copertura = prezzo_futuro * n_turbo
        totale_simulato = valore_ptf_simulato + valore_copertura
        percentuale = self.safe_divide(totale_simulato - totale_copertura, totale_copertura)

        # 4. Hedge Ratio Reale
        pl_portafoglio = valore_ptf_simulato - self.p.portafoglio
        pl_turbo = valore_copertura - capitale
        hedge_ratio = self.safe_divide(pl_turbo, abs(pl_portafoglio)) if pl_portafoglio < 0 else 0.0

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
            "valore_copertura_simulata": valore_copertura,
            "totale_simulato": totale_simulato,
            "percentuale": percentuale,
            "pl_portafoglio": pl_portafoglio,
            "pl_turbo": pl_turbo,
            "hedge_ratio": hedge_ratio
        }