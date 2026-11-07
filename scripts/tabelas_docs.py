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


# ---------------------------------------------------------------- resultados
# ``R`` continua sendo a pasta ``diagnostico``; os resultados ficam em ``R.parent``.
def _j(R, nome):
    return json.loads((R.parent / nome).read_text(encoding="utf-8"))


def mi(v, d=2):
    return br(v / 1e6, d) + " mi"


def tabela_topologia(R, cfg):
    anos = [cfg["ano_atual"], cfg["ano_backtest"]]
    q = _j(R, "qualidade_topologia.json")
    dg = {a: json.loads((R / f"topologia_{a}.json").read_text(encoding="utf-8")) for a in anos}
    pt = _j(R, "porta_qualidade.json")
    lin = [
        ("Circuitos", lambda a: br(q[str(a)]["alimentadores"])),
        ("Nós da rede (PAC)", lambda a: br(q[str(a)]["nos_total"])),
        ("Clientes ligados a um transformador ou PAC", lambda a: br(q[str(a)]["uc_total"])),
        (
            "**Ligados à saída do alimentador, depois do reparo (a porta)**",
            lambda a: f"**{br(q[str(a)]['uc_alcancadas'])} ({pct(q[str(a)]['frac_uc_alcancadas'], 3)})**",
        ),
        (
            "Mínimo pré-registrado e veredito",
            lambda a: f"{pct(pt[str(a)]['minimo'], 0)}: {'passou' if pt[str(a)]['passou'] else 'NÃO passou'}",
        ),
        ("Antes do reparo de lacunas", lambda a: pct(dg[a]["antes_do_reparo"]["frac_uc_alcancadas"], 2)),
        (
            "Componentes religados (lacuna mediana; P90)",
            lambda a: (
                f"{br(q[str(a)]['componentes_religados'])} ({br(q[str(a)]['lacuna_mediana_m'], 1)} m; {br(q[str(a)]['lacuna_p90_m'], 1)} m)"
            ),
        ),
        (
            "Clientes alcançados no mesmo circuito do cadastro",
            lambda a: pct(dg[a]["consistencia_de_circuito"]["frac_clientes_no_mesmo_circuito_do_cadastro"], 2),
        ),
        ("Chaves normalmente abertas (fora do grafo)", lambda a: br(q[str(a)]["chaves_normalmente_abertas"])),
        ("Circuitos sem saída no grafo", lambda a: br(q[str(a)]["alimentadores_sem_saida_no_grafo"])),
    ]
    return md([[r] + [f(a) for a in anos] for r, f in lin], ["", *map(str, anos)])


def tabela_inventario(R, cfg):
    j = _j(R, "diagnostico.json")["inventario"]
    lin = [
        ("Total", j["religadores_no_cadastro"]),
        ("Normalmente abertos (pontos de interligação)", j["religadores_normalmente_abertos"]),
        ("De linha, com clientes a jusante", j["religadores_de_linha_com_clientes"]),
        ("De saída: na subestação, antes do início do alimentador", j["religadores_de_saida"]),
        ("Sem clientes a jusante, outros casos de cadastro", j["religadores_sem_clientes_outros"]),
        ("Com telecomando (`TLCD = 1`)", j["religadores_telecomandados_cadastro"]),
    ]
    return md([[a, br(b)] for a, b in lin], [f"Religadores no cadastro ({cfg['ano_atual']})", ""])


