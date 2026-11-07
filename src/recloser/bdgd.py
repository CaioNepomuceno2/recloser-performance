"""Leitura das camadas da BDGD a partir de um zip local (cache somente leitura).

O zip da ANEEL traz um File Geodatabase (``<nome>.gdb/``) com uma tabela por camada. Cada camada é um conjunto de
arquivos ``aXXXXXXXX.*``, em que ``XXXXXXXX`` é o ``ObjectID`` da camada no catálogo do banco (``GDB_SystemCatalog``)
em hexadecimal. Para não descompactar os ~2 GB inteiros, :func:`extrair_camadas` lê o catálogo direto do zip,
descobre os arquivos das camadas pedidas e extrai só esses (mais as tabelas de sistema, que são pequenas).
O zip nunca é modificado.
"""
from __future__ import annotations

import re
import zipfile
from pathlib import Path

import geopandas as gpd
import pandas as pd
import pyogrio
import pyogrio.raw
import shapely

CAMADAS = {
    "SSDMT": ["COD_ID", "PAC_1", "PAC_2", "CTMT", "COMP", "SUB"],
    "UNSEMT": ["COD_ID", "PAC_1", "PAC_2", "TIP_UNID", "P_N_OPE", "TLCD", "COR_NOM", "CTMT", "SUB", "DAT_CON"],
    "UNREMT": ["COD_ID", "PAC_1", "PAC_2", "CTMT", "SUB"],
    "UNTRMT": ["COD_ID", "PAC_1", "PAC_2", "CTMT", "POT_NOM"],
    "CTMT": ["COD_ID", "NOME", "SUB", "PAC_INI"],
}
TABELAS_UC = {"UCBT_tab": "UNI_TR_MT", "UCMT_tab": "PAC"}   # consumidores: tabela -> chave de ligação à rede
COM_GEOM = {"UNSEMT", "UNTRMT"}
LAYERS = [*CAMADAS, *TABELAS_UC]
SISTEMA = range(1, 9)       # a00000001..a00000008: catálogo e tabelas de sistema do geodatabase
ARQUIVOS_FIXOS = {"gdb", "timestamps"}


def _raiz_gdb(z: zipfile.ZipFile) -> str:
    """Nome da pasta ``*.gdb`` no topo do zip."""
    topos = {n.split("/")[0] for n in z.namelist() if n.split("/")[0].lower().endswith(".gdb")}
    if len(topos) != 1:
        raise ValueError(f"o zip deve ter exatamente uma pasta .gdb no topo, achei {sorted(topos)}")
    return topos.pop()


def zip_do_ano(pasta: Path, ano: int, item: str) -> Path:
    """Zip ``bdgd_<ano>_<item>.gdb.zip`` do cache local; falha se não existir (nada é baixado)."""
    p = Path(pasta) / f"bdgd_{ano}_{item}.gdb.zip"
    if not p.is_file():
        raise FileNotFoundError(f"zip da BDGD de {ano} não encontrado: {p}")
    return p


def numeros_das_camadas(zip_path: Path) -> dict[str, int]:
    """``ObjectID`` de cada tabela do catálogo do geodatabase, lido direto do zip (sem extrair)."""
    zip_path = Path(zip_path)
    with zipfile.ZipFile(zip_path) as z:
        raiz = _raiz_gdb(z)
    pyogrio.set_gdal_config_options({"OPENFILEGDB_LIST_ALL_TABLES": "YES"})
    try:
        meta, fids, _, dados = pyogrio.raw.read(f"/vsizip/{zip_path.as_posix()}/{raiz}", layer="GDB_SystemCatalog",
                                                read_geometry=False, return_fids=True)
    finally:
        pyogrio.set_gdal_config_options({"OPENFILEGDB_LIST_ALL_TABLES": None})
    nomes = dados[list(meta["fields"]).index("Name")]
    return {str(n): int(f) for f, n in zip(fids, nomes)}


