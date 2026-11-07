"""Figuras do README a partir dos resultados (``reports`` e ``data/processed`` da configuração).

Desenha só as figuras cujos arquivos de entrada existem (em MS, sem passar a porta de qualidade não há resultado de rede).
Nas figuras que dependem do ``valor.json`` (1, 2 e 5) o rodapé repete ``origem_efeito`` quando o arquivo traz o campo.
"""
import json

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from pyproj import Transformer

from recloser import config

cfg, _ = config.argumentos(__doc__)
R = config.pasta_relatorios(cfg)
F = R / "figures"
F.mkdir(parents=True, exist_ok=True)
NOME = config.nome(cfg)
ELEMENTOS_MT = ["DISJUNTOR", "RELIGADOR", "CHAVE SECCIONADORA", "CHAVE FUSIVEL"]
ELEMENTOS = cfg.get("figuras", {}).get("elementos", ELEMENTOS_MT)
ROTULO_ELEMENTO = {
    "DISJUNTOR": "Disjuntor", "RELIGADOR": "Religador", "CHAVE SECCIONADORA": "Chave\nseccionadora",
    "CHAVE FUSIVEL": "Chave\nfusível", "TRANSFORMADOR": "Transfor-\nmador", "MEDIDOR": "Medidor",
    "NAO IDENTIFICADO": "Não\nidentificado",
}
COR_ELEMENTO = ["#eb6834", "#2a78d6", "#1baf7a", "#8a8a8a", "#a05cc4", "#c8a000", "#555555"]
plt.rcParams.update({"figure.dpi": 130, "font.size": 10, "axes.spines.top": False, "axes.spines.right": False,
                     "axes.grid": True, "grid.color": "#e6e6e6", "axes.axisbelow": True,
                     "figure.facecolor": "#fcfcfb", "axes.facecolor": "#fcfcfb"})
COR = {"modelo (guloso)": "#2a78d6", "extensao": "#eb6834", "clientes": "#1baf7a", "aleatorio": "#8a8a8a"}
ROT = {"modelo (guloso)": "Modelo (guloso)", "extensao": "Dividir a zona com mais km",
       "clientes": "Dividir a zona com mais clientes", "aleatorio": "Local sorteado"}


def br(v, d=0):
    return f"{v:,.{d}f}".replace(",", "X").replace(".", ",").replace("X", ".")


def existem(*arquivos) -> bool:
    return all((R / a).exists() for a in arquivos)


def origem_efeito(arquivo: str) -> str | None:
    """``origem_efeito`` gravado no JSON de resultados (só MS)."""
    return json.loads((R / arquivo).read_text(encoding="utf-8")).get("origem_efeito") if existem(arquivo) else None


def rodape(fig, origem: str | None) -> None:
    if origem:
        fig.text(0.01, 0.005, f"Efeito do religador: {origem}", fontsize=7.5, color="#666666", ha="left", va="bottom")


ANO = json.loads((R / "diagnostico.json").read_text())["ano"] if existem("diagnostico.json") else cfg["ano_atual"]

# 1. curva K x DEC evitado
if existem("curva_k.csv"):
    c = pd.read_csv(R / "curva_k.csv")
    fig, ax = plt.subplots(figsize=(7.2, 4.2))
    for met, g in c.groupby("metodo"):
        ax.plot(g.k, g.dec_min, marker="o", lw=2.2, color=COR[met], label=ROT[met])
        last = g.iloc[-1]
        dy = {"extensao": 6, "clientes": -6}.get(met, 0)
        ax.annotate(br(last.dec_min, 1) + " min", (last.k, last.dec_min), xytext=(6, dy), textcoords="offset points",
                    va="center", fontsize=9, color=COR[met])
    ax.set_xlabel("Religadores novos")
    ax.set_ylabel("DEC evitado por ano (min)")
    ax.set_xlim(0, 235)
    ax.set_title(f"Mesmo número de religadores, lugares diferentes\n(rede de {ANO}, avaliado pelo modelo de zonas)",
                 loc="left", fontsize=11, fontweight="bold")
    ax.legend(frameon=False, loc="upper left")
    fig.tight_layout()
    rodape(fig, origem_efeito("otimizacao.json"))
    fig.savefig(F / "01_curva_k.png")
    plt.close(fig)

