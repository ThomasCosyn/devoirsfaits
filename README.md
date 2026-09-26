# Devoirs Faits — Assistant pédagogique pour feuilles d'exercices

Assistant conversationnel destiné aux élèves bloqués sur une feuille d'exercices (LaTeX compilée en PDF).
Un petit symbole cliquable inséré à côté de chaque énoncé ouvre l'assistant, qui connaît déjà
l'élève, sa classe, le programme de l'année et l'énoncé de l'exercice ciblé.

## Principe pédagogique

L'assistant ne donne **jamais** la solution d'un bloc. Il applique la méthode socratique :
décomposer l'exercice en petites étapes que l'élève doit réussir seul, demander les énoncés
du cours si nécessaire, et seulement à la fin donner la correction parfaitement rédigée
en ordonnant à l'élève de la recopier dans son cahier.

## Stack

- **Backend** : Python 3.12, FastAPI, Jinja2 (server-rendered, mobile-first) — pas de framework LLM
- **BDD** : PostgreSQL existant (schéma dédié `devoirsfaits`, photos des cahiers stockées)
- **LLM** : API Mistral (multimodal : texte + photo du cahier) via le client OpenAI-compatible
- **Tracing** : Langfuse Cloud (chaque appel LLM tracé : élève, classe, exercice, tokens, coût)
- **Déploiement** : Scaleway Serverless Container (scale-to-0, ~0 €/mois, HTTPS via domaine custom)

## Structure

```
app/
  main.py           Point d'entrée FastAPI
  config.py         Configuration (env)
  db.py             Postgres (pool psycopg, schéma dédié)
  security.py       Sessions signées, hash bcrypt
  llm.py            Client Mistral + système prompt pédagogique + propagate_attributes Langfuse
  langfuse_ext.py   Init Langfuse
  routes/
    auth.py         Login/logout
    chat.py         Chat streaming SSE + upload photo
  templates/        HTML mobile-first (Jinja2)
  static/           CSS/JS minimal
cli/
  manage.py         CLI enseignant : élèves, classes, exercices, programmes
latex/
  askme.sty         Package LaTeX : \askme{id-exercice}
  exemple.tex       Feuille d'exercices d'exemple
deploy/
  Dockerfile        Image pour Serverless Container Scaleway
docs/
  DEPLOIEMENT.md    Guide de déploiement Scaleway pas à pas
```

## Démarrage local (dev)

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env            # renseigner DATABASE_URL, MISTRAL_API_KEY, LANGFUSE_PK/SK
export $(grep -v '^#' .env | xargs)
python cli/manage.py seed-demo  # données de démo (2 classes, 3 élèves, exercices)
uvicorn app.main:app --reload
# → http://localhost:8000
```

## CLI enseignant

```bash
python cli/manage.py add-class 3A --annee 2025-2026 --programme "Programme de 3A : ..."
python cli/manage.py add-exercice 3A ex-pgcd-01 --titre "PGCD - Ex 1" \
    --enonce "Déterminer le PGCD de 120 et 84." \
    --correction "1) On décompose : 120 = 2³×3×5 ..."
python cli/manage.py add-student 3A Dupont Lucie --login lucie.d
python cli/manage.py list-students 3A
```

## Workflow LaTeX

```latex
\usepackage{askme}
...
\begin{exercice}[PGCD - Ex 1]
\askme{ex-pgcd-01}
Déterminer le PGCD de 120 et 84.
\end{exercice}
```

Le package place une petite icône 🧭 cliquable (hyperref) pointant vers
`https://<votre-domaine>/e/ex-pgcd-01`. Seul le PDF publié sur votre site
contient les liens ; la version distribuée sur papier ne permet évidemment pas
de cliquer, mais le lien y est inerte donc sans effet de bord.

## Variables d'environnement

Voir `.env.example`.

## Licence

Projet privé — Thomas Cosyn.
