terraform {
  required_version = ">= 1.9"

  required_providers {
    azurerm = {
      source  = "hashicorp/azurerm"
      version = "~> 4.20"
    }
    random = {
      source  = "hashicorp/random"
      version = "~> 3.6"
    }
  }

  # State lives in a storage account created once by infra/scripts/bootstrap.sh.
  # Run: terraform init -backend-config=backend.hcl   (and export ARM_ACCESS_KEY)
  backend "azurerm" {}
}

provider "azurerm" {
  subscription_id = var.subscription_id
  # The candidate account is a Contributor on one resource group only: it cannot register providers.
  resource_provider_registrations = "none"

  features {
    key_vault {
      purge_soft_delete_on_destroy = true
    }
  }
}
