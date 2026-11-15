locals {
  # name in the container app -> secret in Key Vault
  secret_refs = {
    "apim-subscription-key" = "apim-subscription-key"
    "api-key"               = "api-key"
    "ui-password"           = "ui-password"
    "embedding-api-key"     = "embedding-api-key"
    "database-url"          = "database-url"
  }

  common_env = {
    APIM_BASE_URL        = var.apim_base_url
    CHAT_DEPLOYMENT      = var.chat_deployment
    EMBEDDING_PROVIDER   = "azure"
    EMBEDDING_ENDPOINT   = azurerm_cognitive_account.openai.endpoint
    EMBED_DEPLOYMENT     = azurerm_cognitive_deployment.embedding.name
    EMBEDDING_DIMENSIONS = tostring(var.embedding_dimensions)
  }

  common_secret_env = {
    APIM_SUBSCRIPTION_KEY = "apim-subscription-key"
    EMBEDDING_API_KEY     = "embedding-api-key"
    DATABASE_URL          = "database-url"
    CVSEARCH_API_KEY      = "api-key"
  }
}

# One module-less definition per app keeps the plan readable; api, worker and ui share one image.
resource "azurerm_container_app" "api" {
  name                         = "ca-${local.name}-api"
  resource_group_name          = azurerm_resource_group.main.name
  container_app_environment_id = azurerm_container_app_environment.main.id
  revision_mode                = "Single"
  tags                         = local.tags

  identity {
    type         = "UserAssigned"
    identity_ids = [azurerm_user_assigned_identity.app.id]
  }

  registry {
    server   = azurerm_container_registry.main.login_server
    identity = azurerm_user_assigned_identity.app.id
  }

  dynamic "secret" {
    for_each = local.secret_refs
    content {
      name                = secret.key
      key_vault_secret_id = azurerm_key_vault_secret.app[secret.value].versionless_id
      identity            = azurerm_user_assigned_identity.app.id
    }
  }

  ingress {
    external_enabled = true
    target_port      = local.bootstrap ? 80 : 8000
    transport        = "auto"
    traffic_weight {
      latest_revision = true
      percentage      = 100
    }
  }

  template {
    min_replicas = 1
    max_replicas = 3

    container {
      name    = "api"
      image   = local.image
      cpu     = 0.5
      memory  = "1Gi"
      command = local.bootstrap ? null : ["cvsearch", "api"]

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

      dynamic "liveness_probe" {
        for_each = local.bootstrap ? [] : [1]
        content {
          transport = "HTTP"
          path      = "/health"
          port      = 8000
        }
      }
    }

    http_scale_rule {
      name                = "http"
      concurrent_requests = "20"
    }
  }

  depends_on = [time_sleep.rbac]
}

resource "azurerm_container_app" "worker" {
  name                         = "ca-${local.name}-worker"
  resource_group_name          = azurerm_resource_group.main.name
  container_app_environment_id = azurerm_container_app_environment.main.id
  revision_mode                = "Single"
  tags                         = local.tags

  identity {
    type         = "UserAssigned"
    identity_ids = [azurerm_user_assigned_identity.app.id]
  }

  registry {
    server   = azurerm_container_registry.main.login_server
    identity = azurerm_user_assigned_identity.app.id
  }

  dynamic "secret" {
    for_each = local.secret_refs
    content {
      name                = secret.key
      key_vault_secret_id = azurerm_key_vault_secret.app[secret.value].versionless_id
      identity            = azurerm_user_assigned_identity.app.id
    }
  }

  template {
    # The worker polls a Postgres queue, so it must always run; two replicas are safe (SKIP LOCKED).
    min_replicas = 1
    max_replicas = 2

    container {
      name    = "worker"
      image   = local.image
      cpu     = 0.5
      memory  = "1Gi"
      command = local.bootstrap ? ["sleep", "infinity"] : ["cvsearch", "worker"]

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

  depends_on = [time_sleep.rbac]
}

resource "azurerm_container_app" "ui" {
  name                         = "ca-${local.name}-ui"
  resource_group_name          = azurerm_resource_group.main.name
  container_app_environment_id = azurerm_container_app_environment.main.id
  revision_mode                = "Single"
  tags                         = local.tags

  identity {
    type         = "UserAssigned"
    identity_ids = [azurerm_user_assigned_identity.app.id]
  }

  registry {
    server   = azurerm_container_registry.main.login_server
    identity = azurerm_user_assigned_identity.app.id
  }

  dynamic "secret" {
    for_each = local.secret_refs
    content {
      name                = secret.key
      key_vault_secret_id = azurerm_key_vault_secret.app[secret.value].versionless_id
      identity            = azurerm_user_assigned_identity.app.id
    }
  }

  ingress {
    external_enabled = true
    target_port      = local.bootstrap ? 80 : 8501
    transport        = "auto"
    traffic_weight {
      latest_revision = true
      percentage      = 100
    }
  }

  template {
    min_replicas = 0
    max_replicas = 2

    container {
      name   = "ui"
      image  = local.image
      cpu    = 0.5
      memory = "1Gi"
      command = local.bootstrap ? null : [
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

  depends_on = [time_sleep.rbac]
}
