"""Grava em Parquet só as camadas da BDGD (ANEEL) usadas no estudo.

Saída: ``<cache_bdgd>/<ano>/<CAMADA>.parquet``.

* **MT (padrão):** baixa o snapshot do ArcGIS Hub, extrai, grava as camadas e apaga o download (~1 GB por ano).
* **Com ``bdgd.zips`` na configuração (MS):** lê o zip ``bdgd_<ano>_<item>.gdb.zip`` de uma pasta local somente leitura
  (nada é baixado nem modificado lá), extrai só os arquivos das camadas usadas para ``data/.../raw/<ano>`` do clone,
  grava o Parquet e apaga a extração.

Uso: ``python scripts/00_cache_bdgd.py [--config configs/params_ems.yaml] [ano ...]`` (sem anos: ``ano_atual`` e
``ano_backtest``).
"""
import argparse
import logging
import shutil
import time
import zipfile
from pathlib import Path

import requests

from recloser import bdgd, config

ARCGIS = "https://www.arcgis.com/sharing/rest/content/items/{item}/data"
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")


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


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--config", default=None, help="arquivo de configuração (padrão: RECLOSER_CONFIG ou configs/params.yaml)")
    ap.add_argument("anos", nargs="*", type=int, help="anos dos snapshots (padrão: ano_atual e ano_backtest)")
    args = ap.parse_args()
    cfg = config.carregar(args.config)
    anos = args.anos or [cfg["ano_atual"], cfg["ano_backtest"]]
    opc = cfg.get("bdgd", {})
    zips = opc.get("zips")
    for ano in anos:
        saida = config.pasta_ano(cfg, ano)
        tmp = config.ROOT / "data" / "raw" / str(ano) if zips is None else Path(cfg["cache_bdgd"]).parent / "raw" / str(ano)
        shutil.rmtree(tmp, ignore_errors=True)
        item = cfg["snapshots_bdgd"][ano]
        if zips is None:
            gdb = baixar(item, tmp)
        else:
            pasta = Path(zips)
            gdb = bdgd.extrair_camadas(bdgd.zip_do_ano(pasta if pasta.is_absolute() else config.ROOT / pasta, ano, item),
                                       tmp, bdgd.LAYERS)
        bdgd.gravar_camadas(gdb, saida, extremos_segmentos=bool(opc.get("extremos_segmentos", False)))
        shutil.rmtree(tmp, ignore_errors=True)
        logging.info("%s: camadas gravadas em %s", ano, saida)


if __name__ == "__main__":
    main()
