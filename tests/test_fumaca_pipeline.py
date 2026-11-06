"""Teste de fumaça: scripts 01, 02 e 05 (BDGD -> árvore -> modelo calibrado -> zonas -> religadores novos -> R$).

Seis alimentadores sintéticos (tronco, ramal com fusível, religador de linha, religador na saída, chave aberta e um
componente órfão a 1 m da rede) com histórico de falhas gerado aqui. Tudo em disco temporário, semente fixa, sem rede.
"""
import copy
import json

import numpy as np
import pandas as pd
import pytest

from recloser import analise, config, dados, topologia
from recloser import otimizacao as O

N_ALIM = 6
ANO = 2025
ANOS_TAXA = [2023, 2024, 2025]
MIN_UC, MAX_SERIE, TAU = 20, 3, 0.3


def pac(x_m, y_m):
    """PAC no formato da BDGD: X e Y em centímetros (UTM) + sufixo de 2 letras."""
    return f"{round(x_m * 100):08d}{round(y_m * 100):09d}MT"


def _gravar_bdgd(pasta, rng):
    """Camadas da BDGD (Parquet) de 6 alimentadores. Devolve o nº de UC de cada um."""
    seg, sw, ctmt, trafos, ucbt, uc = [], [], [], [], [], []
    for f in range(N_ALIM):
        cod, x0, y0 = f"{f + 1}", 500000 + 3000 * f, 8000000

        def P(i, x0=x0, y0=y0):  # nó i do tronco (300 m de distância entre nós)
            return pac(x0 + 300 * i, y0)

        ctmt.append({"COD_ID": cod, "NOME": f"{f + 1:06d}", "SUB": "S1", "PAC_INI": P(0)})
        for i in range(8):  # tronco de 2,4 km; nos alimentadores pares, o trecho 5-6 é um religador de linha
            if f % 2 == 0 and i == 5:
                sw.append({"COD_ID": f"{cod}r", "PAC_1": P(5), "PAC_2": P(6), "TIP_UNID": "32", "P_N_OPE": "F",
                           "TLCD": 1, "CTMT": cod})
            else:
                seg.append({"PAC_1": P(i), "PAC_2": P(i + 1), "CTMT": cod, "COMP": 300.0})
        # ramal atrás de um fusível, saindo do nó 3 (nos alimentadores ímpares é longo e tem muitos clientes)
        longo = f % 2 == 1
        b = [pac(x0 + 900, y0 + 100 * (j + 1)) for j in range(3)]
        sw.append({"COD_ID": f"{cod}f", "PAC_1": P(3), "PAC_2": b[0], "TIP_UNID": "22", "P_N_OPE": "F", "TLCD": 0,
                   "CTMT": cod})
        seg += [{"PAC_1": b[j], "PAC_2": b[j + 1], "CTMT": cod, "COMP": 700.0 if longo else 200.0}
                for j in range(2)]
        if f == 1:  # religador na saída: o PAC_INI é o dele e não há cliente atrás dele
            sw.append({"COD_ID": f"{cod}s", "PAC_1": P(0), "PAC_2": pac(x0 - 100, y0 - 50), "TIP_UNID": "32",
                       "P_N_OPE": "F", "TLCD": 1, "CTMT": cod})
        if f == 0:  # chave normalmente aberta para o alimentador seguinte: fora do grafo
            sw.append({"COD_ID": f"{cod}na", "PAC_1": P(8), "PAC_2": pac(x0 + 3000 + 2400, y0), "TIP_UNID": "34",
                       "P_N_OPE": "A", "TLCD": 0, "CTMT": cod})
        locais = [(P(2), "t2"), (P(4), "t4"), (P(6), "t6"), (P(8), "t8"), (b[2], "tb")]
        if f == 2:  # componente órfão (lacuna de cadastro) a 1 m do nó 6, com um trafo de 10 UC
            seg.append({"PAC_1": pac(x0 + 1801, y0), "PAC_2": pac(x0 + 1850, y0), "CTMT": cod, "COMP": 50.0})
            locais.append((pac(x0 + 1850, y0), "to"))
        total = 0
        for no, nome in locais:
            n = 10 if nome == "to" else int(rng.integers(100, 200) if longo and nome == "tb" else rng.integers(20, 80))
            trafos.append({"COD_ID": f"{cod}{nome}", "PAC_1": no, "CTMT": cod, "POT_NOM": 75.0})
            ucbt.append({"UNI_TR_MT": f"{cod}{nome}", "CTMT": cod, "n_uc": n, "ene_ano_kwh": 1e4 * n})
            total += n
        uc.append(total)
    vazio = {"COD_ID": pd.Series(dtype=str), "PAC_1": pd.Series(dtype=str), "PAC_2": pd.Series(dtype=str),
             "CTMT": pd.Series(dtype=str)}
    pasta.mkdir(parents=True)
    for nome, df in [("SSDMT", pd.DataFrame(seg)), ("UNSEMT", pd.DataFrame(sw)), ("UNREMT", pd.DataFrame(vazio)),
                     ("CTMT", pd.DataFrame(ctmt)), ("UNTRMT", pd.DataFrame(trafos)),
                     ("UCBT_tab_agg", pd.DataFrame(ucbt)),
                     ("UCMT_tab_agg", pd.DataFrame({"PAC": pd.Series(dtype=str), "CTMT": pd.Series(dtype=str),
                                                    "n_uc": pd.Series(dtype=int),
                                                    "ene_ano_kwh": pd.Series(dtype=float)}))]:
        df.to_parquet(pasta / f"{nome}.parquet", index=False)
    return uc


