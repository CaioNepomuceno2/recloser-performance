"""Montagem do modelo calibrado de um ano e indicadores de diagnóstico."""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
from scipy.stats import spearmanr

from recloser import config, dados, topologia
from recloser.zonas import Modelo


@dataclass
class Estudo:
    ano: int
    modelo: Modelo
    alimentadores: pd.DataFrame     # um registro por circuito, com histórico e calibração
    chi_por_ci: pd.Series           # CHI por unidade de CI do modelo, por circuito
    saida: pd.DataFrame             # religadores de saída (cod_id, ctmt)


def preparar(cfg: dict, ano: int, anos_taxa: list[int], tau: float | None = None) -> Estudo:
    tau = cfg["confiabilidade"]["tau"] if tau is None else tau
    proc = config.pasta_processada(cfg)
    nos = pd.read_parquet(proc / f"nos_{ano}.parquet")
    al = pd.read_parquet(proc / f"alimentadores_{ano}.parquet")
    hist = dados.historico_alimentador(cfg["falhas"], al, anos_taxa, cfg.get("alimentador", {}).get("largura_nome", 0))
    km = nos.groupby("ctmt").comp_m.sum() / 1000
    taxa_m = (hist.falhas_ano / (km.reindex(hist.index) * 1000)).replace([np.inf, -np.inf], np.nan).dropna()

    # religadores de saída: perto do PAC_INI e sem clientes a jusante na árvore
    perto = topologia.religadores_perto_da_saida(config.pasta_ano(cfg, ano), cfg["tip_unid"])
    m0 = Modelo.de_nos(nos, taxa_m, tau)
    rel = m0.nos.classe == "religador"
    sem_uc = pd.Series(m0.n_sub == 0, index=m0.nos.index)
    eh_saida = rel & sem_uc & m0.nos.cod_id.astype("string").isin(perto.cod_id)
    nos2 = m0.nos.copy()
    nos2.loc[eh_saida, "classe"] = "religador_saida"
    nos2.loc[rel & sem_uc & ~eh_saida, "classe"] = "religador_sem_clientes"
    m = Modelo.de_nos(nos2, taxa_m, tau)

    ci = pd.Series({m.nos.ctmt.iat[i]: m.ci_esperado(i, f) for i, f in m.fatias.values()}, name="ci_modelo")
    t = al.set_index("COD_ID").join(km.rename("km_mt")).join(hist).join(ci)
    lim = cfg["confiabilidade"]
    razao = (t.ci_ano / t.ci_modelo).clip(lim["fator_calibracao_min"], lim["fator_calibracao_max"])
    duracao = t.chi_ano / t.ci_ano
    chi_por_ci = (razao * duracao).replace([np.inf, -np.inf], np.nan)
    chi_por_ci = chi_por_ci.fillna(chi_por_ci.median())
    t["chi_por_ci"] = chi_por_ci
    t["chi_modelo_calibrado"] = t.ci_modelo * chi_por_ci
    saida = nos2[eh_saida][["cod_id", "ctmt"]]
    t["saida_por_religador"] = t.index.isin(saida.ctmt)
    return Estudo(ano=ano, modelo=m, alimentadores=t.reset_index().rename(columns={"COD_ID": "ctmt"}),
                  chi_por_ci=chi_por_ci, saida=saida)


def validacao_modelo(t: pd.DataFrame) -> dict:
    ok = t.ci_ano.notna() & t.ci_modelo.notna() & (t.ci_modelo > 0)
    d = t[ok]
    return {
        "alimentadores": len(d),
        "spearman_ci_modelo_vs_observado": float(spearmanr(d.ci_ano, d.ci_modelo).statistic),
        "razao_ci_observado_sobre_modelo_mediana": float((d.ci_ano / d.ci_modelo).median()),
        "ci_modelo_total": float(d.ci_modelo.sum()),
        "ci_observado_total": float(d.ci_ano.sum()),
    }
