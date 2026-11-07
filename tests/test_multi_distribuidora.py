"""Multi-distribuidora: a configuração padrão é a de MT, a de MS só muda caminhos e recortes, a decodificação do PAC vale em MS,
a porta de qualidade e o rótulo de origem do efeito funcionam. Sem dados reais."""

import json
import zipfile
from pathlib import Path

import numpy as np
import pandas as pd
import pyogrio
import pytest
import yaml
from pyproj import Transformer

from recloser import bdgd, config, dados, diagnostico, topologia

RAIZ = config.ROOT
IDS_MS = {  # snapshots de 31/12 de MS (versão mais recente de cada ano), conforme a REGRAS_MS
    2018: "5382c59d7cc7494a9a1f8cd865187457",
    2019: "b83ad867a35b43189f41b68988f7f0b6",
    2020: "fe56dce0714f4b6795d3b23130f5898a",
    2021: "933af69c57dd41ea8f6048118b8d07e7",
    2022: "ff5242147c86428e88971941a35c7cd1",
    2023: "975f18dfdb0c479cb237893c5b296ca9",
    2024: "b7fad4cd388845a08a01643599ec747b",
    2025: "9a1ce360865f4358b31e9fb2d016aac9",
}
NAO_USAR = {"b8c585ae35224ac8aa0648587ec61bcb", "c3585ae516f340b596617827d60da5ef"}  # 2023 de 17/12/2024; item avulso de 2022


@pytest.fixture(autouse=True)
def _sem_variavel_de_ambiente(monkeypatch):
    monkeypatch.delenv(config.VARIAVEL_AMBIENTE, raising=False)


# ---------------------------------------------------------------- guarda de MT: a configuração padrão resolve os caminhos atuais
def test_configuracao_padrao_resolve_exatamente_os_caminhos_de_mt():
    cfg = config.carregar()
    assert cfg["arquivo_config"] == RAIZ / "configs" / "params.yaml"
    assert cfg["distribuidora"] == "EMT" and config.nome(cfg) == "Energisa MT"
    assert cfg["cache_bdgd"] == RAIZ / "data" / "bdgd"
    assert cfg["falhas"] == (RAIZ / ".." / "distribution-asset-risk" / "data" / "interim" / "falhas.parquet").resolve()
    assert (
        cfg["interrupcoes"]
        == (RAIZ / ".." / "distribution-asset-risk" / "data" / "interim" / "interrupcoes_emt.parquet").resolve()
    )
    assert cfg["valor_json"] == (RAIZ / ".." / "automation-impact" / "reports" / "valor.json").resolve()
    assert config.pasta_relatorios(cfg) == RAIZ / "reports"
    assert config.pasta_processada(cfg) == RAIZ / "data" / "processed"
    assert config.pasta_ano(cfg, 2025) == RAIZ / "data" / "bdgd" / "2025"
    assert config.crs_pac(cfg) == 31981
    assert config.porta_minima(cfg) is None and "origem_efeito" not in cfg and not cfg.get("exigir_origem_efeito")
    assert cfg.get("alimentador", {}).get("largura_nome", 0) == 0 and "bdgd" not in cfg
    assert (
        cfg["ano_atual"] == 2025
        and cfg["ano_backtest"] == 2024
        and cfg["snapshots_bdgd"][2025] == "02a120db1b5149709f8d371c21635adc"
    )


def test_padrao_do_codigo_sem_chaves_novas_e_o_de_mt():
    """Uma configuração antiga, sem nenhuma chave nova (paths, nome, crs_pac...), continua resolvendo para MT."""
    antigo = {
        k: v
        for k, v in yaml.safe_load((RAIZ / "configs" / "params.yaml").read_text(encoding="utf-8")).items()
        if k not in {"paths", "nome", "crs_pac", "qualidade", "alimentador"}
    }
    assert config.pasta_relatorios(antigo) == RAIZ / "reports" and config.pasta_processada(antigo) == RAIZ / "data" / "processed"
    assert config.nome(antigo) == "Energisa MT" and config.crs_pac(antigo) == 31981 and config.porta_minima(antigo) is None


