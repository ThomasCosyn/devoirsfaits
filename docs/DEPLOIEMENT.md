# Déploiement sur Scaleway (Serverless Container scale-to-0)

## Architecture cible

```
PDF sur votre site ──🧭──> https://assistant.votredomaine.fr
                                    │
                          Serverless Container Scaleway
                          (image Docker FastAPI, scale-to-0)
                                    │
                    ┌───────────────┼────────────────┐
                    ▼               ▼                ▼
              Postgres (votre   API Mistral      Langfuse Cloud
              instance existante, (texte+photo)  (tracing, coûts)
              schéma devoirsfaits)
```

## Coûts

| Poste | Coût |
|---|---|
| Serverless Container (scale-to-0) | ~0 €/mois (free tier : 400 000 GB-s + 1M requêtes) |
| Postgres | 0 € (votre instance existante) |
| Langfuse Cloud | gratuit < 50k observations/mois |
| API Mistral | ~0,002–0,005 € par conversation longue |
| **Total** | **~0–2 €/mois en usage scolaire** |

Estimation de consommation : 30 élèves × 15 messages/mois × 20 s de génération à 512 Mo
≈ 150 000 GB-s/mois → dans le free tier.

## 1. Préparer la base de données

Le schéma `devoirsfaits` est créé automatiquement au premier démarrage dans la base
pointée par `DATABASE_URL`. Aucune action sur votre instance, si ce n'est autoriser
l'accès réseau depuis les Serverless Containers :

1. Console Scaleway → votre Managed Database → **Network**.
2. Ajouter le **Private Network** de votre namespace Serverless (ou autoriser les IP publiques
   des Serverless gateways `62.210.0.0/16` selon votre configuration).

Note : les Serverless Containers Scaleway ne peuvent pas joindre une Managed Database en
IP publique si celle-ci est en private network uniquement — vérifiez ce point avant.

## 2. Construire et déployer le container

Option A — Console :

1. Console Scaleway → **Container Registry** : créer un namespace `devoirsfaits`
   (ou réutiliser un registry existant).
2. Construire et pousser l'image :

```bash
docker build -t rg.fr-par.scw.cloud/devoirsfaits/app:latest -f deploy/Dockerfile .
docker push rg.fr-par.scw.cloud/devoirsfaits/app:latest
```

3. Console → **Serverless Container** → créer un container :
   - Image : `rg.fr-par.scw.cloud/devoirsfaits/app:latest`
   - Port : **8080**
   - Min scale : **0**, Max scale : 5
   - Mémoire : 512 Mo
   - Variables d'environnement (voir `.env.example`) :
     `SECRET_KEY`, `DATABASE_URL`, `MISTRAL_API_KEY`, `MISTRAL_MODEL`,
     `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY`, `LANGFUSE_HOST`
   - HTTP timeout : 60 s (le streaming LLM peut durer)

4. **Domaine custom** : onglet du container → ajouter `assistant.votredomaine.fr`.
   Scaleway fournit le certificat HTTPS automatiquement. Créer le CNAME chez votre
   registrar vers l'hostname fourni.

Option B — CLI (`scw` + `serverless framework`) : équivalent, voir la doc Scaleway

Option C — CI/CD GitHub Actions (recommandée) : le workflow `.github/workflows/cicd.yml`
build et déploie automatiquement à chaque push sur `main`.

1. Dans le repo GitHub → **Settings > Secrets and variables > Actions** :
   - Secrets :
     - `SCW_ACCESS_KEY` : access key de la paire de clés API Scaleway (ex. `SCWXXXXXXXXXXXXXXXXX`)
     - `SCW_SECRET_KEY` : secret key de la paire de clés API Scaleway (Console → IAM → API Keys)
     - `SCALEWAY_ORGANIZATION_ID` : ID de l'organisation Scaleway (Console → IAM → Organizations, ou visible dans la console
       à la création de la clé API)
     - `SCALEWAY_PROJECT_ID` : ID du projet Scaleway hébergeant le container
     - `SCALEWAY_REGISTRY_NAMESPACE` : nom du namespace Container Registry (ex. `devoirsfaits`)
   - Variables (Settings > Secrets and variables > Actions > Variables) :
     - `SCALEWAY_CONTAINER_NAME` : nom du Serverless Container (défaut : `devoirsfaits`)
     - `SCALEWAY_REGION` : région (défaut : `fr-par`)
