# --- Identité Scaleway ---
# Trouvés dans la console : Account > Credentials > Organization ID / Project ID
# Ou via `scw config show`
variable "scaleway_organization_id" {
  type        = string
  description = "Organization ID Scaleway"
}

variable "scaleway_project_id" {
  type        = string
  description = "Project ID Scaleway"
}

variable "scaleway_zone" {
  type        = string
  default     = "fr-par-1"
  description = "Zone Scaleway (containers : fr-par)"
}

variable "scaleway_region" {
  type        = string
  default     = "fr-par"
  description = "Région Scaleway"
}

# --- Nommage ---
variable "container_name" {
  type        = string
  default     = "devoirsfaits"
  description = "Nom du container et du namespace serverless"
}

variable "registry_namespace_name" {
  type        = string
  default     = "devoirsfaits"
  description = "Nom du namespace Container Registry"
}

variable "image_tag" {
  type        = string
  default     = "latest"
  description = "Tag de l'image Docker à déployer"
}

# --- Ressources container ---
variable "max_scale" {
  type        = number
  default     = 5
  description = "Nombre max d'instances (scale-to-0 : min_scale=0, gratuit)"
}

variable "memory_limit" {
  type        = number
  default     = 1024
  description = "Mémoire en Mo. 512 suffit pour l'usage scolaire, 1024 confortable avec streaming."
}

variable "max_concurrency" {
  type        = number
  default     = 20
  description = "Requêtes concurrentes par instance"
}

# --- Configuration application ---
variable "database_url" {
  type        = string
  sensitive   = true
  description = "PostgreSQL de votre base partagée, ex: postgresql://user:pass@host:5432/db"
}

variable "secret_key" {
  type        = string
  sensitive   = true
  description = "Clé de signature des sessions (python -c 'import secrets; print(secrets.token_hex(32))')"
}

variable "mistral_api_key" {
  type        = string
  sensitive   = true
  description = "Clé API Mistral (console.mistral.ai)"
}

variable "mistral_model" {
  type        = string
  default     = "mistral-medium-latest"
  description = "Modèle de chat"
}

variable "mistral_max_tokens" {
  type        = number
  default     = 1500
  description = "Tokens max par réponse"
}

variable "langfuse_host" {
  type        = string
  default     = "https://cloud.langfuse.com"
  description = "Host Langfuse"
}

variable "langfuse_public_key" {
  type        = string
  sensitive   = true
  description = "Clé publique Langfuse (vide = tracing désactivé)"
  default     = ""
}

variable "langfuse_secret_key" {
  type        = string
  sensitive   = true
  description = "Clé secrète Langfuse"
  default     = ""
}
