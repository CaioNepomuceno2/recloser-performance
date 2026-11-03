"""Figuras do README a partir de reports/ e data/processed/."""
import json

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from pyproj import Transformer

from recloser import config

R = config.ROOT / "reports"
F = R / "figures"
F.mkdir(parents=True, exist_ok=True)
plt.rcParams.update({"figure.dpi": 130, "font.size": 10, "axes.spines.top": False, "axes.spines.right": False,
                     "axes.grid": True, "grid.color": "#e6e6e6", "axes.axisbelow": True,
                     "figure.facecolor": "#fcfcfb", "axes.facecolor": "#fcfcfb"})
COR = {"modelo (guloso)": "#2a78d6", "extensao": "#eb6834", "clientes": "#1baf7a", "aleatorio": "#8a8a8a"}
ROT = {"modelo (guloso)": "Modelo (guloso)", "extensao": "Dividir a zona com mais km",
       "clientes": "Dividir a zona com mais clientes", "aleatorio": "Local sorteado"}


def br(v, d=0):
    return f"{v:,.{d}f}".replace(",", "X").replace(".", ",").replace("X", ".")


# 1. curva K x DEC evitado
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
ax.set_title("Mesmo número de religadores, lugares diferentes\n(rede de 2025, avaliado pelo modelo de zonas)",
             loc="left", fontsize=11, fontweight="bold")
ax.legend(frameon=False, loc="upper left")
fig.tight_layout()
fig.savefig(F / "01_curva_k.png")
plt.close(fig)

# 2. mapa: rede, religadores de linha existentes e os 100 primeiros propostos
nos = pd.read_parquet(config.ROOT / "data" / "processed" / f"nos_{json.load(open(R / 'diagnostico.json'))['ano']}.parquet",
                      columns=["x", "y", "classe"])
tr = Transformer.from_crs(31981, 4326, always_xy=True)
amostra = nos[np.isfinite(nos.x)].sample(250_000, random_state=0)
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
ax.set_aspect(1 / np.cos(np.radians(-13)))
ax.set_xticks([]), ax.set_yticks([])
ax.grid(False)
for s in ax.spines.values():
    s.set_visible(False)
ax.legend(frameon=False, loc="lower left", markerscale=2)
ax.set_title("Rede de média tensão da Energisa MT (BDGD 2025)", loc="left", fontsize=11, fontweight="bold")
fig.tight_layout()
fig.savefig(F / "02_mapa.png")
plt.close(fig)

# 3. concentração do CHI esperado por zona
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

# 4. desempenho por elemento (2026)
el = pd.read_csv(R / "desempenho_elemento_2026.csv").set_index("elemento")
ordem = ["DISJUNTOR", "RELIGADOR", "CHAVE SECCIONADORA", "CHAVE FUSIVEL"]
nomes = ["Disjuntor", "Religador", "Chave\nseccionadora", "Chave\nfusível"]
el = el.reindex(ordem)
fig, ax = plt.subplots(1, 3, figsize=(10, 3.4))
for a, col, tit in [(ax[0], "interrupcoes", "Interrupções (jan-jul 2026)"),
                    (ax[1], "uc_por_evento_media", "Clientes por interrupção (média)"),
                    (ax[2], "duracao_mediana_h", "Duração mediana (h)")]:
    b = a.bar(nomes, el[col], color=["#eb6834", "#2a78d6", "#1baf7a", "#8a8a8a"])
    a.bar_label(b, labels=[br(v, 1 if "h" in tit else 0) for v in el[col]], fontsize=8.5, padding=2)
    a.set_title(tit, loc="left", fontsize=10, fontweight="bold")
    a.tick_params(axis="x", labelsize=8.5)
fig.tight_layout()
fig.savefig(F / "04_elementos_2026.png")
plt.close(fig)

# 5. backtest
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
ax[0].set_title("O que explica onde a distribuidora instalou\n(AUC por alimentador, 2024 → 2025)", loc="left",
                fontsize=10, fontweight="bold")
v = [bt["chi_evitado_ano_instalacoes_reais_modelo"], bt["chi_evitado_ano_mesmo_numero_no_modelo"]]
b = ax[1].bar([f"{bt['religadores_comparados']} instalações\nreais (2025)", f"{bt['religadores_comparados']} locais\ndo modelo"],
              np.array(v) / 1e3, color=["#8a8a8a", "#2a78d6"])
ax[1].bar_label(b, labels=[br(x / 1e3) + " mil" for x in v], padding=3, fontsize=9)
ax[1].set_ylabel("CHI evitado por ano (mil), pelo modelo")
ax[1].set_title("Mesmo número de religadores, rede de 2024", loc="left", fontsize=10, fontweight="bold")
fig.tight_layout()
fig.savefig(F / "05_backtest.png")
plt.close(fig)

# 6. seletividade
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
