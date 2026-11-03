"""Zonas de proteção e modelo de confiabilidade por zonas.

Convenções (uma linha por nó da árvore, ordenada por alimentador e profundidade):

* **Dispositivo de nível religador:** saída do alimentador (disjuntor da subestação), religadores e
  seccionalizadores. Uma falta que não está sob um fusível é eliminada pelo dispositivo desse nível mais
  próximo a montante; todos os clientes a jusante dele ficam sem energia.
* **Fusível:** uma falta sob um fusível é eliminada pelo fusível; só os clientes a jusante dele são
  interrompidos.
* **Taxa de falhas:** uniforme por metro de rede dentro de cada alimentador, calibrada pelo histórico de
  falhas do próprio alimentador.

Para um alimentador, o número esperado de consumidores interrompidos por ano é
``CI = sum_v lambda_v * N(dispositivo que elimina a falta em v)``. Um religador novo no nó ``c`` dentro da
zona do dispositivo ``d`` reduz ``CI`` em ``L(c) * (N(d) - N(c))``, onde ``L(c)`` é a taxa de falhas a
jusante de ``c`` que hoje seria eliminada por ``d``.

Religamento: uma fração ``tau`` das faltas é transitória. Quando quem elimina a falta é um dispositivo com
religamento (saída ou religador), a falta transitória vira só uma interrupção momentânea e não conta; sob um
fusível, toda falta queima o fusível e vira interrupção sustentada. Por isso trocar um fusível por um
religador reduz ``CI`` em ``tau * Lambda_f * N(f)``, e um religador novo no tronco reduz
``(1 - tau) * L(c) * (N(d) - N(c))``.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

NIVEL_RELIGADOR = {"saida", "religador", "seccionalizador", "religador_novo"}


@dataclass
class Modelo:
    nos: pd.DataFrame
    pai: np.ndarray                 # índice de linha do pai (-1 na saída)
    comp: np.ndarray
    uc: np.ndarray
    kva: np.ndarray
    rel: np.ndarray                 # bool: dispositivo de nível religador
    fus: np.ndarray                 # bool: fusível
    lam_m: np.ndarray               # taxa de falhas por metro (falhas/ano/m) do alimentador da linha
    fatias: dict                    # alim_pos -> (ini, fim)
    tau: float = 0.5                # fração de faltas transitórias eliminadas pelo religamento
    # derivados
    n_sub: np.ndarray = field(default=None)
    km_sub: np.ndarray = field(default=None)
    disp_rel: np.ndarray = field(default=None)
    disp_prot: np.ndarray = field(default=None)
    sob_fus: np.ndarray = field(default=None)
    n_rel_acima: np.ndarray = field(default=None)
    L: np.ndarray = field(default=None)
    KMz: np.ndarray = field(default=None)
    UCz: np.ndarray = field(default=None)
    lam_fus: np.ndarray = field(default=None)  # taxa de faltas eliminadas por cada fusível

    @classmethod
    def de_nos(cls, nos: pd.DataFrame, taxa_por_m: pd.Series, tau: float = 0.5) -> Modelo:
        nos = nos.sort_values(["alim_pos", "prof"]).reset_index(drop=True)
        linha = pd.Series(np.arange(len(nos)), index=nos.no.to_numpy())
        pai = np.where(nos.pai.to_numpy() < 0, -1, linha.reindex(nos.pai.to_numpy()).fillna(-1).to_numpy()).astype(int)
        lim = nos.groupby("alim_pos").indices
        fatias = {k: (int(v.min()), int(v.max()) + 1) for k, v in lim.items()}
        m = cls(nos=nos, pai=pai, comp=nos.comp_m.to_numpy(float), uc=nos.uc.to_numpy(float),
                kva=nos.kva.to_numpy(float), rel=np.array(nos.classe.isin(NIVEL_RELIGADOR).to_numpy(), dtype=bool),
                fus=np.array((nos.classe == "fusivel").to_numpy(), dtype=bool),
                lam_m=nos.ctmt.map(taxa_por_m).fillna(0.0).to_numpy(float), fatias=fatias, tau=tau)
        n = len(nos)
        m.n_sub, m.km_sub, m.L, m.KMz, m.UCz, m.lam_fus = (np.zeros(n) for _ in range(6))
        m.disp_rel, m.disp_prot, m.n_rel_acima = (np.zeros(n, dtype=int) for _ in range(3))
        m.sob_fus = np.zeros(n, bool)
        for ini, fim in fatias.values():
            m.recalcular(ini, fim)
        return m

    def recalcular(self, ini: int, fim: int) -> None:
        """Recalcula as grandezas derivadas de um alimentador (linhas ``ini:fim``)."""
        pai, rel, fus = self.pai, self.rel, self.fus
        dr, dp, sf, na = self.disp_rel, self.disp_prot, self.sob_fus, self.n_rel_acima
        for i in range(ini, fim):  # montante -> jusante
            p = pai[i]
            if p < 0:
                dr[i], dp[i], sf[i], na[i] = i, i, False, 0
                continue
            if rel[i]:
                dr[i], dp[i], sf[i] = i, i, False
                na[i] = na[p] + 1
            elif fus[i]:
                dr[i], dp[i], sf[i], na[i] = dr[p], i, True, na[p]
            else:
                dr[i], dp[i], sf[i], na[i] = dr[p], dp[p], sf[p], na[p]
        lam = self.lam_m[ini:fim] * self.comp[ini:fim]
        lam_eff = np.where(sf[ini:fim], 0.0, lam)
        ns, ks = self.uc[ini:fim].copy(), self.comp[ini:fim].copy()
        L, KMz, UCz = lam_eff.copy(), self.comp[ini:fim].copy(), self.uc[ini:fim].copy()
        for j in range(fim - ini - 1, 0, -1):  # jusante -> montante
            p = pai[ini + j] - ini
            if p < 0:
                continue
            ns[p] += ns[j]
            ks[p] += ks[j]
            if not rel[ini + j]:
                L[p] += L[j]
                KMz[p] += KMz[j]
                UCz[p] += UCz[j]
        self.n_sub[ini:fim], self.km_sub[ini:fim] = ns, ks
        self.L[ini:fim], self.KMz[ini:fim], self.UCz[ini:fim] = L, KMz, UCz
        sob = np.where(sf[ini:fim], lam, 0.0)
        self.lam_fus[ini:fim] = np.bincount(dp[ini:fim] - ini, weights=sob, minlength=fim - ini)

    def ci_esperado(self, ini: int, fim: int) -> float:
        """Consumidores interrompidos por ano esperados no alimentador (antes da calibração)."""
        lam = self.lam_m[ini:fim] * self.comp[ini:fim]
        peso = np.where(self.sob_fus[ini:fim], 1.0, 1.0 - self.tau)
        return float((lam * peso * self.n_sub[self.disp_prot[ini:fim]]).sum())

    def ganho_ci(self, ini: int, fim: int) -> np.ndarray:
        """Redução de CI ao instalar um religador em cada nó do alimentador (0 onde não se aplica).

        No tronco (fora de ramal com fusível) o ganho é de seccionamento; num nó de fusível, é a troca do
        fusível por religador (religamento). Nós dentro de ramais com fusível não são candidatos.
        """
        sl = slice(ini, fim)
        nd = self.n_sub[self.disp_rel[sl]]
        g = (1.0 - self.tau) * self.L[sl] * (nd - self.n_sub[sl])
        g[self.rel[sl] | self.sob_fus[sl]] = 0.0
        fus = self.fus[sl]
        g[fus] = self.tau * self.lam_fus[sl][fus] * self.n_sub[sl][fus]
        return np.clip(g, 0.0, None)

    def zonas(self) -> pd.DataFrame:
        """Uma linha por dispositivo de nível religador, com clientes e rede da zona."""
        n = len(self.nos)
        idx = np.flatnonzero(self.rel)
        z = pd.DataFrame({"linha": idx})
        dono = self.disp_rel
        z["uc_jusante"] = self.n_sub[idx]
        z["uc_zona"] = np.bincount(dono, weights=self.uc, minlength=n)[idx]
        z["km_zona"] = np.bincount(dono, weights=self.comp, minlength=n)[idx] / 1000
        tronco = np.where(self.sob_fus, 0.0, self.comp)
        z["km_zona_sem_fusivel"] = np.bincount(dono, weights=tronco, minlength=n)[idx] / 1000
        z["kva_zona"] = np.bincount(dono, weights=self.kva, minlength=n)[idx]
        lam = self.lam_m * self.comp
        z["falhas_ano_zona"] = np.bincount(dono, weights=lam, minlength=n)[idx]
        z["religadores_em_serie"] = self.n_rel_acima[idx]
        cols = ["no", "classe", "cod_id", "tlcd", "ctmt", "alim_pos", "x", "y", "pac"]
        return pd.concat([z, self.nos.iloc[idx][cols].reset_index(drop=True)], axis=1)
