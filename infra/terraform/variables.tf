variable "location" {
  description = "Azure region for all resources except Azure OpenAI."
  type        = string
  default     = "francecentral"
}

variable "openai_location" {
  description = "Region of the Azure OpenAI account (must offer the embedding model)."
  type        = string
  default     = "francecentral"
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
  description = "Tag of the application image in ACR. Empty = deploy a placeholder image (bootstrap)."
  type        = string
  default     = ""
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

variable "embedding_model" {
  description = "Azure OpenAI embedding model to deploy."
  type        = string
  default     = "text-embedding-3-small"
}

variable "embedding_dimensions" {
  description = "Vector size stored in pgvector (embedding-3 models can be shortened)."
  type        = number
  default     = 1024
}

variable "postgres_sku" {
  description = "PostgreSQL Flexible Server SKU."
  type        = string
  default     = "B_Standard_B1ms"
}

variable "postgres_storage_mb" {
  type    = number
  default = 32768
}

variable "tags" {
  type    = map(string)
  default = {}
}
