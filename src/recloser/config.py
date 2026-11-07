"""Configuração do estudo.

A distribuidora é escolhida pelo arquivo de configuração: ``--config`` nos scripts, a variável de ambiente
``RECLOSER_CONFIG`` ou, sem nenhum dos dois, ``configs/params.yaml`` (Energisa MT). Os padrões do código são os de
MT; outra distribuidora entra por um arquivo próprio (``configs/params_ems.yaml``) que só muda caminhos e recortes.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
VARIAVEL_AMBIENTE = "RECLOSER_CONFIG"
PADRAO = Path("configs") / "params.yaml"

# o que vale quando a configuração não diz nada: os caminhos e o texto de Energisa MT
PASTAS_PADRAO = {"reports": "reports", "processed": str(Path("data") / "processed")}
NOME_PADRAO = "Energisa MT"
CRS_PAC_PADRAO = 31981  # SIRGAS 2000 / UTM 21S


def caminho_config(caminho: str | Path | None = None) -> Path:
    """Arquivo de configuração: argumento, depois ``RECLOSER_CONFIG``, depois ``configs/params.yaml``."""
    escolhido = caminho or os.environ.get(VARIAVEL_AMBIENTE) or PADRAO
    p = Path(escolhido)
    if p.is_absolute() or p.exists():
        return p.resolve()
    return (ROOT / p).resolve()


def carregar(caminho: str | Path | None = None) -> dict:
    p = caminho_config(caminho)
    cfg = yaml.safe_load(p.read_text(encoding="utf-8"))
    for chave in ["cache_bdgd", "falhas", "interrupcoes", "valor_json"]:
        q = Path(cfg[chave])
        cfg[chave] = q if q.is_absolute() else (ROOT / q).resolve()
    cfg["arquivo_config"] = p
    return cfg


def argumentos(descricao: str | None = None) -> tuple[dict, argparse.Namespace]:
    """Lê ``--config`` da linha de comando dos scripts e devolve a configuração e os argumentos."""
    ap = argparse.ArgumentParser(description=descricao)
    ap.add_argument(
        "--config", default=None, help=f"arquivo de configuração (padrão: {VARIAVEL_AMBIENTE} ou {PADRAO.as_posix()})"
    )
    args = ap.parse_args()
    return carregar(args.config), args


def nome(cfg: dict) -> str:
    """Nome da distribuidora para títulos e textos."""
    return cfg.get("nome", NOME_PADRAO)


def crs_pac(cfg: dict) -> int:
    """EPSG em que as coordenadas codificadas nos PAC estão (UTM 21S na BDGD de MT e de MS)."""
    return int(cfg.get("crs_pac", CRS_PAC_PADRAO))


def _pasta(cfg: dict, chave: str) -> Path:
    return ROOT / cfg.get("paths", {}).get(chave, PASTAS_PADRAO[chave])


def pasta_relatorios(cfg: dict) -> Path:
    """Onde os scripts gravam os resultados publicados (``reports`` em MT, ``reports/ems`` em MS)."""
    return _pasta(cfg, "reports")


def pasta_processada(cfg: dict) -> Path:
    """Onde ficam árvores e nós (``data/processed`` em MT, ``data/ems/processed`` em MS)."""
    return _pasta(cfg, "processed")


def pasta_ano(cfg: dict, ano: int) -> Path:
    return Path(cfg["cache_bdgd"]) / str(ano)


# ------------------------------------------------------------------ porta de qualidade da topologia
def porta_minima(cfg: dict) -> float | None:
    """Fração mínima de clientes ligados à saída do alimentador; ``None`` (MT) = sem porta."""
    v = cfg.get("qualidade", {}).get("min_frac_uc_alcancadas")
    return float(v) if v else None


def veredito_porta(cfg: dict, ano: int) -> dict:
    """Aplica a porta pré-registrada ao ``qualidade_topologia.json`` do ano (calculado por ``01_topologia.py``)."""
    minimo = porta_minima(cfg)
    if minimo is None:
        return {"ano": ano, "minimo": None, "valor": None, "passou": True}
    arq = pasta_relatorios(cfg) / "qualidade_topologia.json"
    if not arq.exists():
        return {"ano": ano, "minimo": minimo, "valor": None, "passou": False, "motivo": f"sem {arq.name}: rode 01_topologia.py"}
    q = json.loads(arq.read_text(encoding="utf-8")).get(str(ano))
    if q is None:
        return {"ano": ano, "minimo": minimo, "valor": None, "passou": False, "motivo": f"{arq.name} sem o ano {ano}"}
    valor = float(q["frac_uc_alcancadas"])
    return {"ano": ano, "minimo": minimo, "valor": valor, "passou": valor >= minimo}


def exigir_porta(cfg: dict, ano: int) -> None:
    """Para o script quando a topologia do ano não atinge o mínimo: sem recomendação de local nem backtest."""
    v = veredito_porta(cfg, ano)
    if not v["passou"]:
        raise SystemExit(
            f"PORTA DE QUALIDADE: a topologia de {ano} liga {v['valor']} dos clientes à saída do alimentador "
            f"(mínimo pré-registrado {v['minimo']:.0%}). {v.get('motivo', '')} Resultados que dependem da rede "
            f"não são gerados; ver docs/decisoes_ems.md.".strip()
        )
