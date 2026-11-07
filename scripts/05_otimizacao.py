"""Onde instalar os próximos religadores (rede de 2025): guloso x regras simples, sensibilidade e lista."""
import copy
import json
import logging

import numpy as np
import pandas as pd
from pyproj import Transformer

from recloser import analise, config, dados
from recloser import otimizacao as O

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
cfg, _ = config.argumentos(__doc__)
OUT = config.pasta_relatorios(cfg)
OUT.mkdir(parents=True, exist_ok=True)
oc, vc = cfg["otimizacao"], cfg["valor"]
ks, kmax = oc["ks"], max(oc["ks"])
val = dados.valoracao(cfg["valor_json"], exigir_origem=bool(cfg.get("exigir_origem_efeito")))
ano = cfg["ano_atual"]
config.exigir_porta(cfg, ano)
e = analise.preparar(cfg, ano, cfg["confiabilidade"]["anos_taxa"])
base = copy.deepcopy(e.modelo)
chi_atual = O.chi_total(base, e.chi_por_ci)


def valorar(chi):
    rs_social = chi * val["rs_por_chi_social"]
    rs_comp = chi * val["frac_chi_regulatorio"] * val["rs_por_chi_compensacao"]
    return {"dec_min": chi / val["uc_total"] * 60, "rs_ano_social": rs_social, "rs_ano_compensacao": rs_comp}


anuidade = (1 - (1 + vc["taxa_desconto"]) ** -vc["vida_anos"]) / vc["taxa_desconto"]

# ---------------------------------------------------------------- guloso
esc = O.guloso(copy.deepcopy(base), e.chi_por_ci, kmax, oc["min_clientes"], oc["max_religadores_em_serie"])
esc["chi_acumulado"] = esc.chi_evitado_ano.cumsum()
curva = [{"k": k, "metodo": "modelo (guloso)", "chi_evitado_ano": float(esc.chi_acumulado.iloc[k - 1])} for k in ks]

# ---------------------------------------------------------------- regras simples
for crit in ["extensao", "clientes"]:
    r = O.regra_divisao(copy.deepcopy(base), e.chi_por_ci, ks, crit, oc["min_clientes"], oc["max_religadores_em_serie"])
    curva += [{"k": k, "metodo": crit, "chi_evitado_ano": float(v)} for k, v in r.items()]
    logging.info("%s: %s", crit, r)
rng = np.random.default_rng(42)
sorteios = [O.regra_divisao(copy.deepcopy(base), e.chi_por_ci, ks, "aleatorio", oc["min_clientes"],
                            oc["max_religadores_em_serie"], rng) for _ in range(oc["sorteios_aleatorio"])]
for k in ks:
    curva.append({"k": k, "metodo": "aleatorio", "chi_evitado_ano": float(np.mean([s[k] for s in sorteios]))})
curva = pd.DataFrame(curva)
for c, v in valorar(curva.chi_evitado_ano).items():
    curva[c] = v
curva["investimento_rs"] = curva.k * vc["custo_religador_rs"]
curva["vpl_social_rs"] = curva.rs_ano_social * anuidade - curva.investimento_rs
curva["vpl_compensacao_rs"] = curva.rs_ano_compensacao * anuidade - curva.investimento_rs
dados.rotular_tabela(curva, val).to_csv(OUT / "curva_k.csv", index=False)

# ---------------------------------------------------------------- sensibilidade (k = 100 por padrão)
KS = oc.get("k_sensibilidade", 100)
sens = []
for tau in [0.3, 0.5, 0.7]:
    es = analise.preparar(cfg, ano, cfg["confiabilidade"]["anos_taxa"], tau=tau)
    g = O.guloso(copy.deepcopy(es.modelo), es.chi_por_ci, KS, oc["min_clientes"], oc["max_religadores_em_serie"])
    r = O.regra_divisao(copy.deepcopy(es.modelo), es.chi_por_ci, [KS], "extensao", oc["min_clientes"],
                        oc["max_religadores_em_serie"])
    sens.append({"cenario": f"tau={tau}", "guloso_chi": float(g.chi_evitado_ano.sum()), "extensao_chi": r[KS],
                 "frac_troca_fusivel": float((g.tipo == "troca_de_fusivel").mean())})
