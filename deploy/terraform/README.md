# Déploiement Terraform — Scaleway Serverless Container

Provisionne l'infrastructure d'hébergement de Devoirs Faits :

- un **namespace Container Registry** (stockage de l'image Docker) ;
- un **Serverless Container** scale-to-0 (la BDD n'est **pas** gérée ici : elle est partagée et référencée via `database_url`).

## Prérequis

1. **CLI Scaleway** authentifié : `scw init` (ou token dans `~/.config/scw/config.yaml`). Terraform utilise le fichier de config `scw` si les variables d'identité ne sont pas dans le `.tfvars`.
2. **Terraform** >= 1.5.
3. **Docker** pour construire et pousser l'image.

## Étapes

### 1. Renommer le namespace registry si nécessaire

Par défaut le namespace registry s'appelle `devoirsfaits`. S'il existe déjà (créé via la console), ajustez `registry_namespace_name` dans `terraform.tfvars` pour réutiliser le même — terraform importera, voir « Import » plus bas.

### 2. Renseigner les variables

```bash
cp terraform.tfvars.example terraform.tfvars
# éditez terraform.tfvars :
#  - organization/project ID (console Scaleway > Account > Credentials)
#  - database_url (votre base partagée)
#  - secret_key (une seule fois, gardez-la stable entre les déploiements)
#  - clés API Mistral / Langfuse
```

`terraform.tfvars` contient des secrets : ne le committez pas. Les variables sensibles sont marquées `sensitive` (masquées dans les outputs et les plans).

### 3. Provisionner

```bash
cd deploy/terraform
terraform init
terraform apply
```

Premier `apply` : le container est créé avec une image vide ou absente — c'est normal, le registry est vide à ce stade.

### 4. Construire et pousser l'image

```bash
# depuis la racine du repo
docker login rg.fr-par.scw.cloud -u anonymous --password-stdin <<< "$(scw registry login --output json | jq -r .token)"
# ou: scw registry login docker

docker build -t rg.fr-par.scw.cloud/devoirsfaits/app:latest -f deploy/Dockerfile .
docker push rg.fr-par.scw.cloud/devoirsfaits/app:latest
# (utilisez l'endpoint exact affiché par terraform output registry_endpoint)
```

Puis redéployez pour que le container pointe sur l'image :

```bash
terraform apply   # si image_tag a changé, sinon :
scw container container deploy <container-id>
```

Le plus simple après le premier push : redéployer depuis la console ou via `scw container container deploy`. Le `terraform apply` est idempotent : il ne re-déploie pas si rien ne change.

### 5. Vérifier

```bash
terraform output container_url
# → https://devoirsfaits-xxxxxx.fr-par.scw.cloud
curl -I https://...  # → 303 (redirection login) après cold start (~2-5 s)
```

## Accès réseau BDD

Les Serverless Containers Scaleway doivent joindre votre Managed Database :

- si la BDD est en **Private Network** : rattachez le namespace container au même PN (à ajouter dans `main.tf` via `scaleway_container_namespace` + `private_network_id`, variable à fournir) ;
- si la BDD accepte l'**IP publique** : autorisez les IPs sortantes des Serverless Containers de la région (voir doc Scaleway), ou tout `0.0.0.0/0` avec le flag approprié si acceptable pour vous.

Le schéma `devoirsfaits` (tables + migrations) est créé automatiquement au premier démarrage via `init_db()`.

## Détruire

```bash
terraform destroy
```

Supprime le container et le namespace registry (les images ne sont pas supprimées séparément, le namespace part avec). **La BDD n'est pas touchée.**

## Notes

- `min_scale = 0` : l'instance s'arrête entre les requêtes, coût ~0 € sous le free tier (400 000 GB-s + 1M req/mois), au prix d'un cold start de quelques secondes.
- `timeout = 300` : laisse le streaming LLM souffler sur les longues réponses.
- Les secrets sont injectés comme **variables d'environnement chiffrées** du container (`secret_environment_variables`), jamais dans le state en clair... sauf que si : le state terraform contient les valeurs en clair — stockez le state à l'abri (backend S3 Scaleway recommandé : voir `terraform { backend "s3" }`).
