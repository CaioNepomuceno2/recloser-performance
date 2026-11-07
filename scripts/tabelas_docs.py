"""Imprime em Markdown as tabelas citadas em ``docs/decisoes_ems.md`` e ``docs/resultados_ems.md``.

Cada número das tabelas sai dos arquivos de ``<reports>`` (regenerados pelos scripts); nada é digitado à mão.
Uso: ``python scripts/tabelas_docs.py --config configs/params_ems.yaml NOME [NOME ...]``
(``NOME``: pac, formato_pac, cadastro, tip_unid, duplicatas, vinculo, cobertura_2026, elementos_2026, instalacoes).
"""

import argparse
import json

import pandas as pd

from recloser import config


def br(v, d=0):
    """Número no formato brasileiro (milhar com ponto, decimal com vírgula)."""
    return f"{v:,.{d}f}".replace(",", "X").replace(".", ",").replace("X", ".")


def pct(v, d=1):
    return br(100 * v, d) + "%"


def md(linhas: list[list], cab: list[str]) -> str:
    out = ["| " + " | ".join(cab) + " |", "|" + "|".join(["---"] * len(cab)) + "|"]
    out += ["| " + " | ".join(str(c) for c in ln) + " |" for ln in linhas]
    return "\n".join(out)


def m(v):
    """Metros: notação curta para distâncias de ordem muito diferente."""
    if v < 0.01:
        return "< 0,01 m"
    return br(v, 2 if v < 100 else 0) + " m"


def tabela_pac(R, cfg):
    d = pd.read_csv(R / "pac_utm_resumo.csv")
    d = d[d.ano == cfg["ano_atual"]]
    camadas = [
        ("UNTRMT.PAC_1 x ponto do trafo", "PAC do trafo x ponto do trafo"),
        ("UNSEMT.PAC_1 x ponto da chave", "PAC da chave x ponto da chave"),
        ("SSDMT.PAC_1 x 1o vértice", "PAC_1 do segmento x 1o vértice"),
        ("SSDMT.PAC_2 x último vértice", "PAC_2 do segmento x último vértice"),
    ]
    hip = [
        "UTM 20S (estado todo)",
        "UTM 21S (estado todo)",
        "UTM 22S (estado todo)",
        "UTM 23S (estado todo)",
        "fuso natural de cada ponto (21S / 22S)",
    ]
    linhas = []
    for c, rot in camadas:
        for h in hip:
            r = d[(d.camada == c) & (d.hipotese == h) & (d.regiao == "todo o estado")].iloc[0]
            linhas.append(
                [
                    rot,
                    h.replace(" (estado todo)", ""),
                    br(r.n),
                    m(r.mediana_m),
                    m(r.p99_m),
                    m(r.max_m),
                    pct(r.frac_ate_1m),
                    pct(r.frac_ate_50m, 3),
                    pct(r.frac_ate_100m, 3),
                ]
            )
    return md(linhas, ["Comparação", "Referência", "Pontos", "Mediana", "P99", "Máximo", "≤ 1 m", "≤ 50 m", "≤ 100 m"])


def tabela_formato_pac(R, cfg):
    j = json.loads((R / f"pac_utm_{cfg['ano_atual']}.json").read_text(encoding="utf-8"))
    pl = j["plausibilidade_geografica"]
    linhas = [
        [
            k,
            br(v["n"]),
            pct(v["frac_coordenada_19_20"], 2),
            ", ".join(f"{a}: {br(b)}" for a, b in v["comprimentos"].items() if a in ("19", "20")),
        ]
        for k, v in j["formato"].items()
    ]
    t1 = md(linhas, ["Campo", "Registros", "Com coordenada (19 ou 20 caracteres)", "Registros de 19 e de 20 caracteres"])
    linhas = [
        [
            k,
            br(v["nos_unicos"]),
            f"{br(v['lon_min'], 2)} a {br(v['lon_max'], 2)}",
            f"{br(v['lat_min'], 2)} a {br(v['lat_max'], 2)}",
            pct(v["frac_dentro_do_estado"], 2),
            pct(v["frac_dentro_do_estado_com_margem_0_1_grau"], 2),
        ]
        for k, v in pl.items()
    ]
    t2 = md(
        linhas,
        ["Leitura do PAC como", "Nós distintos", "Longitude", "Latitude", "Dentro do estado", "Dentro, com margem de 0,1°"],
    )
    return t1 + "\n\n" + t2


