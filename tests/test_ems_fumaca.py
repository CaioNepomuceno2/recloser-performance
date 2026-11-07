"""Teste de fumaça de MS: os scripts 01 a 06 de ponta a ponta sobre uma BDGD sintética no estilo de MS, com ``--config``.

Seis alimentadores de 5 caracteres alfanuméricos (``RBR53``), três a oeste e três a leste de 54° W, com PAC de 19 e de 20
caracteres
(UTM 21S estendido), dois snapshots (2024 e 2025, este com dois religadores novos), falhas com o nome completado com zero,
interrupções de 2026 com o elemento que abriu e um ``valor.json`` com ``origem_efeito``. Tudo em disco temporário, sem rede.
Também roda a mesma rede com a configuração no formato de MT (sem rótulo, sem porta, caminhos padrão) para provar que
as saídas de MT não ganham coluna nem campo.
"""

import json
import runpy
import sys

import numpy as np
import pandas as pd
import pytest
import yaml
from pyproj import Transformer

from recloser import config

RAIZ = config.ROOT
SCRIPTS = RAIZ / "scripts"
NOMES_MS = ["RBR53", "CGP01", "AJO51", "DOI06", "SIA52", "CGD52"]
NOMES_MT = [f"{f + 1:06d}" for f in range(6)]
INV = Transformer.from_crs(31981, 4326, always_xy=True)
ROTULO = "transportado de MT"


def pac(x_m, y_m, suf="MT"):
    """PAC no formato da BDGD: X e Y em centímetros (UTM 21S) + sufixo. X de 1.000.000 m para cima vira 20 caracteres."""
    return f"{round(x_m * 100)}{round(y_m * 100):09d}{suf}"


def _origem(f):
    """Alimentadores 0 a 2 a oeste (X ~ 430 km, PAC de 19 caracteres); 3 a 5 a leste (X ~ 1.070 km, PAC de 20 caracteres)."""
    return (430_000 if f % 6 < 3 else 1_070_000) + 3_000 * f, 7_600_000