def tabela_zonas(R, cfg):
    d = _j(R, "diagnostico.json")
    z, s, c, r, v = (
        d["zonas_religador_linha"],
        d["zonas_saida"],
        d["zonas_criticas"],
        d["alimentadores_sem_religador_de_linha"],
        d["validacao_modelo"],
    )
    lin = [
        ("Zonas de religador de linha", br(z["n"])),
        ("Clientes na zona: mediana e P90", f"{br(z['clientes_zona_mediana'])} e {br(z['clientes_zona_p90'])}"),
        ("Rede na zona: mediana e P90 (km)", f"{br(z['km_zona_mediana'], 1)} e {br(z['km_zona_p90'], 1)}"),
        ("Zonas com menos de 50 clientes", pct(z["frac_com_menos_de_50_clientes_na_zona"])),
        ("Zona da saída: clientes e km (medianas)", f"{br(s['clientes_zona_mediana'])} e {br(s['km_zona_mediana'], 1)}"),
        ("Zonas de proteção (saída, religador de linha, seccionalizador)", br(c["zonas"])),
        ("As 10% mais críticas: parte do CHI esperado", pct(c["top10pct_frac_chi_esperado"], 0)),
        ("... das quais zona da saída", pct(c["top10pct_frac_saida"], 0)),
        (
            "Alimentadores sem religador de linha (parte dos clientes e da rede)",
            f"{br(r['n'])} ({pct(r['frac_uc'])} e {pct(r['frac_km'])})",
        ),
        ("... entre os 25% mais longos", br(r["longos_sem_religador_n"])),
        (
            "Rede de MT (km) e falhas por 100 km por ano",
            f"{br(d['rede']['km_mt'])} e {br(d['rede']['falhas_mt_por_100km_ano'], 1)}",
        ),
        (
            "Modelo x CI observado: Spearman (alimentadores)",
            f"{br(v['spearman_ci_modelo_vs_observado'], 2)} ({br(v['alimentadores'])})",
        ),
        ("CI observado sobre CI do modelo: razão mediana", br(v["razao_ci_observado_sobre_modelo_mediana"], 2)),
    ]
    return md([[a, b] for a, b in lin], ["", f"{cfg['ano_atual']}"])


def tabela_calibracao(R, cfg):
    a = pd.read_csv(R.parent / "alimentadores.csv", dtype={"NOME": str}).dropna(subset=["chi_ano", "ci_ano"])
    lim = cfg["confiabilidade"]
    a = a.assign(razao=a.ci_ano / a.ci_modelo, chi_mod=a.ci_modelo * a.chi_por_ci)
    piso, resto = a[a.razao < lim["fator_calibracao_min"]], a[a.razao >= lim["fator_calibracao_min"]]

    def dif(g):
        v = round(100 * (g.chi_mod.sum() / g.chi_ano.sum() - 1), 1) + 0.0
        return ("+" if v > 0 else "") + br(v, 1) + "%"

    def lin(rot, g):
        return [rot, br(len(g)), mi(g.chi_ano.sum()), mi(g.chi_mod.sum()), dif(g)]

    return md(
        [
            lin("Todos os alimentadores com histórico", a),
            lin(f"Razão CI observado / CI do modelo abaixo de {br(lim['fator_calibracao_min'], 1)} (no piso da calibração)", piso),
            lin("Demais", resto),
        ],
        ["Grupo", "Alimentadores", "CHI observado (média anual)", "CHI do modelo calibrado", "Modelo sobre observado"],
    )


def tabela_elementos_desempenho(R, cfg):
    d = pd.read_csv(R.parent / "desempenho_elemento_2026.csv")
    return md(
        [
            [r.elemento, br(r.interrupcoes), br(r.uc_por_evento_media), br(r.duracao_mediana_h, 1) + " h", pct(r.frac_chi, 0)]
            for r in d.itertuples()
        ],
        ["Elemento que abriu", "Interrupções", "Clientes por interrupção (média)", "Duração mediana", "Parte do CHI"],
    )


def tabela_seletividade(R, cfg):
    d = _j(R, "desempenho_2026.json")
    s = d["seletividade"]
    lin = [
        ("Interrupções de MT de 2026 (jan-jul, sem março)", br(d["interrupcoes_mt_2026"])),
        ("Casam com um circuito do cadastro de 2025", pct(d["cobertura_vinculo_alimentador"])),
        (
            "Alimentadores elegíveis (saída por disjuntor, religador de linha, 10 ou mais aberturas)",
            br(s["alimentadores_elegiveis"]),
        ),
        ("Com o disjuntor abrindo mais que o esperado (Benjamini-Hochberg, 5%)", br(s["alimentadores_com_suspeita"])),
        (
            "Fração de aberturas do disjuntor: esperada e observada (medianas)",
            f"{pct(s['frac_disjuntor_esperada_mediana'], 0)} e {pct(s['frac_disjuntor_observada_mediana'], 0)}",
        ),
        (
            "Spearman do CHI do modelo com o CHI de 2026 (alimentadores)",
            f"{br(d['modelo_vs_2026']['spearman_chi_modelo_vs_chi_2026'], 2)} ({br(d['modelo_vs_2026']['alimentadores'])})",
        ),
    ]
    return md([[a, b] for a, b in lin], ["", ""])