def test_pac_xy_padrao_igual_ao_de_mt():
    """``pac_xy`` não mudou: confere contra a implementação original em PAC de 19 e de 20 caracteres, inválidos e vazios."""

    def original(pac):
        s = pac.astype("string").str.strip()
        ok = s.str.len().isin([19, 20]) & s.str[:-2].str.isdigit().fillna(False)
        corpo = s.where(ok).str[:-2]
        return (pd.to_numeric(corpo.str[:-9], errors="coerce") / 100).to_numpy(float), (
            pd.to_numeric(corpo.str[-9:], errors="coerce") / 100
        ).to_numpy(float)

    rng = np.random.default_rng(1)
    pac = pd.Series(
        [f"{rng.integers(10**7, 2 * 10**8)}{rng.integers(7 * 10**8, 9 * 10**8)}{s}" for s in ["MT", "ET"] * 500]
        + ["", "abc", "00613646", None, "1234567890123456XYZ", " 56097953840439966MT "]
    )
    ax, ay = original(pac)
    bx, by = topologia.pac_xy(pac)
    np.testing.assert_array_equal(ax, bx)
    np.testing.assert_array_equal(ay, by)


# ---------------------------------------------------------------- MS: configuração
def test_configuracao_de_ms_so_escreve_em_subpastas_ems():
    cfg = config.carregar("configs/params_ems.yaml")
    assert cfg["arquivo_config"] == RAIZ / "configs" / "params_ems.yaml" and config.nome(cfg) == "Energisa MS"
    assert config.pasta_relatorios(cfg) == RAIZ / "reports" / "ems"
    assert config.pasta_processada(cfg) == RAIZ / "data" / "ems" / "processed"
    assert cfg["cache_bdgd"] == RAIZ / "data" / "ems" / "bdgd"
    base = (RAIZ / ".." / "distribution-asset-risk" / "data" / "ems" / "interim").resolve()
    assert cfg["falhas"] == base / "falhas.parquet" and cfg["interrupcoes"] == base / "interrupcoes_ems.parquet"
    assert cfg["valor_json"] == (RAIZ / ".." / "automation-impact" / "reports" / "ems" / "valor.json").resolve()
    assert cfg["alimentador"]["largura_nome"] == 6 and config.crs_pac(cfg) == 31981 and config.porta_minima(cfg) == 0.95
    assert cfg["exigir_origem_efeito"] is True
    for p in [config.pasta_relatorios(cfg), config.pasta_processada(cfg), cfg["cache_bdgd"]]:
        assert "ems" in p.relative_to(RAIZ).parts  # nada de MS na raiz de reports/ nem de data/


def test_ms_usa_os_oito_snapshots_certos():
    cfg = config.carregar("configs/params_ems.yaml")
    assert cfg["snapshots_bdgd"] == IDS_MS
    assert not (set(cfg["snapshots_bdgd"].values()) & NAO_USAR)
    assert cfg["ano_atual"] == 2025 and cfg["ano_backtest"] == 2024


def test_ms_mantem_as_premissas_de_mt():
    """Nada foi recalibrado para MS: tudo, menos caminhos, nomes e a porta, é igual ao de MT."""
    mt, ms = config.carregar(), config.carregar("configs/params_ems.yaml")
    for chave in ["tip_unid", "topologia", "confiabilidade", "otimizacao", "valor"]:
        assert ms[chave] == mt[chave], chave
    for chave in ["raio_novo_m", "raio_localizacao_m"]:
        assert ms["backtest"][chave] == mt["backtest"][chave]


