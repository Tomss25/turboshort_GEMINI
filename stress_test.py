import pandas as pd
import copy
from calculator import TurboParameters, DeterministicTurboCalculator

def run_stress_test(base_params: TurboParameters, n_turbo_custom: float = None) -> pd.DataFrame:
    # Scenari con Slippage Dinamico (Var. Indice, Slippage Pct Aggiuntivo)
    scenarios = [
        ("Correzione Normale", -0.10, 0.01), # 1% extra spread
        ("Bear Market", -0.20, 0.03),        # 3% extra spread
        ("Flash Crash", -0.25, 0.06),        # 6% extra spread
        ("Black Swan", -0.40, 0.15)          # 15% illiquidità totale
    ]
    
    results = []
    base_calc = DeterministicTurboCalculator(base_params).calculate_all()
    barriera = base_calc['barriera']
    
    near_ko_var = (barriera / base_params.valore_iniziale) - 1.001
    scenarios.insert(0, ("Near K.O. (Barriera -0.1%)", near_ko_var, 0.02))

    for name, var, slippage in scenarios:
        spot_scenario = base_params.valore_iniziale * (1 + var)
        p_scen = copy.deepcopy(base_params)
        p_scen.valore_ipotetico = spot_scenario
        
        # INIEZIONE ILLIQUIDITA'
        p_scen.stress_slippage = slippage
        
        res = DeterministicTurboCalculator(p_scen).calculate_all()
        
        # --- FIX: Allineamento con l'override manuale di app.py ---
        if n_turbo_custom is not None:
            res['n_turbo'] = float(n_turbo_custom)
            costo_unitario_acquisto = p_scen.prezzo_iniziale * (1 + p_scen.bid_ask_spread/2 + p_scen.commissioni_pct)
            valore_unitario_vendita = res['prezzo_futuro'] * (1 - (p_scen.bid_ask_spread/2 + p_scen.commissioni_pct + slippage))
            
            res['capitale'] = p_scen.portafoglio + (res['n_turbo'] * costo_unitario_acquisto)
            res['valore_copertura_simulata'] = res['n_turbo'] * valore_unitario_vendita
            
            perdita_ptf = p_scen.portafoglio - res['valore_ptf_simulato']
            if perdita_ptf > 0:
                gain_netto = res['valore_copertura_simulata'] - (res['n_turbo'] * costo_unitario_acquisto)
                res['hedge_ratio_reale'] = gain_netto / perdita_ptf
            else:
                res['hedge_ratio_reale'] = 0.0

        is_ko = spot_scenario >= barriera
        
        # Ricalcolo coerente del P&L Netto del Turbo
        costo_reale_investito = res['n_turbo'] * p_scen.prezzo_iniziale * (1 + p_scen.bid_ask_spread/2 + p_scen.commissioni_pct)
        
        if is_ko:
            # Se va in KO, la perdita è esattamente il capitale investito nel derivato
            res['pl_turbo_netto'] = -costo_reale_investito 
            res['hedge_ratio_reale'] = 0.0
        else:
            res['pl_turbo_netto'] = res['valore_copertura_simulata'] - costo_reale_investito
            
        pl_netto = res['pl_portafoglio'] + res['pl_turbo_netto']
        
        results.append({
            "Scenario": name,
            "Var. Indice": f"{var*100:.1f}%",
            "Penalty Illiquidità": f"-{slippage*100:.0f}%",
            "P&L Ptf": f"€ {res['pl_portafoglio']:,.0f}",
            "P&L Turbo": f"€ {res['pl_turbo_netto']:,.0f}",
            "P&L Netto": f"€ {pl_netto:,.0f}",
            "Hedge Ratio": f"{res['hedge_ratio_reale']*100:.1f}%",
            "Status": "❌ K.O." if is_ko else "✅ Attivo"
        })
        
    return pd.DataFrame(results)
