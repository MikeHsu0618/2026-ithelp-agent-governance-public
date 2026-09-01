# Lab 02 — Identity Boundary

> 狀態：Day 8–12 `lab-green`。2026-08-23 已跑通 7 組合成 JWT、7 組 Delegation Context、7 組 Token passthrough、9 組 OAuth flow 與 9 組 Cognito dual-path case，完整 Lab 為 72 tests、branch coverage 91.17%。

這個 Lab 服務 Day 7–12。它不會連到作者的企業 IdP、Cognito User Pool 或 Kubernetes 環境；公開版只使用合成 principal、client、issuer、resource 與每次執行時產生的 RSA key。

## Questions

一枚簽章正確的 JWT，是否就能拿來存取這個 MCP resource？錯 issuer、audience、expiry、client、scope、policy claim 或 token type 時，應在哪一層被拒絕？

Token 驗過以後，同一筆 Tool Call 的 Human、Service、Agent、Workload 與 credential context 要如何一起保存？身分未知、欄位缺失與一個過度簡化的 `actor` 字串，是否能被機器分辨？

值班工程師的 Token 在 Agent entry 合法，能否原樣送到另一個 MCP resource？下游嚴格驗 audience、接受共用 audience，以及改用 resource-bound downstream token 時，Audit 會留下什麼差異？

互動式 Human、無人 Scheduler 與代表 Human 呼叫下游的 Runtime，應該分別走哪條 OAuth flow？Callback、scope、client registration、target 或 subject-token audience 錯誤時，應在 Token 發出前的哪個 stage 被拒絕？

同一個 Cognito user-pool issuer 下，Human Authorization Code + PKCE 與 M2M Client Credentials 能否共用同一個 app client 與 audience policy？Client Credentials 不支援 resource binding 時，Gateway 要如何保留 Human boundary 又允許 machine actor？

## Claim

- JWT signature 只回答內容是否由受信任 key 簽出且未被竄改，不能替代 issuer、resource、time 與 token-purpose validation。
- OAuth scope 與應用 policy claim 是不同檢查；登入成功、Token 合法，不表示 policy 已取得足夠 context。
- ID token 即使帶有 `team`，也不能拿來取代 API 所要求的 access token。
- Delegation audit 需要 actor chain、credential 與 target；`actor=user/sre-oncaller` 會遺失 Agent 順序與執行 Workload。
- `UNKNOWN` 與 `NOT_APPLICABLE` 是可查詢狀態，不能混成 `null` 或靠 deployment name 補值。
- 同一枚 Human Token 跨 resource passthrough 時，嚴格下游應拒絕；為了相容而共用 audience／client profile，會讓下游 attribution 塌縮成 Human subject。
- 下游 credential 要綁自己的 audience 與最小 scope；Human delegation 另外保存在與 credential fingerprint、subject、client、audience、target 綁定的 Context。
- Authorization Code + PKCE、Client Credentials 與 Token Exchange 分別代表 Human、Service 自身與 Human delegation；三者不能只因為都會拿到 access token 就共用 principal 語意。
- Cognito Human 與 M2M 可以共用 issuer／JWKS trust anchor，但必須拆成 public／confidential app client；Human 驗 resource-bound `aud`，M2M 以 `client_id` + custom scope 授權。

## Non-claim

- 本 slice 不是 Amazon Cognito emulator，也不證明作者的 private Cognito 設定。
- `at+jwt`／`id+jwt` 是 Lab 用來明確區分 token type 的 synthetic profile；Cognito 整合仍須依 AWS 文件驗 `token_use`、`client_id`、issuer、scope 與對應的 token key。
- 本機 JWKS 是離線文件，不是 production key rotation、cache、TLS 或 outage 測試。
- claim 存在不代表 claim 值已通過完整 ABAC policy。Day 8 只驗證 policy input 是否齊全。
- Delegation Context v0.1 是本系列的公開 audit contract，不是 RFC 8693、A2A 或 OpenTelemetry 標準。
- 合成 ServiceAccount 與 Agent metadata 標為 `ASSERTED`；本 Lab 沒有宣稱已完成 workload attestation 或 context integrity protection。
- Day 10 的 downstream token 由本機 issuer 直接簽出，不是 RFC 8693 Token Exchange、On-Behalf-Of 或 Cognito endpoint 的 emulator。
- Day 11 的 Authorization Server 是 in-memory policy simulator；沒有 HTTP endpoint、browser／consent、`state`／authorization-response `iss`、CIMD fetch、DCR、TLS、refresh token 或 production client authentication。
- Day 11 實作 RFC 8693 Token Exchange 語意。Microsoft Entra OBO request profile 另外說明，不宣稱兩者 wire-compatible。
- Day 12 是 Cognito-shaped offline contract，不是 live Cognito emulator。Terraform 只通過 provider-schema validation；agentgateway 只通過 v1.4.1 config／JWKS／CEL validation，沒有 AWS apply 或真實 Token call。
- agentgateway 官方 tested-provider 表沒有 Cognito；公開 config 使用 Resource Server Only，不宣稱 discovery、DCR／CIMD 或 provider adaptation 已解決。