def tabela_curva(R, cfg):
    p = pd.read_csv(R.parent / "curva_k.csv").pivot(index="k", columns="metodo", values="dec_min")
    return md(
        [
            [br(k)] + [br(p.loc[k, m_], 1) + " min" for m_ in ["modelo (guloso)", "extensao", "clientes", "aleatorio"]]
            for k in p.index
        ],
        [
            "Religadores novos",
            "Modelo (guloso)",
            "Dividir a zona com mais km",
            "Dividir a zona com mais clientes",
            "Local sorteado",
        ],
    )


def tabela_valor(R, cfg):
    c = pd.read_csv(R.parent / "curva_k.csv")
    g = c[c.metodo == "modelo (guloso)"].set_index("k")
    lin = [
        [
            br(k),
            mi(g.loc[k, "chi_evitado_ano"]),
            br(g.loc[k, "dec_min"], 1),
            "R$ " + mi(g.loc[k, "rs_ano_social"], 1),
            "R$ " + mi(g.loc[k, "vpl_social_rs"], 1),
            "R$ " + mi(g.loc[k, "vpl_compensacao_rs"], 1),
        ]
        for k in g.index
    ]
    return md(
        lin,
        [
            "Religadores novos (guloso)",
            "CHI evitado por ano",
            "DEC evitado (min/ano)",
            "R$/ano, visão social",
            "VPL social (20 anos)",
            "VPL só com compensações",
        ],
    )


def tabela_k100(R, cfg):
    k = _j(R, "otimizacao.json")["k100"]
    return md(
        [
            ["Payback social mediano", br(k["payback_social_mediano_anos"], 1) + " ano(s)"],
            ["Pontos com VPL social positivo", pct(k["vpl_positivo_frac"], 0)],
            ["Trocas de fusível por religador", pct(k["frac_troca_fusivel"], 0)],
            ["Alimentadores atendidos", br(k["alimentadores"])],
        ],
        ["Os 100 primeiros locais", ""],
    )


def tabela_sensibilidade(R, cfg):
    d = pd.read_csv(R.parent / "sensibilidade.csv")
    return md(
        [
            [
                r.cenario,
                mi(r.guloso_chi) + " CH",
                mi(r.extensao_chi) + " CH",
                br(r.razao_guloso_extensao, 1) + "×",
                pct(r.frac_troca_fusivel, 0),
            ]
            for r in d.itertuples()
        ],
        ["Cenário (100 religadores)", "Modelo", "Regra por extensão", "Razão", "Troca de fusível"],
    )


