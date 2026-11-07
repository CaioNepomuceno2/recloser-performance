"""Diagnóstico dos dados da ANEEL que o estudo lê: linhas repetidas, vínculo das falhas com o cadastro e cobertura de 2026.

* ``count(*)`` x ``count(distinct *)`` de todo arquivo lido (interrupções, falhas e as camadas da BDGD em Parquet);
* parcela das falhas (e do CHI) do histórico que casa com um circuito do cadastro, com e sem o zero à esquerda do nome;
* cobertura de 2026: mês a mês, quanto das interrupções de MT casa com um circuito do cadastro de 2025 e quanto traz o
  elemento que interrompeu.

Não calcula nenhum resultado do estudo.
Saída: ``<reports>/diagnostico/duplicatas_arquivos.csv``, ``falhas_vinculo_cadastro.csv``, ``cobertura_2026.csv``,
``elemento_2026.csv``. Uso: ``python scripts/diagnostico_aneel.py --config configs/params_ems.yaml``
"""

import logging

import duckdb
import pandas as pd

from recloser import config, dados

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
cfg, _ = config.argumentos(__doc__)
OUT = config.pasta_relatorios(cfg) / "diagnostico"
OUT.mkdir(parents=True, exist_ok=True)
anos = sorted({cfg["ano_backtest"], cfg["ano_atual"]})
larg = cfg.get("alimentador", {}).get("largura_nome", 0)
FILTRO_MT = "origem_mt and origem = 'INTERNA' and tipo = 'NAO PROGRAMADA'"


def contagem(rotulo: str, fonte: str, onde: str = "") -> dict:
    n, nd = duckdb.sql(
        f"select (select count(*) from {fonte} {onde}), (select count(*) from (select distinct * from {fonte} {onde}))"
    ).fetchall()[0]
    return {
        "arquivo": rotulo,
        "linhas": n,
        "distintas": nd,
        "repetidas": n - nd,
        "pct_repetidas": 100 * (n - nd) / n if n else 0.0,
    }


# ---------------------------------------------------------------- linhas repetidas em tudo que o estudo lê
irr = f"read_parquet('{cfg['interrupcoes'].as_posix()}')"
linhas = [
    contagem("interrupcoes (todos os anos)", irr),
    contagem("interrupcoes, só 2026", irr, "where ano = 2026"),
    contagem("interrupcoes, 2026 MT interna não programada (a que 03 lê)", irr, f"where ano = 2026 and {FILTRO_MT}"),
    contagem("falhas.parquet", f"read_parquet('{cfg['falhas'].as_posix()}')"),
]
for ano in anos:
    for nome in ["SSDMT", "UNSEMT", "UNREMT", "UNTRMT", "CTMT", "UCBT_tab_agg", "UCMT_tab_agg"]:
        linhas.append(
            contagem(f"BDGD {ano} {nome}", f"read_parquet('{(config.pasta_ano(cfg, ano) / (nome + '.parquet')).as_posix()}')")
        )
dup = pd.DataFrame(linhas)
dup.to_csv(OUT / "duplicatas_arquivos.csv", index=False)
logging.info("\n%s", dup.to_string())

# ---------------------------------------------------------------- vínculo das falhas com o cadastro
f = pd.read_parquet(cfg["falhas"])
vinc = []
for ano_snap, anos_taxa in [
    (cfg["ano_atual"], cfg["confiabilidade"]["anos_taxa"]),
    (cfg["ano_backtest"], [cfg["ano_backtest"] - 2, cfg["ano_backtest"] - 1, cfg["ano_backtest"]]),
]:
    ct = pd.read_parquet(config.pasta_ano(cfg, ano_snap) / "CTMT.parquet", columns=["COD_ID", "NOME"])
    fa = f[f.ano.isin(anos_taxa)]
    for rotulo, largura in [("nome do cadastro sem completar", 0), (f"nome completado com zeros até {larg}", larg)]:
        if rotulo.startswith("nome completado") and not larg:
            continue
        chaves = set(dados.nome_canonico(ct.NOME, largura)) if largura else set(ct.NOME.astype("string").str.strip())
        casa = fa.alimentador.isin(chaves)
        vinc.append(
            {
                "snapshot": ano_snap,
                "anos_das_falhas": f"{anos_taxa[0]}-{anos_taxa[-1]}",
                "chave": rotulo,
                "falhas": float(fa.n_falhas.sum()),
                "frac_falhas_casadas": float(fa[casa].n_falhas.sum() / fa.n_falhas.sum()),
                "frac_chi_casado": float(fa[casa].chi.sum() / fa.chi.sum()),
                "alimentadores_com_historico": int(fa.alimentador.nunique()),
                "alimentadores_casados": int(fa[casa].alimentador.nunique()),
                "circuitos_no_cadastro": len(ct),
            }
        )
pd.DataFrame(vinc).to_csv(OUT / "falhas_vinculo_cadastro.csv", index=False)
logging.info("\n%s", pd.DataFrame(vinc).to_string())

# ---------------------------------------------------------------- 2026: cobertura e elemento
ct25 = pd.read_parquet(config.pasta_ano(cfg, cfg["ano_atual"]) / "CTMT.parquet", columns=["COD_ID"])
i26 = duckdb.sql(f"select mes, alimentador_cod_id, elemento, chi, uc_afetadas from {irr} where ano = 2026 and {FILTRO_MT}").df()
i26["casa"] = i26.alimentador_cod_id.astype("string").str.strip().isin(ct25.COD_ID.astype("string").str.strip())
i26["identificado"] = i26.elemento.astype("string") != "NAO IDENTIFICADO"
cob = (
    i26.groupby("mes")
    .agg(
        interrupcoes=("chi", "size"),
        frac_casa_cadastro=("casa", "mean"),
        frac_elemento_identificado=("identificado", "mean"),
        chi=("chi", "sum"),
    )
    .reset_index()
)
tot = pd.DataFrame(
    [
        {
            "mes": "jan-jul (sem março)",
            "interrupcoes": len(i26),
            "frac_casa_cadastro": i26.casa.mean(),
            "frac_elemento_identificado": i26.identificado.mean(),
            "chi": i26.chi.sum(),
        }
    ]
)
cob = pd.concat([cob.astype({"mes": "string"}), tot])
cob.to_csv(OUT / "cobertura_2026.csv", index=False)
el = i26.pivot_table(index="elemento", columns="mes", values="chi", aggfunc="size", fill_value=0)
el["total"] = el.sum(axis=1)
el.sort_values("total", ascending=False).reset_index().to_csv(OUT / "elemento_2026.csv", index=False)
logging.info("\n%s\n%s", cob.to_string(), el.sort_values("total", ascending=False).to_string())
meses = sorted(i26.mes.unique())
logging.info("meses de 2026 com registro: %s", meses)
