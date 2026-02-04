"""copresenca.py

Cálculo de co-presença entre colaboradores (relação por dia/semana).

Projeto: Dashboard presencialidade — Volkswagen do Brasil
Padronização:
- Tipagem adiantada: `from __future__ import annotations`
- Logger de módulo: `logging.getLogger(__name__)`
- Docstrings estilo Google (Args/Returns/Raises)
- Linhas <= 100 colunas quando possível
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def calcular_ordem_heatmap(df_full: pd.DataFrame) -> tuple[list[str], list[str]]:
    """Reproduz a ordenação aplicada aos heatmaps de co-presença."""
    if df_full is None or df_full.empty:
        return [], []

    dfp = df_full.copy()
    dfp["Data"] = pd.to_datetime(dfp["Data"], errors="coerce")
    dfp = dfp.dropna(subset=["Data"])
    if dfp.empty:
        return [], []

    days = pd.date_range(
        dfp["Data"].min().normalize(), dfp["Data"].max().normalize(), freq="D"
    )
    pres = (
        dfp.groupby(["Data", "Cadastro"])["Contagem Presença"]
        .max()
        .unstack("Cadastro")
        .reindex(days)
        .fillna(0)
    )

    area_col = "Área" if "Área" in dfp.columns else None
    meta_cols = ["Cadastro", "Nome", "Cargo"]
    if area_col:
        meta_cols.append(area_col)

    meta = (
        dfp.sort_values("Data")
        .drop_duplicates("Cadastro", keep="last")[meta_cols]
        .set_index("Cadastro")
    )
    if area_col:
        meta = meta.rename(columns={area_col: "ÁreaNorm"})
    else:
        meta["ÁreaNorm"] = ""

    def _tok(texto: str) -> list[str]:
        return [
            t.strip()
            for t in str(texto).replace("/", "-").split("-")
            if t.strip()
        ]

    def _akey(area: str) -> tuple:
        tokens = _tok(area)
        return len(tokens), tuple(tokens)

    cad_M = sorted(
        meta.index[meta["Cargo"] == "M"],
        key=lambda c: (
            _akey(meta.loc[c, "ÁreaNorm"]),
            str(meta.loc[c, "Nome"]).lower(),
            str(c),
        ),
    )
    cad_E = sorted(
        meta.index[meta["Cargo"] == "E"],
        key=lambda c: (
            _akey(meta.loc[c, "ÁreaNorm"]),
            str(meta.loc[c, "Nome"]).lower(),
            str(c),
        ),
    )

    if not cad_M or not cad_E:
        return [str(x) for x in cad_M], [str(x) for x in cad_E]

    A = pres.reindex(columns=cad_M).fillna(0).to_numpy(float)
    B = pres.reindex(columns=cad_E).fillna(0).to_numpy(float)
    encontros = A.T @ B
    denom = A.sum(axis=0)[:, None]

    def _rel(am: str, ae: str) -> bool:
        if pd.isna(am) or pd.isna(ae):
            return False
        sm = str(am).replace("/", "-").lower().strip()
        se = str(ae).replace("/", "-").lower().strip()
        return bool(se) and sm.startswith(se)

    areas_M = [meta.loc[c, "ÁreaNorm"] for c in cad_M]
    areas_E = [meta.loc[c, "ÁreaNorm"] for c in cad_E]
    allowed = np.array(
        [
            [_rel(areas_M[i], areas_E[j]) for j in range(len(cad_E))]
            for i in range(len(cad_M))
        ],
        dtype=bool,
    )
    with np.errstate(invalid="ignore"):
        percent = (
            np.divide(
                encontros,
                denom,
                out=np.full_like(encontros, np.nan),
                where=(denom > 0) & allowed,
            )
            * 100
        )

    def _score_por_area(valores: np.ndarray) -> float:
        return -1e9 if np.isnan(valores).all() else np.nanmean(valores)

    m_scores = []
    for i, am in enumerate(areas_M):
        mask_e = [ae == am for ae in areas_E]
        vals = percent[i, mask_e]
        m_scores.append(_score_por_area(vals))

    e_scores = []
    for j, ae in enumerate(areas_E):
        mask_m = [am == ae for am in areas_M]
        vals = percent[mask_m, j]
        e_scores.append(_score_por_area(vals))

    order_M = sorted(
        range(len(cad_M)),
        key=lambda i: (
            _akey(areas_M[i]),
            -m_scores[i],
            str(meta.loc[cad_M[i], "Nome"]).lower(),
            str(cad_M[i]),
        ),
    )
    order_E = sorted(
        range(len(cad_E)),
        key=lambda j: (
            _akey(areas_E[j]),
            -e_scores[j],
            str(meta.loc[cad_E[j], "Nome"]).lower(),
            str(cad_E[j]),
        ),
    )

    cad_M = [str(cad_M[i]) for i in order_M]
    cad_E = [str(cad_E[j]) for j in order_E]
    return cad_M, cad_E