## Versions

```text
Python:       3.14.5
PyJWT:        2.13.0
cryptography: 50.0.0
jsonschema:   4.26.0
pytest:       9.1.1
Tested:       2026-08-23
Terraform:    1.8.2 (AWS provider 6.61.0)
agentgateway: 1.4.1 (config validation only)
Git tag:      尚未建立；正式發稿前補上
```

`uv.lock` 已鎖住完整 dependency graph。Lab 支援 Python `>=3.12,<3.15`；上列版本是本次保存證據時實際執行的環境。

## Architecture

```text
ephemeral LocalIssuer
  ├── in-memory RSA private key ── signs ──> 7 compact JWTs (memory only)
  └── public jwks.json ────────────────────> TokenValidator
                                                 │
                      ┌──────────────────────────┼─────────────────────────┐
                      v                          v                         v
             header / key checks        registered claims         policy inputs
             alg, typ, kid, JWKS         iss, aud, exp, sig        client, scope, team
                      │                          │                         │
                      └──────────────────────────┼─────────────────────────┘
                                                 v
                                      ALLOW or stable DENY code
                                                 │
                                                 v
                       manifest + events + decoded synthetic claims
```

Day 9 在同一個 Lab 上增加另一條離線路徑：

```text
Delegation Context v0.1
  ├── actor_chain
  │     ├── human / service identity slots
  │     ├── ordered agents[]: DELEGATING → EXECUTING
  │     └── workload identity slot
  ├── credential: issuer / subject / client / audiences / fingerprint
  ├── target: resource / action
  └── correlation: event_id / trace_id / timestamp / flow_kind
              │
              ├── JSON Schema Draft 2020-12
              └── semantic checks: sequence / roles / flow identity states
                              │
                              v
                  ACCEPT or stable REJECT code
```

Day 10 把兩條路徑接在一起：

```text
值班工程師的 token (aud=Agent entry)
  ├── Agent entry ── ALLOW
  └── passthrough to Observability MCP
        ├── strict own-audience validation ── DENY / AUDIENCE_MISMATCH
        └── shared entry audience ─────────── ALLOW / COLLAPSED_TO_TOKEN_SUBJECT

runtime token (aud=Observability MCP, sub=Investigator runtime)
  + Delegation Context bound to fingerprint, claims, target, action
        └── Observability MCP ─────────────── ALLOW / FULL_CHAIN
```

Day 11 再回答 downstream token 從哪裡來：

```text
值班工程師 + public CLI
  └── Authorization Code + PKCE ──> sub=user/sre-oncaller, aud=entry

Scheduler confidential client
  └── Client Credentials ─────────> sub=client/sre-scheduler, aud=tool

值班工程師的 entry token + authenticated Runtime
  └── RFC 8693 Token Exchange ────> sub=user/sre-oncaller, act=runtime, aud=tool
```

Day 12 把兩條 flow 映射到 Cognito provider contract：

```text
Human public client + PKCE
  └── access token: aud + sub + client_id + custom scope

M2M confidential client + Client Credentials
  └── access token: client_id + custom scope (no resource-bound aud)

兩者 ──> agentgateway common JWT validation
              └── conditional CEL policy ──> Observability MCP
```

## Locked design decisions

### 1. 不啟動 HTTP IdP

Issuer 每次執行時建立 2048-bit RSA key pair，private key 只存在記憶體；公開 key 以標準 JWKS 寫入 evidence。Validator 直接讀受信任的 JWKS object，不採信 JWT header 裡可能出現的 `jku`／`x5u` URL。

