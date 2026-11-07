"""Backtest: a priorização feita com a rede de ``ano_backtest`` aponta onde a distribuidora instalou religadores no ano seguinte?

Também compara o CHI evitado que o modelo atribui a essas instalações com o efeito do ``valor.json`` do projeto
``automation-impact``. Quando o ``valor.json`` traz ``origem_efeito`` (MS: "transportado de MT"), essa comparação é
entre o modelo e o efeito de **outra** distribuidora aplicado à exposição desta, e **não valida o modelo**.
"""

from __future__ import annotations

import copy

import numpy as np
import pandas as pd
from pyproj import Transformer
from scipy.spatial import cKDTree
from sklearn.metrics import roc_auc_score

from recloser import analise, config, dados
from recloser import otimizacao as O
from recloser.analise import Estudo

NOTA_COMPARACAO = (
    "chi_evitado_ano_did_por_religador e fator_did_sobre_modelo usam o efeito do valor.json, cuja origem está em "
    "origem_efeito. Se não for 'medido', a comparação não valida o modelo."
)


def religadores_novos(cfg: dict, a0: int, a1: int) -> pd.DataFrame:
    """Religadores fechados em ``a1`` sem o mesmo ``COD_ID`` e sem religador de ``a0`` a menos de ``raio_novo_m``.

    Devolve as colunas do cadastro mais ``x``/``y`` no CRS dos PAC (``crs_pac``).
    """
    bt = cfg["backtest"]
    tr = Transformer.from_crs(4326, config.crs_pac(cfg), always_xy=True)
    cols = ["COD_ID", "TIP_UNID", "P_N_OPE", "lon", "lat", "DAT_CON"]
    r0 = pd.read_parquet(config.pasta_ano(cfg, a0) / "UNSEMT.parquet", columns=cols)
    r1 = pd.read_parquet(config.pasta_ano(cfg, a1) / "UNSEMT.parquet", columns=cols)
    rel = cfg["tip_unid"]["religador"]
    r0 = r0[r0.TIP_UNID.astype(str).str.strip().isin(rel)]
    r1 = r1[r1.TIP_UNID.astype(str).str.strip().isin(rel) & (r1.P_N_OPE.astype(str).str.strip() == "F")].copy()
    x0, y0 = tr.transform(r0.lon.to_numpy(), r0.lat.to_numpy())
    r1["x"], r1["y"] = tr.transform(r1.lon.to_numpy(), r1.lat.to_numpy())
    dist_antigo, _ = cKDTree(np.c_[x0, y0]).query(np.c_[r1.x, r1.y])
    return r1[(~r1.COD_ID.isin(r0.COD_ID)) & (dist_antigo > bt["raio_novo_m"])].copy()