def tabela_cadastro(R, cfg):
    anos = sorted({cfg["ano_backtest"], cfg["ano_atual"]})
    js = {a: json.loads((R / f"cadastro_{a}.json").read_text(encoding="utf-8")) for a in anos}
    lin = [
        ("Segmentos de MT (`SSDMT`)", lambda j: br(j["camadas"]["SSDMT"])),
        ("Rede MT (km)", lambda j: br(j["camadas"]["SSDMT_km"])),
        ("Segmentos sem `COMP` (nulo ou zero)", lambda j: br(j["camadas"]["SSDMT_comp_nulo_ou_zero"])),
        ("Chaves e equipamentos (`UNSEMT`)", lambda j: br(j["camadas"]["UNSEMT"])),
        ("Religadores (`TIP_UNID` 32)", lambda j: br(j["religadores"]["n"])),
        ("Religadores telecomandados", lambda j: pct(j["religadores"]["frac_telecomandados"])),
        ("Religadores normalmente abertos", lambda j: pct(j["religadores"]["frac_normalmente_abertos"])),
        ("Chaves fusíveis (22 a 27)", lambda j: br(j["classes_unsemt"]["fusivel"])),
        ("Seccionalizadores (35, 36)", lambda j: br(j["classes_unsemt"]["seccionalizador"])),
        ("Disjuntores (29, 30, 53)", lambda j: br(j["classes_unsemt"]["disjuntor"])),
        ("Fora do mapeamento (virão como `chave`)", lambda j: pct(j["frac_unsemt_fora_do_mapeamento"])),
        ("Reguladores (`UNREMT`)", lambda j: br(j["camadas"]["UNREMT"])),
        ("Transformadores MT (`UNTRMT`)", lambda j: br(j["camadas"]["UNTRMT"])),
        ("Circuitos (`CTMT`)", lambda j: br(j["camadas"]["CTMT"])),
        ("Consumidores BT (`UCBT_tab`)", lambda j: br(j["camadas"]["UCBT_consumidores"])),
        ("Consumidores MT (`UCMT_tab`)", lambda j: br(j["camadas"]["UCMT_consumidores"])),
        ("BT com transformador no cadastro", lambda j: pct(j["clientes"]["bt_com_transformador_no_cadastro"], 2)),
        ("MT com PAC na rede", lambda j: pct(j["clientes"]["mt_com_pac_na_rede"], 2)),
        (
            "Consumidores ligados a um transformador ou PAC",
            lambda j: pct(j["clientes"]["cadastro_consumidores_ligados_a_trafo_ou_pac"], 2),
        ),
        ("`PAC_INI` dos circuitos presente na rede", lambda j: pct(j["clientes"]["pac_ini_na_rede"], 1)),
        ("`CTMT` do cliente BT igual ao do seu transformador", lambda j: pct(j["clientes"]["ucbt_ctmt_igual_ao_do_trafo"], 2)),
        ("`UNSEMT.CTMT` existe em `CTMT`", lambda j: pct(j["circuitos"]["unsemt_ctmt_existe_em_ctmt"], 1)),
        ("`CTMT.NOME`: 5 caracteres", lambda j: br(j["circuitos"]["nome_comprimentos"].get("5", 0))),
        ("`CTMT.NOME`: só dígitos", lambda j: pct(j["circuitos"]["nome_so_digitos"], 0)),
        ("`CTMT.NOME` repetido (depois de completar a 6)", lambda j: br(j["circuitos"]["canonico_repetidos"])),
    ]
    return md([[r] + [f(js[a]) for a in anos] for r, f in lin], ["", *map(str, anos)])


def tabela_tip_unid(R, cfg):
    a = cfg["ano_atual"]
    d = pd.read_csv(R / f"tip_unid_{a}.csv", dtype={"TIP_UNID": str}).head(12)
    return md(
        [[r.TIP_UNID, r.classe, br(r.n), pct(r.frac_telecomandadas, 1), pct(r.frac_abertas, 1)] for r in d.itertuples()],
        ["`TIP_UNID`", "Classe no estudo", "Equipamentos", "Telecomandados", "Normalmente abertos"],
    )


def tabela_duplicatas(R, cfg):
    d = pd.read_csv(R / "duplicatas_arquivos.csv")
    return md(
        [[r.arquivo, br(r.linhas), br(r.distintas), br(r.repetidas), br(r.pct_repetidas, 3)] for r in d.itertuples()],
        ["Arquivo", "`count(*)`", "`count(distinct *)`", "Repetidas", "%"],
    )


def tabela_vinculo(R, cfg):
    d = pd.read_csv(R / "falhas_vinculo_cadastro.csv")
    return md(
        [
            [
                r.snapshot,
                r.anos_das_falhas,
                r.chave,
                br(r.falhas),
                pct(r.frac_falhas_casadas, 2),
                pct(r.frac_chi_casado, 2),
                f"{br(r.alimentadores_casados)} de {br(r.alimentadores_com_historico)}",
            ]
            for r in d.itertuples()
        ],
        [
            "Cadastro",
            "Falhas de",
            "Chave do nome do circuito",
            "Falhas",
            "Casam",
            "CHI casa",
            "Alimentadores do histórico que casam",
        ],
    )


def tabela_cobertura_2026(R, cfg):
    d = pd.read_csv(R / "cobertura_2026.csv")
    return md(
        [[r.mes, br(r.interrupcoes), pct(r.frac_casa_cadastro), pct(r.frac_elemento_identificado, 0)] for r in d.itertuples()],
        [
            "Mês de 2026",
            "Interrupções de MT (internas, não programadas)",
            "Casam com um circuito do cadastro de 2025",
            "Com elemento identificado",
        ],
    )


