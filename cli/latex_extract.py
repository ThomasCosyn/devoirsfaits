"""Extraction des environnements askme / askmecorrection depuis un fichier .tex."""
from __future__ import annotations

import re

ASKME_RE = re.compile(
    r"\\begin\{askme\}\{([^}]*)\}\{([^}]*)\}\{([^}]*)\}(.*?)\\end\{askme\}",
    re.S,
)

# \begin{exo}[titre][slug] ... \end{exo} : exercices balisés par un slug.
# Le titre reste le 1er argument optionnel ; le slug est le 2e.
# Compatibilité : \begin{exo}[slug] (1 seul argument ressemblant à un slug) est aussi accepté.
EXO_OPT_RE_TEMPLATE = (
    r"\\begin\{(?P<env>%s)\}"
    r"(?:\[(?P<arg1>[^\]]*)\])?(?:\[(?P<arg2>[^\]]*)\])?"
    r"(?P<body>.*?)\\end\{(?P=env)\}"
)

# Un slug ne contient que des minuscules, chiffres et tirets (pas une phrase).
SLUG_RE = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
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


def _strip_tikz(text: str) -> str:
    """Retire les environnements graphiques (tikzpicture, etc.) : l'assistant
    pédagogique travaille sur du texte."""
    for env in ("tikzpicture", "pspicture", "picture"):
        text = re.sub(
            r"\\begin\{" + env + r"\}(.*?)\\end\{" + env + r"\}",
            " [figure] ",
            text,
            flags=re.S,
        )
    return text


def latex_to_text(tex: str) -> str:
    out = _strip_tikz(tex)
    for pattern, repl in _MATH_REPLACEMENTS:
        out = re.sub(pattern, repl, out)
    for cmd in _SIMPLE_COMMANDS:
        out = re.sub(r"\\" + cmd + r"\s*(\{[^}]*\})?", "", out)
    out = re.sub(r"\\href\{[^}]*\}\{([^}]*)\}", r"\1", out)
    out = re.sub(r"\\url\{([^}]*)\}", r"\1", out)
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


def extract_exo_opt(
    tex_content: str,
    env_names: tuple[str, ...] = ("exo", "exercice", "Exo"),
    titre_prefix: str = "Exercice",
) -> list[dict]:
    r"""Extrait les \begin{exo}[slug] ... \end{exo}.

    Le niveau n'est pas connu localement : le CLI doit le passer via
    --niveau (ou une commande \askmeniveau{...} dans le fichier).
    """
    result = []
    envs = "|".join(re.escape(e) for e in env_names)
    pattern = re.compile(EXO_OPT_RE_TEMPLATE % envs, re.S)
    for m in pattern.finditer(tex_content):
        arg1 = (m.group("arg1") or "").strip()
        arg2 = (m.group("arg2") or "").strip()
        # [titre][slug] ou [slug] seul (ressemblant à un slug)
        if arg2 and SLUG_RE.match(arg2):
            slug, titre = arg2, (arg1 or f"{titre_prefix} {arg2}")
        elif arg1 and not arg2 and SLUG_RE.match(arg1):
            slug, titre = arg1, f"{titre_prefix} {arg1}"
        else:
            continue
        result.append({
            "slug": slug,
            "titre": titre,
            "niveau": None,
            "enonce": latex_to_text(m.group("body")),
        })
    return result


def parse_tex_file(path: str) -> tuple[list[dict], dict[str, str]]:
    with open(path, encoding="utf-8") as f:
        content = f.read()
    return extract_askme(content), extract_askmecorrection(content)