def test_variavel_de_ambiente_e_argumento(monkeypatch):
    monkeypatch.setenv(config.VARIAVEL_AMBIENTE, "configs/params_ems.yaml")
    assert config.carregar()["distribuidora"] == "EMS"
    assert config.carregar("configs/params.yaml")["distribuidora"] == "EMT"  # o argumento vale mais que a variável
    monkeypatch.delenv(config.VARIAVEL_AMBIENTE)
    assert config.carregar()["distribuidora"] == "EMT"


def test_argumentos_da_linha_de_comando(monkeypatch):
    monkeypatch.setattr("sys.argv", ["x.py", "--config", "configs/params_ems.yaml"])
    cfg, args = config.argumentos("teste")
    assert cfg["distribuidora"] == "EMS" and args.config == "configs/params_ems.yaml"
    monkeypatch.setattr("sys.argv", ["x.py"])
    assert config.argumentos("teste")[0]["distribuidora"] == "EMT"


# ---------------------------------------------------------------- PAC: decodificação com casos reais de MS
# (PAC, longitude, latitude) de trafos da BDGD de 2025 de MS
CASOS_MS = [
    ("40852670760024832ET", -57.88430933780563, -21.698815573679724),  # 19 caracteres, oeste
    ("42721345758317862MT", -57.704421365453584, -21.853890429699504),  # 19 caracteres, oeste (chave de 2025)
    ("80114760738846937MT", -54.04943677958369, -23.586306292501376),  # 19 caracteres, junto à fronteira 21S/22S
    ("100305396758257012ET", -52.13785020862019, -21.789191677353983),  # 20 caracteres, leste: X > 1.000.000 m
    ("102994510779841840ET", -51.94408169241615, -19.83869942923525),  # 20 caracteres, extremo leste
]


@pytest.mark.parametrize(("pac", "lon", "lat"), CASOS_MS)
def test_pac_de_ms_e_utm_21s_para_o_estado_todo(pac, lon, lat):
    x, y = topologia.pac_xy(pd.Series([pac]))
    gx, gy = Transformer.from_crs(4326, 31981, always_xy=True).transform(lon, lat)
    assert np.hypot(x[0] - gx, y[0] - gy) < 0.05  # no fuso 21S, a menos de 5 cm do ponto da BDGD
    # em qualquer outro fuso a coordenada decodificada fica a centenas de km
    for epsg in (31980, 31982, 31983):
        ox, oy = Transformer.from_crs(4326, epsg, always_xy=True).transform(lon, lat)
        assert np.hypot(x[0] - ox, y[0] - oy) > 500_000
    d = diagnostico.distancias(pd.Series([pac]), np.array([lon]), np.array([lat]), 31981)
    assert d[0] < 0.05
    assert len(pac) == (20 if x[0] >= 1_000_000 else 19)  # 20 caracteres <=> X com 9 dígitos <=> X >= 1.000.000 m


def test_pac_de_20_caracteres_nao_e_lido_como_x_de_8_digitos():
    x, y = topologia.pac_xy(pd.Series(["100305396758257012ET", "40852670760024832ET"]))
    assert x == pytest.approx([1_003_053.96, 408_526.70]) and y == pytest.approx([7_582_570.12, 7_600_248.32])


def test_diagnostico_resume_distancias_e_plausibilidade():
    d = diagnostico.resumo_distancias(np.array([0.0, 0.5, 49.0, 99.0, 300.0, np.nan]))
    assert d["n"] == 5 and d["frac_ate_1m"] == pytest.approx(0.4) and d["frac_ate_50m"] == pytest.approx(0.6)
    assert d["frac_ate_100m"] == pytest.approx(0.8) and d["max_m"] == 300
    assert diagnostico.resumo_distancias(np.array([np.nan])) == {"n": 0}
    f = diagnostico.formato_pac(
        pd.Series(["42721345758317862MT", "100305396758257012ET", "00613646", "1234567890123456XYZ", None])
    )
    assert f.coordenada.tolist() == [True, True, False, False, False]
    # o 21S estendido a leste faz sentido; ler o mesmo PAC como 22S joga o ponto para fora de MS
    lon21, lat21 = diagnostico.lonlat_do_pac(pd.Series(["100305396758257012ET"]), 31981)
    lon22, _ = diagnostico.lonlat_do_pac(pd.Series(["100305396758257012ET"]), 31982)
    assert -52.2 < lon21[0] < -52.0 and lon22[0] > -47
    assert 0.9995 < diagnostico.fator_escala(-57, -21, 31981) < 1.0005 and diagnostico.fator_escala(
        -51, -20, 31981
    ) == pytest.approx(1.0045, abs=2e-4)


