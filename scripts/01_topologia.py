"""Monta a árvore radial dos alimentadores para o ano atual e o ano do backtest."""
import json
import logging

from recloser import config, topologia

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
cfg = config.carregar()
proc = config.ROOT / "data" / "processed"
proc.mkdir(parents=True, exist_ok=True)
qualidade = {}
for ano in [cfg["ano_atual"], cfg["ano_backtest"]]:
    rede = topologia.construir(config.pasta_ano(cfg, ano), cfg["tip_unid"], cfg["topologia"]["max_gap_m"])
    rede.nos.to_parquet(proc / f"nos_{ano}.parquet", index=False)
    rede.alimentadores.to_parquet(proc / f"alimentadores_{ano}.parquet", index=False)
    qualidade[ano] = rede.qualidade | {"dispositivos_na_arvore": rede.nos.classe.value_counts().to_dict()}
    logging.info("%s: %s", ano, rede.qualidade)
(config.ROOT / "reports" / "qualidade_topologia.json").write_text(json.dumps(qualidade, indent=2, ensure_ascii=False))