HTTP 只會替這份 JSON 增加傳輸、cache 與 rotation 問題，無助於 Day 8 判讀 issuer／audience／scope。這些 production 問題列入後續整合，不塞進最小 Lab。

### 2. 驗證與授權輸入分兩段

`header`／`key`／`signature`／`claims` 階段確認 Token 可以被信任，`policy` 階段再檢查 OAuth client、scope 與 `team`。事件保留拒絕 stage，避免所有錯誤都只剩 `401 invalid token`。

### 3. 不把 bearer token 寫進 evidence

Compact JWT 只在程序記憶體中交給 validator。Artifact 只保存 issuer 建立 Token 時使用的合成 claims，並清楚標為 `issuer-input-claims`，不把「decode 看得到」誤寫成「已驗證」。測試會掃描整個 run directory，確認沒有 compact JWT 或 PEM private key。

### 4. 固定演算法與受控 `kid`

Validator 只允許 `RS256`，JWK 必須是 `RSA`、`use=sig`、`alg=RS256` 且至少 2048 bits。`kid` 只能使用短的英數、點、底線與連字號；同一個 `kid` 找不到或匹配多把 key 都拒絕。

## Commands

從 repo root 執行：

```bash
make lab-02-up
make lab-02-check
make lab-02-demo
make lab-02-delegation
make lab-02-passthrough
make lab-02-oauth
make lab-02-cognito
make lab-02-cognito-config-check
make lab-02-down
```

要取得 machine-readable summary：

```bash
uv run --directory labs/02-identity-boundary \
  identity-boundary run --output json
```

## 2026-08-19 執行結果

| Case | 預期 | 實際 | Decision code | 失敗階段 |
| --- | --- | --- | --- | --- |
| `valid_access` | ALLOW | ALLOW | `ALLOW` | `complete` |
| `wrong_issuer` | DENY | DENY | `ISSUER_MISMATCH` | `claims` |
| `wrong_audience` | DENY | DENY | `AUDIENCE_MISMATCH` | `claims` |
| `expired_access` | DENY | DENY | `TOKEN_EXPIRED` | `claims` |
| `missing_scope` | DENY | DENY | `SCOPE_MISSING` | `policy` |
| `access_missing_team` | DENY | DENY | `CLAIM_MISSING` | `policy` |
| `id_token_has_team` | DENY | DENY | `TOKEN_TYPE_INVALID` | `header` |

Day 8 slice 完成時為 24 passed，branch coverage 87.07%，並已包含錯 client、未知 signing key、非 allowlist 演算法、危險 `kid`、過大 Token、弱 RSA key、marker symlink 與 cleanup ownership 的回歸測試。Lab 後續承接 Day 9–12，目前完整測試為 72 passed，branch coverage 91.17%。

## Day 9 Delegation Context 執行結果

| Case | 預期 | 實際 | Decision code | 階段 |
| --- | --- | --- | --- | --- |
| `human_delegated` | ACCEPT | ACCEPT | `ACCEPT` | `complete` |
| `scheduled_service` | ACCEPT | ACCEPT | `ACCEPT` | `complete` |
| `a2a_unknown_workload` | ACCEPT | ACCEPT | `ACCEPT` | `complete` |
| `missing_workload_slot` | REJECT | REJECT | `REQUIRED_FIELD_MISSING` | `schema` |
| `human_null` | REJECT | REJECT | `NULL_NOT_ALLOWED` | `schema` |
| `duplicate_agent_sequence` | REJECT | REJECT | `AGENT_SEQUENCE_INVALID` | `semantics` |
| `actor_only` | REJECT | REJECT | `REQUIRED_FIELD_MISSING` | `schema` |

Day 9 slice 完成時，完整 Lab 為 37 passed，branch coverage 89.86%。該 slice 額外測試 schema package data、opaque subject、W3C trace ID、explicit identity states、Agent order／role、safe evidence、CLI 與 raw credential 欄位拒絕。

Human delegated 與純 A2A case 沒有獨立 Service actor，因此 `service` slot 為 `NOT_APPLICABLE`。Public OAuth `client_id` 留在 credential context；只有通過 client authentication 的 M2M flow 才把 Service principal 寫進 `service`。

## Day 10 Token Passthrough 執行結果

