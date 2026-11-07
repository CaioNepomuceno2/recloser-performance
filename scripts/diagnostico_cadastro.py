"""Diagnóstico do cadastro (BDGD) de cada snapshot usado: camadas, TIP_UNID, nomes de circuito e ligação dos clientes.

Não monta a árvore nem calcula nenhum resultado: só conta o que há nas camadas (e como as chaves se ligam), para
embasar as decisões de ``docs/decisoes_ems.md`` antes de qualquer resultado.

Saída: ``<reports>/diagnostico/cadastro_<ano>.json``, ``tip_unid_<ano>.csv`` e ``cadastro_resumo.csv``.
Uso: ``python scripts/diagnostico_cadastro.py --config configs/params_ems.yaml``
"""

import json
import logging

import pandas as pd

from recloser import config, topologia

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
cfg, _ = config.argumentos(__doc__)
OUT = config.pasta_relatorios(cfg) / "diagnostico"
OUT.mkdir(parents=True, exist_ok=True)
anos = sorted({cfg["ano_backtest"], cfg["ano_atual"]})
cod = cfg["tip_unid"]
resumo = []


def txt(s: pd.Series) -> pd.Series:
    return s.astype("string").str.strip()


for ano in anos:
    d = config.pasta_ano(cfg, ano)
    seg = pd.read_parquet(d / "SSDMT.parquet", columns=["PAC_1", "PAC_2", "CTMT", "COMP"])
    sw = pd.read_parquet(
        d / "UNSEMT.parquet", columns=["COD_ID", "PAC_1", "PAC_2", "TIP_UNID", "P_N_OPE", "TLCD", "CTMT", "DAT_CON"]
    )
    rg = pd.read_parquet(d / "UNREMT.parquet", columns=["COD_ID", "PAC_1", "PAC_2", "CTMT"])
    tr = pd.read_parquet(d / "UNTRMT.parquet", columns=["COD_ID", "PAC_1", "CTMT", "POT_NOM"])
    ct = pd.read_parquet(d / "CTMT.parquet", columns=["COD_ID", "NOME", "SUB", "PAC_INI"])
    ucbt = pd.read_parquet(d / "UCBT_tab_agg.parquet")
    ucmt = pd.read_parquet(d / "UCMT_tab_agg.parquet")
    for df, cols in [
        (seg, ["PAC_1", "PAC_2", "CTMT"]),
        (sw, ["COD_ID", "PAC_1", "PAC_2", "CTMT"]),
        (rg, ["PAC_1", "PAC_2", "CTMT"]),
        (tr, ["COD_ID", "PAC_1", "CTMT"]),
        (ct, ["COD_ID", "NOME", "PAC_INI"]),
        (ucbt, ["UNI_TR_MT", "CTMT"]),
        (ucmt, ["PAC", "CTMT"]),
    ]:
        for c in cols:
            df[c] = txt(df[c])
    res: dict = {"ano": ano}

    # ---------------------------------------------------------------- camadas
    comp = pd.to_numeric(seg.COMP, errors="coerce")
    res["camadas"] = {
        "SSDMT": len(seg),
        "SSDMT_km": float(comp.fillna(0).sum() / 1000),
        "SSDMT_comp_nulo_ou_zero": int((comp.fillna(0) <= 0).sum()),
        "UNSEMT": len(sw),
        "UNREMT": len(rg),
        "UNTRMT": len(tr),
        "CTMT": len(ct),
        "UCBT_consumidores": int(ucbt.n_uc.sum()),
        "UCMT_consumidores": int(ucmt.n_uc.sum()),
    }

    # ---------------------------------------------------------------- TIP_UNID (mapeamento de MT conferido em MS)
    tip = txt(sw.TIP_UNID)
    classe = topologia.classificar_tip_unid(tip, cod)
    tab = (
        pd.DataFrame(
            {
                "TIP_UNID": tip,
                "classe": classe,
                "tlcd": pd.to_numeric(sw.TLCD, errors="coerce").fillna(0) == 1,
                "aberta": txt(sw.P_N_OPE) == "A",
            }
        )
        .groupby(["TIP_UNID", "classe"])
        .agg(n=("tlcd", "size"), frac_telecomandadas=("tlcd", "mean"), frac_abertas=("aberta", "mean"))
        .reset_index()
        .sort_values("n", ascending=False)
    )
    tab.to_csv(OUT / f"tip_unid_{ano}.csv", index=False)
    rel = sw[classe == "religador"]
    res["religadores"] = {
        "n": len(rel),
        "frac_telecomandados": float((pd.to_numeric(rel.TLCD, errors="coerce") == 1).mean()),
        "frac_normalmente_abertos": float((txt(rel.P_N_OPE) == "A").mean()),
    }
    res["classes_unsemt"] = {k: int(v) for k, v in classe.value_counts().items()}
    res["frac_unsemt_fora_do_mapeamento"] = float((classe == "chave").mean())
    res["P_N_OPE"] = {str(k): int(v) for k, v in txt(sw.P_N_OPE).value_counts(dropna=False).items()}

    # ---------------------------------------------------------------- nomes e chaves de circuito
    nome = ct.NOME
    res["circuitos"] = {
        "n": len(ct),
        "nome_comprimentos": {str(k): int(v) for k, v in nome.str.len().value_counts().sort_index().items()},
        "nome_so_digitos": float(nome.str.fullmatch(r"\d+").mean()),
        "nome_alfanumerico": float(nome.str.fullmatch(r"[A-Z0-9]+").mean()),
        "nomes_repetidos": int(nome.duplicated().sum()),
        "exemplos": nome.head(6).tolist(),
        "ssdmt_ctmt_existe_em_ctmt": float(seg.CTMT.isin(ct.COD_ID).mean()),
        "unsemt_ctmt_existe_em_ctmt": float(sw.CTMT.isin(ct.COD_ID).mean()),
        "untrmt_ctmt_existe_em_ctmt": float(tr.CTMT.isin(ct.COD_ID).mean()),
    }
    # nome canônico (largura da configuração) e repetidos depois dele
    larg = cfg.get("alimentador", {}).get("largura_nome", 0)
    canon = nome.str.zfill(larg) if larg else nome
    res["circuitos"]["canonico_comprimentos"] = {str(k): int(v) for k, v in canon.str.len().value_counts().sort_index().items()}
    res["circuitos"]["canonico_repetidos"] = int(canon.duplicated().sum())

    # ---------------------------------------------------------------- nós e ligação dos clientes à rede
    nos = (
        pd.concat([seg.PAC_1, seg.PAC_2, sw.PAC_1, sw.PAC_2, rg.PAC_1, rg.PAC_2, tr.PAC_1, ucmt.PAC, ct.PAC_INI])
        .dropna()
        .drop_duplicates()
    )
    n_bt = ucbt.n_uc.sum()
    ligado_bt = ucbt[ucbt.UNI_TR_MT.isin(tr.COD_ID)].n_uc.sum()
    n_mt = ucmt.n_uc.sum()
    ligado_mt = ucmt[
        ucmt.PAC.isin(pd.concat([seg.PAC_1, seg.PAC_2, sw.PAC_1, sw.PAC_2, rg.PAC_1, rg.PAC_2, tr.PAC_1]).dropna())
    ].n_uc.sum()
    res["clientes"] = {
        "bt_consumidores": int(n_bt),
        "bt_com_transformador_no_cadastro": float(ligado_bt / n_bt),
        "mt_consumidores": int(n_mt),
        "mt_com_pac_na_rede": float(ligado_mt / n_mt) if n_mt else None,
        "cadastro_consumidores_ligados_a_trafo_ou_pac": float((ligado_bt + ligado_mt) / (n_bt + n_mt)),
        "trafos_sem_consumidor": float((~tr.COD_ID.isin(ucbt.UNI_TR_MT)).mean()),
        "trafos_com_pac_na_rede_de_segmentos": float(tr.PAC_1.isin(pd.concat([seg.PAC_1, seg.PAC_2])).mean()),
        "pac_ini_na_rede": float(
            ct.PAC_INI.isin(pd.concat([seg.PAC_1, seg.PAC_2, sw.PAC_1, sw.PAC_2, rg.PAC_1, rg.PAC_2])).mean()
        ),
        "pac_nos_total": int(len(nos)),
        # circuito do cliente no cadastro x circuito do trafo (UCBT.CTMT x UNTRMT.CTMT)
        "ucbt_ctmt_igual_ao_do_trafo": float(
            ucbt.merge(tr[["COD_ID", "CTMT"]].rename(columns={"COD_ID": "UNI_TR_MT", "CTMT": "CTMT_trafo"}), on="UNI_TR_MT").pipe(
                lambda m: m.n_uc.to_numpy()[(m.CTMT == m.CTMT_trafo).fillna(False).to_numpy(bool)].sum() / m.n_uc.sum()
            )
        ),
    }

    # ---------------------------------------------------------------- datas das chaves (formato e padrão)
    dc = txt(sw.DAT_CON)
    anos_dc = pd.to_numeric(dc.str[-4:], errors="coerce")
    r = anos_dc[classe == "religador"]
    res["dat_con_religadores"] = {
        "formato_dd_mm_aaaa": float(dc.str.fullmatch(r"\d{2}/\d{2}/\d{4}").mean()),
        "nulos": int(dc.isna().sum()),
        "por_ano_ultimos": {str(int(k)): int(v) for k, v in r.value_counts().sort_index().tail(6).items()},
        "padrao_1920": int((dc[classe == "religador"] == "01/01/1920").sum()),
        "padrao_1980": int((dc[classe == "religador"] == "01/01/1980").sum()),
        "antes_de_1990": int((r < 1990).sum()),
    }
    (OUT / f"cadastro_{ano}.json").write_text(json.dumps(res, indent=2, ensure_ascii=False, default=float), encoding="utf-8")
    resumo.append(
        {
            "ano": ano,
            **res["camadas"],
            **{f"religadores_{k}": v for k, v in res["religadores"].items()},
            "unsemt_fora_do_mapeamento": res["frac_unsemt_fora_do_mapeamento"],
            "bt_com_transformador": res["clientes"]["bt_com_transformador_no_cadastro"],
            "pac_ini_na_rede": res["clientes"]["pac_ini_na_rede"],
        }
    )
    logging.info("%s: %s", ano, json.dumps(res["clientes"], default=float))

pd.DataFrame(resumo).to_csv(OUT / "cadastro_resumo.csv", index=False)
