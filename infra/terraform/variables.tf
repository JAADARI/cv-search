variable "subscription_id" {
  description = "Azure subscription id."
  type        = string
}

variable "resource_group_name" {
  description = "Existing resource group to deploy into (resource groups cannot be created with this account)."
  type        = string
}

variable "project" {
  description = "Short name used as prefix for every resource."
  type        = string
  default     = "cvsearch"
}

variable "environment" {
  description = "Environment name (dev, prod...)."
  type        = string
  default     = "dev"
}

variable "image_tag" {
  description = "Tag of the application image in ACR."
  type        = string
}

variable "apim_base_url" {
  description = "Base URL of the LLM gateway (APIM)."
  type        = string
}

variable "apim_subscription_key" {
  description = "Subscription key of the LLM gateway."
  type        = string
  sensitive   = true
}

variable "chat_deployment" {
  description = "Chat model deployment name exposed by the gateway."
  type        = string
  default     = "gpt-5"
}

variable "postgres_sku" {
  description = "PostgreSQL Flexible Server SKU (the guardrail policy allows B1ms and B2s)."
  type        = string
  default     = "B_Standard_B1ms"
}

variable "tags" {
  type    = map(string)
  default = {}
}