| Case | Decision | Decision code | Attribution |
| --- | --- | --- | --- |
| `user_to_entry_resource` | ALLOW | `ALLOW` | `TOKEN_SUBJECT_AT_ENTRY` |
| `passthrough_to_tool_strict` | DENY | `AUDIENCE_MISMATCH` | `NOT_EVALUATED` |
| `passthrough_shared_audience` | ALLOW | `ALLOW` | `COLLAPSED_TO_TOKEN_SUBJECT` |
| `audience_bound_downstream` | ALLOW | `ALLOW` | `FULL_CHAIN` |
| `downstream_token_replay_entry` | DENY | `AUDIENCE_MISMATCH` | `NOT_EVALUATED` |
| `missing_delegation_context` | DENY | `DELEGATION_CONTEXT_REQUIRED` | `NOT_EVALUATED` |
| `mismatched_delegation_context` | DENY | `DELEGATION_CONTEXT_MISMATCH` | `NOT_EVALUATED` |

完整 Lab 目前為 46 passed，branch coverage 91.33%。前三個 case 使用同一枚值班工程師的 Token；Artifact 只保留 SHA-256 fingerprint，不保存 compact JWT。

## Day 11 OAuth Flow 執行結果

| Case | Flow | Decision | Decision code | Principal |
| --- | --- | --- | --- | --- |
| `pkce_human_success` | PKCE | ISSUE | `TOKEN_ISSUED` | `user/sre-oncaller` |
| `pkce_callback_mismatch` | PKCE | DENY | `REDIRECT_URI_MISMATCH` | `NOT_ISSUED` |
| `pkce_invalid_scope` | PKCE | DENY | `INVALID_SCOPE` | `NOT_ISSUED` |
| `pkce_unregistered_client` | PKCE | DENY | `CLIENT_NOT_REGISTERED` | `NOT_ISSUED` |
| `client_credentials_success` | Client Credentials | ISSUE | `TOKEN_ISSUED` | `client/sre-scheduler` |
| `client_credentials_public_client` | Client Credentials | DENY | `UNAUTHORIZED_CLIENT` | `NOT_ISSUED` |
| `token_exchange_success` | Token Exchange | ISSUE | `TOKEN_ISSUED` | `user/sre-oncaller via client/runtime` |
| `token_exchange_invalid_target` | Token Exchange | DENY | `INVALID_TARGET` | `NOT_ISSUED` |
| `token_exchange_wrong_subject_audience` | Token Exchange | DENY | `SUBJECT_TOKEN_INVALID` | `NOT_ISSUED` |

完整 Lab 現為 62 passed，branch coverage 91.21%。Authorization code、PKCE verifier、client credential、compact JWT 與 private key 都不寫入 Artifact。

## Day 12 Cognito Dual Path 執行結果

| Case | Path | Decision | Decision code | Principal／stage |
| --- | --- | --- | --- | --- |
| `human_pkce_success` | Human | ALLOW | `POLICY_ALLOWED` | `user/sre-oncaller` |
| `human_callback_mismatch` | Human | DENY | `REDIRECT_URI_MISMATCH` | authorization |
| `human_scope_invalid` | Human | DENY | `INVALID_SCOPE` | authorization |
| `human_missing_policy_claim` | Human | DENY | `CLAIM_MISSING` | policy |
| `m2m_client_credentials_success` | M2M | ALLOW | `POLICY_ALLOWED` | `client/sre-scheduler` |
| `m2m_public_client` | M2M | DENY | `UNAUTHORIZED_CLIENT` | client authentication |
| `m2m_wrong_secret` | M2M | DENY | `INVALID_CLIENT` | client authentication |
| `m2m_openid_scope` | M2M | DENY | `INVALID_SCOPE` | token |
| `m2m_resource_binding` | M2M | DENY | `RESOURCE_BINDING_UNSUPPORTED` | token |

完整 Lab 現為 72 passed，branch coverage 91.17%。M2M fixture 不合成 resource-bound `aud`，audit Human 為 `NOT_APPLICABLE`，machine actor 由 verified `client_id` 取得。Terraform `validate` 與 agentgateway v1.4.1 `--validate-only` 另外通過；兩者都沒有被標成 live AWS／Cognito integration PASS。

## Expected terminal output

