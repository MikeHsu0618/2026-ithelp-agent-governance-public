variable "aws_region" {
  description = "AWS Region that hosts the synthetic Cognito user pool."
  type        = string
  default     = "ap-northeast-1"
}

variable "domain_prefix" {
  description = "Globally unique Cognito managed-login domain prefix."
  type        = string
  default     = "replace-me-day12-agent-lab"
}

variable "human_callback_urls" {
  description = "Exact callbacks used by the interactive public client."
  type        = list(string)
  default     = ["http://127.0.0.1:8765/callback"]
}

variable "resource_server_identifier" {
  description = "Short identifier used as the custom-scope prefix."
  type        = string
  default     = "platform"
}

variable "resource_indicator" {
  description = "URL sent as resource= for Human Authorization Code requests."
  type        = string
  default     = "https://observability.lab.example/mcp"
}
