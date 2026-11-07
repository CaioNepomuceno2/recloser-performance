"""Desempenho observado em 2026 (jan-jul): quem abriu o circuito e sinal de falta de seletividade."""
import json
import logging

import numpy as np
import pandas as pd
from scipy.stats import binomtest, spearmanr

from recloser import analise, config, dados

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
cfg, _ = config.argumentos(__doc__)
OUT = config.pasta_relatorios(cfg)
OUT.mkdir(parents=True, exist_ok=True)
config.exigir_porta(cfg, cfg["ano_atual"])
e = analise.preparar(cfg, cfg["ano_atual"], cfg["confiabilidade"]["anos_taxa"])
m, al = e.modelo, e.alimentadores.copy()
al["ctmt"] = al.ctmt.astype("string")

i26 = dados.interrupcoes_2026(cfg["interrupcoes"])
i26["ctmt"] = i26.ctmt.astype("string")
cobertura = float(i26.ctmt.isin(al.ctmt).mean())

# ---------------------------------------------------------------- por tipo de elemento
el = (i26.groupby("elemento")
      .agg(interrupcoes=("chi", "size"), uc_por_evento_mediana=("uc_afetadas", "median"),
           uc_por_evento_media=("uc_afetadas", "mean"), duracao_mediana_h=("duracao_h", "median"),
           chi=("chi", "sum"))
      .sort_values("interrupcoes", ascending=False))
el["frac_chi"] = el.chi / el.chi.sum()
el.reset_index().to_csv(OUT / "desempenho_elemento_2026.csv", index=False)

# ---------------------------------------------------------------- seletividade (sinal de suspeita)
# fração esperada de faltas eliminadas pelo disjuntor de saída, entre as eliminadas por saída ou religador:
# taxa de faltas fora de ramais com fusível na zona da saída / taxa total fora de ramais com fusível
lam = m.lam_m * m.comp
eff = np.where(m.sob_fus, 0.0, lam)
zona_saida = np.zeros(len(m.nos), bool)
for ini, fim in m.fatias.values():
    zona_saida[ini:fim] = m.disp_rel[ini:fim] == ini
df = pd.DataFrame({"ctmt": m.nos.ctmt.astype("string"), "eff": eff, "saida": eff * zona_saida})
esp = df.groupby("ctmt")[["eff", "saida"]].sum()
esp["frac_disjuntor_esperada"] = esp.saida / esp.eff
esp["religadores_linha"] = m.nos[m.nos.classe == "religador"].groupby(m.nos.ctmt.astype("string")).size()
esp["religadores_linha"] = esp.religadores_linha.fillna(0)
obs = i26.pivot_table(index="ctmt", columns="elemento", values="chi", aggfunc="size").fillna(0)
d = esp.join(obs[["DISJUNTOR", "RELIGADOR"]], how="inner").join(al.set_index("ctmt")[["NOME", "saida_por_religador"]])
elegivel = (~d.saida_por_religador) & (d.religadores_linha > 0) & ((d.DISJUNTOR + d.RELIGADOR) >= 10)
d = d[elegivel].copy()
d["frac_disjuntor_observada"] = d.DISJUNTOR / (d.DISJUNTOR + d.RELIGADOR)
d["p_valor"] = [binomtest(int(a), int(a + b), float(np.clip(p, 1e-3, 1 - 1e-3)), alternative="greater").pvalue
                for a, b, p in zip(d.DISJUNTOR, d.RELIGADOR, d.frac_disjuntor_esperada)]
# Benjamini-Hochberg
ordem = d.p_valor.rank(method="first")
d["p_ajustado"] = (d.p_valor * len(d) / ordem).clip(upper=1.0)
d["p_ajustado"] = d.sort_values("p_valor").p_ajustado[::-1].cummin()[::-1].reindex(d.index)
d["suspeita"] = d.p_ajustado < 0.05
d.reset_index().sort_values("p_valor").to_csv(OUT / "seletividade_2026.csv", index=False)

# ---------------------------------------------------------------- CHI esperado do modelo x CHI observado em 2026
chi26 = i26.groupby("ctmt").chi.sum()
cmp_ = al.set_index("ctmt")[["chi_modelo_calibrado", "ci_modelo"]].join(chi26.rename("chi_2026"), how="inner")
cmp_ = cmp_[cmp_.chi_modelo_calibrado.notna()]
resumo = {
    "cobertura_vinculo_alimentador": cobertura,
    "interrupcoes_mt_2026": len(i26),
    "elementos": el.reset_index().to_dict("records"),
    "seletividade": {
        "alimentadores_elegiveis": len(d),
        "criterio": "saída por disjuntor, ao menos 1 religador de linha e 10 aberturas de disjuntor+religador",
        "frac_disjuntor_esperada_mediana": float(d.frac_disjuntor_esperada.median()),
        "frac_disjuntor_observada_mediana": float(d.frac_disjuntor_observada.median()),
        "alimentadores_com_suspeita": int(d.suspeita.sum()),
        "chi_2026_nos_suspeitos": float(chi26.reindex(d[d.suspeita].index).sum()),
    },
    "modelo_vs_2026": {"alimentadores": len(cmp_),
                       "spearman_chi_modelo_vs_chi_2026": float(spearmanr(cmp_.chi_modelo_calibrado, cmp_.chi_2026).statistic),
                       "spearman_ci_topologico_vs_chi_2026": float(spearmanr(cmp_.ci_modelo, cmp_.chi_2026).statistic)},
}
(OUT / "desempenho_2026.json").write_text(json.dumps(resumo, indent=2, ensure_ascii=False, default=float))
logging.info(json.dumps({k: v for k, v in resumo.items() if k != "elementos"}, indent=1, ensure_ascii=False))
print(el.round(2).to_string())
