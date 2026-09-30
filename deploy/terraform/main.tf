terraform {
  required_version = ">= 1.5"

  required_providers {
    scaleway = {
      source  = "scaleway/scaleway"
      version = "~> 2.0"
    }
  }
}

provider "scaleway" {
  zone            = var.scaleway_zone
  region          = var.scaleway_region
  organization_id = var.scaleway_organization_id
  project_id      = var.scaleway_project_id
}

# --- Registry namespace pour l'image de l'application ---

resource "scaleway_registry_namespace" "app" {
  name        = var.registry_namespace_name
  description = "Images Docker de Devoirs Faits"
  # gratuit sous quota
}

# --- Namespace serverless (doit exister avant le container) ---

resource "scaleway_container_namespace" "app" {
  name = var.container_name
}

# --- Container serverless (scale-to-0) ---

resource "scaleway_container" "app" {
  name       = var.container_name
  namespace  = scaleway_container_namespace.app.id
  registry_image = "${scaleway_registry_namespace.app.endpoint}/app:${var.image_tag}"

  port           = 8080
  min_scale      = 0
  max_scale      = var.max_scale
  memory_limit   = var.memory_limit   # Mo. Le CPU est alloué proportionnellement à la mémoire.

  http_option    = "redirected"       # HTTP -> HTTPS automatique
  max_concurrency = var.max_concurrency
  timeout        = 300                # secondes max par requête (streaming LLM)

  environment_variables = {
    APP_NAME     = "Devoirs Faits"
    MISTRAL_MODEL       = var.mistral_model
    MISTRAL_BASE_URL    = "https://api.mistral.ai/v1"
    MISTRAL_MAX_TOKENS  = var.mistral_max_tokens
    LANGFUSE_HOST       = var.langfuse_host
    IMAGE_MAX_DIM       = "1280"
    IMAGE_JPEG_QUALITY  = "70"
  }

  secret_environment_variables = {
    DATABASE_URL       = var.database_url
    SECRET_KEY          = var.secret_key
    MISTRAL_API_KEY     = var.mistral_api_key
    LANGFUSE_PUBLIC_KEY = var.langfuse_public_key
    LANGFUSE_SECRET_KEY = var.langfuse_secret_key
  }
}

# --- Outputs ---

output "registry_endpoint" {
  description = "Endpoint du registry pour docker push"
  value       = scaleway_registry_namespace.app.endpoint
}

output "container_url" {
  description = "URL publique du container"
  value       = scaleway_container.app.domain_name
}