def avaliar(
    cfg: dict, e: Estudo, novos: pd.DataFrame, val: dict, a0: int, a1: int, anos_taxa: list[int]
) -> tuple[dict, pd.DataFrame]:
    """Resultados do backtest para um conjunto de religadores novos. Não altera ``e``."""
    oc, bt = cfg["otimizacao"], cfg["backtest"]
    m = copy.deepcopy(e.modelo)

    ok = np.isfinite(m.nos.x.to_numpy())
    linhas_xy = np.flatnonzero(ok)
    dist, j = cKDTree(np.c_[m.nos.x.to_numpy()[ok], m.nos.y.to_numpy()[ok]]).query(np.c_[novos.x, novos.y])
    novos = novos.assign(dist_no_m=dist, linha=linhas_xy[j])
    loc = novos[novos.dist_no_m <= bt["raio_localizacao_m"]].copy()
    # instalado dentro de um ramal com fusível = religador no lugar do fusível que protege aquele ramal
    loc["dentro_de_ramal"] = m.sob_fus[loc.linha]
    loc["linha_modelo"] = np.where(loc.dentro_de_ramal, m.disp_prot[loc.linha], loc.linha)
    loc["ctmt"] = m.nos.ctmt.to_numpy()[loc.linha_modelo]

    # ---------------------------------------------------------------- ganho de cada nó com a rede de a0
    fator = {a: float(e.chi_por_ci.get(m.nos.ctmt.iat[ini], 0.0)) for a, (ini, fim) in m.fatias.items()}
    g = np.zeros(len(m.nos))
    for a, (ini, fim) in m.fatias.items():
        g[ini:fim] = O.ganho_chi(m, ini, fim, fator[a], oc["min_clientes"], oc["max_religadores_em_serie"])
    cand = np.sort(g[g > 0])
    loc["ganho_chi_ano"] = g[loc.linha_modelo]
    loc["percentil_entre_candidatos"] = np.where(
        loc.ganho_chi_ano > 0, np.searchsorted(cand, loc.ganho_chi_ano) / max(len(cand), 1), np.nan
    )
    loc["uc_jusante"] = m.n_sub[loc.linha_modelo]
    loc["motivo_sem_ganho"] = np.select(
        [
            loc.ganho_chi_ano > 0,
            loc.uc_jusante < oc["min_clientes"],
            m.n_rel_acima[loc.linha_modelo] >= oc["max_religadores_em_serie"],
        ],
        ["", "menos de 50 clientes a jusante", "já há religadores demais em série"],
        "outro (sem clientes a proteger)",
    )

    # alimentador: recebeu religador novo? x pontuação do modelo e regras simples
    porf = pd.DataFrame({"ctmt": m.nos.ctmt, "g": g}).groupby("ctmt").g.agg(["max", "sum"])
    al = e.alimentadores.set_index("ctmt")
    f = porf.join(al[["km_mt", "chi_ano"]]).join(m.nos.groupby("ctmt").uc.sum().rename("uc"))
    f["recebeu"] = f.index.isin(loc.ctmt)
    f = f.fillna(0)
    medidas = [
        ("modelo_maior_ganho", "max"),
        ("modelo_soma_ganhos", "sum"),
        ("extensao_km", "km_mt"),
        ("clientes", "uc"),
        ("chi_historico", "chi_ano"),
    ]
    auc = {nome: float(roc_auc_score(f.recebeu, f[c])) if f.recebeu.nunique() == 2 else None for nome, c in medidas}

    # ---------------------------------------------------------------- efeito do modelo para as instalações reais
    m_guloso = copy.deepcopy(m)
    antes = O.chi_total(m, e.chi_por_ci)
    for i in pd.unique(loc.linha_modelo):
        if not m.rel[i]:
            O.instalar(m, int(i))
    depois = O.chi_total(m, e.chi_por_ci)
    chi_por_rel_modelo = (antes - depois) / max(len(loc), 1)
    did = val["chi_evitado_por_religador_did"]
    # o mesmo número de religadores, nos locais escolhidos pelo modelo (avaliados pelo mesmo modelo)
    esc = O.guloso(m_guloso, e.chi_por_ci, len(loc), oc["min_clientes"], oc["max_religadores_em_serie"])
    chi_guloso = float(esc.chi_evitado_ano.sum()) if len(esc) else 0.0
    resumo = {
        "anos": [a0, a1],
        "anos_taxa_de_falhas": anos_taxa,
        "religadores_novos": len(novos),
        "religadores_novos_com_data_de_conexao_recente": int(novos.DAT_CON.astype(str).str[-4:].isin([str(a0), str(a1)]).sum()),
        "localizados_na_rede_anterior": len(loc),
        "frac_dentro_de_ramal_com_fusivel": float(loc.dentro_de_ramal.mean()),
        "frac_com_ganho_no_modelo": float((loc.ganho_chi_ano > 0).mean()),
        "motivos_sem_ganho": loc[loc.ganho_chi_ano <= 0].motivo_sem_ganho.value_counts().to_dict(),
        "percentil_mediano_entre_candidatos": float(loc.percentil_entre_candidatos.median()),
        "frac_no_top10pct_dos_candidatos": float((loc.percentil_entre_candidatos >= 0.9).mean()),
        "auc_alimentador_recebeu_religador": auc,
        "alimentadores_que_receberam": int(f.recebeu.sum()),
        "chi_evitado_ano_modelo_por_religador": float(chi_por_rel_modelo),
        "chi_evitado_ano_did_por_religador": did,
        "chi_evitado_ano_did_por_religador_ic95": val["chi_evitado_por_religador_did_ic95"],
        "chi_evitado_ano_instalacoes_reais_modelo": float(antes - depois),
        "chi_evitado_ano_mesmo_numero_no_modelo": chi_guloso,
        "razao_modelo_sobre_real": float(chi_guloso / (antes - depois)) if antes > depois else None,
        "religadores_comparados": len(loc),
        "fator_did_sobre_modelo": float(did / chi_por_rel_modelo) if chi_por_rel_modelo > 0 else None,
    }
    return resumo, loc.drop(columns=["linha", "linha_modelo"])


def executar(cfg: dict) -> tuple[dict, pd.DataFrame]:
    """Backtest completo de ``cfg``: devolve o resumo (``backtest.json``) e as instalações localizadas (CSV)."""
    a0, a1 = cfg["ano_backtest"], cfg["ano_atual"]
    anos_taxa = [a0 - 2, a0 - 1, a0]  # só informação disponível em dez/a0
    e = analise.preparar(cfg, a0, anos_taxa)
    val = dados.valoracao(cfg["valor_json"], exigir_origem=bool(cfg.get("exigir_origem_efeito")))
    novos = religadores_novos(cfg, a0, a1)
    resumo, loc = avaliar(cfg, e, novos, val, a0, a1, anos_taxa)
    anos_conf = cfg["backtest"].get("anos_data_confirmada")
    if anos_conf:
        # sensibilidade pré-registrada: instalação nova só com DAT_CON no período (o cadastro mistura instalação e remanejamento)
        confirmados = novos[novos.DAT_CON.astype(str).str[-4:].isin([str(a) for a in anos_conf])]
        sens, _ = avaliar(cfg, e, confirmados, val, a0, a1, anos_taxa)
        resumo["sensibilidade_dat_con_no_periodo"] = {"anos_dat_con": list(anos_conf), **sens}
    if val.get("origem_efeito"):
        resumo = {**dados.rotulo(val), "nota_comparacao_did": NOTA_COMPARACAO, **resumo}
    return resumo, dados.rotular_tabela(loc, val)
