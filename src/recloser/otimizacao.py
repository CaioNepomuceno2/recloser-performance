"""Escolha de locais para religadores novos.

O ganho de um religador num nó é a redução de CHI esperado do alimentador (modelo de zonas,
:mod:`recloser.zonas`), já multiplicada pelo fator de calibração do alimentador. Como o ganho de um conjunto
de religadores é submodular (cada religador novo reduz o ganho dos outros na mesma zona), o algoritmo guloso
com recálculo do alimentador alterado tem garantia de pelo menos (1 - 1/e) do ótimo para a função de ganho.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from recloser.zonas import Modelo


def _candidato(m: Modelo, ini: int, fim: int, min_uc: float, max_serie: int) -> np.ndarray:
    sl = slice(ini, fim)
    nd = m.n_sub[m.disp_rel[sl]]
    tronco = (~m.rel[sl]) & (~m.sob_fus[sl]) & (m.n_sub[sl] >= min_uc) & ((nd - m.n_sub[sl]) >= min_uc)
    troca_fusivel = m.fus[sl] & (m.n_sub[sl] >= min_uc)
    return (tronco | troca_fusivel) & (m.n_rel_acima[sl] < max_serie)


def ganho_chi(m: Modelo, ini: int, fim: int, chi_por_ci: float, min_uc: float, max_serie: int) -> np.ndarray:
    g = m.ganho_ci(ini, fim) * chi_por_ci
    g[~_candidato(m, ini, fim, min_uc, max_serie)] = 0.0
    return g


def instalar(m: Modelo, linha: int) -> None:
    """Instala um religador no nó (num nó de fusível, o religador substitui o fusível)."""
    m.rel[linha] = True
    m.fus[linha] = False
    m.nos.loc[linha, "classe"] = "religador_novo"
    alim = int(m.nos.alim_pos.iat[linha])
    m.recalcular(*m.fatias[alim])


def guloso(m: Modelo, chi_por_ci: pd.Series, k: int, min_uc: float, max_serie: int) -> pd.DataFrame:
    """Instala ``k`` religadores em sequência, sempre no nó de maior ganho. Altera ``m``."""
    fator = {a: float(chi_por_ci.get(m.nos.ctmt.iat[ini], 0.0)) for a, (ini, fim) in m.fatias.items()}
    ganho = np.zeros(len(m.nos))
    for a, (ini, fim) in m.fatias.items():
        ganho[ini:fim] = ganho_chi(m, ini, fim, fator[a], min_uc, max_serie)
    escolhas = []
    for passo in range(k):
        i = int(np.argmax(ganho))
        if ganho[i] <= 0:
            break
        a = int(m.nos.alim_pos.iat[i])
        d = int(m.disp_rel[i])
        escolhas.append({"passo": passo + 1, "linha": i, "chi_evitado_ano": float(ganho[i]),
                         "tipo": "troca_de_fusivel" if m.fus[i] else "tronco",
                         "uc_jusante": float(m.n_sub[i]), "uc_protegidas": float(m.n_sub[d] - m.n_sub[i]),
                         "km_jusante_zona": float(m.KMz[i] / 1000)})
        instalar(m, i)
        ini, fim = m.fatias[a]
        ganho[ini:fim] = ganho_chi(m, ini, fim, fator[a], min_uc, max_serie)
    out = pd.DataFrame(escolhas)
    if len(out):
        cols = ["no", "ctmt", "alim_pos", "x", "y", "pac"]
        out = pd.concat([out, m.nos.iloc[out.linha][cols].reset_index(drop=True)], axis=1)
    return out


def chi_total(m: Modelo, chi_por_ci: pd.Series) -> float:
    tot = 0.0
    for ini, fim in m.fatias.values():
        tot += m.ci_esperado(ini, fim) * float(chi_por_ci.get(m.nos.ctmt.iat[ini], 0.0))
    return tot


def regra_divisao(m: Modelo, chi_por_ci: pd.Series, ks: list[int], criterio: str, min_uc: float, max_serie: int,
                  rng: np.random.Generator | None = None) -> dict[int, float]:
    """Regras simples de planejamento, avaliadas pelo mesmo modelo. Altera ``m``.

    * ``extensao``: divide ao meio (em km) a zona com mais rede;
    * ``clientes``: divide ao meio (em clientes) a zona com mais clientes;
    * ``aleatorio``: nó candidato sorteado.

    Devolve o CHI evitado por ano acumulado em cada ``k`` de ``ks``.
    """
    antes = chi_total(m, chi_por_ci)
    out = {}
    for passo in range(1, max(ks) + 1):
        cand_tot = np.zeros(len(m.nos), bool)
        for ini, fim in m.fatias.values():
            cand_tot[ini:fim] = _candidato(m, ini, fim, min_uc, max_serie)
        cand_tot &= ~m.fus  # as regras simples só dividem o tronco
        idx = np.flatnonzero(cand_tot)
        if len(idx) == 0:
            break
        if criterio == "aleatorio":
            i = int(rng.choice(idx))
        else:
            base = m.KMz if criterio == "extensao" else m.UCz
            tamanho = base[m.disp_rel]  # tamanho da zona a que cada nó pertence
            zona_alvo = m.disp_rel[idx][np.argmax(tamanho[idx])]
            cz = idx[m.disp_rel[idx] == zona_alvo]
            i = int(cz[np.argmin(np.abs(base[cz] - base[zona_alvo] / 2))])
        instalar(m, i)
        if passo in ks:
            out[passo] = antes - chi_total(m, chi_por_ci)
    return out
