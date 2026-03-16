import pandas as pd
import copy
from calculator import TurboParameters, DeterministicTurboCalculator

def run_stress_test(base_params: TurboParameters) -> pd.DataFrame:
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
        
        is_ko = spot_scenario >= barriera
        if is_ko:
            res['pl_turbo_netto'] = -res['capitale'] 
            res['hedge_ratio_reale'] = 0.0
            
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