# ---------------------------------------------------------------- chave do alimentador
def test_nome_do_circuito_de_ms_precisa_de_zero_a_esquerda():
    ctmt = pd.DataFrame({"COD_ID": ["10", "11", "12"], "NOME": ["RBR53", "CGP01", " AJO51"]})
    falhas = pd.DataFrame(
        {
            "alimentador": ["0RBR53", "0CGP01", "0AJO51", "0XXX99"],
            "ano": 2025,
            "mes": 1,
            "modo": "OUTRAS",
            "n_falhas": [3, 6, 9, 12],
            "ci": 1.0,
            "chi": 2.0,
            "chi_regulatorio": 1.0,
        }
    )
    import tempfile

    with tempfile.TemporaryDirectory() as t:
        falhas.to_parquet(Path(t) / "f.parquet")
        sem = dados.historico_alimentador(Path(t) / "f.parquet", ctmt, [2025])
        com = dados.historico_alimentador(Path(t) / "f.parquet", ctmt, [2025], largura_nome=6)
    assert sem.empty  # sem completar, nenhuma falha casa e o modelo zera
    assert com.falhas_ano.to_dict() == {"10": 3.0, "11": 6.0, "12": 9.0}


def test_nome_de_mt_nao_muda_com_a_largura_padrao():
    ctmt = pd.DataFrame({"COD_ID": ["10", "11"], "NOME": ["013014", "013015"]})
    falhas = pd.DataFrame(
        {
            "alimentador": ["013014", "013015", "01301499"],
            "ano": 2025,
            "mes": 1,
            "modo": "OUTRAS",
            "n_falhas": [3, 6, 9],
            "ci": 1.0,
            "chi": 2.0,
            "chi_regulatorio": 1.0,
        }
    )
    import tempfile

    with tempfile.TemporaryDirectory() as t:
        falhas.to_parquet(Path(t) / "f.parquet")
        a = dados.historico_alimentador(Path(t) / "f.parquet", ctmt, [2025])
        b = dados.historico_alimentador(Path(t) / "f.parquet", ctmt, [2025], largura_nome=6)
    pd.testing.assert_frame_equal(a, b)
    assert dados.nome_canonico(pd.Series([" RBR53", "013014"]), 6).tolist() == ["0RBR53", "013014"]


# ---------------------------------------------------------------- porta de qualidade
def _cfg_porta(tmp_path, minimo):
    cfg = {"paths": {"reports": "rel"}}
    if minimo is not None:
        cfg["qualidade"] = {"min_frac_uc_alcancadas": minimo}
    return cfg


def _grava_qualidade(tmp_path, monkeypatch, valores):
    monkeypatch.setattr(config, "ROOT", tmp_path)
    (tmp_path / "rel").mkdir(exist_ok=True)
    (tmp_path / "rel" / "qualidade_topologia.json").write_text(
        json.dumps({str(a): {"frac_uc_alcancadas": v} for a, v in valores.items()})
    )


def test_porta_passa_quando_atinge_o_minimo(tmp_path, monkeypatch):
    _grava_qualidade(tmp_path, monkeypatch, {2025: 0.95, 2024: 0.999})
    cfg = _cfg_porta(tmp_path, 0.95)
    assert config.veredito_porta(cfg, 2025)["passou"] and config.veredito_porta(cfg, 2024)["passou"]
    config.exigir_porta(cfg, 2025)  # não levanta


