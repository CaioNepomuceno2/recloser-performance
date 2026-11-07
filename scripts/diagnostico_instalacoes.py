"""Diagnóstico das "instalações novas" que o backtest infere da diferença entre dois cadastros.

O backtest chama de instalação nova o religador fechado do cadastro de ``ano_atual`` cujo ``COD_ID`` não existia em
``ano_backtest`` e que não tem religador de ``ano_backtest`` a menos de ``raio_novo_m``. Em MS o cadastro mistura
instalação e remanejamento (``automation-impact``: ganhos brutos de religadores bem maiores que o saldo). Este script
mede o que dá para medir sobre isso, sem forçar nenhum pareamento e sem calcular resultado do estudo:

* quanto do cadastro mudou de um ano para o outro (chaves, telecomando, ``COD_ID`` reaproveitado);
* a estabilidade da posição dos religadores que mantêm o ``COD_ID`` (de onde vem o raio de 100 m);
* quantos "novos" têm ``DAT_CON`` no período, antes dele, ou ficam a menos de 100 m de um religador antigo;
* quantos religadores do cadastro antigo sumiram (proxy de remanejamento ou retirada).

Saída: ``<reports>/diagnostico/instalacoes.json``.
Uso: ``python scripts/diagnostico_instalacoes.py --config configs/params_ems.yaml``
"""

import json
import logging

import numpy as np
import pandas as pd
from pyproj import Transformer
from scipy.spatial import cKDTree

from recloser import config, topologia

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
cfg, _ = config.argumentos(__doc__)
OUT = config.pasta_relatorios(cfg) / "diagnostico"
OUT.mkdir(parents=True, exist_ok=True)
a0, a1 = cfg["ano_backtest"], cfg["ano_atual"]
raio_novo = cfg["backtest"]["raio_novo_m"]
tr = Transformer.from_crs(4326, config.crs_pac(cfg), always_xy=True)
cols = ["COD_ID", "CTMT", "TIP_UNID", "P_N_OPE", "TLCD", "DAT_CON", "lon", "lat"]


def ler(ano: int) -> pd.DataFrame:
    u = pd.read_parquet(config.pasta_ano(cfg, ano) / "UNSEMT.parquet", columns=cols)
    u["COD_ID"] = u.COD_ID.astype("string").str.strip()
    u["classe"] = topologia.classificar_tip_unid(u.TIP_UNID, cfg["tip_unid"])
    u["aberta"] = u.P_N_OPE.astype(str).str.strip() == "A"
    u["x"], u["y"] = tr.transform(u.lon.to_numpy(), u.lat.to_numpy())
    u["ano_dat_con"] = pd.to_numeric(u.DAT_CON.astype("string").str[-4:], errors="coerce")
    return u


u0, u1 = ler(a0), ler(a1)
r0, r1 = u0[u0.classe == "religador"], u1[u1.classe == "religador"]
r1f = r1[~r1.aberta]
res: dict = {"snapshots": [a0, a1], "raio_novo_m": raio_novo}

# ---------------------------------------------------------------- o salto do cadastro
res["cadastro"] = {
    "unsemt": {str(a0): len(u0), str(a1): len(u1)},
    "classes": {str(a): {k: int(v) for k, v in u.classe.value_counts().items()} for a, u in [(a0, u0), (a1, u1)]},
    "religadores": {str(a0): len(r0), str(a1): len(r1), f"{a1}_fechados": len(r1f)},
    "frac_religadores_telecomandados": {str(a0): float((r0.TLCD == 1).mean()), str(a1): float((r1.TLCD == 1).mean())},
    "frac_cod_id_so_digitos": {str(a): float(u.COD_ID.str.fullmatch(r"\d+").mean()) for a, u in [(a0, u0), (a1, u1)]},
    "frac_cod_id_do_ano_atual_que_ja_existia": float(u1.COD_ID.isin(u0.COD_ID).mean()),
    "frac_cod_id_do_ano_base_que_continua": float(u0.COD_ID.isin(u1.COD_ID).mean()),
}