def extrair_camadas(zip_path: Path, destino: Path, camadas: list[str]) -> Path:
    """Extrai de ``zip_path`` só os arquivos das ``camadas`` (e as tabelas de sistema) para ``destino``.

    Devolve o caminho do ``.gdb`` extraído. Se uma camada não existe no zip, levanta ``KeyError``.
    """
    zip_path, destino = Path(zip_path), Path(destino)
    nums = numeros_das_camadas(zip_path)
    faltam = [c for c in camadas if c not in nums]
    if faltam:
        raise KeyError(f"camadas ausentes em {zip_path.name}: {faltam}")
    numeros = {*SISTEMA, *(nums[c] for c in camadas)}
    with zipfile.ZipFile(zip_path) as z:
        raiz = _raiz_gdb(z)
        gdb = destino / raiz
        gdb.mkdir(parents=True, exist_ok=True)
        for info in z.infolist():
            base = info.filename.rsplit("/", 1)[-1]
            if info.is_dir() or not base:
                continue
            m = re.match(r"a([0-9a-f]{8})\.", base)
            if base in ARQUIVOS_FIXOS or (m and int(m.group(1), 16) in numeros):
                z.extract(info, destino)
    return gdb


def _extremos(df: gpd.GeoDataFrame) -> pd.DataFrame:
    """Longitude e latitude (WGS 84) do primeiro e do último vértice de cada segmento."""
    g = df.geometry.values
    n = shapely.get_num_geometries(g)
    pontos = {"1": shapely.get_point(shapely.get_geometry(g, 0), 0), "2": shapely.get_point(shapely.get_geometry(g, n - 1), -1)}
    out = {}
    for k, pts in pontos.items():
        s = gpd.GeoSeries(pts, crs=df.crs).to_crs(4326)
        out[f"lon{k}"], out[f"lat{k}"] = s.x.to_numpy(), s.y.to_numpy()
    return pd.DataFrame(out, index=df.index)


def gravar_camadas(gdb: Path, saida: Path, extremos_segmentos: bool = False) -> None:
    """Grava em ``saida`` só as camadas usadas no estudo, em Parquet.

    Pontos (``UNSEMT``, ``UNTRMT``) ganham ``lon``/``lat``; consumidores viram contagens por transformador (BT) e por
    PAC (MT). Com ``extremos_segmentos``, ``SSDMT`` ganha a coordenada dos dois extremos da linha (``lon1``...``lat2``),
    que é o que permite conferir a codificação do PAC contra a geometria.
    """
    saida = Path(saida)
    saida.mkdir(parents=True, exist_ok=True)
    for camada, cols in CAMADAS.items():
        campos = set(pyogrio.read_info(gdb, layer=camada)["fields"])
        geom = camada in COM_GEOM or (extremos_segmentos and camada == "SSDMT")
        df = pyogrio.read_dataframe(gdb, layer=camada, columns=[c for c in cols if c in campos],
                                    read_geometry=geom, use_arrow=True)
        if camada in COM_GEOM:
            g = df.geometry.to_crs(4326).representative_point()
            df["lon"], df["lat"] = g.x, g.y
            df = pd.DataFrame(df.drop(columns="geometry"))
        elif geom:
            df = pd.concat([pd.DataFrame(df.drop(columns="geometry")), _extremos(df)], axis=1)
        df.to_parquet(saida / f"{camada}.parquet", index=False)
    # consumidores por transformador (BT) e por ponto de conexão (MT)
    for camada, chave in TABELAS_UC.items():
        df = pyogrio.read_dataframe(gdb, layer=camada, columns=[chave, "CTMT"], read_geometry=False, use_arrow=True)
        agg = df.groupby([chave, "CTMT"], dropna=False).size().rename("n_uc").reset_index()
        agg["ene_ano_kwh"] = 0.0
        agg.astype({chave: "string", "CTMT": "string"}).to_parquet(saida / f"{camada}_agg.parquet", index=False)