def tabela_backtest(R, cfg):
    b = _j(R, "backtest.json")
    s = b["sensibilidade_dat_con_no_periodo"]
    i = pd.read_csv(R.parent / "backtest_instalacoes.csv")
    sub = i[i.DAT_CON.astype(str).str[-4:].isin([str(a) for a in s["anos_dat_con"]])]
    ba, sa = b["auc_alimentador_recebeu_religador"], s["auc_alimentador_recebeu_religador"]
    lin = [
        ("Religadores novos", br(b["religadores_novos"]), br(s["religadores_novos"])),
        (
            "Localizados a até 50 m de um nó da rede de 2024",
            br(b["localizados_na_rede_anterior"]),
            br(s["localizados_na_rede_anterior"]),
        ),
        ("Alimentadores que receberam", br(b["alimentadores_que_receberam"]), br(s["alimentadores_que_receberam"])),
        ("AUC: extensão do alimentador", br(ba["extensao_km"], 2), br(sa["extensao_km"], 2)),
        ("AUC: CHI histórico", br(ba["chi_historico"], 2), br(sa["chi_historico"], 2)),
        ("AUC: modelo (maior ganho)", br(ba["modelo_maior_ganho"], 2), br(sa["modelo_maior_ganho"], 2)),
        ("AUC: clientes", br(ba["clientes"], 2), br(sa["clientes"], 2)),
        (
            "Instalações com menos de 50 clientes a jusante",
            pct((i.uc_jusante < 50).mean(), 0),
            pct((sub.uc_jusante < 50).mean(), 0),
        ),
        (
            "Instalações dentro de ramal com fusível",
            pct(b["frac_dentro_de_ramal_com_fusivel"], 0),
            pct(s["frac_dentro_de_ramal_com_fusivel"], 0),
        ),
        ("Instalações com ganho no modelo", pct(b["frac_com_ganho_no_modelo"], 0), pct(s["frac_com_ganho_no_modelo"], 0)),
        (
            "Instalações no top 10% dos candidatos",
            pct(b["frac_no_top10pct_dos_candidatos"], 0),
            pct(s["frac_no_top10pct_dos_candidatos"], 0),
        ),
        (
            "CHI evitado por ano, instalações reais (modelo)",
            br(b["chi_evitado_ano_instalacoes_reais_modelo"] / 1e3) + " mil",
            br(s["chi_evitado_ano_instalacoes_reais_modelo"] / 1e3) + " mil",
        ),
        (
            "CHI evitado por ano, mesmo número de locais do modelo",
            br(b["chi_evitado_ano_mesmo_numero_no_modelo"] / 1e3) + " mil",
            br(s["chi_evitado_ano_mesmo_numero_no_modelo"] / 1e3) + " mil",
        ),
        (
            "Razão (locais do modelo / instalações reais)",
            br(b["razao_modelo_sobre_real"], 1) + "×",
            br(s["razao_modelo_sobre_real"], 1) + "×",
        ),
    ]
    return md([list(x) for x in lin], ["", "Regra de MT (principal)", "Sensibilidade: `DAT_CON` em 2024 ou 2025"])


def tabela_piso(R, cfg):
    j = _j(R, "diagnostico/calibracao_piso.json")
    pos, bt = j["posicionamento"], j["backtest"]
    ref = pct(j["parte_do_chi_observado_nos_alimentadores_no_piso"], 0)
    lin = []
    for k in ("100", "200"):
        t = pos[k]
        lin.append(
            [
                f"Posicionamento (rede de {cfg['ano_atual']}): {k} primeiros locais",
                f"{br(t['pontos_em_alimentadores_no_piso'])} de {k} ({pct(t['frac_dos_pontos'], 0)})",
                f"{pct(t['frac_do_chi_evitado'], 0)} ({br(t['dec_min_nos_alimentadores_no_piso'], 1)} de {br(t['dec_min_total'], 1)} min)",
            ]
        )
    sem = pos["100_sem_alimentadores_no_piso"]
    lin.append(["... os 100 primeiros, sem alimentadores no piso (guloso refeito)", "0 de 100", f"{br(sem['dec_min'], 1)} min de DEC"])
    for nome, t in (("instalações reais", bt["instalacoes_reais"]), ("locais do modelo", bt["locais_do_modelo_mesmo_numero"])):
        lin.append(
            [
                f"Backtest (rede de {cfg['ano_backtest']}): {nome}",
                f"{br(t['em_alimentadores_no_piso'])} de {br(t['n'])} ({pct(t['frac'], 0)})",
                pct(t["frac_do_chi_evitado"], 0),
            ]
        )
    r = bt["sem_alimentadores_no_piso"]
    lin.append(
        [
            f"... razão locais do modelo / instalações reais, sem alimentadores no piso ({br(r['instalacoes_reais_localizadas'])} instalações)",
            "",
            f"{br(r['razao_modelo_sobre_real'], 1)}×",
        ]
    )
    nota = (
        f"*Referência: os alimentadores no piso têm {ref} do CHI observado de {cfg['ano_atual']} "
        f"({br(j['alimentadores_com_historico']['no_piso'])} de {br(j['alimentadores_com_historico']['n'])} alimentadores) e "
        f"{pct(bt['parte_do_chi_observado_nos_alimentadores_no_piso'], 0)} do de {cfg['ano_backtest']} "
        f"({br(bt['alimentadores_no_piso_na_rede_de_2024'])} alimentadores).*"
    )
    return md(lin, ["", "Pontos em alimentadores no piso da calibração", "Parte do CHI evitado pelo modelo"]) + "\n\n" + nota


