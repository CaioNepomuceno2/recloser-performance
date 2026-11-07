"""Leitura das bases auxiliares: falhas históricas, interrupções de 2026 e valoração."""
from __future__ import annotations

import json
from pathlib import Path

import duckdb
import pandas as pd


def nome_canonico(nome: pd.Series, largura: int = 0) -> pd.Series:
    """Nome do circuito na chave do ``distribution-asset-risk``: sem espaços e, se ``largura`` > 0, com zeros à esquerda.

    Em MT o ``CTMT.NOME`` já é a chave (6 dígitos) e ``largura`` fica em 0. Em MS o nome tem 5 caracteres
    alfanuméricos (``RBR53``) e a chave é ``0RBR53``: ``largura = 6``.
    """
    s = nome.astype("string").str.strip()
    return s.str.zfill(largura) if largura else s


def historico_alimentador(falhas: Path, ctmt: pd.DataFrame, anos: list[int], largura_nome: int = 0) -> pd.DataFrame:
    """Médias anuais de falhas MT, CI e CHI por circuito (``COD_ID`` do snapshot).

    ``falhas`` é a tabela alimentador × ano × mês × modo do projeto ``distribution-asset-risk``, em que o
    alimentador é o nome operacional do circuito (``CTMT.NOME``, completado com zeros até ``largura_nome``
    caracteres quando for o caso).
    """
    f = pd.read_parquet(falhas)
    f = f[f.ano.isin(anos)]
    g = f.groupby("alimentador")[["n_falhas", "ci", "chi", "chi_regulatorio"]].sum() / len(anos)
    g.columns = ["falhas_ano", "ci_ano", "chi_ano", "chi_reg_ano"]
    if largura_nome:
        ctmt = ctmt.assign(NOME=nome_canonico(ctmt.NOME, largura_nome))
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


def valoracao(valor_json: Path, exigir_origem: bool = False) -> dict:
    """Valores de referência do projeto ``automation-impact`` (R$/CHI, efeito medido por religador).

    O ``valor.json`` de MS traz ``origem_efeito`` (o efeito do religador é "transportado de MT" ou "medido em MS");
    o de MT não tem o campo. Com ``exigir_origem`` o campo é obrigatório, e quem usa a valoração tem que repetir
    o rótulo na própria saída (:func:`rotulo`).
    """
    v = json.loads(Path(valor_json).read_text())
    origem = v.get("origem_efeito")
    if exigir_origem and not origem:
        raise ValueError(f"{valor_json} não traz 'origem_efeito'; sem ele não dá para rotular as saídas")
    out = {
        "rs_por_chi_social": v["rs_por_chi_social"],
        "rs_por_chi_compensacao": v["rs_por_chi_compensacao"],
        "frac_chi_regulatorio": v["frac_chi_regulatorio"],
        "uc_total": v["uc_total"],
        "chi_evitado_por_religador_did": v["chi_evitado_ano_por_religador"],
        "chi_evitado_por_religador_did_ic95": v["chi_evitado_ano_por_religador_ic95"],
        "efeito_chi_pct_did": v["efeito_chi_pct"],
    }
    if origem:
        out["origem_efeito"] = origem
    return out


def rotulo(val: dict) -> dict:
    """``{"origem_efeito": ...}`` quando a valoração tem a origem do efeito; vazio em MT (saídas de MT não mudam)."""
    return {"origem_efeito": val["origem_efeito"]} if val.get("origem_efeito") else {}


def rotular_tabela(df: pd.DataFrame, val: dict) -> pd.DataFrame:
    """Acrescenta a coluna ``origem_efeito`` a um CSV de saída; em MT devolve a tabela sem alteração."""
    r = rotulo(val)
    return df.assign(**r) if r else df
