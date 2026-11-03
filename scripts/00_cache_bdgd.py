"""Baixa os snapshots da BDGD (ANEEL) e grava em Parquet só as camadas usadas no estudo.

Adaptado do cache compartilhado usado nos projetos irmãos (distribution-asset-risk). Cada GDB tem ~1 GB
compactado; ele é apagado depois da extração. Saída: ``<cache_bdgd>/<ano>/<CAMADA>.parquet``.
"""
import logging
import shutil
import sys
import time
import zipfile
from pathlib import Path

import pandas as pd
import pyogrio
import requests

from recloser import config

ARCGIS = "https://www.arcgis.com/sharing/rest/content/items/{item}/data"
CAMADAS = {
    "SSDMT": ["COD_ID", "PAC_1", "PAC_2", "CTMT", "COMP", "SUB"],
    "UNSEMT": ["COD_ID", "PAC_1", "PAC_2", "TIP_UNID", "P_N_OPE", "TLCD", "COR_NOM", "CTMT", "SUB", "DAT_CON"],
    "UNREMT": ["COD_ID", "PAC_1", "PAC_2", "CTMT", "SUB"],
    "UNTRMT": ["COD_ID", "PAC_1", "PAC_2", "CTMT", "POT_NOM"],
    "CTMT": ["COD_ID", "NOME", "SUB", "PAC_INI"],
}
COM_GEOM = {"UNSEMT", "UNTRMT"}
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
cfg = config.carregar()
anos = [int(a) for a in sys.argv[1:]] or [cfg["ano_atual"], cfg["ano_backtest"]]


def baixar(item: str, destino: Path) -> Path:
    destino.mkdir(parents=True, exist_ok=True)
    zpath = destino / "bdgd.gdb.zip"
    for tentativa in range(4):
        try:
            with requests.get(ARCGIS.format(item=item), stream=True, timeout=3000) as r:
                r.raise_for_status()
                with open(zpath, "wb") as f:
                    f.writelines(r.iter_content(1 << 22))
            break
        except requests.RequestException:
            if tentativa == 3:
                raise
            time.sleep(2 ** (tentativa + 1))
    with zipfile.ZipFile(zpath) as z:
        z.extractall(destino)
    zpath.unlink()
    return next(p for p in destino.rglob("*.gdb") if p.is_dir())


for ano in anos:
    saida = config.pasta_ano(cfg, ano)
    saida.mkdir(parents=True, exist_ok=True)
    tmp = config.ROOT / "data" / "raw" / str(ano)
    gdb = baixar(cfg["snapshots_bdgd"][ano], tmp)
    for camada, cols in CAMADAS.items():
        campos = set(pyogrio.read_info(gdb, layer=camada)["fields"])
        df = pyogrio.read_dataframe(gdb, layer=camada, columns=[c for c in cols if c in campos],
                                    read_geometry=camada in COM_GEOM, use_arrow=True)
        if camada in COM_GEOM:
            g = df.geometry.to_crs(4326).representative_point()
            df["lon"], df["lat"] = g.x, g.y
            df = pd.DataFrame(df.drop(columns="geometry"))
        df.to_parquet(saida / f"{camada}.parquet", index=False)
    # consumidores por transformador (BT) e por ponto de conexão (MT)
    for camada, chave in [("UCBT_tab", "UNI_TR_MT"), ("UCMT_tab", "PAC")]:
        df = pyogrio.read_dataframe(gdb, layer=camada, columns=[chave, "CTMT"], read_geometry=False, use_arrow=True)
        agg = df.groupby([chave, "CTMT"], dropna=False).size().rename("n_uc").reset_index()
        agg["ene_ano_kwh"] = 0.0
        agg.astype({chave: "string", "CTMT": "string"}).to_parquet(saida / f"{camada}_agg.parquet", index=False)
    shutil.rmtree(tmp, ignore_errors=True)
    logging.info("%s: camadas gravadas em %s", ano, saida)
