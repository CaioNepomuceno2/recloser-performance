"""Quanto do ganho de DEC vem de alimentadores no piso da calibração?

O fator de calibração de cada alimentador (CI observado / CI do modelo) é limitado a ``fator_calibracao_min``. Nos
alimentadores em que a razão fica abaixo do piso, o CHI do modelo é maior que o observado e o ganho de cada religador candidato é
superestimado pelo mesmo fator, o que também puxa o guloso para eles. Este script mede, sem mudar nenhum parâmetro:

* a lista priorizada de ``ano_atual`` (100 e 200 primeiros): quantos pontos e que parte do CHI evitado estão em alimentadores
  no piso;
* o backtest (rede de ``ano_backtest``): o mesmo para as instalações reais e para os locais escolhidos pelo modelo;
* os mesmos resultados **sem** os alimentadores no piso (o ganho deles é zerado no guloso e as instalações reais neles saem
  do backtest).

Saída: ``<reports>/diagnostico/calibracao_piso.json``.
Uso: ``python scripts/diagnostico_piso.py --config configs/params_ems.yaml``
"""

import copy
import json
import logging
from dataclasses import replace

import pandas as pd

from recloser import analise, config, dados
from recloser import otimizacao as O
from recloser.backtest import avaliar, religadores_novos

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
cfg, _ = config.argumentos(__doc__)
R = config.pasta_relatorios(cfg)
OUT = R / "diagnostico"
OUT.mkdir(parents=True, exist_ok=True)
piso = cfg["confiabilidade"]["fator_calibracao_min"]
a0, a1 = cfg["ano_backtest"], cfg["ano_atual"]
oc = cfg["otimizacao"]
res: dict = {"piso_da_calibracao": piso}


def no_piso(al: pd.DataFrame) -> set:
    """``ctmt`` dos alimentadores com histórico cuja razão CI observado / CI do modelo fica abaixo do piso."""
    r = al.ci_ano / al.ci_modelo
    return set(al.ctmt.astype(str)[r < piso])


# ---------------------------------------------------------------- posicionamento (rede de ano_atual)
config.exigir_porta(cfg, a1)
al = pd.read_csv(R / "alimentadores.csv", dtype={"ctmt": str}).dropna(subset=["ci_ano"])
chi_obs = al.assign(piso=al.ctmt.isin(no_piso(al))).groupby("piso").chi_ano.sum()
res["alimentadores_com_historico"] = {"n": len(al), "no_piso": len(no_piso(al))}
res["parte_do_chi_observado_nos_alimentadores_no_piso"] = float(chi_obs.get(True, 0.0) / chi_obs.sum())
lista = pd.read_csv(R / "lista_priorizada.csv", dtype={"ctmt": str})
lista["no_piso"] = lista.ctmt.isin(no_piso(al))
res["posicionamento"] = {}
for k in (100, 200):
    t = lista.head(k)
    res["posicionamento"][str(k)] = {
        "pontos_em_alimentadores_no_piso": int(t.no_piso.sum()),
        "frac_dos_pontos": float(t.no_piso.mean()),
        "frac_do_chi_evitado": float(t.chi_evitado_ano[t.no_piso].sum() / t.chi_evitado_ano.sum()),
        "dec_min_total": float(t.dec_min.sum()),
        "dec_min_nos_alimentadores_no_piso": float(t.dec_min[t.no_piso].sum()),
    }

val = dados.valoracao(cfg["valor_json"], exigir_origem=bool(cfg.get("exigir_origem_efeito")))
e1 = analise.preparar(cfg, a1, cfg["confiabilidade"]["anos_taxa"])
pisos1 = no_piso(e1.alimentadores.dropna(subset=["ci_ano"]))
fator1 = e1.chi_por_ci.where(~e1.chi_por_ci.index.astype(str).isin(pisos1), 0.0)
VAZIO = pd.DataFrame({"ctmt": [], "chi_evitado_ano": []})
sem = O.guloso(copy.deepcopy(e1.modelo), fator1, 100, oc["min_clientes"], oc["max_religadores_em_serie"])
if len(sem) == 0:
    sem = VAZIO
