"""Diagnóstico: que referência a codificação do PAC usa? (e se o casamento a 50 m / 100 m vale)

Para cada snapshot, decodifica os PAC de 19 a 20 caracteres como coordenada (``topologia.pac_xy``) e compara com a
geometria da BDGD (trafos, chaves e extremos dos segmentos) em cada referência candidata: UTM 20S, 21S, 22S e 23S, e
"o fuso natural de cada ponto" (21S a oeste de 54 W, 22S a leste). Mede também o formato dos PAC, a plausibilidade
geográfica (dentro do estado) e o fator de escala. Não depende de resultado nenhum do estudo.

Saída: ``<reports>/diagnostico/pac_utm_<ano>.json`` e ``pac_utm_resumo.csv``.
Uso: ``python scripts/diagnostico_pac.py --config configs/params_ems.yaml``
"""

import json
import logging
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd

from recloser import config, diagnostico, topologia

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
cfg, _ = config.argumentos(__doc__)
OUT = config.pasta_relatorios(cfg) / "diagnostico"
OUT.mkdir(parents=True, exist_ok=True)
MERIDIANO_21S_22S = -54.0  # fronteira entre os fusos 21S e 22S
anos = sorted({cfg["ano_backtest"], cfg["ano_atual"]})

malha = cfg.get("referencias", {}).get("malha_uf")
estado = None
if malha:
    p = Path(malha)
    estado = gpd.read_file(p if p.is_absolute() else (config.ROOT / p).resolve()).geometry.union_all()

linhas = []


def registra(ano, camada, hipotese, regiao, d):
    linhas.append({"ano": ano, "camada": camada, "hipotese": hipotese, "regiao": regiao, **diagnostico.resumo_distancias(d)})


