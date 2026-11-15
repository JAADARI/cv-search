output "acr_name" {
  value = azurerm_container_registry.main.name
}

output "api_url" {
  value = "https://${azurerm_container_app.api.ingress[0].fqdn}"
}

output "ui_url" {
  value = "https://${azurerm_container_app.ui.ingress[0].fqdn}"
}

output "key_vault" {
  value = azurerm_key_vault.main.name
}

output "retrieve_credentials" {
  description = "Commands to read the generated API key and UI password."
  value = {
    api_key     = "az keyvault secret show --vault-name ${azurerm_key_vault.main.name} --name api-key --query value -o tsv"
    ui_password = "az keyvault secret show --vault-name ${azurerm_key_vault.main.name} --name ui-password --query value -o tsv"
  }
}
