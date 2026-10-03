"""Extraction des environnements askme / askmecorrection depuis un fichier .tex."""
from __future__ import annotations

import re

ASKME_RE = re.compile(
    r"\\begin\{askme\}\{([^}]*)\}\{([^}]*)\}\{([^}]*)\}(.*?)\\end\{askme\}",
    re.S,
)
ASKMECORRECTION_RE = re.compile(
    r"\\begin\{askmecorrection\}\{([^}]*)\}(.*?)\\end\{askmecorrection\}",
    re.S,
)

_MATH_REPLACEMENTS: list[tuple[str, str]] = [
    (r"\\dfrac\{([^{}]*)\}\{([^{}]*)\}", r"\1/\2"),
    (r"\\frac\{([^{}]*)\}\{([^{}]*)\}", r"\1/\2"),
    (r"\\sqrt\{([^{}]*)\}", r"√\1"),
    (r"\\mathrm\{([^{}]*)\}", r"\1"),
    (r"\\times", "×"),
    (r"\\div", "÷"),
    (r"\\leq", "≤"),
    (r"\\geq", "≥"),
    (r"\\neq", "≠"),
    (r"\\approx", "≈"),
    (r"\\infty", "∞"),
    (r"\\pi", "π"),
    (r"\\alpha", "α"),
    (r"\\beta", "β"),
    (r"\\deg", "degré"),
    (r"\\,\s*", " "),
    (r"\\;", " "),
    (r"\\:", " "),
    (r"\\!", ""),
    (r"\\,", " "),
    (r"\\quad", "  "),
    (r"\\qquad", "   "),
    (r"\\par\b", "\n"),
    (r"\\\\", "\n"),
    (r"\\textbf\{([^{}]*)\}", r"\1"),
    (r"\\textit\{([^{}]*)\}", r"\1"),
    (r"\\text\{([^{}]*)\}", r"\1"),
    (r"\\item\b", "- "),
    (r"\$([^$]*)\$", r"\1"),
    (r"\$\$([^$]*)\$\$", r"\1"),
    (r"\\begin\{itemize\}|\\begin\{enumerate\}", ""),
    (r"\\end\{itemize\}|\\end\{enumerate\}", ""),
    (r"~", " "),
]

_SIMPLE_COMMANDS = [
    "noindent", "indent", "smallskip", "medskip", "bigskip", "vspace",
    "hfill", "centering", "newpage", "clearpage", "linebreak", "pagebreak",
]


def latex_to_text(tex: str) -> str:
    out = tex
    for pattern, repl in _MATH_REPLACEMENTS:
        out = re.sub(pattern, repl, out)
    for cmd in _SIMPLE_COMMANDS:
        out = re.sub(r"\\" + cmd + r"\s*(\{[^}]*\})?", "", out)
    out = re.sub(r"[ \t]+\n", "\n", out)
    out = re.sub(r"\n{3,}", "\n\n", out)
    return out.strip()


def extract_askme(tex_content: str) -> list[dict]:
    result = []
    for m in ASKME_RE.finditer(tex_content):
        slug, titre, niveau, body = m.groups()
        result.append({
            "slug": slug.strip(),
            "titre": titre.strip(),
            "niveau": niveau.strip(),
            "enonce": latex_to_text(body),
        })
    return result


def extract_askmecorrection(tex_content: str) -> dict[str, str]:
    result = {}
    for m in ASKMECORRECTION_RE.finditer(tex_content):
        slug, body = m.groups()
        result[slug.strip()] = latex_to_text(body)
    return result


def parse_tex_file(path: str) -> tuple[list[dict], dict[str, str]]:
    with open(path, encoding="utf-8") as f:
        content = f.read()
    return extract_askme(content), extract_askmecorrection(content)
