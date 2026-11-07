"""Backtest: a priorização feita com a rede de ``ano_backtest`` aponta onde a distribuidora instalou religadores em ``ano_atual``?

Também compara o CHI evitado que o modelo atribui a essas instalações com o efeito do ``valor.json`` (ver ``recloser.backtest``).
Em MS a topologia de ``ano_backtest`` precisa passar a porta de qualidade (``docs/decisoes_ems.md``, seção 6).
"""
import json
import logging

from recloser import backtest, config

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
cfg, _ = config.argumentos(__doc__)
OUT = config.pasta_relatorios(cfg)
OUT.mkdir(parents=True, exist_ok=True)
config.exigir_porta(cfg, cfg["ano_backtest"])
resumo, loc = backtest.executar(cfg)
loc.to_csv(OUT / "backtest_instalacoes.csv", index=False)
(OUT / "backtest.json").write_text(json.dumps(resumo, indent=2, ensure_ascii=False))
logging.info(json.dumps(resumo, indent=1, ensure_ascii=False))