def _gravar_bdgd(pasta, rng, nomes, ano, novos=(), pac_ini_quebrado=(), n_alim=6):
    """Camadas da BDGD (Parquet) de 6 alimentadores. ``novos``: (alimentador, nó) cujo trecho vira religador (só 2025)."""
    seg, sw, ctmt, trafos, ucbt, uc = [], [], [], [], [], []
    for f in range(n_alim):
        cod, (x0, y0) = f"{900 + f}", _origem(f)

        def P(i, x0=x0, y0=y0):
            return pac(x0 + 300 * i, y0)

        ctmt.append(
            {
                "COD_ID": cod,
                "NOME": nomes[f],
                "SUB": "S1",
                "PAC_INI": P(0) if f not in pac_ini_quebrado else pac(x0 - 5_000, y0 - 5_000),
            }
        )
        novos_f = {i for (ff, i) in novos if ff == f}
        for i in range(8):
            if f % 2 == 0 and i == 5:
                sw.append(
                    {
                        "COD_ID": f"{cod}r",
                        "PAC_1": P(5),
                        "PAC_2": P(6),
                        "TIP_UNID": "32",
                        "P_N_OPE": "F",
                        "TLCD": 1,
                        "CTMT": cod,
                        "DAT_CON": "15/06/2015",
                    }
                )
            elif i in novos_f:
                sw.append(
                    {
                        "COD_ID": f"{cod}n{i}",
                        "PAC_1": P(i),
                        "PAC_2": P(i + 1),
                        "TIP_UNID": "32",
                        "P_N_OPE": "F",
                        "TLCD": 1,
                        "CTMT": cod,
                        "DAT_CON": "10/03/2025" if i == 2 else "12/05/2019",
                    }
                )
            else:
                seg.append({"PAC_1": P(i), "PAC_2": P(i + 1), "CTMT": cod, "COMP": 300.0})
        longo = f % 2 == 1
        b = [pac(x0 + 900, y0 + 100 * (j + 1)) for j in range(3)]
        sw.append(
            {
                "COD_ID": f"{cod}f",
                "PAC_1": P(3),
                "PAC_2": b[0],
                "TIP_UNID": "22",
                "P_N_OPE": "F",
                "TLCD": 0,
                "CTMT": cod,
                "DAT_CON": "01/01/2010",
            }
        )
        seg += [{"PAC_1": b[j], "PAC_2": b[j + 1], "CTMT": cod, "COMP": 700.0 if longo else 200.0} for j in range(2)]
        if f == 1:  # religador na saída: o PAC_INI é o dele
            sw.append(
                {
                    "COD_ID": f"{cod}s",
                    "PAC_1": P(0),
                    "PAC_2": pac(x0 - 100, y0 - 50),
                    "TIP_UNID": "32",
                    "P_N_OPE": "F",
                    "TLCD": 1,
                    "CTMT": cod,
                    "DAT_CON": "15/06/2015",
                }
            )
        if f == 0:  # chave normalmente aberta, fora do grafo
            sw.append(
                {
                    "COD_ID": f"{cod}na",
                    "PAC_1": P(8),
                    "PAC_2": pac(x0 + 5_400, y0),
                    "TIP_UNID": "19",
                    "P_N_OPE": "A",
                    "TLCD": 0,
                    "CTMT": cod,
                    "DAT_CON": "01/01/2010",
                }
            )
        total = 0
        for no, nome in [(P(2), "t2"), (P(4), "t4"), (P(6), "t6"), (P(8), "t8"), (b[2], "tb")]:
            n = int(rng.integers(100, 200) if longo and nome == "tb" else rng.integers(20, 80))
            trafos.append({"COD_ID": f"{cod}{nome}", "PAC_1": no, "CTMT": cod, "POT_NOM": 75.0})
            ucbt.append({"UNI_TR_MT": f"{cod}{nome}", "CTMT": cod, "n_uc": n, "ene_ano_kwh": 0.0})
            total += n
        uc.append(total)
    sw = pd.DataFrame(sw)
    xs = [float(p[:-11]) / 100 for p in sw.PAC_1]  # lon/lat da chave = coordenada do seu PAC_1, como na BDGD
    ys = [float(p[-11:-2]) / 100 for p in sw.PAC_1]
    sw["lon"], sw["lat"] = INV.transform(xs, ys)
    vazio = {
        "COD_ID": pd.Series(dtype=str),
        "PAC_1": pd.Series(dtype=str),
        "PAC_2": pd.Series(dtype=str),
        "CTMT": pd.Series(dtype=str),
    }
    pasta.mkdir(parents=True)
    for nome, df in [
        ("SSDMT", pd.DataFrame(seg)),
        ("UNSEMT", sw),
        ("UNREMT", pd.DataFrame(vazio)),
        ("CTMT", pd.DataFrame(ctmt)),
        ("UNTRMT", pd.DataFrame(trafos)),
        ("UCBT_tab_agg", pd.DataFrame(ucbt)),
        (
            "UCMT_tab_agg",
            pd.DataFrame(
                {
                    "PAC": pd.Series(dtype=str),
                    "CTMT": pd.Series(dtype=str),
                    "n_uc": pd.Series(dtype=int),
                    "ene_ano_kwh": pd.Series(dtype=float),
                }
            ),
        ),
    ]:
        df.to_parquet(pasta / f"{nome}.parquet", index=False)
    return uc