res["posicionamento"]["100_sem_alimentadores_no_piso"] = {
    "pontos": len(sem),
    "chi_evitado_ano": float(sem.chi_evitado_ano.sum()),
    "dec_min": float(sem.chi_evitado_ano.sum() / val["uc_total"] * 60),
}

# ---------------------------------------------------------------- backtest (rede de ano_backtest)
config.exigir_porta(cfg, a0)
anos_taxa = [a0 - 2, a0 - 1, a0]
e = analise.preparar(cfg, a0, anos_taxa)
pisos0 = no_piso(e.alimentadores.dropna(subset=["ci_ano"]))
chi0 = (
    e.alimentadores.dropna(subset=["ci_ano"]).assign(piso=lambda d: d.ctmt.astype(str).isin(pisos0)).groupby("piso").chi_ano.sum()
)
inst = pd.read_csv(R / "backtest_instalacoes.csv", dtype={"ctmt": str})
inst["no_piso"] = inst.ctmt.isin(pisos0)
m = copy.deepcopy(e.modelo)
esc = O.guloso(m, e.chi_por_ci, len(inst), oc["min_clientes"], oc["max_religadores_em_serie"])
if len(esc) == 0:
    esc = VAZIO
esc["no_piso"] = esc.ctmt.astype(str).isin(pisos0)
res["backtest"] = {
    "alimentadores_no_piso_na_rede_de_2024": len(pisos0),
    "parte_do_chi_observado_nos_alimentadores_no_piso": float(chi0.get(True, 0.0) / chi0.sum()),
    "instalacoes_reais": {
        "n": len(inst),
        "em_alimentadores_no_piso": int(inst.no_piso.sum()),
        "frac": float(inst.no_piso.mean()),
        "frac_do_chi_evitado": float(inst.ganho_chi_ano[inst.no_piso].sum() / inst.ganho_chi_ano.sum()),
    },
    "locais_do_modelo_mesmo_numero": {
        "n": len(esc),
        "em_alimentadores_no_piso": int(esc.no_piso.sum()),
        "frac": float(esc.no_piso.mean()),
        "frac_do_chi_evitado": float(esc.chi_evitado_ano[esc.no_piso].sum() / esc.chi_evitado_ano.sum()),
        "chi_evitado_ano": float(esc.chi_evitado_ano.sum()),
    },
}
# backtest sem os alimentadores no piso: o guloso não vê ganho neles e as instalações reais neles saem da conta
novos = religadores_novos(cfg, a0, a1)
_, loc = avaliar(cfg, e, novos, val, a0, a1, anos_taxa)
manter = set(loc[~loc.ctmt.astype(str).isin(pisos0)].COD_ID)
e2 = replace(e, chi_por_ci=e.chi_por_ci.where(~e.chi_por_ci.index.astype(str).isin(pisos0), 0.0))
r2, _ = avaliar(cfg, e2, novos[novos.COD_ID.isin(manter)], val, a0, a1, anos_taxa)
res["backtest"]["sem_alimentadores_no_piso"] = {
    "instalacoes_reais_localizadas": r2["localizados_na_rede_anterior"],
    "chi_evitado_ano_instalacoes_reais_modelo": r2["chi_evitado_ano_instalacoes_reais_modelo"],
    "chi_evitado_ano_mesmo_numero_no_modelo": r2["chi_evitado_ano_mesmo_numero_no_modelo"],
    "razao_modelo_sobre_real": r2["razao_modelo_sobre_real"],
}
res.update(dados.rotulo(val))
(OUT / "calibracao_piso.json").write_text(json.dumps(res, indent=2, ensure_ascii=False), encoding="utf-8")
logging.info(json.dumps(res, indent=1, ensure_ascii=False))
