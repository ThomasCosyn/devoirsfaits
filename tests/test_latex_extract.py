"""Tests de latex_to_text : tableaux LaTeX (tabular/center/hline), \\%, {,}."""
from __future__ import annotations

from cli.latex_extract import latex_to_text

TABULAR_EXO = r"""
\begin{center}
\begin{tabular}{|l|>{\arraybackslash}p{0.8cm}|>{\arraybackslash}p{0.8cm}|>{\arraybackslash}p{0.8cm}|>{\arraybackslash}p{0.8cm}|}
\hline
Fractionnaire & 2/5 & & & \\
\hline
Décimale & & 0{,}75 & & \\
\hline
Pourcentage & & & 8 \% & 60 \% \\
\hline
\end{tabular}
\end{center}

Calculer :
\begin{enumerate}
\item 10\% de 50 patients
\item 25\% de 80 dossiers médicaux
\end{enumerate}
"""


def test_tabular_devient_tableau_markdown():
    out = latex_to_text(TABULAR_EXO)
    assert "\\begin{tabular}" not in out
    assert "\\begin{center}" not in out
    assert "hline" not in out
    assert "arraybackslash" not in out
    assert "| Fractionnaire | 2/5 |" in out
    assert "| --- " in out
    assert "| Décimale |  | 0,75 |" in out
    assert "8 %" in out and "60 %" in out


def test_pourcent_et_item_nettoyes():
    out = latex_to_text(TABULAR_EXO)
    assert "- 10% de 50 patients" in out
    assert "- 25% de 80 dossiers médicaux" in out
    assert "\\%" not in out
    assert "\\item" not in out


def test_segments_math_preserves():
    out = latex_to_text(r"PGCD de $120$ et $\frac{84}{120}$, soit $\times$")
    assert "$120$" in out
    assert r"$\frac{84}{120}$" in out
    assert r"$\times$" in out


def test_tabular_sans_double_backslash_hline():
    # variante avec séparateurs de ligne déjà transformés en retours à la ligne
    body = "\n\\hline\nA & 1 &\n\n\\hline\nB & 2 &\n"
    tex = "\\begin{tabular}{|l|l|}\n" + body + "\\end{tabular}"
    out = latex_to_text(tex)
    assert "| A | 1 |" in out
    assert "| B | 2 |" in out