def _gravar_historico(tmp, rng, uc, nomes, ms, n_alim=6):
    linhas = []
    for f in range(n_alim):
        taxa_mes = (1.2 + 0.1 * f) * 2.4 / 12 / 2
        for ano in (2022, 2023, 2024, 2025):
            for mes in range(1, 13):
                for modo in ["VEGETACAO", "OUTROS"]:
                    n = int(rng.poisson(taxa_mes * 3))
                    ci = n * uc[f] * 0.5 * rng.uniform(0.8, 1.2)
                    chi = ci * rng.uniform(0.8, 2.5)
                    linhas.append(
                        {
                            "alimentador": ("0" + nomes[f]) if ms else nomes[f],
                            "ano": ano,
                            "mes": mes,
                            "modo": modo,
                            "n_falhas": n,
                            "ci": ci,
                            "chi": chi,
                            "chi_regulatorio": 0.7 * chi,
                        }
                    )
    pd.DataFrame(linhas).to_parquet(tmp / "falhas.parquet", index=False)
    # interrupções de 2026: cada alimentador com aberturas de disjuntor e de religador, mais outros elementos
    rows = []
    for f in range(n_alim):
        for k, el in enumerate(
            ["DISJUNTOR"] * 5 + ["RELIGADOR"] * 8 + ["CHAVE FUSIVEL"] * 3 + ["MEDIDOR"] * 4 + ["NAO IDENTIFICADO"] * 2
        ):
            rows.append(
                {
                    "alimentador_cod_id": f"{900 + f}",
                    "subestacao": "S1",
                    "elemento": el,
                    "uc_afetadas": 30 + k,
                    "duracao_h": 1.5,
                    "chi": (30 + k) * 1.5,
                    "expurgo": "NAO HOUVE EXPURGO",
                    "grupo_causa": "VENTO",
                    "inicio": pd.Timestamp("2026-02-01") + pd.Timedelta(days=k),
                    "ano": 2026,
                    "mes": 2,
                    "origem_mt": True,
                    "origem": "INTERNA",
                    "tipo": "NAO PROGRAMADA",
                }
            )
    pd.DataFrame(rows).to_parquet(tmp / "interrupcoes.parquet", index=False)


def _montar(tmp_path, monkeypatch, ms=True, quebrar=()):
    """Cria os dados e a configuração (``--config``) e devolve o caminho do YAML."""
    rng = np.random.default_rng(7)
    nomes = NOMES_MS if ms else NOMES_MT
    monkeypatch.setattr(config, "ROOT", tmp_path)
    base = tmp_path / "bdgd"
    uc = _gravar_bdgd(base / "2024", rng, nomes, 2024, pac_ini_quebrado=(1, 2, 4) if 2024 in quebrar else ())
    _gravar_bdgd(
        base / "2025",
        np.random.default_rng(7),
        nomes,
        2025,
        novos=[(1, 2), (3, 2), (4, 6)],
        pac_ini_quebrado=(1, 2, 4) if 2025 in quebrar else (),
    )
    _gravar_historico(tmp_path, rng, uc, nomes, ms)
    valor = {
        "rs_por_chi_social": 5.9,
        "rs_por_chi_compensacao": 1.9,
        "frac_chi_regulatorio": 0.3,
        "uc_total": float(sum(uc)),
        "chi_evitado_ano_por_religador": 100.0,
        "chi_evitado_ano_por_religador_ic95": [50.0, 150.0],
        "efeito_chi_pct": -10.0,
    }
    (tmp_path / "valor.json").write_text(json.dumps({"origem_efeito": ROTULO, **valor} if ms else valor))
    cfg = yaml.safe_load((RAIZ / "configs" / ("params_ems.yaml" if ms else "params.yaml")).read_text(encoding="utf-8"))
    cfg.update(
        cache_bdgd=str(base),
        falhas=str(tmp_path / "falhas.parquet"),
        interrupcoes=str(tmp_path / "interrupcoes.parquet"),
        valor_json=str(tmp_path / "valor.json"),
        otimizacao={**cfg["otimizacao"], "ks": [2, 4], "min_clientes": 20, "sorteios_aleatorio": 2, "k_sensibilidade": 3},
        confiabilidade={**cfg["confiabilidade"], "anos_taxa": [2023, 2024, 2025]},
    )
    cfg["backtest"] = {**cfg["backtest"], "raio_localizacao_m": 50}
    cfg.pop("bdgd", None)
    cfg.pop("referencias", None)
    arq = tmp_path / "config.yaml"
    arq.write_text(yaml.safe_dump(cfg, allow_unicode=True), encoding="utf-8")
    return arq


def rodar(script, config_yaml, monkeypatch):
    monkeypatch.setattr(sys, "argv", [script, "--config", str(config_yaml)])
    runpy.run_path(str(SCRIPTS / script), run_name="__main__")


def rodar_tudo(config_yaml, monkeypatch):
    for s in [
        "01_topologia.py",
        "02_diagnostico.py",
        "03_desempenho_2026.py",
        "04_backtest.py",
        "05_otimizacao.py",
        "06_figuras.py",
    ]:
        rodar(s, config_yaml, monkeypatch)


