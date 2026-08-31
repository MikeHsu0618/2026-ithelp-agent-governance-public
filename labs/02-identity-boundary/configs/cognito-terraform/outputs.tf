output "issuer" {
  description = "Expected iss claim for both Human and M2M access tokens."
  value = format(
    "https://cognito-idp.%s.amazonaws.com/%s",
    var.aws_region,
    aws_cognito_user_pool.agent_lab.id,
  )
}

output "human_client_id" {
  description = "Public Authorization Code + PKCE app-client ID."
  value       = aws_cognito_user_pool_client.human.id
}

output "m2m_client_id" {
  description = "Confidential Client Credentials app-client ID; this is not the secret."
  value       = aws_cognito_user_pool_client.m2m.id
}

output "custom_scope" {
  description = "Custom scope shared by Human and M2M access tokens."
  value       = local.query_scope
}

output "human_resource_indicator" {
  description = "Send this URL as resource= only on the Human authorization request."
  value       = var.resource_indicator
}
