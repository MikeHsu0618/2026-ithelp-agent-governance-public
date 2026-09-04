# Cognito Human／M2M 雙路徑盤點表

## App client contract

| 欄位 | Human | M2M |
| --- | --- | --- |
| App client | Public | Confidential |
| Client secret | 不產生、不打包進 CLI | 必須有，放 Secret Manager／受控 secret store |
| Grant | Authorization Code | Client Credentials |
| PKCE | S256 | 不適用 |
| Callback | Exact allowlist | 不適用 |
| Scope | OIDC scope + custom scope，依需求 | Custom resource-server scope only |
| `resource` | URL，可在 Authorization Code request 使用 | Cognito 不支援 Client Credentials resource binding |
| `aud` | 有 resource binding 時必須等於目標 API | 不應要求 Human path 的 resource-bound `aud` |
| Audit Human | 來自已驗證的 `sub` | `NOT_APPLICABLE` |
| Audit machine actor | App client／runtime context | 來自已驗證的 `client_id` |

## Gateway validation order

```text
1. JWT size / alg / kid / JWKS / signature
2. iss / exp / token_use=access
3. client_id belongs to an allowed app-client profile
4. scope contains the required custom scope
5a. Human profile: require sub + expected aud (+ organization policy claims)
5b. M2M profile: use client_id as machine actor, without Human aud/sub semantics
6. Tool-level authorization
7. Audit actor, client, scope, target, decision, trace ID
```

## Failure map

| Lab case | Stage | Code | 優先檢查 |
| --- | --- | --- | --- |
| `human_callback_mismatch` | authorization | `REDIRECT_URI_MISMATCH` | 實際 callback host／port／path 與 app-client allowlist |
| `human_scope_invalid` | authorization | `INVALID_SCOPE` | resource metadata、request scope、app-client allowlist |
| `human_missing_policy_claim` | policy | `CLAIM_MISSING` | pre-token customization／group mapping 與 Gateway policy input |
| `m2m_public_client` | client authentication | `UNAUTHORIZED_CLIENT` | 是否誤用 Human public client |
| `m2m_wrong_secret` | client authentication | `INVALID_CLIENT` | secret version、rotation、client ID 配對 |
| `m2m_openid_scope` | token | `INVALID_SCOPE` | M2M 是否只請求 custom resource-server scope |
| `m2m_resource_binding` | token | `RESOURCE_BINDING_UNSUPPORTED` | 移除 Client Credentials request 的 `resource`，Gateway 改驗 client + scope |

## Repo commands

```bash
make lab-02-up
make lab-02-check
make lab-02-cognito
make lab-02-cognito-config-check
```

`lab-02-cognito-config-check` 會執行 Terraform syntax／provider-schema validation，以及 agentgateway v1.4.1 `--validate-only`。它不會 apply AWS 資源，也不會啟動 MCP target。

## Production checklist

- [ ] Human 與 M2M 使用不同 app client，沒有混合 grant。
- [ ] Public client 沒有 durable secret，PKCE 固定使用 S256。
- [ ] Callback 以 client 實際行為建 allowlist，`localhost` 與 `127.0.0.1` 分開登錄。
- [ ] M2M secret 不進 image、Git、terminal history 或低權限 Terraform state。
- [ ] Secret rotation 能同時接受新舊 credential，並有完成切換的截止時間。
- [ ] Human resource indicator 是 URL，Gateway 對 Human token 驗 `aud`。
- [ ] M2M policy 以受信任 `client_id` + custom scope 授權，不虛構 Human。
- [ ] JWKS cache／rotation、issuer outage 與 stale-key 行為有實際演練。
- [ ] Audit 能分辨 `user/sre-oncaller` 與 `client/sre-scheduler`，不只留下 `authenticated=true`。
- [ ] Cognito M2M token request volume、token lifetime 與 cache 策略已納入成本估算。
