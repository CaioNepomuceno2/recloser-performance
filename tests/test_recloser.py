"""Testes com redes sintéticas pequenas, em que o resultado esperado é conhecido."""
import copy
import itertools

import numpy as np
import pandas as pd
import pytest

from recloser import otimizacao as O
from recloser import topologia as T
from recloser.zonas import Modelo

COD = {"religador": ["32"], "seccionalizador": ["35", "36"], "fusivel": ["22", "23"], "disjuntor": ["29"]}


def _arvore(classes_extra=None, tau=0.5):
    """Alimentador sintético:

    saída(0) -1km- 1 -1km- 2 -1km- 3(100 UC) ; 2 -fusível- 4 -2km- 5(50 UC) ; 1 -1km- 6(20 UC)
    """
    pai = [-1, 0, 1, 2, 2, 4, 1]
    classe = ["saida", "segmento", "segmento", "segmento", "fusivel", "segmento", "segmento"]
    if classes_extra:
        for i, c in classes_extra.items():
            classe[i] = c
    comp = [0, 1000, 1000, 1000, 0, 2000, 1000]
    uc = [0, 0, 0, 100, 0, 50, 20]
    nos = pd.DataFrame({"no": range(7), "pai": pai, "alim_pos": 0, "prof": [0, 1, 2, 3, 3, 4, 2],
                        "classe": classe, "comp_m": comp, "uc": uc, "kva": uc, "ctmt": "A", "cod_id": None,
                        "tlcd": 0, "x": np.nan, "y": np.nan, "pac": [f"p{i}" for i in range(7)]})
    return Modelo.de_nos(nos, pd.Series({"A": 1e-3}), tau=tau)  # 1 falha/ano por km


def _r(m, no):
    """Linha do modelo correspondente ao nó (o modelo reordena por profundidade)."""
    return int(np.flatnonzero(m.nos.no.to_numpy() == no)[0])


def test_pac_xy_decodifica_utm():
    x, y = T.pac_xy(pd.Series(["56097953840439966MT", "00613646", "123456789012345678ET"]))
    assert x[0] == pytest.approx(560979.53) and y[0] == pytest.approx(8404399.66)
    assert np.isnan(x[1])
    assert x[2] == pytest.approx(1234567.89) and y[2] == pytest.approx(123456.78)


def test_classificar_tip_unid():
    c = T.classificar_tip_unid(pd.Series(["32", "22", "34", " 36"]), COD)
    assert c.tolist() == ["religador", "fusivel", "chave", "seccionalizador"]


def test_zonas_e_ci():
    m = _arvore()
    assert m.n_sub[_r(m, 0)] == 170 and m.n_sub[_r(m, 2)] == 150 and m.n_sub[_r(m, 4)] == 50
    assert m.sob_fus[_r(m, 5)] and not m.sob_fus[_r(m, 3)]
    # faltas: 1 em cada km de tronco (nós 1,2,3,6 -> 4 falhas, peso 1-tau, eliminadas na saída, 170 UC)
    # e 2 sob o fusível (peso 1, 50 UC)
    assert m.ci_esperado(0, 7) == pytest.approx(4 * 0.5 * 170 + 2 * 50)


def test_ganho_igual_a_reducao_de_ci():
    """O ganho analítico de cada nó candidato bate com a redução exata de CI ao instalar o religador."""
    for no in [1, 2, 3, 4, 6]:
        m = _arvore()
        g = m.ganho_ci(0, 7)[_r(m, no)]
        antes = m.ci_esperado(0, 7)
        O.instalar(m, _r(m, no))
        assert antes - m.ci_esperado(0, 7) == pytest.approx(g), no


def test_guloso_igual_forca_bruta():
    fator = pd.Series({"A": 1.0})
    for k in [1, 2]:
        melhor = 0.0
        for comb in itertools.combinations([1, 2, 3, 4, 6], k):
            m = _arvore()
            antes = O.chi_total(m, fator)
            for i in comb:
                O.instalar(m, _r(m, i))
            melhor = max(melhor, antes - O.chi_total(m, fator))
        m = _arvore()
        esc = O.guloso(m, fator, k, min_uc=1, max_serie=5)
        assert esc.chi_evitado_ano.sum() == pytest.approx(melhor)


