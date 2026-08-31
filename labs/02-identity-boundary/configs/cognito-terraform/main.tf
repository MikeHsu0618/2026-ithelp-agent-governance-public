locals {
  query_scope = "${var.resource_server_identifier}/observability.query"
}

resource "aws_cognito_user_pool" "agent_lab" {
  name = "ithelp-day12-agent-lab"

  deletion_protection = "INACTIVE"

  admin_create_user_config {
    allow_admin_create_user_only = true
  }
}

resource "aws_cognito_user_pool_domain" "agent_lab" {
  domain       = var.domain_prefix
  user_pool_id = aws_cognito_user_pool.agent_lab.id
}

resource "aws_cognito_resource_server" "observability" {
  identifier   = var.resource_server_identifier
  name         = "Observability MCP"
  user_pool_id = aws_cognito_user_pool.agent_lab.id

  scope {
    scope_name        = "observability.query"
    scope_description = "Query synthetic observability data through MCP"
  }
}

resource "aws_cognito_user_pool_client" "human" {
  name         = "sre-console-human"
  user_pool_id = aws_cognito_user_pool.agent_lab.id

  generate_secret                      = false
  allowed_oauth_flows_user_pool_client = true
  allowed_oauth_flows                  = ["code"]
  allowed_oauth_scopes                 = ["openid", local.query_scope]
  callback_urls                        = var.human_callback_urls
  supported_identity_providers         = ["COGNITO"]

  access_token_validity  = 5
  id_token_validity      = 5
  refresh_token_validity = 1

  token_validity_units {
    access_token  = "minutes"
    id_token      = "minutes"
    refresh_token = "days"
  }

  enable_token_revocation       = true
  prevent_user_existence_errors = "ENABLED"

  depends_on = [aws_cognito_resource_server.observability]
}

resource "aws_cognito_user_pool_client" "m2m" {
  name         = "sre-scheduler-m2m"
  user_pool_id = aws_cognito_user_pool.agent_lab.id

  generate_secret                      = true
  allowed_oauth_flows_user_pool_client = true
  allowed_oauth_flows                  = ["client_credentials"]
  allowed_oauth_scopes                 = [local.query_scope]

  access_token_validity = 5

  token_validity_units {
    access_token = "minutes"
  }

  enable_token_revocation       = true
  prevent_user_existence_errors = "ENABLED"

  depends_on = [aws_cognito_resource_server.observability]
}
