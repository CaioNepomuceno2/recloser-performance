"""Monta a árvore radial dos alimentadores para o ano atual e o ano do backtest.

Com ``qualidade.min_frac_uc_alcancadas`` na configuração (MS), grava também ``porta_qualidade.json`` com o veredito da
porta pré-registrada (``docs/decisoes_ems.md``, seção 6) para cada ano.
"""
import json
import logging

from recloser import config, topologia

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
cfg, _ = config.argumentos(__doc__)
proc = config.pasta_processada(cfg)
proc.mkdir(parents=True, exist_ok=True)
out = config.pasta_relatorios(cfg)
out.mkdir(parents=True, exist_ok=True)
anos = [cfg["ano_atual"], cfg["ano_backtest"]]
qualidade = {}
for ano in anos:
    rede = topologia.construir(config.pasta_ano(cfg, ano), cfg["tip_unid"], cfg["topologia"]["max_gap_m"])
    rede.nos.to_parquet(proc / f"nos_{ano}.parquet", index=False)
    rede.alimentadores.to_parquet(proc / f"alimentadores_{ano}.parquet", index=False)
    qualidade[ano] = rede.qualidade | {"dispositivos_na_arvore": rede.nos.classe.value_counts().to_dict()}
    logging.info("%s: %s", ano, rede.qualidade)
(out / "qualidade_topologia.json").write_text(json.dumps(qualidade, indent=2, ensure_ascii=False))
if config.porta_minima(cfg) is not None:
    porta = {str(a): config.veredito_porta(cfg, a) for a in anos}
    (out / "porta_qualidade.json").write_text(json.dumps(porta, indent=2, ensure_ascii=False))
    logging.info("porta de qualidade: %s", porta)
