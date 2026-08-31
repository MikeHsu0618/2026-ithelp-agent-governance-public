# Day 12 configuration samples

These files are deployment-shaped examples, not evidence that a live AWS account was changed.
All pool IDs, client IDs, domains, callbacks, resources, and scopes are synthetic.

## Cognito Terraform

The Terraform split is intentional:

- `human`: public app client, Authorization Code only, no client secret;
- `m2m`: confidential app client, Client Credentials only, generated secret;
- both may request the same custom scope;
- only the Human authorization request sends the URL-formatted `resource` indicator.

Syntax validation:

```bash
terraform -chdir=labs/02-identity-boundary/configs/cognito-terraform init -backend=false
terraform -chdir=labs/02-identity-boundary/configs/cognito-terraform validate
```

The example has not been applied to an AWS account. Before applying it, replace the domain,
callback, resource, naming, retention, tags, and user-pool policies. A generated Cognito client
secret is sensitive and will exist in Terraform state; use an encrypted remote backend with tightly
restricted access. The repo deliberately does not output or persist that secret.

PKCE is performed by the public client at runtime. Cognito app-client configuration enables the
Authorization Code grant but does not contain the transient `code_verifier` or `code_challenge`.

## agentgateway resource-server policy

`agentgateway-cognito.yaml` uses one MCP listener and one gateway policy boundary. The common JWT
layer requires only claims present on both Cognito paths. CEL then applies conditional rules:

- Human must carry the expected `client_id`, `sub`, `aud`, and scope;
- M2M must carry the expected `client_id` and scope while resource-bound `aud` stays absent.

The M2M rule intentionally does not authorize by `sub`. The offline fixture omits it because there is
no Human subject to represent, but production attribution is derived from the verified `client_id`
rather than assuming a provider/version-specific `sub` shape.

The committed config points to `cognito-jwks.json`, which contains one synthetic RSA public key and
no signing material. This lets `--validate-only` load and parse JWKS without pretending a fake user
pool exists. Production must replace `jwks.file` with the real Cognito issuer's
`/.well-known/jwks.json` URL and verify key-rotation behavior.

Validate the exact committed file with the pinned image:

```bash
docker run --rm \
  -v "$PWD/labs/02-identity-boundary/configs:/config:ro" \
  cr.agentgateway.dev/agentgateway@sha256:efd79355b89094a8225a9db465d9a01dc656b377f0bab458761b935a13231d29 \
  --file /config/agentgateway-cognito.yaml \
  --validate-only
```

This is Resource Server Only mode. It validates JWTs and publishes protected-resource metadata; it
does not claim that Cognito is a tested agentgateway provider, proxy Cognito discovery, or provide
Dynamic Client Registration. The `npx` target follows the upstream documentation example and is not
started by `--validate-only`.