def test_porta_para_quando_nao_atinge_o_minimo(tmp_path, monkeypatch):
    _grava_qualidade(tmp_path, monkeypatch, {2025: 0.9499, 2024: 0.99})
    cfg = _cfg_porta(tmp_path, 0.95)
    v = config.veredito_porta(cfg, 2025)
    assert not v["passou"] and v["valor"] == pytest.approx(0.9499) and v["minimo"] == 0.95
    with pytest.raises(SystemExit, match="PORTA DE QUALIDADE"):
        config.exigir_porta(cfg, 2025)
    config.exigir_porta(cfg, 2024)  # cada ano na sua análise: 2024 passa e libera o backtest


def test_porta_recusa_sem_o_arquivo_de_qualidade(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "ROOT", tmp_path)
    with pytest.raises(SystemExit, match="01_topologia"):
        config.exigir_porta(_cfg_porta(tmp_path, 0.95), 2025)
    _grava_qualidade(tmp_path, monkeypatch, {2025: 0.99})
    with pytest.raises(SystemExit):  # o ano pedido não está no arquivo
        config.exigir_porta(_cfg_porta(tmp_path, 0.95), 2024)


def test_mt_nao_tem_porta(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "ROOT", tmp_path)  # nem arquivo de qualidade existe
    cfg = _cfg_porta(tmp_path, None)
    assert config.porta_minima(cfg) is None and config.veredito_porta(cfg, 2025)["passou"]
    config.exigir_porta(cfg, 2025)


# ---------------------------------------------------------------- rótulo de origem do efeito
VALOR = {
    "rs_por_chi_social": 5.5,
    "rs_por_chi_compensacao": 2.1,
    "frac_chi_regulatorio": 0.5,
    "uc_total": 1e6,
    "chi_evitado_ano_por_religador": 3000.0,
    "chi_evitado_ano_por_religador_ic95": [1000.0, 5000.0],
    "efeito_chi_pct": -16.5,
}


def test_origem_do_efeito_e_exigida_e_repetida(tmp_path):
    ms, mt = tmp_path / "ms.json", tmp_path / "mt.json"
    ms.write_text(json.dumps({"origem_efeito": "transportado de MT", **VALOR}))
    mt.write_text(json.dumps(VALOR))
    v = dados.valoracao(ms, exigir_origem=True)
    assert v["origem_efeito"] == "transportado de MT" and dados.rotulo(v) == {"origem_efeito": "transportado de MT"}
    tabela = pd.DataFrame({"a": [1, 2]})
    assert dados.rotular_tabela(tabela, v).origem_efeito.tolist() == ["transportado de MT"] * 2
    assert "origem_efeito" not in tabela  # a tabela original não é alterada
    with pytest.raises(ValueError, match="origem_efeito"):
        dados.valoracao(mt, exigir_origem=True)  # MS não roda sem o rótulo
    vmt = dados.valoracao(mt)  # MT: sem rótulo, saídas iguais às de antes
    assert "origem_efeito" not in vmt and dados.rotulo(vmt) == {}
    assert dados.rotular_tabela(tabela, vmt) is tabela
    assert {k: v[k] for k in vmt} == vmt  # as demais chaves são as mesmas nos dois


def test_valor_json_de_ms_publicado_tem_o_mesmo_esquema_de_mt_mais_a_origem():
    """Se o clone irmão está ao lado, confere o ``valor.json`` de MS (origem transportada) contra o que este repositório lê."""
    p = (RAIZ / ".." / "automation-impact" / "reports" / "ems" / "valor.json").resolve()
    if not p.exists():
        pytest.skip("automation-impact de MS não está ao lado")
    v = dados.valoracao(p, exigir_origem=True)
    assert v["origem_efeito"] == "transportado de MT" and v["uc_total"] > 1e6