uniforme = pd.Series(float(e.chi_por_ci.median()), index=e.chi_por_ci.index)
g = O.guloso(copy.deepcopy(base), uniforme, KS, oc["min_clientes"], oc["max_religadores_em_serie"])
r = O.regra_divisao(copy.deepcopy(base), uniforme, [KS], "extensao", oc["min_clientes"], oc["max_religadores_em_serie"])
sens.append({"cenario": "sem calibração por alimentador", "guloso_chi": float(g.chi_evitado_ano.sum()),
             "extensao_chi": r[KS], "frac_troca_fusivel": float((g.tipo == "troca_de_fusivel").mean())})
for mc in [25, 100]:
    g = O.guloso(copy.deepcopy(base), e.chi_por_ci, KS, mc, oc["max_religadores_em_serie"])
    r = O.regra_divisao(copy.deepcopy(base), e.chi_por_ci, [KS], "extensao", mc, oc["max_religadores_em_serie"])
    sens.append({"cenario": f"min_clientes={mc}", "guloso_chi": float(g.chi_evitado_ano.sum()), "extensao_chi": r[KS],
                 "frac_troca_fusivel": float((g.tipo == "troca_de_fusivel").mean())})
sens = pd.DataFrame(sens)
sens["razao_guloso_extensao"] = sens.guloso_chi / sens.extensao_chi
dados.rotular_tabela(sens, val).to_csv(OUT / "sensibilidade.csv", index=False)

# ---------------------------------------------------------------- lista priorizada
tr = Transformer.from_crs(config.crs_pac(cfg), 4326, always_xy=True)
esc["lon"], esc["lat"] = tr.transform(esc.x.to_numpy(), esc.y.to_numpy())
al = e.alimentadores.set_index("ctmt")
esc["alimentador"] = esc.ctmt.map(al.NOME)
esc["subestacao_bdgd"] = esc.ctmt.map(al.SUB)
for c, v in valorar(esc.chi_evitado_ano).items():
    esc[c] = v
esc["payback_social_anos"] = vc["custo_religador_rs"] / esc.rs_ano_social
esc["vpl_social_rs"] = esc.rs_ano_social * anuidade - vc["custo_religador_rs"]
lista = esc[["passo", "alimentador", "ctmt", "subestacao_bdgd", "tipo", "uc_jusante", "km_jusante_zona",
             "chi_evitado_ano", "dec_min", "rs_ano_social", "rs_ano_compensacao", "payback_social_anos",
             "vpl_social_rs", "lon", "lat", "pac"]]
dados.rotular_tabela(lista.round(4), val).to_csv(OUT / "lista_priorizada.csv", index=False)

pivot = curva.pivot(index="k", columns="metodo", values="chi_evitado_ano")
resumo = {
    **dados.rotulo(val),
    "ano": ano,
    "chi_esperado_atual_mt": chi_atual,
    "curva": curva.round(2).to_dict("records"),
    "razao_guloso_sobre_extensao": pivot["modelo (guloso)"].div(pivot["extensao"]).round(2).to_dict(),
    "razao_guloso_sobre_aleatorio": pivot["modelo (guloso)"].div(pivot["aleatorio"]).round(2).to_dict(),
    "k100": {"frac_troca_fusivel": float((esc.head(100).tipo == "troca_de_fusivel").mean()),
             "alimentadores": int(esc.head(100).ctmt.nunique()),
             "payback_social_mediano_anos": float(esc.head(100).payback_social_anos.median()),
             "vpl_positivo_frac": float((esc.head(100).vpl_social_rs > 0).mean())},
    "k200_frac_chi_mt": float(esc.chi_acumulado.iloc[-1] / chi_atual),
    "sensibilidade": sens.round(3).to_dict("records"),
    "premissas": {"custo_religador_rs": vc["custo_religador_rs"], "vida_anos": vc["vida_anos"],
                  "taxa_desconto": vc["taxa_desconto"], "tau": cfg["confiabilidade"]["tau"],
                  "rs_por_chi_social": val["rs_por_chi_social"], "uc_total_dec": val["uc_total"]},
}
(OUT / "otimizacao.json").write_text(json.dumps(resumo, indent=2, ensure_ascii=False, default=float))
logging.info(pivot.round(0).to_string())
logging.info(sens.round(2).to_string())
