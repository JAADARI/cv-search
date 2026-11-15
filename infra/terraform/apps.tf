locals {
  # Container Apps secrets (encrypted at rest by the platform), keyed by the name used in env blocks.
  secrets = {
    "acr-password"          = azurerm_container_registry.main.admin_password
    "apim-subscription-key" = var.apim_subscription_key
    "api-key"               = random_password.api_key.result
    "ui-password"           = random_password.ui_password.result
    "database-url" = join("", [
      "postgresql://cvsearch:", random_password.db.result, "@", azurerm_postgresql_flexible_server.main.fqdn,
      ":5432/", azurerm_postgresql_flexible_server_database.main.name, "?sslmode=require"
    ])
  }

  # Embeddings run in-process (local multilingual model baked into the image): the OpenAI account of
  # this subscription has key auth disabled and no role can be granted, see docs/adr/0004.
  common_env = {
    APIM_BASE_URL        = var.apim_base_url
    CHAT_DEPLOYMENT      = var.chat_deployment
    EMBEDDING_PROVIDER   = "local"
    EMBEDDING_DIMENSIONS = "1024"
    FASTEMBED_CACHE_PATH = "/opt/fastembed"
  }

  common_secret_env = {
    APIM_SUBSCRIPTION_KEY = "apim-subscription-key"
    DATABASE_URL          = "database-url"
    CVSEARCH_API_KEY      = "api-key"
  }
}

resource "azurerm_container_app" "api" {
  name                         = "ca-${local.name}-api"
  resource_group_name          = local.rg
  container_app_environment_id = azurerm_container_app_environment.main.id
  revision_mode                = "Single"
  tags                         = local.tags

  registry {
    server               = azurerm_container_registry.main.login_server
    username             = azurerm_container_registry.main.admin_username
    password_secret_name = "acr-password"
  }

  dynamic "secret" {
    for_each = nonsensitive(toset(keys(local.secrets)))
    content {
      name  = secret.value
      value = local.secrets[secret.value]
    }
  }

  ingress {
    external_enabled = true
    target_port      = 8000
    transport        = "auto"
    traffic_weight {
      latest_revision = true
      percentage      = 100
    }
  }

  template {
    min_replicas = 1
    max_replicas = 2

    container {
      name    = "api"
      image   = local.image
      cpu     = 2
      memory  = "4Gi"
      command = ["cvsearch", "api"]

      dynamic "env" {
        for_each = local.common_env
        content {
          name  = env.key
          value = env.value
        }
      }
      dynamic "env" {
        for_each = local.common_secret_env
        content {
          name        = env.key
          secret_name = env.value
        }
      }

      liveness_probe {
        transport               = "HTTP"
        path                    = "/health"
        port                    = 8000
        initial_delay           = 45
        interval_seconds        = 20
        failure_count_threshold = 3
      }
    }

    http_scale_rule {
      name                = "http"
      concurrent_requests = "20"
    }
  }
}

resource "azurerm_container_app" "worker" {
  name                         = "ca-${local.name}-worker"
  resource_group_name          = local.rg
  container_app_environment_id = azurerm_container_app_environment.main.id
  revision_mode                = "Single"
  tags                         = local.tags

  registry {
    server               = azurerm_container_registry.main.login_server
    username             = azurerm_container_registry.main.admin_username
    password_secret_name = "acr-password"
  }

  dynamic "secret" {
    for_each = nonsensitive(toset(keys(local.secrets)))
    content {
      name  = secret.value
      value = local.secrets[secret.value]
    }
  }

  template {
    # The worker polls a Postgres queue, so it always runs; extra replicas are safe (FOR UPDATE SKIP LOCKED).
    min_replicas = 1
    max_replicas = 2

    container {
      name    = "worker"
      image   = local.image
      cpu     = 2
      memory  = "4Gi"
      command = ["cvsearch", "worker"]

      dynamic "env" {
        for_each = local.common_env
        content {
          name  = env.key
          value = env.value
        }
      }
      dynamic "env" {
        for_each = local.common_secret_env
        content {
          name        = env.key
          secret_name = env.value
        }
      }
    }
  }
}

resource "azurerm_container_app" "ui" {
  name                         = "ca-${local.name}-ui"
  resource_group_name          = local.rg
  container_app_environment_id = azurerm_container_app_environment.main.id
  revision_mode                = "Single"
  tags                         = local.tags

  registry {
    server               = azurerm_container_registry.main.login_server
    username             = azurerm_container_registry.main.admin_username
    password_secret_name = "acr-password"
  }

  dynamic "secret" {
    for_each = nonsensitive(toset(keys(local.secrets)))
    content {
      name  = secret.value
      value = local.secrets[secret.value]
    }
  }

  ingress {
    external_enabled = true
    target_port      = 8501
    transport        = "auto"
    traffic_weight {
      latest_revision = true
      percentage      = 100
    }
  }

  template {
    min_replicas = 1
    max_replicas = 2

    container {
      name   = "ui"
      image  = local.image
      cpu    = 0.5
      memory = "1Gi"
      command = [
        "streamlit", "run", "src/cvsearch/ui/streamlit_app.py",
        "--server.port=8501", "--server.address=0.0.0.0", "--server.headless=true"
      ]

      env {
        name  = "CVSEARCH_API_URL"
        value = "https://${azurerm_container_app.api.ingress[0].fqdn}"
      }
      env {
        name        = "CVSEARCH_API_KEY"
        secret_name = "api-key"
      }
      env {
        name        = "CVSEARCH_UI_PASSWORD"
        secret_name = "ui-password"
      }
    }

    http_scale_rule {
      name                = "http"
      concurrent_requests = "30"
    }
  }
}
