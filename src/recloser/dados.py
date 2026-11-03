"""Leitura das bases auxiliares: falhas históricas, interrupções de 2026 e valoração."""
from __future__ import annotations

import json
from pathlib import Path

import duckdb
import pandas as pd


def historico_alimentador(falhas: Path, ctmt: pd.DataFrame, anos: list[int]) -> pd.DataFrame:
    """Médias anuais de falhas MT, CI e CHI por circuito (``COD_ID`` do snapshot).

    ``falhas`` é a tabela alimentador × ano × mês × modo do projeto ``distribution-asset-risk``, em que o
    alimentador é o nome operacional do circuito (``CTMT.NOME``).
    """
    f = pd.read_parquet(falhas)
    f = f[f.ano.isin(anos)]
    g = f.groupby("alimentador")[["n_falhas", "ci", "chi", "chi_regulatorio"]].sum() / len(anos)
    g.columns = ["falhas_ano", "ci_ano", "chi_ano", "chi_reg_ano"]
    mapa = ctmt.drop_duplicates("NOME").set_index("NOME").COD_ID
    g = g.reset_index()
    g["ctmt"] = g.alimentador.map(mapa)
    return g.dropna(subset=["ctmt"]).groupby("ctmt").sum(numeric_only=True)


def falhas_por_modo(falhas: Path, anos: list[int]) -> pd.DataFrame:
    f = pd.read_parquet(falhas)
    f = f[f.ano.isin(anos)]
    return (f.groupby("modo")[["n_falhas", "chi"]].sum() / len(anos)).reset_index()


def interrupcoes_2026(interrupcoes: Path) -> pd.DataFrame:
    """Interrupções MT internas não programadas de 2026 com o tipo de elemento que interrompeu."""
    return duckdb.sql(f"""
        select alimentador_cod_id as ctmt, subestacao, elemento, uc_afetadas, duracao_h, chi, expurgo,
               grupo_causa, inicio
        from read_parquet('{interrupcoes}')
        where ano = 2026 and origem_mt and origem = 'INTERNA' and tipo = 'NAO PROGRAMADA'
    """).df()


def valoracao(valor_json: Path) -> dict:
    """Valores de referência do projeto ``automation-impact`` (R$/CHI, efeito medido por religador)."""
    v = json.loads(Path(valor_json).read_text())
    return {
        "rs_por_chi_social": v["rs_por_chi_social"],
        "rs_por_chi_compensacao": v["rs_por_chi_compensacao"],
        "frac_chi_regulatorio": v["frac_chi_regulatorio"],
        "uc_total": v["uc_total"],
        "chi_evitado_por_religador_did": v["chi_evitado_ano_por_religador"],
        "chi_evitado_por_religador_did_ic95": v["chi_evitado_ano_por_religador_ic95"],
        "efeito_chi_pct_did": v["efeito_chi_pct"],
    }
