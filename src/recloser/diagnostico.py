"""Diagnósticos da codificação do PAC (coordenada UTM nos códigos de 19 a 20 caracteres).

Os PAC da BDGD de 19 ou 20 caracteres trazem a coordenada do ponto: ``X`` (8 ou 9 dígitos) e ``Y`` (9 dígitos), em
centímetros, mais 2 letras de sufixo. :func:`topologia.pac_xy` decodifica. As funções daqui comparam o resultado com a
geometria da própria BDGD, em cada referência candidata, para dizer qual é a que a codificação realmente usa.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import shapely
from pyproj import Proj, Transformer

from recloser import topologia

# SIRGAS 2000 / UTM 20S a 23S
FUSOS = {"20S": 31980, "21S": 31981, "22S": 31982, "23S": 31983}


def formato_pac(pac: pd.Series) -> pd.DataFrame:
    """Comprimento do PAC e se segue o formato de coordenada (19 ou 20 caracteres: dígitos + 2 letras)."""
    s = pac.astype("string").str.strip()
    ok = s.str.len().isin([19, 20]) & s.str[:-2].str.isdigit().fillna(False)
    return pd.DataFrame({"comprimento": s.str.len(), "coordenada": ok.to_numpy(bool), "sufixo": s.str[-2:].where(ok)})


def distancias(pac: pd.Series, lon: np.ndarray, lat: np.ndarray, epsg: int) -> np.ndarray:
    """Distância (m, no plano da referência ``epsg``) entre a coordenada do PAC e a geometria (graus), NaN sem coordenada."""
    x, y = topologia.pac_xy(pac)
    gx, gy = Transformer.from_crs(4326, epsg, always_xy=True).transform(np.asarray(lon, float), np.asarray(lat, float))
    return np.hypot(gx - x, gy - y)


def resumo_distancias(d: np.ndarray) -> dict:
    """Quantis e frações dentro de 1, 50 e 100 m (as distâncias do casamento do backtest) das distâncias finitas."""
    d = np.asarray(d, float)
    d = d[np.isfinite(d)]
    if len(d) == 0:
        return {"n": 0}
    return {
        "n": int(len(d)),
        "mediana_m": float(np.median(d)),
        "p90_m": float(np.percentile(d, 90)),
        "p99_m": float(np.percentile(d, 99)),
        "max_m": float(d.max()),
        "frac_ate_1m": float((d <= 1).mean()),
        "frac_ate_50m": float((d <= 50).mean()),
        "frac_ate_100m": float((d <= 100).mean()),
    }


def lonlat_do_pac(pac: pd.Series, epsg: int) -> tuple[np.ndarray, np.ndarray]:
    """Longitude e latitude dos PAC com coordenada, lidos como ``epsg``; NaN nos demais."""
    x, y = topologia.pac_xy(pac)
    ok = np.isfinite(x)
    lon, lat = np.full(len(x), np.nan), np.full(len(x), np.nan)
    lon[ok], lat[ok] = Transformer.from_crs(epsg, 4326, always_xy=True).transform(x[ok], y[ok])
    return lon, lat


def dentro_do_estado(lon: np.ndarray, lat: np.ndarray, estado: shapely.Geometry, margem_graus: float = 0.0) -> float:
    """Fração dos pontos finitos dentro do polígono do estado (com margem, para a malha simplificada do IBGE)."""
    ok = np.isfinite(lon) & np.isfinite(lat)
    if not ok.any():
        return float("nan")
    poli = estado.buffer(margem_graus) if margem_graus else estado
    return float(shapely.contains_xy(poli, lon[ok], lat[ok]).mean())


def fator_escala(lon: float, lat: float, epsg: int) -> float:
    """Fator de escala da projeção ``epsg`` no ponto (1 = distância no plano igual à distância no terreno)."""
    return float(Proj(epsg).get_factors(lon, lat).parallel_scale)
