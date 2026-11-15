data "azurerm_client_config" "current" {}

data "azurerm_resource_group" "main" {
  name = var.resource_group_name
}

resource "random_string" "suffix" {
  length  = 5
  upper   = false
  special = false
}

locals {
  name     = "${var.project}-${var.environment}"
  flat     = "${var.project}${var.environment}${random_string.suffix.result}"
  location = data.azurerm_resource_group.main.location
  rg       = data.azurerm_resource_group.main.name
  tags     = merge({ project = var.project, environment = var.environment, managed_by = "terraform" }, var.tags)
  image    = "${azurerm_container_registry.main.login_server}/${var.project}:${var.image_tag}"
}

# ---------------------------------------------------------------- database
resource "random_password" "db" {
  length  = 32
  special = false
}

# PostgreSQL Flexible Server with pgvector. The guardrail policy forbids virtual networks,
# so the server is reachable over TLS with a strong password and an Azure-services-only firewall rule.
resource "azurerm_postgresql_flexible_server" "main" {
  name                          = "psql-${local.flat}"
  resource_group_name           = local.rg
  location                      = local.location
  version                       = "16"
  administrator_login           = "cvsearch"
  administrator_password        = random_password.db.result
  sku_name                      = var.postgres_sku
  storage_mb                    = 32768
  backup_retention_days         = 7
  public_network_access_enabled = true
  tags                          = local.tags

  lifecycle {
    ignore_changes = [zone, high_availability[0].standby_availability_zone]
  }
}

resource "azurerm_postgresql_flexible_server_database" "main" {
  name      = "cvsearch"
  server_id = azurerm_postgresql_flexible_server.main.id
  charset   = "UTF8"
  collation = "en_US.utf8"
}

# pgvector must be allow-listed before the application can CREATE EXTENSION.
resource "azurerm_postgresql_flexible_server_configuration" "extensions" {
  name      = "azure.extensions"
  server_id = azurerm_postgresql_flexible_server.main.id
  value     = "VECTOR"
}

resource "azurerm_postgresql_flexible_server_firewall_rule" "azure_services" {
  name             = "AllowAzureServices"
  server_id        = azurerm_postgresql_flexible_server.main.id
  start_ip_address = "0.0.0.0"
  end_ip_address   = "0.0.0.0"
}

# ---------------------------------------------------------------- secrets
resource "random_password" "api_key" {
  length  = 40
  special = false
}

resource "random_password" "ui_password" {
  length  = 20
  special = false
}

# Key Vault keeps the generated credentials retrievable by the operator. Access-policy mode is used
# because this account cannot create role assignments (needed by RBAC mode).
resource "azurerm_key_vault" "main" {
  name                       = "kv-${local.flat}"
  resource_group_name        = local.rg
  location                   = local.location
  tenant_id                  = data.azurerm_client_config.current.tenant_id
  sku_name                   = "standard"
  rbac_authorization_enabled = false
  purge_protection_enabled   = false
  soft_delete_retention_days = 7
  tags                       = local.tags

  access_policy {
    tenant_id          = data.azurerm_client_config.current.tenant_id
    object_id          = data.azurerm_client_config.current.object_id
    secret_permissions = ["Get", "List", "Set", "Delete", "Purge", "Recover"]
  }
}

resource "azurerm_key_vault_secret" "api_key" {
  name         = "api-key"
  value        = random_password.api_key.result
  key_vault_id = azurerm_key_vault.main.id
}

resource "azurerm_key_vault_secret" "ui_password" {
  name         = "ui-password"
  value        = random_password.ui_password.result
  key_vault_id = azurerm_key_vault.main.id
}

# ---------------------------------------------------------------- registry and compute
resource "azurerm_container_registry" "main" {
  name                = "acr${local.flat}"
  resource_group_name = local.rg
  location            = local.location
  sku                 = "Basic"
  admin_enabled       = true # managed-identity pulls need a role assignment, which this account cannot create
  tags                = local.tags
}

resource "azurerm_log_analytics_workspace" "main" {
  name                = "log-${local.name}"
  resource_group_name = local.rg
  location            = local.location
  sku                 = "PerGB2018"
  retention_in_days   = 30
  tags                = local.tags
}

resource "azurerm_container_app_environment" "main" {
  name                       = "cae-${local.name}"
  resource_group_name        = local.rg
  location                   = local.location
  log_analytics_workspace_id = azurerm_log_analytics_workspace.main.id
  tags                       = local.tags
}