# 2. mapa: rede, religadores de linha existentes e os 100 primeiros propostos
ARQ_NOS = config.pasta_processada(cfg) / f"nos_{ANO}.parquet"
if existem("zonas.csv", "lista_priorizada.csv", "diagnostico.json") and ARQ_NOS.exists():
    nos = pd.read_parquet(ARQ_NOS, columns=["x", "y", "classe"])
    tr = Transformer.from_crs(config.crs_pac(cfg), 4326, always_xy=True)
    finitos = nos[np.isfinite(nos.x)]
    amostra = finitos.sample(min(250_000, len(finitos)), random_state=0)
    lx, ly = tr.transform(amostra.x.to_numpy(), amostra.y.to_numpy())
    z = pd.read_csv(R / "zonas.csv")
    rl = z[z.classe == "religador"]
    rx, ry = tr.transform(rl.x.to_numpy(), rl.y.to_numpy())
    lista = pd.read_csv(R / "lista_priorizada.csv").head(100)
    fig, ax = plt.subplots(figsize=(7.2, 7.2))
    ax.scatter(lx, ly, s=0.05, color="#c9c9c9", rasterized=True)
    ax.scatter(rx, ry, s=4, color="#2a78d6", alpha=0.6, label=f"Religadores de linha hoje ({br(len(rl))})")
    ax.scatter(lista.lon, lista.lat, s=60, marker="*", color="#d0342c", edgecolor="white", lw=0.4,
               label="100 primeiros locais propostos")
    ax.set_aspect(1 / np.cos(np.radians(cfg.get("mapa", {}).get("lat_aspecto", -13))))
    ax.set_xticks([]), ax.set_yticks([])
    ax.grid(False)
    for s in ax.spines.values():
        s.set_visible(False)
    ax.legend(frameon=False, loc="lower left", markerscale=2)
    ax.set_title(f"Rede de média tensão da {NOME} (BDGD {ANO})", loc="left", fontsize=11, fontweight="bold")
    fig.tight_layout()
    rodape(fig, origem_efeito("otimizacao.json"))
    fig.savefig(F / "02_mapa.png")
    plt.close(fig)

# 3. concentração do CHI esperado por zona
if existem("zonas.csv"):
    z = pd.read_csv(R / "zonas.csv")
    rl = z[z.classe == "religador"]
    zz = z[z.classe.isin(["saida", "religador", "seccionalizador"])].sort_values("chi_esperado_ano", ascending=False)
    acum = zz.chi_esperado_ano.cumsum() / zz.chi_esperado_ano.sum()
    frac = np.arange(1, len(zz) + 1) / len(zz)
    fig, ax = plt.subplots(1, 2, figsize=(9.6, 3.8))
    ax[0].plot(frac * 100, acum * 100, color="#2a78d6", lw=2.2)
    i10 = int(round(len(zz) * 0.1)) - 1
    ax[0].scatter([10], [acum.iloc[i10] * 100], color="#d0342c", zorder=3)
    ax[0].annotate(f"10% das zonas = {br(acum.iloc[i10] * 100)}% do CHI", (10, acum.iloc[i10] * 100), xytext=(14, -18),
                   textcoords="offset points", fontsize=9)
    ax[0].set_xlabel("% das zonas de proteção (ordenadas por CHI esperado)")
    ax[0].set_ylabel("% acumulado do CHI esperado")
    ax[0].set_title("Poucas zonas concentram o risco", loc="left", fontsize=10.5, fontweight="bold")
    bins = np.logspace(0, 4.2, 30)
    ax[1].hist(z[z.classe == "saida"].uc_zona.clip(lower=1), bins=bins, color="#eb6834", alpha=0.75,
               label="Zona da saída (só o disjuntor protege)")
    ax[1].hist(rl.uc_zona.clip(lower=1), bins=bins, color="#2a78d6", alpha=0.75, label="Zona de religador de linha")
    ax[1].set_xscale("log")
    ax[1].set_xlabel("Clientes na zona (escala log)")
    ax[1].set_ylabel("Zonas")
    ax[1].legend(frameon=False, fontsize=8.5)
    ax[1].set_title("Clientes por zona de proteção", loc="left", fontsize=10.5, fontweight="bold")
    fig.tight_layout()
    fig.savefig(F / "03_zonas.png")
    plt.close(fig)