def tabela_comparacao_mt(R, cfg):
    """Comparação descritiva com MT, por consumidor e por km. Lê os resultados publicados de MT, só para leitura."""
    mt = config.ROOT / "reports"
    ms_d, mt_d = _j(R, "diagnostico.json"), json.loads((mt / "diagnostico.json").read_text(encoding="utf-8"))
    ms_b, mt_b = _j(R, "backtest.json"), json.loads((mt / "backtest.json").read_text(encoding="utf-8"))
    ms_q = _j(R, "qualidade_topologia.json")[str(cfg["ano_atual"])]
    mt_q = json.loads((mt / "qualidade_topologia.json").read_text(encoding="utf-8"))["2025"]
    ms_c, mt_c = pd.read_csv(R.parent / "curva_k.csv"), pd.read_csv(mt / "curva_k.csv")
    ms_i, mt_i = pd.read_csv(R.parent / "backtest_instalacoes.csv"), pd.read_csv(mt / "backtest_instalacoes.csv")

    def dec(c, met):
        return br(c[(c.k == 100) & (c.metodo == met)].dec_min.iloc[0], 1)

    def par(rot, f):
        return [rot, f(mt_d, mt_b, mt_q, mt_c, mt_i), f(ms_d, ms_b, ms_q, ms_c, ms_i)]

    def km(d):
        return d["rede"]["km_mt"]

    lin = [
        par("Rede de MT (km)", lambda d, b, q, c, i: br(km(d))),
        par("Clientes ligados à saída", lambda d, b, q, c, i: br(q["uc_alcancadas"])),
        par("Clientes por km de rede", lambda d, b, q, c, i: br(q["uc_alcancadas"] / km(d), 1)),
        par("Falhas de MT por 100 km por ano (registros da ANEEL, 2023-2025)", lambda d, b, q, c, i: br(d["rede"]["falhas_mt_por_100km_ano"], 1)),
        par("Religadores de linha por 100 km", lambda d, b, q, c, i: br(100 * d["inventario"]["religadores_de_linha_com_clientes"] / km(d), 2)),
        par("Religadores de linha por 100 mil clientes", lambda d, b, q, c, i: br(1e5 * d["inventario"]["religadores_de_linha_com_clientes"] / q["uc_alcancadas"], 0)),
        par("Zona mediana de religador de linha: clientes", lambda d, b, q, c, i: br(d["zonas_religador_linha"]["clientes_zona_mediana"])),
        par("Zonas de religador com menos de 50 clientes", lambda d, b, q, c, i: pct(d["zonas_religador_linha"]["frac_com_menos_de_50_clientes_na_zona"], 0)),
        par("10% das zonas: parte do CHI esperado", lambda d, b, q, c, i: pct(d["zonas_criticas"]["top10pct_frac_chi_esperado"], 0)),
        par("Modelo x CI observado: Spearman", lambda d, b, q, c, i: br(d["validacao_modelo"]["spearman_ci_modelo_vs_observado"], 2)),
        par("CI observado sobre CI do modelo (mediana)", lambda d, b, q, c, i: br(d["validacao_modelo"]["razao_ci_observado_sobre_modelo_mediana"], 2)),
        par("Backtest: AUC da extensão", lambda d, b, q, c, i: br(b["auc_alimentador_recebeu_religador"]["extensao_km"], 2)),
        par("Backtest: AUC dos clientes", lambda d, b, q, c, i: br(b["auc_alimentador_recebeu_religador"]["clientes"], 2)),
        par("Backtest: instalações com menos de 50 clientes a jusante", lambda d, b, q, c, i: pct((i.uc_jusante < 50).mean(), 0)),
        par("DEC evitado com 100 religadores: modelo (min/ano)", lambda d, b, q, c, i: dec(c, "modelo (guloso)")),
        par("DEC evitado com 100 religadores: regra por extensão (min/ano)", lambda d, b, q, c, i: dec(c, "extensao")),
    ]
    return md(lin, ["", "Energisa MT", "Energisa MS"])


