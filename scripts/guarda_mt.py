"""Guarda de MT: o código novo, com a configuração padrão, grava exatamente o que o código anterior gravava.

Cria dois ``git worktree`` temporários (``--base``, o commit anterior às mudanças de multi-distribuidora, e ``--novo``),
gera a mesma
BDGD sintética no formato de MT (60 alimentadores, dois snapshots, falhas, interrupções e ``valor.json``, sem rótulo de origem),
roda ``01`` a ``06`` em cada um e compara, byte a byte (SHA-256), tudo que sai em ``reports/`` e ``data/processed/``.
Só a linha de amostragem do mapa do ``06`` do código base é ajustada (ele falha com menos de 250 mil nós); é a mesma conta.
Nenhum arquivo de MT do repositório é lido nem escrito: os resultados publicados de MT não são tocados.

Saída: ``<reports>/diagnostico/guarda_mt.json`` (commits, número de arquivos e o hash de cada um).
Uso: ``python scripts/guarda_mt.py --base 7cedd3d --novo HEAD --config configs/params_ems.yaml``
"""

import argparse
import hashlib
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

from recloser import config

RAIZ = config.ROOT
SCRIPTS = ["01_topologia.py", "02_diagnostico.py", "03_desempenho_2026.py", "04_backtest.py", "05_otimizacao.py", "06_figuras.py"]
N_ALIM = 60
AJUSTE_06 = (
    "amostra = nos[np.isfinite(nos.x)].sample(250_000, random_state=0)",
    "_f = nos[np.isfinite(nos.x)]; amostra = _f.sample(min(250_000, len(_f)), random_state=0)",
)


def git(*args, cwd=RAIZ) -> str:
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True, encoding="utf-8").stdout.strip()


def gerar_dados(novo: Path, dados: Path) -> Path:
    """BDGD sintética no formato de MT, com as funções do teste de fumaça do próprio código novo."""
    spec = importlib.util.spec_from_file_location("fumaca", novo / "tests" / "test_ems_fumaca.py")
    fum = importlib.util.module_from_spec(spec)
    sys.path.insert(0, str(novo / "src"))
    spec.loader.exec_module(fum)
    nomes = [f"{f + 1:06d}" for f in range(N_ALIM)]
    rng = np.random.default_rng(7)
    uc = fum._gravar_bdgd(dados / "bdgd" / "2024", rng, nomes, 2024, n_alim=N_ALIM)
    novos = [(1, 2), (3, 2), (4, 6), (7, 4), (9, 2), (10, 6), (13, 2)]
    fum._gravar_bdgd(dados / "bdgd" / "2025", np.random.default_rng(7), nomes, 2025, novos=novos, n_alim=N_ALIM)
    for ano in (
        2024,
        2025,
    ):  # 10x mais clientes por trafo: a sensibilidade fixa (min_clientes = 100, k = 100) precisa de candidatos
        f = dados / "bdgd" / str(ano) / "UCBT_tab_agg.parquet"
        d = pd.read_parquet(f)
        d["n_uc"] = d["n_uc"] * 10
        d.to_parquet(f, index=False)
    uc = [u * 10 for u in uc]
    fum._gravar_historico(dados, rng, uc, nomes, False, n_alim=N_ALIM)
    (dados / "valor.json").write_text(
        json.dumps(
            {
                "rs_por_chi_social": 5.9,
                "rs_por_chi_compensacao": 1.9,
                "frac_chi_regulatorio": 0.3,
                "uc_total": float(sum(uc)),
                "chi_evitado_ano_por_religador": 100.0,
                "chi_evitado_ano_por_religador_ic95": [50.0, 150.0],
                "efeito_chi_pct": -10.0,
            }
        )
    )
    cfg = yaml.safe_load((novo / "configs" / "params.yaml").read_text(encoding="utf-8"))
    cfg.update(
        cache_bdgd=str(dados / "bdgd"),
        falhas=str(dados / "falhas.parquet"),
        interrupcoes=str(dados / "interrupcoes.parquet"),
        valor_json=str(dados / "valor.json"),
    )
    cfg["otimizacao"] = {**cfg["otimizacao"], "ks": [2, 4], "min_clientes": 20, "sorteios_aleatorio": 2}
    cfg["backtest"] = {**cfg["backtest"], "raio_localizacao_m": 50}
    destino = dados / "config.yaml"
    destino.write_text(yaml.safe_dump(cfg, allow_unicode=True), encoding="utf-8")
    return destino