# ---------------------------------------------------------------- BDGD a partir de zip local
def _gdb_sintetico(pasta: Path) -> Path:
    import geopandas as gpd
    from shapely.geometry import LineString, Point

    gdb = pasta / "Energisa_MS_404_2025-12-31_V11_teste.gdb"
    pac = "40852670760024832"
    ponto = Point(-57.8843, -21.6988)
    gpd.GeoDataFrame(
        {
            "COD_ID": ["1", "2"],
            "PAC_1": [pac + "MT"] * 2,
            "PAC_2": [pac + "MT"] * 2,
            "CTMT": ["9", "9"],
            "COMP": [10.0, 20.0],
            "SUB": ["S", "S"],
        },
        geometry=[LineString([(-57.8843, -21.6988), (-57.8842, -21.6987)])] * 2,
        crs=4674,
    ).to_file(gdb, layer="SSDMT", driver="OpenFileGDB")
    gpd.GeoDataFrame(
        {
            "COD_ID": ["1"],
            "PAC_1": [pac + "ET"],
            "PAC_2": [pac + "ET"],
            "TIP_UNID": ["32"],
            "P_N_OPE": ["F"],
            "TLCD": [1],
            "COR_NOM": ["12"],
            "CTMT": ["9"],
            "SUB": ["S"],
            "DAT_CON": ["01/02/2025"],
        },
        geometry=[ponto],
        crs=4674,
    ).to_file(gdb, layer="UNSEMT", driver="OpenFileGDB")
    gpd.GeoDataFrame(
        {"COD_ID": ["1"], "PAC_1": [pac + "ET"], "PAC_2": [pac + "ET"], "CTMT": ["9"], "SUB": ["S"]}, geometry=[ponto], crs=4674
    ).to_file(gdb, layer="UNREMT", driver="OpenFileGDB")
    gpd.GeoDataFrame(
        {"COD_ID": ["t1"], "PAC_1": [pac + "ET"], "PAC_2": [pac + "ET"], "CTMT": ["9"], "POT_NOM": [75.0]},
        geometry=[ponto],
        crs=4674,
    ).to_file(gdb, layer="UNTRMT", driver="OpenFileGDB")
    tabelas = {
        "CTMT": {"COD_ID": ["9"], "NOME": ["RBR53"], "SUB": ["S"], "PAC_INI": [pac + "MT"]},
        "UCBT_tab": {"UNI_TR_MT": ["t1", "t1", "t2"], "CTMT": ["9", "9", "9"]},
        "UCMT_tab": {"PAC": [pac + "MT"], "CTMT": ["9"]},
        "EQSE": {"COD_ID": ["x"], "OUTRA": [1]},  # camada que o estudo não usa
    }
    for nome, colunas in tabelas.items():  # tabelas sem geometria
        pyogrio.write_dataframe(pd.DataFrame(colunas), gdb, layer=nome, driver="OpenFileGDB")
    return gdb


@pytest.fixture(scope="module")
def zip_sintetico(tmp_path_factory):
    base = tmp_path_factory.mktemp("bdgd")
    gdb = _gdb_sintetico(base)
    z = base / "bdgd_2025_item.gdb.zip"
    with zipfile.ZipFile(z, "w", zipfile.ZIP_DEFLATED) as zf:
        for p in sorted(gdb.rglob("*")):
            zf.write(p, p.relative_to(base).as_posix())
    return z