# 4. desempenho por elemento (2026); em MS todos os elementos relevantes, já que o preenchimento do campo é irregular
if existem("desempenho_elemento_2026.csv"):
    el = pd.read_csv(R / "desempenho_elemento_2026.csv").set_index("elemento")
    ordem = ELEMENTOS
    nomes = [ROTULO_ELEMENTO.get(o, o.title()) for o in ordem]
    el = el.reindex(ordem)
    fig, ax = plt.subplots(1, 3, figsize=(10, 3.4) if len(ordem) == 4 else (16, 3.9))
    for a, col, tit in [(ax[0], "interrupcoes", "Interrupções (jan-jul 2026)"),
                        (ax[1], "uc_por_evento_media", "Clientes por interrupção (média)"),
                        (ax[2], "duracao_mediana_h", "Duração mediana (h)")]:
        b = a.bar(nomes, el[col], color=COR_ELEMENTO[:len(ordem)])
        a.bar_label(b, labels=[br(v, 1 if "h" in tit else 0) for v in el[col]], fontsize=8.5, padding=2)
        a.set_title(tit, loc="left", fontsize=10, fontweight="bold")
        a.tick_params(axis="x", labelsize=8.5 if len(ordem) == 4 else 8)
    fig.tight_layout()
    fig.savefig(F / "04_elementos_2026.png")
    plt.close(fig)

# 5. backtest
if existem("backtest.json"):
    bt = json.load(open(R / "backtest.json"))
    fig, ax = plt.subplots(1, 2, figsize=(9.6, 3.6))
    auc = bt["auc_alimentador_recebeu_religador"]
    rot = {"extensao_km": "Extensão (km)", "chi_historico": "CHI histórico", "modelo_maior_ganho": "Modelo",
           "clientes": "Clientes"}
    items = [(rot[k], auc[k]) for k in ["extensao_km", "chi_historico", "modelo_maior_ganho", "clientes"]]
    b = ax[0].barh([i[0] for i in items][::-1], [i[1] for i in items][::-1], color="#2a78d6")
    ax[0].bar_label(b, labels=[br(i[1], 2) for i in items][::-1], padding=3, fontsize=9)
    ax[0].axvline(0.5, color="#888", lw=1, ls="--")
    ax[0].set_xlim(0.4, 0.85)
    ax[0].set_title(f"O que explica onde a distribuidora instalou\n(AUC por alimentador, {bt['anos'][0]} → {bt['anos'][1]})",
                    loc="left", fontsize=10, fontweight="bold")
    v = [bt["chi_evitado_ano_instalacoes_reais_modelo"], bt["chi_evitado_ano_mesmo_numero_no_modelo"]]
    b = ax[1].bar([f"{bt['religadores_comparados']} instalações\nreais ({bt['anos'][1]})",
                   f"{bt['religadores_comparados']} locais\ndo modelo"], np.array(v) / 1e3, color=["#8a8a8a", "#2a78d6"])
    ax[1].bar_label(b, labels=[br(x / 1e3) + " mil" for x in v], padding=3, fontsize=9)
    ax[1].set_ylabel("CHI evitado por ano (mil), pelo modelo")
    ax[1].set_title(f"Mesmo número de religadores, rede de {bt['anos'][0]}", loc="left", fontsize=10, fontweight="bold")
    fig.tight_layout()
    rodape(fig, bt.get("origem_efeito"))
    fig.savefig(F / "05_backtest.png")
    plt.close(fig)

# 6. seletividade
if existem("seletividade_2026.csv"):
    s = pd.read_csv(R / "seletividade_2026.csv")
    fig, ax = plt.subplots(figsize=(5.6, 4.6))
    ax.plot([0, 1], [0, 1], color="#888", lw=1, ls="--")
    ax.scatter(s.frac_disjuntor_esperada, s.frac_disjuntor_observada, s=(s.DISJUNTOR + s.RELIGADOR) * 0.6,
               c=np.where(s.suspeita, "#d0342c", "#2a78d6"), alpha=0.7, edgecolor="white", lw=0.5)
    ax.set_xlabel("Fração esperada de aberturas do disjuntor (modelo de zonas)")
    ax.set_ylabel("Fração observada em 2026 (jan-jul)")
    ax.set_title(f"Disjuntor abrindo mais que o esperado\n{int(s.suspeita.sum())} de {len(s)} alimentadores (vermelho)",
                 loc="left", fontsize=10.5, fontweight="bold")
    fig.tight_layout()
    fig.savefig(F / "06_seletividade.png")
    plt.close(fig)
print("ok")
