"""Configuração do estudo (``configs/params.yaml``)."""
from __future__ import annotations

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]


def carregar(caminho: str | Path = ROOT / "configs" / "params.yaml") -> dict:
    cfg = yaml.safe_load(Path(caminho).read_text(encoding="utf-8"))
    for chave in ["cache_bdgd", "falhas", "interrupcoes", "valor_json"]:
        p = Path(cfg[chave])
        cfg[chave] = p if p.is_absolute() else (ROOT / p).resolve()
    return cfg


def pasta_ano(cfg: dict, ano: int) -> Path:
    return Path(cfg["cache_bdgd"]) / str(ano)