def tabela_elementos_2026(R, cfg):
    d = pd.read_csv(R / "elemento_2026.csv")
    return md(
        [[r.elemento, br(r.total), pct(r.total / d.total.sum())] for r in d.itertuples()],
        ["Elemento que interrompeu", "Interrupções", "%"],
    )


def tabela_instalacoes(R, cfg):
    j = json.loads((R / "instalacoes.json").read_text(encoding="utf-8"))
    a0, a1 = j["snapshots"]
    c, rb, st, sm, ca = (
        j["cadastro"],
        j["regra_do_backtest"],
        j["cod_id_estavel"],
        j["religadores_que_sumiram"],
        j["cadastro"]["classes"],
    )
    chave = next(k for k in rb if k.startswith("novos_dat_con_em_"))
    linhas = [
        [f"Chaves e equipamentos (`UNSEMT`), {a0} e {a1}", f"{br(c['unsemt'][str(a0)])} e {br(c['unsemt'][str(a1)])}"],
        [f"Chaves fusíveis, {a0} e {a1}", f"{br(ca[str(a0)]['fusivel'])} e {br(ca[str(a1)]['fusivel'])}"],
        [f"Seccionalizadores, {a0} e {a1}", f"{br(ca[str(a0)]['seccionalizador'])} e {br(ca[str(a1)]['seccionalizador'])}"],
        [
            f"Religadores, {a0} e {a1} (saldo)",
            f"{br(c['religadores'][str(a0)])} e {br(c['religadores'][str(a1)])} (+{br(sm['saldo_religadores'])})",
        ],
        [
            f"Religadores telecomandados, {a0} e {a1}",
            f"{pct(c['frac_religadores_telecomandados'][str(a0)], 0)} e {pct(c['frac_religadores_telecomandados'][str(a1)], 0)}",
        ],
        [f"`COD_ID` de {a1} que já existia em {a0}", pct(c["frac_cod_id_do_ano_atual_que_ja_existia"])],
        [f"`COD_ID` de {a0} que continua em {a1}", pct(c["frac_cod_id_do_ano_base_que_continua"])],
        [
            f"Religadores fechados em {a1} com `COD_ID` de {a0}: n e deslocamento mediano",
            f"{br(st['n'])} e {m(st['deslocamento_mediana_m'])}",
        ],
        [
            "... dentro de 1 m / 50 m / 100 m",
            f"{pct(st['frac_ate_1m'])} / {pct(st['frac_ate_50m'])} / {pct(st['frac_ate_100m'])}",
        ],
        [f"Religadores fechados em {a1}", br(rb["religadores_fechados_no_ano_atual"])],
        ["... com `COD_ID` novo", br(rb["cod_id_novo"])],
        [
            "... dos quais a menos de 100 m de um religador antigo (não contam como novos)",
            br(rb["cod_id_novo_com_religador_antigo_a_menos_de_100m"]),
        ],
        [
            "**Novos pela regra do backtest** (`COD_ID` novo e nenhum religador antigo a menos de 100 m)",
            f"**{br(rb['novos_pela_regra'])}**",
        ],
        [f"... com `DAT_CON` em {a0} ou {a1}", f"{br(rb[chave])} ({pct(rb[chave] / rb['novos_pela_regra'], 0)})"],
        [
            f"... com `DAT_CON` anterior a {a0}",
            f"{br(rb['novos_dat_con_antes_do_ano_base'])} ({pct(rb['frac_novos_dat_con_antes_do_ano_base'], 0)})",
        ],
        [
            f"Religadores de {a0} que sumiram (`COD_ID` ausente e nenhum religador a menos de 100 m)",
            br(sm["cod_id_ausente_e_sem_religador_a_menos_de_100m"]),
        ],
        ["... só `COD_ID` ausente", br(sm["cod_id_ausente_no_ano_atual"])],
        ["Novos em circuitos onde sumiu algum religador", br(sm["novos_em_circuitos_onde_sumiu_religador"])],
    ]
    return md(linhas, ["", "Valor"])


TABELAS = {
    "pac": tabela_pac,
    "formato_pac": tabela_formato_pac,
    "cadastro": tabela_cadastro,
    "tip_unid": tabela_tip_unid,
    "duplicatas": tabela_duplicatas,
    "vinculo": tabela_vinculo,
    "cobertura_2026": tabela_cobertura_2026,
    "elementos_2026": tabela_elementos_2026,
    "instalacoes": tabela_instalacoes,
}

if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--config", default=None)
    ap.add_argument("nomes", nargs="+", choices=sorted(TABELAS))
    args = ap.parse_args()
    cfg = config.carregar(args.config)
    R = config.pasta_relatorios(cfg) / "diagnostico"
    for n in args.nomes:
        print(f"<!-- {n} -->\n{TABELAS[n](R, cfg)}\n")