2. Le workflow exécute : build de l'image → push vers le registry
   (`app:latest` + `app:<sha>`) → `scw container container deploy` pour redéployer.
3. Les pull requests exécutent uniquement les vérifications (lint/imports/syntaxe JS),
   sans déployer.
"Deploy a container".

## 3. Créer vos données (classes, élèves, exercices)

Depuis votre machine, avec une version locale du code et `DATABASE_URL` pointant vers
votre base Scaleway :

```bash
export DATABASE_URL="postgresql://user:pass@your-db.fr-par.scw.cloud:5432/mabase"
python cli/manage.py add-niveau 2nd
python cli/manage.py set-programme 2nd --fichier programme-2nd.txt
python cli/manage.py add-class 2nd10 --niveau 2nd
python cli/manage.py sync feuille.tex corrige.tex   # exercices + corrections depuis vos .tex
python cli/manage.py import-eleves 2nd10 eleves.txt # 1re ligne = niveau
```

Workflow type à chaque nouvelle feuille : compiler le PDF (l'icône y est déjà),
puis `sync` pour mettre à jour la base. Le `.tex` est la source unique.

## 4. LaTeX

Sur votre machine, copier `latex/askme.sty` à côté de votre feuille (ou dans `texmf`) :

```latex
\usepackage{askme}
\askmesetup{assistant.votredomaine.fr}
...
\begin{askme}{ex-pgcd-01}{Exercice 1}{3e}
Déterminer le PGCD de 120 et 84...
\end{askme}
```

Compiler avec `pdflatex` puis synchroniser :

```bash
python cli/manage.py sync feuille.tex corrige.tex
```

Voir `latex/exemple.tex` et `latex/exemple-corrige.tex` pour un exemple complet.
Le PDF publié sur votre site contient le symbole 🧭 cliquable ; la version papier
ne l'est pas (lien inerte sur papier, sans effet). La correction n'est jamais dans le PDF
de l'élève ni dans l'URL — uniquement en base, côté serveur.

## 5. Vérifier

1. Ouvrir `https://assistant.votredomaine.fr/e/ex-pgcd-01` → page de login.
2. Se connecter avec un compte élève → le chat doit s'afficher avec le titre de l'exercice.
3. Envoyer un message → réponse en streaming.
4. Sur [cloud.langfuse.com](https://cloud.langfuse.com) : la trace doit apparaître avec
   user_id (élève), session (conversation), tags (classe, exercice) et la consommation
   de tokens Mistral.

## Mise à jour

```bash
docker build -t rg.fr-par.scw.cloud/devoirsfaits/app:latest -f deploy/Dockerfile .
docker push rg.fr-par.scw.cloud/devoirsfaits/app:latest
# le container redéploie la nouvelle image (ou redeploy via console/CLI)
```

## Si le cold start agace (2-5 s)

Passer **min scale = 1** dans la config du container : ~1-2 €/mois en plus,
réponse immédiate en permanence.

## Notes sécurité

- HTTPS automatique (domaine custom Scaleway), cookies de session `Secure` + `HttpOnly`.
- Mots de passe hashés bcrypt, pas d'endpoint public d'inscription.
- Les photos des cahiers sont compressées (1280px, JPEG q70) avant envoi au LLM
  (économie de tokens) et stockées dans Postgres pour votre suivi pédagogique.
- Aucune clé dans l'image Docker : tout passe par les variables d'environnement du container.