def rodar(lado: Path, cfg_yaml: Path) -> list[tuple[str, int]]:
    """Roda 01 a 06 no worktree ``lado`` (a configuração entra como ``configs/params.yaml``, o caminho padrão de MT)."""
    shutil.copy(cfg_yaml, lado / "configs" / "params.yaml")
    for d in ("reports", "data"):
        shutil.rmtree(lado / d, ignore_errors=True)
    (lado / "reports").mkdir()
    p6 = lado / "scripts" / "06_figuras.py"
    t = p6.read_text(encoding="utf-8")
    if AJUSTE_06[0] in t:
        p6.write_text(t.replace(*AJUSTE_06), encoding="utf-8")
    env = {**os.environ, "PYTHONPATH": str(lado / "src"), "PYTHONUTF8": "1", "MPLBACKEND": "Agg"}
    env.pop(config.VARIAVEL_AMBIENTE, None)
    out = []
    for s in SCRIPTS:
        r = subprocess.run(
            [sys.executable, str(lado / "scripts" / s)], cwd=lado, env=env, capture_output=True, text=True, encoding="utf-8"
        )
        if r.returncode:
            print(f"{lado.name}/{s} falhou:\n{r.stderr[-600:]}")
        out.append((s, r.returncode))
    return out


def hashes(lado: Path) -> dict[str, str]:
    out = {}
    for base in ("reports", "data/processed"):
        for p in sorted((lado / base).rglob("*")):
            if p.is_file():
                out[p.relative_to(lado).as_posix()] = hashlib.sha256(p.read_bytes()).hexdigest()
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--base", required=True, help="commit anterior às mudanças (código de MT original)")
    ap.add_argument("--novo", default="HEAD", help="commit com o código novo (padrão: HEAD)")
    ap.add_argument("--config", default=None, help="configuração cujos relatórios recebem o resultado (padrão: a de MS)")
    args = ap.parse_args()
    cfg = config.carregar(args.config or "configs/params_ems.yaml")
    sha_base, sha_novo = git("rev-parse", args.base), git("rev-parse", args.novo)
    tmp = Path(tempfile.mkdtemp(prefix="guarda_mt_"))
    lados = {"base": tmp / "base", "novo": tmp / "novo"}
    try:
        git("worktree", "add", "--detach", str(lados["base"]), sha_base)
        git("worktree", "add", "--detach", str(lados["novo"]), sha_novo)
        cfg_yaml = gerar_dados(lados["novo"], tmp / "dados")
        exec_ = {k: rodar(v, cfg_yaml) for k, v in lados.items()}
        hb, hn = hashes(lados["base"]), hashes(lados["novo"])
    finally:
        for v in lados.values():
            subprocess.run(["git", "worktree", "remove", "--force", str(v)], cwd=RAIZ, capture_output=True)
        shutil.rmtree(tmp, ignore_errors=True)
    iguais = sorted(k for k in hb if k in hn and hb[k] == hn[k])
    res = {
        "base": sha_base,
        "novo": sha_novo,
        "dados": f"BDGD sintética no formato de MT: {N_ALIM} alimentadores, snapshots 2024 e 2025, sem origem_efeito",
        "scripts_com_erro": {k: [s for s, c in v if c] for k, v in exec_.items()},
        "arquivos_base": len(hb),
        "arquivos_novo": len(hn),
        "iguais": len(iguais),
        "so_na_base": sorted(set(hb) - set(hn)),
        "so_no_novo": sorted(set(hn) - set(hb)),
        "diferentes": sorted(k for k in hb if k in hn and hb[k] != hn[k]),
        "sha256": {k: hb[k] for k in iguais},
    }
    res["identico"] = bool(not any(res["scripts_com_erro"].values()) and res["iguais"] == len(hb) == len(hn) and len(hb) > 0)
    saida = config.pasta_relatorios(cfg) / "diagnostico"
    saida.mkdir(parents=True, exist_ok=True)
    (saida / "guarda_mt.json").write_text(json.dumps(res, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps({k: v for k, v in res.items() if k != "sha256"}, indent=1, ensure_ascii=False))
    if not res["identico"]:
        raise SystemExit("guarda de MT: as saídas do código novo diferem das do código base")


if __name__ == "__main__":
    main()