for ano in anos:
    d = config.pasta_ano(cfg, ano)
    tr = pd.read_parquet(d / "UNTRMT.parquet", columns=["PAC_1", "lon", "lat"])
    sw = pd.read_parquet(d / "UNSEMT.parquet", columns=["PAC_1", "PAC_2", "lon", "lat"])
    sg = pd.read_parquet(d / "SSDMT.parquet", columns=["PAC_1", "PAC_2", "COMP", "lon1", "lat1", "lon2", "lat2"])
    ct = pd.read_parquet(d / "CTMT.parquet", columns=["PAC_INI"])
    re_ = pd.read_parquet(d / "UNREMT.parquet", columns=["PAC_1", "PAC_2"])
    res: dict = {"ano": ano, "formato": {}, "referencias": {}, "plausibilidade_geografica": {}}

    # ---------------------------------------------------------------- formato dos PAC
    for nome, s in [
        ("UNTRMT.PAC_1", tr.PAC_1),
        ("UNSEMT.PAC_1", sw.PAC_1),
        ("UNSEMT.PAC_2", sw.PAC_2),
        ("SSDMT.PAC_1", sg.PAC_1),
        ("SSDMT.PAC_2", sg.PAC_2),
        ("CTMT.PAC_INI", ct.PAC_INI),
        ("UNREMT.PAC_1", re_.PAC_1),
    ]:
        f = diagnostico.formato_pac(s)
        res["formato"][nome] = {
            "n": int(len(s)),
            "frac_coordenada_19_20": float(f.coordenada.mean()),
            "comprimentos": {str(k): int(v) for k, v in f.comprimento.value_counts().sort_index().items()},
            "sufixos": {str(k): int(v) for k, v in f.sufixo.value_counts().head(6).items()},
        }
    # 20 caracteres <=> X com 9 dígitos <=> X >= 1.000.000 m (só existe se o fuso 21S for estendido a leste)
    for nome, s in [("UNTRMT.PAC_1", tr.PAC_1), ("SSDMT.PAC_1", sg.PAC_1)]:
        f = diagnostico.formato_pac(s)
        x, _y = topologia.pac_xy(s)
        ok = f.coordenada.to_numpy()
        res["formato"][nome]["x_min_m"], res["formato"][nome]["x_max_m"] = float(np.nanmin(x)), float(np.nanmax(x))
        res["formato"][nome]["comprimento_20_igual_a_x_acima_de_1e6_m"] = bool(
            ((f.comprimento.to_numpy() == 20) == (x >= 1e6))[ok].all()
        )
        res["formato"][nome]["frac_x_acima_de_1e6_m"] = float((x[ok] >= 1e6).mean())

    # ---------------------------------------------------------------- distância PAC x geometria, por referência
    pontos = {
        "UNTRMT.PAC_1 x ponto do trafo": (tr.PAC_1, tr.lon.to_numpy(), tr.lat.to_numpy()),
        "UNSEMT.PAC_1 x ponto da chave": (sw.PAC_1, sw.lon.to_numpy(), sw.lat.to_numpy()),
        "SSDMT.PAC_1 x 1o vértice": (sg.PAC_1, sg.lon1.to_numpy(), sg.lat1.to_numpy()),
        "SSDMT.PAC_2 x último vértice": (sg.PAC_2, sg.lon2.to_numpy(), sg.lat2.to_numpy()),
    }
    for camada, (pac, lon, lat) in pontos.items():
        oeste = lon <= MERIDIANO_21S_22S
        for nome, epsg in diagnostico.FUSOS.items():
            dist = diagnostico.distancias(pac, lon, lat, epsg)
            registra(ano, camada, f"UTM {nome} (estado todo)", "todo o estado", dist)
            if nome in ("21S", "22S"):
                registra(ano, camada, f"UTM {nome} (estado todo)", "oeste de 54 W", dist[oeste])
                registra(ano, camada, f"UTM {nome} (estado todo)", "leste de 54 W", dist[~oeste])
        natural = np.where(oeste, diagnostico.distancias(pac, lon, lat, 31981), diagnostico.distancias(pac, lon, lat, 31982))
        registra(ano, camada, "fuso natural de cada ponto (21S / 22S)", "todo o estado", natural)
    # segmento ligado nos dois extremos: o PAC_1 é o 1o vértice? e o comprimento COMP confere com a distância dos PAC?
    d1 = diagnostico.distancias(sg.PAC_1, sg.lon1.to_numpy(), sg.lat1.to_numpy(), 31981)
    d2 = diagnostico.distancias(sg.PAC_2, sg.lon2.to_numpy(), sg.lat2.to_numpy(), 31981)
    c1 = diagnostico.distancias(sg.PAC_1, sg.lon2.to_numpy(), sg.lat2.to_numpy(), 31981)
    c2 = diagnostico.distancias(sg.PAC_2, sg.lon1.to_numpy(), sg.lat1.to_numpy(), 31981)
    ambos = np.isfinite(d1) & np.isfinite(d2)
    registra(
        ano, "SSDMT (máximo dos dois extremos, PAC_1 no 1o vértice)", "UTM 21S (estado todo)", "todo o estado", np.maximum(d1, d2)
    )
    registra(ano, "SSDMT (máximo dos dois extremos, invertido)", "UTM 21S (estado todo)", "todo o estado", np.maximum(c1, c2))
    x1, y1 = topologia.pac_xy(sg.PAC_1)
    x2, y2 = topologia.pac_xy(sg.PAC_2)
    comp = pd.to_numeric(sg.COMP, errors="coerce").to_numpy()
    val = ambos & np.isfinite(comp) & (comp > 0)
    razao = np.hypot(x1 - x2, y1 - y2)[val] / comp[val]
    res["segmentos"] = {
        "n": int(len(sg)),
        "com_pac_valido_nos_dois_lados": float(ambos.mean()),
        "comp_valido": int(val.sum()),
        "dist_pac1_pac2_sobre_comp": {
            "mediana": float(np.median(razao)),
            "p5": float(np.percentile(razao, 5)),
            "p95": float(np.percentile(razao, 95)),
        },
        "pac_1_no_primeiro_vertice_ate_1m": float((np.maximum(d1, d2)[ambos] <= 1).mean()),
        "invertido_ate_1m": float((np.maximum(c1, c2)[ambos] <= 1).mean()),
    }

    # ---------------------------------------------------------------- plausibilidade geográfica
    nos = pd.concat([tr.PAC_1, sw.PAC_1, sg.PAC_1, sg.PAC_2]).drop_duplicates()
    for nome, epsg in diagnostico.FUSOS.items():
        lon, lat = diagnostico.lonlat_do_pac(nos, epsg)
        p = {
            "nos_unicos": int(np.isfinite(lon).sum()),
            "lon_min": float(np.nanmin(lon)),
            "lon_max": float(np.nanmax(lon)),
            "lat_min": float(np.nanmin(lat)),
            "lat_max": float(np.nanmax(lat)),
        }
        if estado is not None:
            p["frac_dentro_do_estado"] = diagnostico.dentro_do_estado(lon, lat, estado)
            p["frac_dentro_do_estado_com_margem_0_1_grau"] = diagnostico.dentro_do_estado(lon, lat, estado, 0.1)
        res["plausibilidade_geografica"][f"UTM {nome}"] = p
    res["fator_escala_utm21s"] = {
        f"lon {lo} lat {la}": diagnostico.fator_escala(lo, la, 31981)
        for lo, la in [(-57, -21), (-58.17, -21), (-54, -21), (-50.92, -20), (-50.92, -23)]
    }
    (OUT / f"pac_utm_{ano}.json").write_text(json.dumps(res, indent=2, ensure_ascii=False), encoding="utf-8")
    logging.info(
        "%s: PAC de trafos %.4f com coordenada; mediana UTM 21S %s",
        ano,
        res["formato"]["UNTRMT.PAC_1"]["frac_coordenada_19_20"],
        [
            r["mediana_m"]
            for r in linhas
            if r["ano"] == ano
            and r["camada"].startswith("UNTRMT")
            and r["hipotese"].startswith("UTM 21S")
            and r["regiao"] == "todo o estado"
        ],
    )

pd.DataFrame(linhas).to_csv(OUT / "pac_utm_resumo.csv", index=False)
logging.info("gravado em %s", OUT)