# ---------------------------------------------------------------- COD_ID estável: onde está o religador nos dois anos?
estaveis = r1f.merge(r0[["COD_ID", "x", "y"]], on="COD_ID", suffixes=("", "_0"))
desloc = np.hypot(estaveis.x - estaveis.x_0, estaveis.y - estaveis.y_0)
res["cod_id_estavel"] = {
    "n": len(estaveis),
    "deslocamento_mediana_m": float(desloc.median()),
    "p99_m": float(desloc.quantile(0.99)),
    "frac_ate_1m": float((desloc <= 1).mean()),
    "frac_ate_50m": float((desloc <= 50).mean()),
    "frac_ate_100m": float((desloc <= raio_novo).mean()),
    "frac_acima_de_100m": float((desloc > raio_novo).mean()),
}

# ---------------------------------------------------------------- a regra do backtest e suas variantes
dist_antigo, _ = cKDTree(np.c_[r0.x, r0.y]).query(np.c_[r1f.x, r1f.y])
r1f = r1f.assign(cod_novo=~r1f.COD_ID.isin(r0.COD_ID), dist_antigo_m=dist_antigo)
novos = r1f[r1f.cod_novo & (r1f.dist_antigo_m > raio_novo)]
cod_novo_perto = r1f[r1f.cod_novo & (r1f.dist_antigo_m <= raio_novo)]
anos_conf = cfg["backtest"].get("anos_data_confirmada", [a0, a1])
dat = novos.ano_dat_con
res["regra_do_backtest"] = {
    "religadores_fechados_no_ano_atual": len(r1f),
    "cod_id_novo": int(r1f.cod_novo.sum()),
    "cod_id_novo_com_religador_antigo_a_menos_de_100m": len(cod_novo_perto),
    "novos_pela_regra": len(novos),
    "novos_dat_con_por_ano": {str(int(k)): int(v) for k, v in dat.value_counts().sort_index().tail(8).items()},
    "novos_dat_con_nula": int(dat.isna().sum()),
    f"novos_dat_con_em_{'_ou_'.join(map(str, anos_conf))}": int(dat.isin(anos_conf).sum()),
    "novos_dat_con_antes_do_ano_base": int((dat < min(anos_conf)).sum()),
    "frac_novos_dat_con_antes_do_ano_base": float((dat < min(anos_conf)).mean()),
    "cod_id_novo_perto_dat_con_em_periodo": int(cod_novo_perto.ano_dat_con.isin(anos_conf).sum()),
}

# ---------------------------------------------------------------- religadores que sumiram (remanejamento ou retirada)
d_novo, _ = cKDTree(np.c_[r1.x, r1.y]).query(np.c_[r0.x, r0.y])
sumiram = r0[~r0.COD_ID.isin(r1.COD_ID) & (d_novo > raio_novo)]
sumiram_cod = r0[~r0.COD_ID.isin(r1.COD_ID)]
circ_sumiu = set(sumiram.CTMT.dropna())
res["religadores_que_sumiram"] = {
    "cod_id_ausente_no_ano_atual": len(sumiram_cod),
    "cod_id_ausente_e_sem_religador_a_menos_de_100m": len(sumiram),
    "circuitos_com_religador_que_sumiu": len(circ_sumiu),
    "novos_em_circuitos_onde_sumiu_religador": int(novos.CTMT.isin(circ_sumiu).sum()),
    "frac_novos_em_circuitos_onde_sumiu_religador": float(novos.CTMT.isin(circ_sumiu).mean()),
    "saldo_religadores": len(r1) - len(r0),
    "novos_menos_sumidos": len(novos) - len(sumiram),
}
(OUT / "instalacoes.json").write_text(json.dumps(res, indent=2, ensure_ascii=False, default=float), encoding="utf-8")
logging.info(json.dumps(res, indent=1, ensure_ascii=False, default=float))