def tabela_destaques(R, cfg):
    q = _j(R, "qualidade_topologia.json")[str(cfg["ano_atual"])]
    d, b, sel = _j(R, "diagnostico.json"), _j(R, "backtest.json"), _j(R, "desempenho_2026.json")["seletividade"]
    dec = pd.read_csv(R.parent / "curva_k.csv").query("k == 100").set_index("metodo").dec_min
    sem_piso = _j(R, "diagnostico/calibracao_piso.json")["posicionamento"]["100_sem_alimentadores_no_piso"]["dec_min"]
    i = pd.read_csv(R.parent / "backtest_instalacoes.csv")
    v, z, cr, auc = d["validacao_modelo"], d["zonas_religador_linha"], d["zonas_criticas"], b["auc_alimentador_recebeu_religador"]
    lin = [
        [
            "Topologia reconstruída",
            f"**{pct(q['frac_uc_alcancadas'], 3)}** dos {br(q['uc_total'] / 1e6, 2)} milhão de clientes ligados à saída do seu alimentador (mínimo pré-registrado: 95%)",
        ],
        [
            "Modelo de zonas x CI observado por alimentador",
            f"Spearman **{br(v['spearman_ci_modelo_vs_observado'], 2)}** ({br(v['alimentadores'])} alimentadores, 2023-2025). O CI do modelo é "
            f"{br(1 / v['razao_ci_observado_sobre_modelo_mediana'], 1)} vezes o observado (razão mediana {br(v['razao_ci_observado_sobre_modelo_mediana'], 2)})",
        ],
        [
            "Religadores de linha (com clientes a jusante)",
            f"**{br(d['inventario']['religadores_de_linha_com_clientes'])}**. Outros {br(d['inventario']['religadores_de_saida'])} fazem papel de disjuntor de saída na subestação",
        ],
        [
            "Zonas de religador com menos de 50 clientes",
            f"**{pct(z['frac_com_menos_de_50_clientes_na_zona'], 0)}**, e a zona mediana tem {br(z['clientes_zona_mediana'])} clientes",
        ],
        [
            "Concentração do risco",
            f"**10% das zonas** de proteção respondem por **{pct(cr['top10pct_frac_chi_esperado'], 0)}** do CHI esperado. {pct(cr['top10pct_frac_saida'], 0)} delas são zona da saída",
        ],
        [
            "Onde a distribuidora instalou religadores em 2025",
            f"Explicado sobretudo pela **extensão** do alimentador (AUC {br(auc['extensao_km'], 2)}) e pelo CHI histórico ({br(auc['chi_historico'], 2)}), não pelos "
            f"clientes ({br(auc['clientes'], 2)}). **{pct((i.uc_jusante < 50).mean(), 0)}** das instalações protegem menos de 50 clientes",
        ],
        [
            f"Mesmo número de religadores ({br(b['religadores_comparados'])}), nos locais do modelo",
            f"**{br(b['razao_modelo_sobre_real'], 0)}×** o CHI evitado das instalações reais, avaliado pelo mesmo modelo",
        ],
        [
            "100 religadores novos, locais do modelo (rede 2025)",
            f'**{br(dec["modelo (guloso)"], 0)} min de DEC/ano** evitados no modelo (**{br(sem_piso, 0)} min** sem os alimentadores no piso da calibração), contra {br(dec["extensao"], 0)} min da regra "dividir a zona com mais km" '
            f"e {br(dec['aleatorio'], 0)} min de locais sorteados",
        ],
        [
            "Disjuntor abrindo mais que o esperado (2026)",
            f"{br(sel['alimentadores_com_suspeita'])} de {br(sel['alimentadores_elegiveis'])} alimentadores elegíveis. **Só descritivo**: o campo de elemento quase não registra disjuntor em MS",
        ],
    ]
    return md(lin, ["", ""])


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
    "topologia": tabela_topologia,
    "inventario": tabela_inventario,
    "zonas": tabela_zonas,
    "calibracao": tabela_calibracao,
    "elementos_desempenho": tabela_elementos_desempenho,
    "seletividade": tabela_seletividade,
    "curva": tabela_curva,
    "valor": tabela_valor,
    "k100": tabela_k100,
    "sensibilidade": tabela_sensibilidade,
    "backtest": tabela_backtest,
    "piso": tabela_piso,
    "comparacao_mt": tabela_comparacao_mt,
    "destaques": tabela_destaques,
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