```text
CASE                     EXPECTED   ACTUAL     CODE
--------------------------------------------------------------------------
valid_access             ALLOW      ALLOW      ALLOW
wrong_issuer             DENY       DENY       ISSUER_MISMATCH
wrong_audience           DENY       DENY       AUDIENCE_MISMATCH
expired_access           DENY       DENY       TOKEN_EXPIRED
missing_scope            DENY       DENY       SCOPE_MISSING
access_missing_team      DENY       DENY       CLAIM_MISSING
id_token_has_team        DENY       DENY       TOKEN_TYPE_INVALID

7/7 cases matched
Evidence: .../labs/02-identity-boundary/artifacts/<run-id>
Encoded JWT persisted: no
Private key persisted: no
```

Day 9：

```text
CASE                         EXPECTED   ACTUAL     CODE
----------------------------------------------------------------------------------
human_delegated              ACCEPT     ACCEPT     ACCEPT
scheduled_service            ACCEPT     ACCEPT     ACCEPT
a2a_unknown_workload         ACCEPT     ACCEPT     ACCEPT
missing_workload_slot        REJECT     REJECT     REQUIRED_FIELD_MISSING
human_null                   REJECT     REJECT     NULL_NOT_ALLOWED
duplicate_agent_sequence     REJECT     REJECT     AGENT_SEQUENCE_INVALID
actor_only                   REJECT     REJECT     REQUIRED_FIELD_MISSING

7/7 cases matched
Raw credential persisted: no
```

Day 10：

```text
CASE                               DECISION   CODE                           ATTRIBUTION
----------------------------------------------------------------------------------------------------------------
user_to_entry_resource             ALLOW      ALLOW                          TOKEN_SUBJECT_AT_ENTRY
passthrough_to_tool_strict         DENY       AUDIENCE_MISMATCH              NOT_EVALUATED
passthrough_shared_audience        ALLOW      ALLOW                          COLLAPSED_TO_TOKEN_SUBJECT
audience_bound_downstream          ALLOW      ALLOW                          FULL_CHAIN
downstream_token_replay_entry      DENY       AUDIENCE_MISMATCH              NOT_EVALUATED
missing_delegation_context         DENY       DELEGATION_CONTEXT_REQUIRED    NOT_EVALUATED
mismatched_delegation_context      DENY       DELEGATION_CONTEXT_MISMATCH    NOT_EVALUATED

7/7 cases matched
Same Human token reused across passthrough hops: yes (fingerprint only)
Raw credential persisted: no
```

Day 11：

```text
pkce_human_success                        PKCE                 ISSUE  TOKEN_ISSUED
client_credentials_success                CLIENT_CREDENTIALS   ISSUE  TOKEN_ISSUED
token_exchange_success                    TOKEN_EXCHANGE       ISSUE  TOKEN_ISSUED
pkce_callback_mismatch                    PKCE                 DENY   REDIRECT_URI_MISMATCH
pkce_invalid_scope                        PKCE                 DENY   INVALID_SCOPE
pkce_unregistered_client                  PKCE                 DENY   CLIENT_NOT_REGISTERED

9/9 cases matched
Authorization code persisted: no
PKCE verifier persisted: no
Client secret persisted: no
Raw credential persisted: no
```

## Evidence

每次 run 使用獨立目錄：

```text
artifacts/<run-id>/manifest.json
artifacts/<run-id>/summary.json
artifacts/<run-id>/events.jsonl
artifacts/<run-id>/jwks.json
artifacts/<run-id>/tokens/decoded/<case>.json
artifacts/<run-id>/expected/<case>.json
```

`manifest.json` 保存 Python／PyJWT 版本、fixture SHA-256 與是否落盤 Token／private key。`events.jsonl` 只保存 case、ALLOW／DENY、decision code 與 stage，不保存 claims。

Day 9 run 另外保存：

```text
artifacts/<day09-run-id>/manifest.json
artifacts/<day09-run-id>/summary.json
artifacts/<day09-run-id>/events.jsonl
artifacts/<day09-run-id>/schemas/delegation-context-v0.1.schema.json
artifacts/<day09-run-id>/contexts/<case>.json
artifacts/<day09-run-id>/expected/<case>.json
```

Credential 只保存 issuer、subject、client、audiences 與 SHA-256 fingerprint。Schema 使用封閉物件，`access_token` 等未宣告欄位會被拒絕。

