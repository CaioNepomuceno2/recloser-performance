"""Grafo radial dos alimentadores de média tensão a partir da BDGD.

Nós são os pontos de acoplamento (PAC) da BDGD. Arestas:

* segmentos de MT (``SSDMT``), com comprimento ``COMP`` em metros;
* chaves e equipamentos de seccionamento (``UNSEMT``), exceto os normalmente abertos (``P_N_OPE = 'A'``);
* reguladores de tensão (``UNREMT``).

A raiz de cada alimentador é o ``PAC_INI`` do circuito (``CTMT``), onde fica o disjuntor da saída na
subestação. Uma busca em largura a partir de uma raiz virtual ligada a todas as saídas devolve uma
árvore: cada nó tem um pai, um alimentador e uma profundidade.

Componentes desconectados (quebras de cadastro) são religados ao nó mais próximo do mesmo alimentador
quando a lacuna é menor que ``max_gap_m``; os PAC de 19 a 20 caracteres codificam a coordenada UTM
(SIRGAS 2000 / UTM 21S, em centímetros), o que permite medir essa distância.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.sparse import coo_matrix
from scipy.sparse.csgraph import breadth_first_order, connected_components
from scipy.spatial import cKDTree

# prioridade quando há mais de uma aresta entre o mesmo par de nós
PRIORIDADE = {"disjuntor": 0, "religador": 1, "seccionalizador": 2, "fusivel": 3, "chave": 4,
              "regulador": 5, "segmento": 6}


def classificar_tip_unid(tip: pd.Series, codigos: dict[str, list[str]]) -> pd.Series:
    """Classe do equipamento de seccionamento a partir do código ``TIP_UNID``."""
    out = pd.Series("chave", index=tip.index, dtype="object")
    for classe, cods in codigos.items():
        out[tip.astype(str).str.strip().isin(cods)] = classe
    return out


def pac_xy(pac: pd.Series) -> tuple[np.ndarray, np.ndarray]:
    """Coordenadas UTM (m) codificadas no PAC; NaN quando o código não traz coordenada.

    Formato observado: X (8 ou 9 dígitos, cm) + Y (9 dígitos, cm) + sufixo de 2 letras (``MT``, ``ET``...).
    """
    s = pac.astype("string").str.strip()
    ok = s.str.len().isin([19, 20]) & s.str[:-2].str.isdigit().fillna(False)
    corpo = s.where(ok).str[:-2]
    y = pd.to_numeric(corpo.str[-9:], errors="coerce") / 100
    x = pd.to_numeric(corpo.str[:-9], errors="coerce") / 100
    return x.to_numpy(float), y.to_numpy(float)


@dataclass
class Rede:
    """Árvore da rede de MT de um ano."""

    nos: pd.DataFrame        # um registro por nó alcançado: no, pai, alimentador, prof, x, y, e atributos da aresta pai->no
    alimentadores: pd.DataFrame
    qualidade: dict


def _arestas(d: Path, codigos: dict) -> tuple[pd.DataFrame, pd.DataFrame]:
    seg = pd.read_parquet(d / "SSDMT.parquet", columns=["PAC_1", "PAC_2", "CTMT", "COMP"])
    seg = seg.assign(classe="segmento", cod_id=None, tlcd=0,
                     comp_m=pd.to_numeric(seg.COMP, errors="coerce").fillna(0.0))
    sw = pd.read_parquet(d / "UNSEMT.parquet",
                         columns=["COD_ID", "PAC_1", "PAC_2", "TIP_UNID", "P_N_OPE", "TLCD", "CTMT"])
    sw["classe"] = classificar_tip_unid(sw.TIP_UNID, codigos)
    abertas = sw[sw.P_N_OPE.astype(str).str.strip() == "A"]
    sw = sw[sw.P_N_OPE.astype(str).str.strip() != "A"]
    sw = sw.assign(cod_id=sw.COD_ID, tlcd=pd.to_numeric(sw.TLCD, errors="coerce").fillna(0).astype(int),
                   comp_m=0.0)
    reg = pd.read_parquet(d / "UNREMT.parquet", columns=["COD_ID", "PAC_1", "PAC_2", "CTMT"])
    reg = reg.assign(classe="regulador", cod_id=reg.COD_ID, tlcd=0, comp_m=0.0)
    cols = ["PAC_1", "PAC_2", "CTMT", "classe", "cod_id", "tlcd", "comp_m"]
    arestas = pd.concat([seg[cols], sw[cols], reg[cols]], ignore_index=True)
    for c in ["PAC_1", "PAC_2", "CTMT"]:
        arestas[c] = arestas[c].astype("string").str.strip()
    return arestas, abertas


def construir(d: Path, codigos: dict, max_gap_m: float = 500.0) -> Rede:
    """Monta a árvore radial de todos os alimentadores do snapshot em ``d``."""
    d = Path(d)
    arestas, abertas = _arestas(d, codigos)
    ctmt = pd.read_parquet(d / "CTMT.parquet", columns=["COD_ID", "NOME", "SUB", "PAC_INI"])
    for c in ["COD_ID", "NOME", "SUB", "PAC_INI"]:
        ctmt[c] = ctmt[c].astype("string").str.strip()
    trafos = pd.read_parquet(d / "UNTRMT.parquet", columns=["COD_ID", "PAC_1", "CTMT", "POT_NOM"])
    trafos["COD_ID"] = trafos.COD_ID.astype("string").str.strip()
    trafos["PAC_1"] = trafos.PAC_1.astype("string").str.strip()
    ucbt = pd.read_parquet(d / "UCBT_tab_agg.parquet")
    ucbt["UNI_TR_MT"] = ucbt.UNI_TR_MT.astype("string").str.strip()
    trafos["n_uc"] = trafos.COD_ID.map(ucbt.groupby("UNI_TR_MT").n_uc.sum()).fillna(0)
    trafos["kva"] = pd.to_numeric(trafos.POT_NOM, errors="coerce").fillna(0)
    ucmt = pd.read_parquet(d / "UCMT_tab_agg.parquet")
    ucmt["PAC"] = ucmt.PAC.astype("string").str.strip()

    nomes = pd.Index(pd.unique(pd.concat([arestas.PAC_1, arestas.PAC_2, trafos.PAC_1, ucmt.PAC,
                                          ctmt.PAC_INI]).dropna()))
    n = len(nomes) + 1
    raiz = n - 1
    a, b = nomes.get_indexer(arestas.PAC_1), nomes.get_indexer(arestas.PAC_2)
    ok = (a >= 0) & (b >= 0)
    a, b = a[ok], b[ok]
    arestas = arestas[ok].reset_index(drop=True)
    saidas = nomes.get_indexer(ctmt.PAC_INI)
    tem_saida = saidas >= 0

    # clientes e kVA por nó
    uc_no = np.zeros(n)
    kva_no = np.zeros(n)
    np.add.at(uc_no, nomes.get_indexer(trafos.PAC_1).clip(0), trafos.n_uc.to_numpy() * (nomes.get_indexer(trafos.PAC_1) >= 0))
    np.add.at(kva_no, nomes.get_indexer(trafos.PAC_1).clip(0), trafos.kva.to_numpy() * (nomes.get_indexer(trafos.PAC_1) >= 0))
    im = nomes.get_indexer(ucmt.PAC)
    np.add.at(uc_no, im.clip(0), ucmt.n_uc.to_numpy() * (im >= 0))

    # CTMT majoritário por nó (para religar componentes ao alimentador certo)
    ctmt_no = pd.concat([pd.Series(arestas.CTMT.values, index=a), pd.Series(arestas.CTMT.values, index=b)])
    ctmt_no = ctmt_no.dropna()
    ctmt_no = ctmt_no[~ctmt_no.index.duplicated()]
    x, y = pac_xy(pd.Series(np.r_[nomes.to_numpy(), [""]]))

    extra_a, extra_b, gaps = [], [], []
    rows = np.r_[a, b, np.full(tem_saida.sum(), raiz), saidas[tem_saida]]
    cols = np.r_[b, a, saidas[tem_saida], np.full(tem_saida.sum(), raiz)]
    for _ in range(3):  # religa em ondas: um componente religado pode servir de âncora para outro
        G = coo_matrix((np.ones(len(rows), dtype=np.int8), (rows, cols)), shape=(n, n)).tocsr()
        ordem = breadth_first_order(G, raiz, directed=False, return_predecessors=False)
        alcancado = np.zeros(n, bool)
        alcancado[ordem] = True
        _, lab = connected_components(G, directed=False)
        orf = np.flatnonzero(~alcancado & np.isfinite(x))
        if len(orf) == 0:
            break
        novos = 0
        df_orf = pd.DataFrame({"no": orf, "comp": lab[orf], "ctmt": ctmt_no.reindex(orf).to_numpy()})
        df_orf = df_orf.dropna(subset=["ctmt"])
        alc = np.flatnonzero(alcancado & np.isfinite(x))
        df_alc = pd.DataFrame({"no": alc, "ctmt": ctmt_no.reindex(alc).to_numpy()}).dropna()
        arvores = {c: (g.no.to_numpy(), cKDTree(np.c_[x[g.no], y[g.no]])) for c, g in df_alc.groupby("ctmt")}
        for _comp, g in df_orf.groupby("comp"):
            ct = g.ctmt.mode().iat[0]
            if ct not in arvores:
                continue
            idx, tree = arvores[ct]
            dist, j = tree.query(np.c_[x[g.no], y[g.no]], k=1)
            k = int(np.argmin(dist))
            if dist[k] <= max_gap_m:
                extra_a.append(int(g.no.iat[k]))
                extra_b.append(int(idx[j[k]]))
                gaps.append(float(dist[k]))
                novos += 1
        if novos == 0:
            break
        rows = np.r_[rows, extra_a[-novos:], extra_b[-novos:]]
        cols = np.r_[cols, extra_b[-novos:], extra_a[-novos:]]

    G = coo_matrix((np.ones(len(rows), dtype=np.int8), (rows, cols)), shape=(n, n)).tocsr()
    ordem, pred = breadth_first_order(G, raiz, directed=False, return_predecessors=True)
    ordem = ordem[1:]
    pai = pred[ordem]

    # alimentador e profundidade em ordem de BFS (pai sempre antes do filho)
    pos_saida = pd.Series(np.flatnonzero(tem_saida), index=saidas[tem_saida])
    pos_saida = pos_saida[~pos_saida.index.duplicated()].to_dict()
    alim_l = [-1] * n
    prof_l = [0] * n
    for v, p in zip(ordem.tolist(), pai.tolist()):
        if p == raiz:
            alim_l[v] = pos_saida.get(v, -1)
        else:
            alim_l[v] = alim_l[p]
            prof_l[v] = prof_l[p] + 1
    alim = np.asarray(alim_l)
    prof = np.asarray(prof_l, dtype=np.int32)

    # atributos da aresta pai -> nó
    chave = pd.DataFrame({"u": np.minimum(a, b), "v": np.maximum(a, b), "classe": arestas.classe.to_numpy(),
                          "cod_id": arestas.cod_id.to_numpy(), "tlcd": arestas.tlcd.to_numpy(),
                          "comp_m": arestas.comp_m.to_numpy()})
    chave["prio"] = chave.classe.map(PRIORIDADE)
    chave = chave.sort_values("prio").drop_duplicates(["u", "v"])
    nos = pd.DataFrame({"no": ordem, "pai": np.where(pai == raiz, -1, pai), "alim_pos": alim[ordem],
                        "prof": prof[ordem]})
    nos["u"] = np.minimum(nos.no, np.where(nos.pai < 0, raiz, nos.pai))
    nos["v"] = np.maximum(nos.no, np.where(nos.pai < 0, raiz, nos.pai))
    nos = nos.merge(chave[["u", "v", "classe", "cod_id", "tlcd", "comp_m"]], on=["u", "v"], how="left")
    nos["classe"] = nos.classe.fillna(pd.Series(np.where(nos.pai < 0, "saida", "religacao"), index=nos.index))
    nos["comp_m"] = nos.comp_m.fillna(0.0)
    nos["tlcd"] = nos.tlcd.fillna(0).astype(int)
    nos = nos.drop(columns=["u", "v"])
    nos["uc"] = uc_no[nos.no]
    nos["kva"] = kva_no[nos.no]
    nos["x"], nos["y"] = x[nos.no], y[nos.no]
    nos["pac"] = nomes.to_numpy()[nos.no]
    nos["ctmt"] = ctmt.COD_ID.to_numpy()[nos.alim_pos]
    nos = nos.sort_values(["alim_pos", "prof"]).reset_index(drop=True)

    uc_total = float(trafos.n_uc.sum() + ucmt.n_uc.sum())
    qualidade = {
        "nos_total": int(n - 1),
        "nos_alcancados": len(nos),
        "uc_total": uc_total,
        "uc_alcancadas": float(nos.uc.sum()),
        "frac_uc_alcancadas": float(nos.uc.sum() / uc_total) if uc_total else 0.0,
        "componentes_religados": len(gaps),
        "lacuna_mediana_m": float(np.median(gaps)) if gaps else 0.0,
        "lacuna_p90_m": float(np.percentile(gaps, 90)) if gaps else 0.0,
        "chaves_normalmente_abertas": len(abertas),
        "alimentadores": len(ctmt),
        "alimentadores_sem_saida_no_grafo": int((~tem_saida).sum()),
    }
    alimentadores = ctmt.assign(alim_pos=np.arange(len(ctmt)), tem_saida=tem_saida)
    return Rede(nos=nos, alimentadores=alimentadores, qualidade=qualidade)


def religadores_perto_da_saida(d: Path, codigos: dict, saltos: int = 2) -> pd.DataFrame:
    """Religadores a até ``saltos`` manobras (só chaves, sem segmentos) do ``PAC_INI`` de algum circuito.

    Em subestações pequenas o religador faz o papel do disjuntor de saída e fica entre o barramento e o
    início do alimentador; na árvore ele aparece sem clientes a jusante.
    """
    d = Path(d)
    sw = pd.read_parquet(d / "UNSEMT.parquet", columns=["COD_ID", "PAC_1", "PAC_2", "TIP_UNID", "P_N_OPE"])
    for c in ["COD_ID", "PAC_1", "PAC_2"]:
        sw[c] = sw[c].astype("string").str.strip()
    sw = sw[sw.P_N_OPE.astype(str).str.strip() != "A"]
    sw["classe"] = classificar_tip_unid(sw.TIP_UNID, codigos)
    ctmt = pd.read_parquet(d / "CTMT.parquet", columns=["COD_ID", "PAC_INI"])
    ctmt["PAC_INI"] = ctmt.PAC_INI.astype("string").str.strip()
    ctmt["COD_ID"] = ctmt.COD_ID.astype("string").str.strip()
    lados = pd.concat([sw[["COD_ID", "PAC_1", "PAC_2", "classe"]].rename(columns={"PAC_1": "a", "PAC_2": "b"}),
                       sw[["COD_ID", "PAC_2", "PAC_1", "classe"]].rename(columns={"PAC_2": "a", "PAC_1": "b"})])
    fronteira = ctmt.rename(columns={"PAC_INI": "a", "COD_ID": "ctmt"})[["ctmt", "a"]]
    achados, vistos = [], set()
    for salto in range(1, saltos + 1):
        e = fronteira.merge(lados, on="a")
        e = e[~e.COD_ID.isin(vistos)]
        vistos |= set(e.COD_ID)
        achados.append(e[e.classe == "religador"][["ctmt", "COD_ID"]].assign(salto=salto))
        fronteira = e[["ctmt", "b"]].rename(columns={"b": "a"}).drop_duplicates()
    out = pd.concat(achados).drop_duplicates("COD_ID")
    return out.rename(columns={"COD_ID": "cod_id"})