# ---------------------------------------------------------------- MS de ponta a ponta
@pytest.fixture(scope="module")
def ms_completo(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("ms")
    with pytest.MonkeyPatch.context() as mp:
        arq = _montar(tmp, mp)
        rodar_tudo(arq, mp)
        yield tmp


def test_ms_fumaca_topologia_com_pac_de_19_e_20_caracteres(ms_completo):
    rel = ms_completo / "reports" / "ems"
    q = json.loads((rel / "qualidade_topologia.json").read_text())
    for ano in ("2024", "2025"):
        assert q[ano]["frac_uc_alcancadas"] == pytest.approx(1.0) and q[ano]["alimentadores"] == 6
        assert q[ano]["alimentadores_sem_saida_no_grafo"] == 0
    porta = json.loads((rel / "porta_qualidade.json").read_text())
    assert porta["2024"]["passou"] and porta["2025"]["passou"] and porta["2025"]["minimo"] == 0.95
    nos = pd.read_parquet(ms_completo / "data" / "ems" / "processed" / "nos_2025.parquet")
    assert nos.x.max() > 1_000_000 and nos.x.min() < 500_000  # oeste (19 caracteres) e leste (20 caracteres) na mesma árvore
    assert nos.pac.str.len().isin([19, 20]).all() and nos.ctmt.nunique() == 6


def test_ms_fumaca_saidas_so_em_subpastas_ems(ms_completo):
    assert not (ms_completo / "reports" / "curva_k.csv").exists() and not (ms_completo / "data" / "processed").exists()
    arquivos = {p.name for p in (ms_completo / "reports" / "ems").iterdir()}
    assert {
        "qualidade_topologia.json",
        "porta_qualidade.json",
        "diagnostico.json",
        "zonas.csv",
        "alimentadores.csv",
        "desempenho_2026.json",
        "backtest.json",
        "backtest_instalacoes.csv",
        "curva_k.csv",
        "lista_priorizada.csv",
        "otimizacao.json",
        "sensibilidade.csv",
        "figures",
    } <= arquivos
    fig = {p.name for p in (ms_completo / "reports" / "ems" / "figures").iterdir()}
    assert fig == {
        "01_curva_k.png",
        "02_mapa.png",
        "03_zonas.png",
        "04_elementos_2026.png",
        "05_backtest.png",
        "06_seletividade.png",
    }


def test_ms_fumaca_modelo_usa_o_historico_com_o_nome_completado(ms_completo):
    """Com o nome de 5 caracteres sem zero, o histórico ficaria vazio e o modelo, zerado."""
    al = pd.read_csv(ms_completo / "reports" / "ems" / "alimentadores.csv")
    assert set(al.NOME) == set(NOMES_MS)
    assert (al.falhas_ano > 0).all() and (al.chi_ano > 0).all() and al.ci_modelo.gt(0).all()


def test_ms_fumaca_origem_do_efeito_em_toda_saida_que_le_o_valor_json(ms_completo):
    rel = ms_completo / "reports" / "ems"
    for js in ["backtest.json", "otimizacao.json"]:
        assert json.loads((rel / js).read_text())["origem_efeito"] == ROTULO, js
    assert list(json.loads((rel / "backtest.json").read_text()))[0] == "origem_efeito"
    for csv in ["backtest_instalacoes.csv", "curva_k.csv", "sensibilidade.csv", "lista_priorizada.csv"]:
        d = pd.read_csv(rel / csv)
        assert len(d) > 0 and set(d.origem_efeito) == {ROTULO}, csv
    bt = json.loads((rel / "backtest.json").read_text())
    assert "não valida" in bt["nota_comparacao_did"] or "nao valida" in bt["nota_comparacao_did"].lower()
    assert "origem_efeito" not in json.loads((rel / "diagnostico.json").read_text())  # o que não lê o valor.json não é rotulado


def test_ms_fumaca_backtest_localiza_os_religadores_novos_de_2025(ms_completo):
    bt = json.loads((ms_completo / "reports" / "ems" / "backtest.json").read_text())
    assert bt["anos"] == [2024, 2025] and bt["religadores_novos"] == 3 and bt["localizados_na_rede_anterior"] == 3
    # dois novos têm DAT_CON de 2025 e um de 2019: a sensibilidade pré-registrada fica só com os dois primeiros
    assert bt["religadores_novos_com_data_de_conexao_recente"] == 2
    s = bt["sensibilidade_dat_con_no_periodo"]
    assert s["anos_dat_con"] == [2024, 2025] and s["religadores_novos"] == 2 and s["localizados_na_rede_anterior"] == 2
    assert 0 <= bt["frac_com_ganho_no_modelo"] <= 1 and bt["chi_evitado_ano_did_por_religador"] == 100.0
    inst = pd.read_csv(ms_completo / "reports" / "ems" / "backtest_instalacoes.csv")
    assert (inst.dist_no_m < 1).all()  # o religador novo está no PAC de um nó da rede de 2024, em UTM 21S nos dois lados
    assert inst.x.max() > 1_000_000  # inclui o caso de 20 caracteres


def test_ms_fumaca_otimizacao_e_lista(ms_completo):
    rel = ms_completo / "reports" / "ems"
    lista = pd.read_csv(rel / "lista_priorizada.csv")
    assert len(lista) >= 2 and lista.chi_evitado_ano.is_monotonic_decreasing and set(lista.alimentador) <= set(NOMES_MS)
    assert lista.lon.between(-58.2, -50.9).all() and lista.lat.between(-24.1, -17.1).all()  # lon/lat em MS, pelo crs_pac
    curva = pd.read_csv(rel / "curva_k.csv")
    assert set(curva.k) == {2, 4} and (curva.dec_min > 0).all()
    ot = json.loads((rel / "otimizacao.json").read_text())
    assert ot["premissas"]["uc_total_dec"] > 0 and ot["origem_efeito"] == ROTULO


def test_ms_fumaca_seletividade_e_descritiva_e_lista_todos_os_elementos(ms_completo):
    rel = ms_completo / "reports" / "ems"
    el = pd.read_csv(rel / "desempenho_elemento_2026.csv").set_index("elemento")
    assert {"DISJUNTOR", "RELIGADOR", "CHAVE FUSIVEL", "MEDIDOR", "NAO IDENTIFICADO"} <= set(el.index)
    d = json.loads((rel / "desempenho_2026.json").read_text())
    assert d["seletividade"]["alimentadores_elegiveis"] >= 1 and d["cobertura_vinculo_alimentador"] == 1.0


# ---------------------------------------------------------------- a porta de qualidade
def test_porta_reprovada_so_deixa_diagnostico_e_a_causa(tmp_path, monkeypatch):
    arq = _montar(tmp_path, monkeypatch, quebrar=(2024, 2025))
    rodar("01_topologia.py", arq, monkeypatch)
    rel = tmp_path / "reports" / "ems"
    porta = json.loads((rel / "porta_qualidade.json").read_text())
    assert not porta["2024"]["passou"] and not porta["2025"]["passou"] and porta["2025"]["valor"] < 0.95
    for s in ["02_diagnostico.py", "03_desempenho_2026.py", "04_backtest.py", "05_otimizacao.py"]:
        with pytest.raises(SystemExit, match="PORTA DE QUALIDADE"):
            rodar(s, arq, monkeypatch)
    rodar("06_figuras.py", arq, monkeypatch)  # sem resultado de rede, desenha só o que existe (nada)
    publicado = {p.name for p in rel.iterdir()}
    assert publicado == {"qualidade_topologia.json", "porta_qualidade.json", "figures"}
    assert list((rel / "figures").iterdir()) == []
    rodar("diagnostico_topologia.py", arq, monkeypatch)  # a causa: clientes de circuitos sem saída na rede
    d = json.loads((rel / "diagnostico" / "topologia_2025.json").read_text())
    perda = d["clientes_nao_alcancados"]
    assert perda["total"] > 0 and perda["lacuna_acima_do_limite"] == perda["total"]  # trechos a ~7 km da (falsa) saída
    assert d["antes_do_reparo"]["frac_uc_alcancadas"] < 0.95 and len(d["circuitos_com_mais_perda"]) == 3


def test_porta_de_2024_reprovada_bloqueia_so_o_backtest(tmp_path, monkeypatch):
    arq = _montar(tmp_path, monkeypatch, quebrar=(2024,))
    rodar("01_topologia.py", arq, monkeypatch)
    with pytest.raises(SystemExit, match="2024"):
        rodar("04_backtest.py", arq, monkeypatch)
    for s in ["02_diagnostico.py", "03_desempenho_2026.py", "05_otimizacao.py"]:
        rodar(s, arq, monkeypatch)  # a rede de 2025 passou e libera as saídas dela
    rel = tmp_path / "reports" / "ems"
    assert (rel / "lista_priorizada.csv").exists() and not (rel / "backtest.json").exists()


def test_porta_de_2025_reprovada_bloqueia_o_posicionamento_mas_nao_o_backtest(tmp_path, monkeypatch):
    arq = _montar(tmp_path, monkeypatch, quebrar=(2025,))
    rodar("01_topologia.py", arq, monkeypatch)
    for s in ["02_diagnostico.py", "03_desempenho_2026.py", "05_otimizacao.py"]:
        with pytest.raises(SystemExit, match="2025"):
            rodar(s, arq, monkeypatch)
    rodar("04_backtest.py", arq, monkeypatch)  # usa a rede de 2024 e só a posição dos religadores de 2025
    rel = tmp_path / "reports" / "ems"
    assert (rel / "backtest.json").exists() and not (rel / "lista_priorizada.csv").exists()


def test_ms_sem_origem_no_valor_json_nao_roda(tmp_path, monkeypatch):
    arq = _montar(tmp_path, monkeypatch)
    v = json.loads((tmp_path / "valor.json").read_text())
    del v["origem_efeito"]
    (tmp_path / "valor.json").write_text(json.dumps(v))
    rodar("01_topologia.py", arq, monkeypatch)
    for s in ["04_backtest.py", "05_otimizacao.py"]:
        with pytest.raises(ValueError, match="origem_efeito"):
            rodar(s, arq, monkeypatch)


# ---------------------------------------------------------------- MT: mesma rede, configuração no formato de MT
def test_mt_com_configuracao_padrao_nao_ganha_rotulo_nem_campo(tmp_path, monkeypatch):
    arq = _montar(tmp_path, monkeypatch, ms=False)
    cfg = config.carregar(arq)
    assert config.porta_minima(cfg) is None and not cfg.get("exigir_origem_efeito") and "paths" not in cfg
    rodar_tudo(arq, monkeypatch)
    rel = tmp_path / "reports"  # MT: reports/ e data/processed (caminhos padrão)
    assert (rel / "qualidade_topologia.json").exists() and (tmp_path / "data" / "processed" / "nos_2025.parquet").exists()
    assert not (rel / "porta_qualidade.json").exists() and not (rel / "ems").exists()
    for js in ["backtest.json", "otimizacao.json", "diagnostico.json"]:
        assert "origem_efeito" not in json.loads((rel / js).read_text()), js
    bt = json.loads((rel / "backtest.json").read_text())
    assert "sensibilidade_dat_con_no_periodo" not in bt and "nota_comparacao_did" not in bt
    assert list(bt)[:3] == ["anos", "anos_taxa_de_falhas", "religadores_novos"]
    for csv in ["backtest_instalacoes.csv", "curva_k.csv", "sensibilidade.csv", "lista_priorizada.csv"]:
        assert "origem_efeito" not in pd.read_csv(rel / csv).columns, csv
    assert list(pd.read_csv(rel / "lista_priorizada.csv").columns) == [
        "passo",
        "alimentador",
        "ctmt",
        "subestacao_bdgd",
        "tipo",
        "uc_jusante",
        "km_jusante_zona",
        "chi_evitado_ano",
        "dec_min",
        "rs_ano_social",
        "rs_ano_compensacao",
        "payback_social_anos",
        "vpl_social_rs",
        "lon",
        "lat",
        "pac",
    ]
    assert list(pd.read_csv(rel / "curva_k.csv").columns) == [
        "k",
        "metodo",
        "chi_evitado_ano",
        "dec_min",
        "rs_ano_social",
        "rs_ano_compensacao",
        "investimento_rs",
        "vpl_social_rs",
        "vpl_compensacao_rs",
    ]
    al = pd.read_csv(rel / "alimentadores.csv", dtype={"NOME": str})
    assert set(al.NOME) == set(NOMES_MT) and (al.falhas_ano > 0).all()  # em MT o nome do cadastro já é a chave, sem completar