def test_religador_existente_limita_ganho_a_montante():
    m = _arvore({1: "religador"})
    assert m.disp_rel[_r(m, 3)] == _r(m, 1) and m.n_rel_acima[_r(m, 3)] == 1
    assert m.ganho_ci(0, 7)[_r(m, 1)] == 0  # já é religador
    # num nó a jusante do religador, o ganho usa os clientes a jusante do religador, não da saída
    g3 = m.ganho_ci(0, 7)[_r(m, 3)]
    assert g3 == pytest.approx(0.5 * 1 * (170 - 100))


def test_regra_divisao_nao_mexe_em_fusivel():
    m = _arvore()
    r = O.regra_divisao(copy.deepcopy(m), pd.Series({"A": 1.0}), [1], "extensao", 1, 5)
    assert r[1] > 0


def _grava(d, nome, df):
    df.to_parquet(d / f"{nome}.parquet", index=False)


def test_construir_rede_com_chave_aberta_e_lacuna(tmp_path):
    """Rede: saída R -seg- a -religador- b -seg- c(trafo 30 UC); chave aberta c-d; componente órfão e-f
    a 1 m de c (lacuna de cadastro) com trafo de 10 UC."""
    def pac(x, y):
        return f"{int(x * 100):08d}{int(y * 100):09d}MT"
    R, a, b, c, d = pac(500000, 8000000), pac(500100, 8000000), pac(500101, 8000000), pac(500200, 8000000), pac(500300, 8000000)
    e, f = pac(500201, 8000000), pac(500250, 8000000)
    _grava(tmp_path, "SSDMT", pd.DataFrame({"PAC_1": [R, b, e], "PAC_2": [a, c, f], "CTMT": ["1", "1", "1"],
                                            "COMP": [100.0, 100.0, 50.0]}))
    _grava(tmp_path, "UNSEMT", pd.DataFrame({"COD_ID": ["r1", "s1"], "PAC_1": [a, c], "PAC_2": [b, d],
                                             "TIP_UNID": ["32", "34"], "P_N_OPE": ["F", "A"], "TLCD": [1, 0],
                                             "CTMT": ["1", "1"]}))
    _grava(tmp_path, "UNREMT", pd.DataFrame({"COD_ID": pd.Series(dtype=str), "PAC_1": pd.Series(dtype=str),
                                             "PAC_2": pd.Series(dtype=str), "CTMT": pd.Series(dtype=str)}))
    _grava(tmp_path, "CTMT", pd.DataFrame({"COD_ID": ["1"], "NOME": ["001001"], "SUB": ["S"], "PAC_INI": [R]}))
    _grava(tmp_path, "UNTRMT", pd.DataFrame({"COD_ID": ["t1", "t2"], "PAC_1": [c, f], "CTMT": ["1", "1"],
                                             "POT_NOM": [75.0, 30.0]}))
    _grava(tmp_path, "UCBT_tab_agg", pd.DataFrame({"UNI_TR_MT": ["t1", "t2"], "CTMT": ["1", "1"],
                                                   "n_uc": [30, 10], "ene_ano_kwh": [0.0, 0.0]}))
    _grava(tmp_path, "UCMT_tab_agg", pd.DataFrame({"PAC": pd.Series(dtype=str), "CTMT": pd.Series(dtype=str),
                                                   "n_uc": pd.Series(dtype=int), "ene_ano_kwh": pd.Series(dtype=float)}))
    rede = T.construir(tmp_path, COD, max_gap_m=5)
    q = rede.qualidade
    assert q["frac_uc_alcancadas"] == pytest.approx(1.0)
    assert q["componentes_religados"] == 1
    assert d not in set(rede.nos.pac)          # atrás da chave aberta
    assert (rede.nos.classe == "religador").sum() == 1
    m = Modelo.de_nos(rede.nos, pd.Series({"1": 1e-3}))
    i_rel = int(np.flatnonzero(m.nos.classe == "religador")[0])
    assert m.n_sub[i_rel] == 40
