"""Diagnóstico da topologia reconstruída: cobertura antes e depois do reparo, causa dos clientes não alcançados e consistência.

Roda depois de ``01_topologia.py``. Não é a porta de qualidade (essa é ``frac_uc_alcancadas`` de
``qualidade_topologia.json``); é o que explica o número: quanto do que se ganha vem do reparo de lacunas, de onde vêm os
clientes que a árvore não alcança e se o circuito em que cada trafo cai na árvore é o do cadastro (``UNTRMT.CTMT``).

Saída: ``<reports>/diagnostico/topologia_<ano>.json``.
Uso: ``python scripts/diagnostico_topologia.py --config configs/params_ems.yaml``
"""

import json
import logging

import numpy as np
import pandas as pd
from scipy.spatial import cKDTree

from recloser import config, topologia

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
cfg, _ = config.argumentos(__doc__)
OUT = config.pasta_relatorios(cfg) / "diagnostico"
OUT.mkdir(parents=True, exist_ok=True)
proc = config.pasta_processada(cfg)
max_gap = cfg["topologia"]["max_gap_m"]
qual = json.loads((config.pasta_relatorios(cfg) / "qualidade_topologia.json").read_text(encoding="utf-8"))

for ano in sorted({cfg["ano_atual"], cfg["ano_backtest"]}):
    d = config.pasta_ano(cfg, ano)
    res: dict = {"ano": ano, "max_gap_m": max_gap}
    # ---------------------------------------------------------------- antes x depois do reparo de lacunas
    sem_reparo = topologia.construir(d, cfg["tip_unid"], max_gap_m=-1.0).qualidade
    res["antes_do_reparo"] = {
        k: sem_reparo[k] for k in ("uc_total", "uc_alcancadas", "frac_uc_alcancadas", "componentes_religados")
    }
    depois = qual[str(ano)]
    res["depois_do_reparo"] = {
        k: depois[k]
        for k in (
            "uc_total",
            "uc_alcancadas",
            "frac_uc_alcancadas",
            "componentes_religados",
            "lacuna_mediana_m",
            "lacuna_p90_m",
            "alimentadores_sem_saida_no_grafo",
        )
    }

    # ---------------------------------------------------------------- quem não foi alcançado, e por quê
    nos = pd.read_parquet(proc / f"nos_{ano}.parquet", columns=["pac", "ctmt", "x", "y", "uc"])
    al = pd.read_parquet(proc / f"alimentadores_{ano}.parquet", columns=["COD_ID", "NOME"])
    tr = pd.read_parquet(d / "UNTRMT.parquet", columns=["COD_ID", "PAC_1", "CTMT"])
    ucbt = pd.read_parquet(d / "UCBT_tab_agg.parquet")
    for df, cols in [(tr, ["COD_ID", "PAC_1", "CTMT"]), (ucbt, ["UNI_TR_MT"]), (nos, ["pac", "ctmt"])]:
        for c in cols:
            df[c] = df[c].astype("string").str.strip()
    tr["n_uc"] = tr.COD_ID.map(ucbt.groupby("UNI_TR_MT").n_uc.sum()).fillna(0)
    tr["alcancado"] = tr.PAC_1.isin(set(nos.pac))
    # consistência: o circuito da árvore é o do cadastro?
    no_ctmt = nos.drop_duplicates("pac").set_index("pac").ctmt
    alc = tr[tr.alcancado & (tr.n_uc > 0)].copy()
    alc["ctmt_arvore"] = alc.PAC_1.map(no_ctmt)
    igual = (alc.ctmt_arvore == alc.CTMT).fillna(False).to_numpy(bool)
    res["consistencia_de_circuito"] = {
        "trafos_alcancados_com_clientes": len(alc),
        "frac_clientes_no_mesmo_circuito_do_cadastro": float(alc.n_uc.to_numpy()[igual].sum() / alc.n_uc.sum()),
    }
    perdidos = tr[~tr.alcancado & (tr.n_uc > 0)].copy()
    x, y = topologia.pac_xy(perdidos.PAC_1)
    perdidos["tem_coordenada"] = np.isfinite(x)
    perdidos["gap_m"] = np.nan
    alcx, alcy = topologia.pac_xy(pd.Series(nos.pac.unique()))
    nos_u = nos.drop_duplicates("pac").assign(x=alcx, y=alcy).dropna(subset=["x"])
    arv = {c: cKDTree(np.c_[g.x, g.y]) for c, g in nos_u.groupby("ctmt")}
    for ct, g in perdidos[perdidos.tem_coordenada].groupby("CTMT"):
        if ct in arv:
            idx = g.index
            dist, _ = arv[ct].query(np.c_[x[perdidos.index.get_indexer(idx)], y[perdidos.index.get_indexer(idx)]])
            perdidos.loc[idx, "gap_m"] = dist
    sem_coord = ~perdidos.tem_coordenada
    sem_circ = perdidos.tem_coordenada & perdidos.gap_m.isna()
    longe = perdidos.gap_m > max_gap
    perto = perdidos.gap_m <= max_gap
    uc = perdidos.n_uc
    res["clientes_nao_alcancados"] = {
        "total": float(uc.sum()),
        "trafos": len(perdidos),
        "PAC_sem_coordenada": float(uc[sem_coord].sum()),
        "circuito_sem_nenhum_no_alcancado": float(uc[sem_circ].sum()),
        "lacuna_acima_do_limite": float(uc[longe].sum()),
        "lacuna_dentro_do_limite_mas_sem_ligacao": float(uc[perto].sum()),
        "lacuna_mediana_m": float(perdidos.gap_m.median()) if perdidos.gap_m.notna().any() else None,
        "lacuna_p90_m": float(perdidos.gap_m.quantile(0.9)) if perdidos.gap_m.notna().any() else None,
    }
    top = perdidos.groupby("CTMT").n_uc.sum().sort_values(ascending=False).head(10)
    nome = al.assign(COD_ID=al.COD_ID.astype("string").str.strip()).set_index("COD_ID").NOME
    res["circuitos_com_mais_perda"] = [
        {"ctmt": k, "nome": str(nome.get(k, "")), "clientes_nao_alcancados": float(v)} for k, v in top.items()
    ]
    (OUT / f"topologia_{ano}.json").write_text(json.dumps(res, indent=2, ensure_ascii=False, default=float), encoding="utf-8")
    logging.info(
        "%s: %s",
        ano,
        json.dumps({k: res[k] for k in ("antes_do_reparo", "depois_do_reparo", "clientes_nao_alcancados")}, default=float),
    )
