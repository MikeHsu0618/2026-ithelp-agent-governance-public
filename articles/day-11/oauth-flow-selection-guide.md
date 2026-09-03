# OAuth Flow 選擇與故障判讀表

這份表搭配 `make lab-02-oauth` 使用。它先問 Token 應該代表誰，再決定 grant，不會看到「Agent」就一律選 Client Credentials。

## 先選 principal，再選 flow

| 工作 | 使用者是否在線 | Token 應代表 | Flow | 合成 Token 主欄位 | 不該做的事 |
| --- | --- | --- | --- | --- | --- |
| 值班工程師從 CLI 啟動 Agent | 是 | 值班工程師 | Authorization Code + PKCE | `sub=user/sre-oncaller`、`client_id=sre-console`、`aud=entry` | 把 durable client secret 放進 public CLI |
| Scheduler 定時查詢 | 否 | Scheduler service | Client Credentials | `sub=client/sre-scheduler`、`aud=tool` | 為了補 Audit 而假造 `user/sre-oncaller` |
| Runtime 代表值班工程師呼叫下游 | 上游已取得值班工程師的 Token | 值班工程師 + current runtime actor | RFC 8693 Token Exchange | `sub=user/sre-oncaller`、`act.sub=client/sre-investigator-runtime`、`aud=tool` | 把 entry Token 原樣 passthrough，或改走 app-only 後還說是值班工程師 |

## Registration 不是 grant

截至 MCP `2026-07-28`，client ID 可以依序從 pre-registration、Client ID Metadata Documents（CIMD）、legacy DCR fallback 或手動設定取得。拿到 client ID 之後，才進入 Authorization Code + PKCE。MCP 這個版本引用 CIMD draft-00，本文另外連到目前的 [draft-02](https://datatracker.ietf.org/doc/html/draft-ietf-oauth-client-id-metadata-document-02)。它仍是 Internet-Draft。

Lab 沒有假裝實作 CIMD fetch 或 DCR endpoint。`pkce_unregistered_client` 只驗一個更基礎的 contract：Authorization Server 不認得 client 時，不得繼續簽 code／Token。

## Stable code 對照

| Case | Stage | Code | 先檢查什麼 |
| --- | --- | --- | --- |
| `pkce_callback_mismatch` | `authorization_request` | `REDIRECT_URI_MISMATCH` | scheme、host、port、path 是否與 registration 完全一致，`localhost` 與 `127.0.0.1` 要分開列 |
| `pkce_invalid_scope` | `authorization_request` | `INVALID_SCOPE` | 當次 challenge／metadata 要求的 scope，是否也在該 client allowlist 中 |
| `pkce_unregistered_client` | `registration` | `CLIENT_NOT_REGISTERED` | pre-registration、CIMD capability、legacy DCR fallback 是否真的存在 |
| `client_credentials_public_client` | `client_authentication` | `UNAUTHORIZED_CLIENT` | public client 是否被誤當成能安全保存 credential 的 confidential client |
| `token_exchange_invalid_target` | `token_request` | `INVALID_TARGET` | runtime 是否被允許取得該 downstream resource 的 Token |
| `token_exchange_wrong_subject_audience` | `subject_token` | `SUBJECT_TOKEN_INVALID` | subject token 是否真的發給目前 middle tier，底層 reason 是 `AUDIENCE_MISMATCH` |
| Token Exchange actor-binding unit test | `delegation_policy` | `ACTOR_NOT_AUTHORIZED` | `actor_token.sub` 是否與 authenticated client 一致，且 Human Token 的 `may_act.sub` 是否允許該 actor |

## Token Exchange 的最小 Delegation Contract

這份 Lab 刻意要求 `subject_token` 與 `actor_token` 同時存在。Runtime 的 client authentication 只能證明「誰向 token endpoint 發 request」，不能自動證明 Human 已把 delegation 交給這個 actor。

```text
subject_token.sub       = user/sre-oncaller
subject_token.may_act   = client/sre-investigator-runtime
actor_token.sub         = client/sre-investigator-runtime
authenticated client_id = sre-investigator-runtime
```

四個值對得上，Authorization Server 才能簽出 `sub=user/sre-oncaller`、`act.sub=client/sre-investigator-runtime` 的 downstream Token。只有 `subject_token` 時，RFC 8693 能表達 impersonation，不能把 current actor 當成已驗證的 delegation 結果。

## 查 final evidence

從 repo root：

```bash
jq -c \
  'select(.decision == "DENY") | {case_id, flow, stage, code, reason_code}' \
  assets/screenshots/day-11/evidence/demo-events.jsonl
```

只比較三條成功 flow 的 principal：

```bash
jq -c \
  'select(.decision == "ISSUE") | {case_id, subject, actor, resource, scopes}' \
  assets/screenshots/day-11/evidence/demo-events.jsonl
```

預期會看到：

```text
PKCE               subject=user/sre-oncaller          actor=user/sre-oncaller
Client Credentials subject=client/sre-scheduler actor=client/sre-scheduler
Token Exchange     subject=user/sre-oncaller          actor=client/sre-investigator-runtime
```

## Evidence 邊界

Artifact 只保存 synthetic claims、safe registration metadata、decision event 與 credential fingerprint。Authorization code、PKCE verifier、client credential、compact JWT 與 RSA private key 不落盤。Fingerprint 只服務合成 Lab，production 的跨系統 credential correlation 仍應採 keyed HMAC、短 retention 與受控查詢。