def _gravar_falhas(caminho, uc, rng):
    """Falhas, CI e CHI por alimentador, ano, mês e modo: 1,2 a 1,8 falhas por km e ano, ~50% dos clientes por falha."""
    linhas = []
    for f in range(N_ALIM):
        taxa_mes = (1.2 + 0.1 * f) * 2.4 / 12 / 2
        for ano in ANOS_TAXA:
            for mes in range(1, 13):
                for modo in ["VEGETACAO", "OUTROS"]:
                    n = int(rng.poisson(taxa_mes * 3))
                    ci = n * uc[f] * 0.5 * rng.uniform(0.8, 1.2)
                    chi = ci * rng.uniform(0.8, 2.5)
                    linhas.append({"alimentador": f"{f + 1:06d}", "ano": ano, "mes": mes, "modo": modo,
                                   "n_falhas": n, "ci": ci, "chi": chi, "chi_regulatorio": 0.7 * chi})
    pd.DataFrame(linhas).to_parquet(caminho, index=False)


def test_fumaca_pipeline_arvore_modelo_zonas_otimizacao(tmp_path, monkeypatch):
    rng = np.random.default_rng(5)
    cfg = config.carregar()
    cfg.update(cache_bdgd=tmp_path / "bdgd", falhas=tmp_path / "falhas.parquet", valor_json=tmp_path / "valor.json")
    monkeypatch.setattr(config, "ROOT", tmp_path)
    proc = tmp_path / "data" / "processed"
    proc.mkdir(parents=True)
    uc = _gravar_bdgd(config.pasta_ano(cfg, ANO), rng)
    _gravar_falhas(cfg["falhas"], uc, rng)
    cfg["valor_json"].write_text(json.dumps({
        "rs_por_chi_social": 5.9, "rs_por_chi_compensacao": 1.9, "frac_chi_regulatorio": 0.3, "uc_total": float(sum(uc)),
        "chi_evitado_ano_por_religador": 100.0, "chi_evitado_ano_por_religador_ic95": [50.0, 150.0],
        "efeito_chi_pct": -10.0}))

    # script 01: árvore radial de cada alimentador
    rede = topologia.construir(config.pasta_ano(cfg, ANO), cfg["tip_unid"], cfg["topologia"]["max_gap_m"])
    rede.nos.to_parquet(proc / f"nos_{ANO}.parquet", index=False)
    rede.alimentadores.to_parquet(proc / f"alimentadores_{ANO}.parquet", index=False)
    q = rede.qualidade
    assert q["frac_uc_alcancadas"] == pytest.approx(1.0) and q["uc_total"] == sum(uc)
    assert q["componentes_religados"] == 1 and q["lacuna_mediana_m"] == pytest.approx(1.0, abs=0.01)
    assert q["chaves_normalmente_abertas"] == 1 and q["alimentadores_sem_saida_no_grafo"] == 0
    assert rede.nos.groupby("ctmt").size().shape[0] == N_ALIM
    assert (rede.nos.pai.isin(rede.nos.no) | (rede.nos.pai < 0)).all()  # todo nó tem pai na árvore

    # script 02: modelo calibrado com o histórico, religadores de saída e zonas de proteção
    e = analise.preparar(cfg, ANO, ANOS_TAXA, tau=TAU)  # tau diferente de 0,5 para não esconder 'tau' trocado por '1 - tau'
    m, al = e.modelo, e.alimentadores
    classes = m.nos.classe.value_counts().to_dict()
    assert classes["saida"] == N_ALIM and classes["fusivel"] == N_ALIM and classes["religador"] == 3
    assert classes["religador_saida"] == 1 and e.saida.cod_id.tolist() == ["2s"]
    assert al.saida_por_religador.sum() == 1 and (al.ci_modelo > 0).all() and (al.km_mt > 0).all()
    assert (e.chi_por_ci > 0).all() and e.chi_por_ci.index.isin(al.ctmt).all()
    ajuste = (al.ci_ano / al.ci_modelo).clip(cfg["confiabilidade"]["fator_calibracao_min"],
                                             cfg["confiabilidade"]["fator_calibracao_max"])
    assert (al.chi_modelo_calibrado / al.ci_modelo).to_numpy() == pytest.approx(
        (ajuste * al.chi_ano / al.ci_ano).to_numpy())  # CHI calibrado = CI do modelo x razão x duração média
    v = analise.validacao_modelo(al)
    assert v["alimentadores"] == N_ALIM and -1 <= v["spearman_ci_modelo_vs_observado"] <= 1
    assert v["spearman_ci_modelo_vs_observado"] > 0  # alimentadores com mais CI observado têm mais CI no modelo
    z = m.zonas()
    assert z.uc_zona.sum() == pytest.approx(m.uc.sum())  # cada cliente e cada metro de rede pertencem a uma zona
    assert z.km_zona.sum() == pytest.approx(m.comp.sum() / 1000)
    assert (z.uc_jusante >= z.uc_zona).all() and (z.falhas_ano_zona >= 0).all()
    modos = dados.falhas_por_modo(cfg["falhas"], ANOS_TAXA)
    assert set(modos.modo) == {"VEGETACAO", "OUTROS"} and (modos.n_falhas >= 0).all()

    # script 05: onde instalar os próximos religadores e quanto vale
    base = copy.deepcopy(m)
    chi_atual = O.chi_total(base, e.chi_por_ci)
    assert chi_atual > 0
    instalado = copy.deepcopy(base)
    esc = O.guloso(instalado, e.chi_por_ci, 6, MIN_UC, MAX_SERIE)
    assert 1 <= len(esc) <= 6 and (esc.chi_evitado_ano > 0).all()
    assert esc.linha.is_unique and (esc.uc_jusante >= MIN_UC).all()
    assert set(esc.tipo) == {"tronco", "troca_de_fusivel"}  # há os dois tipos de ganho na lista
    # o que o guloso diz que evita é exatamente o que o CHI do modelo perde ao instalar
    assert chi_atual - O.chi_total(instalado, e.chi_por_ci) == pytest.approx(esc.chi_evitado_ano.sum())
    assert 0 < esc.chi_evitado_ano.sum() < chi_atual
    acumulado = esc.chi_evitado_ano.cumsum()
    assert acumulado.is_monotonic_increasing
    # no 1º passo o guloso não perde para nenhuma regra simples
    primeiro = esc.chi_evitado_ano.iloc[0]
    for crit in ["extensao", "clientes", "aleatorio"]:
        r = O.regra_divisao(copy.deepcopy(base), e.chi_por_ci, [1], crit, MIN_UC, MAX_SERIE, np.random.default_rng(1))
        assert 0 < r[1] <= primeiro + 1e-9, crit

    # valoração: DEC, R$ social e R$ de compensação saem do mesmo CHI evitado
    val = dados.valoracao(cfg["valor_json"])
    rs_social = esc.chi_evitado_ano * val["rs_por_chi_social"]
    rs_comp = esc.chi_evitado_ano * val["frac_chi_regulatorio"] * val["rs_por_chi_compensacao"]
    dec_min = esc.chi_evitado_ano / val["uc_total"] * 60
    assert (rs_comp < rs_social).all() and (dec_min > 0).all()
    vc = cfg["valor"]
    anuidade = (1 - (1 + vc["taxa_desconto"]) ** -vc["vida_anos"]) / vc["taxa_desconto"]
    payback = vc["custo_religador_rs"] / rs_social
    vpl = rs_social * anuidade - vc["custo_religador_rs"]
    assert (payback > 0).all() and ((vpl > 0) == (payback < anuidade)).all()  # VPL positivo <=> payback < anuidade
