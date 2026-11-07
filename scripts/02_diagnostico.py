"""Zonas de proteção dos religadores (2025) e validação do modelo de confiabilidade."""
import json
import logging

import numpy as np
import pandas as pd

from recloser import analise, config, dados

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
cfg, _ = config.argumentos(__doc__)
OUT = config.pasta_relatorios(cfg)
OUT.mkdir(parents=True, exist_ok=True)
ano = cfg["ano_atual"]
config.exigir_porta(cfg, ano)
e = analise.preparar(cfg, ano, cfg["confiabilidade"]["anos_taxa"])
m, al = e.modelo, e.alimentadores

# ---------------------------------------------------------------- religadores no cadastro e na árvore
u = pd.read_parquet(config.pasta_ano(cfg, ano) / "UNSEMT.parquet", columns=["COD_ID", "TIP_UNID", "P_N_OPE", "TLCD"])
rel_cad = u[u.TIP_UNID.astype(str).str.strip().isin(cfg["tip_unid"]["religador"])]
classes = m.nos.classe.value_counts()
inventario = {
    "religadores_no_cadastro": len(rel_cad),
    "religadores_normalmente_abertos": int((rel_cad.P_N_OPE.astype(str).str.strip() == "A").sum()),
    "religadores_telecomandados_cadastro": int((pd.to_numeric(rel_cad.TLCD, errors="coerce") == 1).sum()),
    "religadores_de_linha_com_clientes": int(classes.get("religador", 0)),
    "religadores_de_saida": int(classes.get("religador_saida", 0)),
    "religadores_sem_clientes_outros": int(classes.get("religador_sem_clientes", 0)),
    "seccionalizadores": int(classes.get("seccionalizador", 0)),
    "chaves_fusiveis_na_arvore": int(classes.get("fusivel", 0)),
    "alimentadores": len(al),
    "alimentadores_com_saida_por_religador": int(al.saida_por_religador.sum()),
}

# ---------------------------------------------------------------- zonas
z = m.zonas()
z["dispositivo"] = z.classe.map({"saida": "saída do alimentador", "religador": "religador de linha",
                                 "seccionalizador": "seccionalizador"})
linha = z[z.classe == "religador"]
saidas = z[z.classe == "saida"]
# alimentadores: religadores de linha, extensão e clientes
n_rel = linha.groupby("ctmt").size()
km = m.nos.groupby("ctmt").comp_m.sum() / 1000
uc = m.nos.groupby("ctmt").uc.sum()
fa = pd.DataFrame({"km_mt": km, "uc": uc, "religadores_linha": n_rel}).fillna({"religadores_linha": 0})
fa["km_por_dispositivo"] = fa.km_mt / (fa.religadores_linha + 1)
fa["uc_por_dispositivo"] = fa.uc / (fa.religadores_linha + 1)
fa = fa.join(al.set_index("ctmt")[["NOME", "SUB", "chi_ano", "ci_ano", "falhas_ano", "ci_modelo",
                                   "chi_por_ci", "saida_por_religador"]])
fa.index.name = "ctmt"
fa.reset_index().to_csv(OUT / "alimentadores.csv", index=False)
p75 = fa.km_mt.quantile(0.75)
sem_rel = fa[fa.religadores_linha == 0]
longos_sem = fa[(fa.km_mt >= p75) & (fa.religadores_linha == 0)]

# CHI esperado (calibrado) causado por faltas em cada zona
lam = m.lam_m * m.comp
peso = np.where(m.sob_fus, 1.0, 1.0 - m.tau)
fator = m.nos.ctmt.map(e.chi_por_ci).fillna(0).to_numpy()
chi_no = lam * peso * m.n_sub[m.disp_prot] * fator
z["chi_esperado_ano"] = np.bincount(m.disp_rel, weights=chi_no, minlength=len(m.nos))[z.linha]
zz = z[z.classe.isin(["saida", "religador", "seccionalizador"])].sort_values("chi_esperado_ano", ascending=False)
top10 = zz.head(max(1, round(len(zz) * 0.10)))
z.drop(columns=["linha"]).to_csv(OUT / "zonas.csv", index=False)

# taxa de falhas por km e por modo
modos = dados.falhas_por_modo(cfg["falhas"], cfg["confiabilidade"]["anos_taxa"])
km_total = float(km.sum())
modos["falhas_por_100km_ano"] = modos.n_falhas / km_total * 100
modos.to_csv(OUT / "falhas_por_modo.csv", index=False)

resumo = {
    "ano": ano,
    "inventario": inventario,
    "validacao_modelo": analise.validacao_modelo(al),
    "zonas_religador_linha": {
        "n": len(linha),
        "clientes_jusante_mediana": float(linha.uc_jusante.median()),
        "clientes_zona_mediana": float(linha.uc_zona.median()),
        "clientes_zona_p90": float(linha.uc_zona.quantile(0.9)),
        "km_zona_mediana": float(linha.km_zona.median()),
        "km_zona_p90": float(linha.km_zona.quantile(0.9)),
        "frac_com_menos_de_50_clientes_na_zona": float((linha.uc_zona < 50).mean()),
        "em_serie_max": int(linha.religadores_em_serie.max()),
    },
    "zonas_saida": {
        "clientes_zona_mediana": float(saidas.uc_zona.median()),
        "km_zona_mediana": float(saidas.km_zona.median()),
    },
    "alimentadores_sem_religador_de_linha": {
        "n": len(sem_rel), "frac_uc": float(sem_rel.uc.sum() / fa.uc.sum()),
        "frac_km": float(sem_rel.km_mt.sum() / km_total),
        "longos_sem_religador_n": len(longos_sem), "km_p75": float(p75),
        "longos_sem_religador_uc": float(longos_sem.uc.sum()),
    },
    "zonas_criticas": {"zonas": len(zz), "top10pct_n": len(top10),
                       "top10pct_frac_chi_esperado": float(top10.chi_esperado_ano.sum() / zz.chi_esperado_ano.sum()),
                       "top10pct_uc_zona": float(top10.uc_zona.sum()),
                       "top10pct_frac_saida": float((top10.classe == "saida").mean())},
    "rede": {"km_mt": km_total, "uc_alcancadas": float(uc.sum()),
             "falhas_mt_por_100km_ano": float(modos.n_falhas.sum() / km_total * 100)},
}
(OUT / "diagnostico.json").write_text(json.dumps(resumo, indent=2, ensure_ascii=False))
logging.info(json.dumps(resumo, indent=1, ensure_ascii=False))