def test_extrai_so_as_camadas_pedidas_sem_alterar_o_zip(zip_sintetico, tmp_path):
    antes = zip_sintetico.stat().st_mtime_ns, zip_sintetico.stat().st_size
    nums = bdgd.numeros_das_camadas(zip_sintetico)
    assert {"SSDMT", "UNSEMT", "UCBT_tab", "EQSE"} <= set(nums)
    gdb = bdgd.extrair_camadas(zip_sintetico, tmp_path / "raw", bdgd.LAYERS)
    assert gdb.name.endswith(".gdb") and gdb.is_dir()
    extraidos = {p.name.split(".")[0] for p in gdb.iterdir() if p.name.startswith("a")}
    assert f"a{nums['EQSE']:08x}" not in extraidos  # camada que o estudo não usa não é extraída
    for c in bdgd.LAYERS:
        assert f"a{nums[c]:08x}" in extraidos
    with pytest.raises(KeyError, match="camadas ausentes"):
        bdgd.extrair_camadas(zip_sintetico, tmp_path / "raw2", ["NAO_EXISTE"])
    assert (zip_sintetico.stat().st_mtime_ns, zip_sintetico.stat().st_size) == antes  # o cache é somente leitura


def test_grava_parquet_com_lon_lat_e_extremos(zip_sintetico, tmp_path):
    gdb = bdgd.extrair_camadas(zip_sintetico, tmp_path / "raw", bdgd.LAYERS)
    bdgd.gravar_camadas(gdb, tmp_path / "saida", extremos_segmentos=True)
    unsemt = pd.read_parquet(tmp_path / "saida" / "UNSEMT.parquet")
    assert unsemt.lon.iloc[0] == pytest.approx(-57.8843, abs=1e-6) and unsemt.lat.iloc[0] == pytest.approx(-21.6988, abs=1e-6)
    seg = pd.read_parquet(tmp_path / "saida" / "SSDMT.parquet")
    assert {"lon1", "lat1", "lon2", "lat2"} <= set(seg.columns) and seg.lon2.iloc[0] == pytest.approx(-57.8842, abs=1e-6)
    uc = pd.read_parquet(tmp_path / "saida" / "UCBT_tab_agg.parquet").set_index("UNI_TR_MT").n_uc
    assert uc.to_dict() == {"t1": 2, "t2": 1}
    assert pd.read_parquet(tmp_path / "saida" / "CTMT.parquet").NOME.tolist() == ["RBR53"]
    bdgd.gravar_camadas(gdb, tmp_path / "saida_mt")  # sem extremos (MT): a camada de segmentos não ganha colunas
    assert "lon1" not in pd.read_parquet(tmp_path / "saida_mt" / "SSDMT.parquet").columns


def test_script_00_le_o_zip_local_e_nao_baixa(zip_sintetico, tmp_path, monkeypatch):
    import runpy
    import sys

    cfg = yaml.safe_load((RAIZ / "configs" / "params_ems.yaml").read_text(encoding="utf-8"))
    cfg.update(
        cache_bdgd=str(tmp_path / "ems" / "bdgd"),
        bdgd={"zips": str(zip_sintetico.parent), "extremos_segmentos": True},
        snapshots_bdgd={2024: "item", 2025: "item"},
        falhas=str(tmp_path / "f"),
        interrupcoes=str(tmp_path / "i"),
        valor_json=str(tmp_path / "v"),
    )
    arq = tmp_path / "c.yaml"
    arq.write_text(yaml.safe_dump(cfg), encoding="utf-8")
    monkeypatch.setattr(sys, "argv", ["00_cache_bdgd.py", "--config", str(arq), "2025"])
    import requests

    monkeypatch.setattr(requests, "get", lambda *a, **k: pytest.fail("não deve baixar nada"))
    runpy.run_path(str(RAIZ / "scripts" / "00_cache_bdgd.py"), run_name="__main__")
    saida = tmp_path / "ems" / "bdgd" / "2025"
    assert {p.name for p in saida.iterdir()} >= {"SSDMT.parquet", "UNSEMT.parquet", "UCBT_tab_agg.parquet", "CTMT.parquet"}
    assert not (tmp_path / "ems" / "raw" / "2025").exists()  # a extração temporária é apagada