Day 10 run 另外保存：

```text
artifacts/<day10-run-id>/manifest.json
artifacts/<day10-run-id>/summary.json
artifacts/<day10-run-id>/events.jsonl
artifacts/<day10-run-id>/token-fingerprints.json
artifacts/<day10-run-id>/tokens/issuer-input/{user-access,downstream-access}.json
artifacts/<day10-run-id>/contexts/{audience-bound-downstream,mismatched-fingerprint}.json
```

Denied Token 只留下 fingerprint 與 rejection code，不把 unverified claim 當成 authenticated principal。ALLOW event 才會保存 validator 已確認的 subject／client；完整 actor chain 另從已通過 schema 與 request binding 的 Context 取得。

Day 11 run 另外保存：

```text
artifacts/<day11-run-id>/registrations.json
artifacts/<day11-run-id>/credential-fingerprints.json
artifacts/<day11-run-id>/tokens/issuer-input/human-entry.json
artifacts/<day11-run-id>/tokens/issuer-output/{pkce,client-credentials,token-exchange}.json
```

Registration snapshot 只保存 client type、redirect URI、grant、scope、resource 與是否已配置 client authentication；不保存 raw 或 derived client credential。Authorization code 與 PKCE verifier 完全不落盤。

## Day 12 planned slice

| Day | Slice | 正向證據 | 負向證據 |
| ---: | --- | --- | --- |
| 12 | Cognito path | 去識別化 Human／M2M config 與 Gateway validation | client type、scope 或 access-token claim 不符時失敗 |

## Synthetic identities shared by later slices

| Slot | Synthetic value |
| --- | --- |
| Human | `user/sre-oncaller` |
| Service | `client/sre-scheduler` |
| Agent | `agent/sre-investigator@v1` |
| Workload | `k8s://lab/identity-boundary/sa/sre-agent` |
| Resource | `mcp://lab/observability/query` |

沒有 Human 的排程任務寫 `NOT_APPLICABLE`；理應存在但尚未取得的 workload identity 寫 `UNKNOWN`。兩者不能都塞成 `null`。

## Cleanup

`make lab-02-down` 只會刪除 `labs/02-identity-boundary/artifacts/`。目錄必須位於正確 Lab root、不是 symlink，並帶有內容完全匹配的 `.lab-02-artifacts` marker；否則拒絕刪除。

## Troubleshooting

1. `TOKEN_TYPE_INVALID`：確認送到 API 的是 access token，不是因為 claim 較豐富就誤用 ID token。
2. `AUDIENCE_MISMATCH`：確認 Token 綁定的是目前 resource；不要關閉 audience validation 來讓兩個 backend 共用同一枚 User token。
3. `CLAIM_MISSING`：登入與簽章可能都成功；先確認 policy 依賴的 claim 是否真的進入 access token，再決定調整 Token customization 或 policy input。
4. Artifact cleanup 被拒絕：不要手動偽造 marker 或用 symlink 繞過。確認路徑後移走自己的檔案，再由 Lab 建立新的 `artifacts/`。
5. `NULL_NOT_ALLOWED`：用 `UNKNOWN` 或 `NOT_APPLICABLE`，並寫出 reason；不要讓 consumer 猜 null 的意思。
6. `AGENT_SEQUENCE_INVALID`：Agent sequence 必須從 0 連續遞增。只有最後一個 Agent 能標 `EXECUTING`。
7. `DELEGATION_CONTEXT_REQUIRED`：Token 可能正確，但下游 policy 要求保留 Human delegation；補 Context，不要退回 Human Token passthrough。
8. `DELEGATION_CONTEXT_MISMATCH`：檢查 fingerprint、issuer、subject、client、audiences、target 與 action 是否屬於同一筆 Request；不要只關掉 binding check。
9. `REDIRECT_URI_MISMATCH`：把 scheme、host、port、path 逐字比對 registration；`localhost` 與 `127.0.0.1` 要分開列。
10. `CLIENT_NOT_REGISTERED`：確認 pre-registration、CIMD capability 或 legacy DCR fallback；不要把 registration failure 誤判成 PKCE failure。
11. `SUBJECT_TOKEN_INVALID`：先確認 subject token 的 audience 是目前 middle tier，再看 scope／expiry；不要拿任意可驗簽 Token 做 exchange。
