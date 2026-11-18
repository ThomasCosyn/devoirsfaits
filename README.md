# exo — Assistant pédagogique pour feuilles d'exercices

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
  tutor.py          Tuteur v2 : API POST /api/chat (stream texte brut), blocs brouillon/étape,
                    niveaux d'indice, anti-fuite, génération des réponses de référence
  langfuse_ext.py   Init Langfuse
  routes/
    auth.py         Login/logout
    chat.py         Chat streaming SSE + upload photo
  templates/        HTML mobile-first (Jinja2) — chat.html (front v2), chat-legacy.html (ancien front)
  static/           CSS/JS minimal (styles.css/app.js = front v2, style.css/chat.js = legacy)
cli/
  manage.py         CLI enseignant : élèves, classes, exercices, programmes, réponses de référence
tests/              Tests unitaires (pytest) : `pip install -r requirements-dev.txt && pytest`
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
python cli/manage.py seed-demo  # données de démo (le .env est chargé automatiquement)
uvicorn app.main:app --reload
# → http://localhost:8000
```

Le fichier `.env` est chargé automatiquement par l'application et le CLI
(python-dotenv) — pas besoin de l'exporter dans le shell.

## CLI enseignant

```bash
python cli/manage.py add-niveau 2nd
python cli/manage.py set-programme 2nd --fichier programme-2nd.txt
python cli/manage.py add-class 2nd10 --niveau 2nd --annee 2025-2026
python cli/manage.py sync feuille.tex corrige.tex     # exercices depuis LaTeX
# Base non joignable depuis votre poste (architecture conteneurisée, base en
# private network) ? La synchro passe par le serveur déployé (compte prof) :
python cli/manage.py sync-remote https://assistant.votredomaine.fr feuille.tex corrige.tex --login <compte-prof>
python cli/manage.py import-eleves 2nd10 eleves.txt  # 1re ligne = niveau
python cli/manage.py list-students
```

### Réponses de référence structurées (tuteur v2)

Chaque exercice peut porter `reponse_finale`, `methode`, `etapes` (2 à 5 titres) et un
`statut` (`brouillon` | `valide`). Un exercice au statut `brouillon` n'est **jamais**
utilisé comme vérité en prod : le prompt demande alors au tuteur de rester prudent.

```bash
python cli/manage.py gen-reponses [--niveau 2nde] [--limit 20] [--out reponses.json]
#   → génère les champs via Mistral, statut 'brouillon'
python cli/manage.py export-reponses --out reponses.csv   # relecture humaine (JSON ou CSV)
python cli/manage.py import-reponses reponses.json        # après relecture → statut 'valide'
```

## API v2 (front chat.html)

`POST /api/chat` — entrée JSON :

```json
{ "messages": [{"role": "user|assistant", "content": "..."}],
  "image": "data:image/...;base64,... ou null",
  "context": {"exercice_id": "ex-pgcd-01", "niveau_indice": 0, "eleve": "...", "classe": "..."} }
```

Sortie : flux de **texte brut** (chunked, `text/plain`) markdown + LaTeX, avec balise
`<etape n=".." total=".."/>` en tête de chaque réponse et blocs interactifs
` ```brouillon {json}``` `. `niveau_indice` : 0 = socratique, 1 = notion, 2 = méthode,
3 = première étape faite. L'ancien endpoint SSE `POST /api/chat/{slug}` reste fonctionnel
(front legacy). Aucun contenu de message n'est stocké ni journalisé en clair côté serveur
(traces Langfuse réduites aux métadonnées, ids hachés).

## Workflow LaTeX (source unique, pas de double saisie)

Les exercices sont écrits **une seule fois**, dans vos fichiers `.tex`. Le package `askme`
insère l'icône cliquable, et le CLI synchronise les énoncés/corrections vers la base :

```latex
\usepackage{askme}
\askmesetup{assistant.mondomaine.fr}
...
% feuille élève
\begin{askme}{ex-pgcd-01}{Exercice 1}{3e}
Déterminer le PGCD de 120 et 84...
\end{askme}

% corrigé (fichier séparé, jamais distribué)
\begin{askmecorrection}{ex-pgcd-01}
1) On décompose : $120 = 2^3 \times 3 \times 5$...
\end{askmecorrection}
```

```bash
python cli/manage.py sync feuille.tex corrige.tex   # upsert énoncés + corrections
```

La conversion LaTeX → texte lisible (frac → a/b, `\times` → ×, etc.) est automatique.
L'icône 🧭 du PDF pointe vers `/e/ex-pgcd-01` ; la correction n'existe **que** côté serveur —
rien de sensible dans le PDF ou l'URL.

## Mode exercice libre

Si l'élève arrive sur l'assistant sans passer par une feuille (`/` → `/e/libre`),
l'assistant lui demande de recopier ou photographier son énoncé, puis applique
la même méthode socratique. Une conversation distincte est créée pour chaque session libre.

## Garde-fous anti-détournement

Le prompt système restreint strictement l'assistant aux maths : refus des sujets hors
programme, des demandes de faire les devoirs à la place de l'élève, des manipulations
de rôle ("ignore les consignes"), des contenus inappropriés ; orientation vers un adulte
de confiance en cas d'évocation de danger.

## Variables d'environnement

Voir `.env.example`.

## Licence

Projet privé — Thomas Cosyn.
