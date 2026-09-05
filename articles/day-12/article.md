# Day 12｜Cognito 雙路徑實戰：同一個 Issuer，拆開 Human 與 M2M

同一個 Observability MCP 有兩種呼叫者。值班工程師從 CLI 登入後查詢資料，Scheduler 則在沒有人操作時定時執行。兩邊拿到的 access token 都由同一個 Cognito user pool 簽發，我一開始便把它們當成同一套 JWT 驗證規則下的兩種用法。

真正把兩枚 Token 攤開後，差異正好落在 Gateway 最不能含糊的欄位：

```text
Human  access token: aud + sub + client_id + scope
M2M    access token:       client_id + scope
```

Human 走 Authorization Code + PKCE，可以用 resource binding 把目標 API 寫進 `aud`。Cognito 的 Client Credentials 不支援同一套 resource binding。如果 Gateway 要求每枚 Token 都帶指定的 `aud` 與 `sub`，合法的 M2M Token 會被擋掉。反過來，若把 `aud` 全面改成 optional，Human Token 又會失去 resource boundary。

Day 11 比較的三種 OAuth flow 中，Cognito 可以直接接住 Human 與 M2M，公開 token endpoint 沒有列出 RFC 8693 Token Exchange。這一篇先把前兩條路落地，Runtime delegation 的缺口繼續留在平台設計裡。公開 Lab 會用九組 case 檢查 app client、callback、scope、audience 與 policy 分流，看看同一個 issuer 到底能共用到什麼程度。

## 先拆 App Client，再談 Gateway

<img src="https://raw.githubusercontent.com/MikeHsu0618/2026-ithelp-agent-governance-public/day-13/assets/third-party/aws/amazon-cognito-architecture-icon.png" alt="Amazon Cognito 官方 AWS Architecture Icon" width="96">

Day 6 已交代 Keycloak 與 Cognito 的選型過程。Keycloak 的 federated login、role claim、Gateway 與 MCP RBAC 都曾在 Kubernetes 跑通。最後改用 Cognito，考量的是組織既有身分生命週期、跨團隊 ownership 與維運人力，而不是 Keycloak 接不起來。

換成 Cognito 之後，app client 仍得按互動方式與 credential lifecycle 分類。若只用「這是 Agent client」命名，過幾個月後通常已看不出它代表登入者、Scheduler，還是某個 Agent runtime。

| | Human CLI | Scheduler M2M |
| --- | --- | --- |
| App client | Public | Confidential |
| Grant | Authorization Code | Client Credentials |
| Durable secret | 不應存在 | 必須存在並輪替 |
| PKCE | S256 | 不適用 |
| Callback | Exact allowlist | 不適用 |
| Token principal | 登入的 Human | App client／workload |

[Cognito app-client 文件](https://docs.aws.amazon.com/cognito/latest/developerguide/user-pool-settings-client-apps.html)把 public client 定義為沒有 client secret，confidential client 則有 secret。Client Credentials 只能用有 secret 的 app client，而且不能和 Authorization Code／Implicit grant 放在同一個 app client。這兩條路從 Cognito registration 開始就是兩份設定，不能等 Token 到了 Gateway 才猜它原本是哪一種 caller。

## Human 路徑使用 PKCE 與 Resource Binding

Human CLI 使用沒有 durable secret 的 public app client：

```text
generate_secret = false
allowed_oauth_flows = ["code"]
callback = http://127.0.0.1:8765/callback
scope = openid + platform/observability.query
```

Public client 無法安全保存長期 secret。每次登入時，Client 先建立一次性的 `code_verifier`，送出 S256 `code_challenge`，收到 authorization code 後再用原 verifier 兌換 Token。[Cognito PKCE 文件](https://docs.aws.amazon.com/cognito/latest/developerguide/using-pkce-in-authorization-code.html)要求 Authorization Code grant 使用 S256。

Callback 是我串接不同 MCP client 時最常回頭檢查的設定之一。公開 Lab 登錄 `http://127.0.0.1:8765/callback`，負向案例把 port 改成 `9999`，即使 host 與 path 都沒變，仍會得到 `REDIRECT_URI_MISMATCH`。實際整合還遇過 `localhost` 與 `127.0.0.1` 不一致，以及 client scope allowlist 沒跟 registration 一起更新。看起來只差一小段字串，Authorization Server 看到的就是另一個 redirect URI。

Human authorization request 另外帶入目標 resource：

```text
resource=https://observability.lab.example/mcp
```

Cognito 會把這個 URL 寫進 access-token `aud`。下游除了驗 user pool，也能確認 Token 是不是發給自己的。[AWS Resource Binding 文件](https://docs.aws.amazon.com/cognito/latest/developerguide/cognito-user-pools-define-resource-servers.html#cognito-user-pools-resource-binding)將這項能力限制在 managed login 的 Authorization Code／Implicit user flow，SDK authentication model 不適用。

公開 Lab 產生的 Human claims 如下：

```json
{
  "iss": "https://cognito-idp.ap-northeast-1.amazonaws.com/ap-northeast-1_LabPool",
  "aud": "https://observability.lab.example/mcp",
  "sub": "user/sre-oncaller",
  "client_id": "sre-console",
  "scope": "platform/observability.query",
  "team": "platform",
  "token_use": "access"
}
```

從通用 JWT profile 切到 Cognito 時，還有一個容易漏掉的 header 差異。Cognito 官方 access-token 範例只有 `kid` 與 `alg`，不保證 `typ=at+jwt`。公開 validator 因此接受 Cognito 的 Token shape，再用 `token_use=access` 阻擋 ID Token 混入 API 路徑，而不是為了沿用舊 profile 自行補造 `typ`。[Cognito access-token claim 文件](https://docs.aws.amazon.com/cognito/latest/developerguide/amazon-cognito-user-pools-using-the-access-token.html)

## M2M 路徑使用 Client ID 與 Custom Scope

Scheduler 沒有瀏覽器、callback 或 Human consent，它使用另一個 confidential app client：

```text
generate_secret = true
allowed_oauth_flows = ["client_credentials"]
scope = platform/observability.query
```

Cognito Client Credentials 只回 access token，不回 ID token 或 refresh token。它能要求的也只有 resource server 定義的 custom scopes。[Cognito token endpoint](https://docs.aws.amazon.com/cognito/latest/developerguide/token-endpoint.html)與 [M2M 文件](https://docs.aws.amazon.com/cognito/latest/developerguide/cognito-user-pools-define-resource-servers.html#cognito-user-pools-define-resource-servers-m2m)都把這項限制寫在 flow contract 裡。

公開 Lab 的 M2M claims 維持最小集合：

```json
{
  "iss": "https://cognito-idp.ap-northeast-1.amazonaws.com/ap-northeast-1_LabPool",
  "client_id": "sre-scheduler",
  "scope": "platform/observability.query",
  "token_use": "access"
}
```

這條路徑沒有登入者，所以 Audit 的 Human 欄位記成 `NOT_APPLICABLE`，machine actor 則由驗證後的 `client_id` 記成 `client/sre-scheduler`。Policy 不依賴某個 provider 版本是否另帶 `sub` 類欄位。即使 Token 裡日後出現同名欄位，也不能直接把 machine subject 當成人類身分。

M2M 還多出一份必須長期管理的 client secret。Cognito app client 可以同時保留兩把 secret，輪替流程便能先發新 secret、更新 workload，確認舊版已沒有流量後再撤掉舊 secret。只把 secret 放進 Kubernetes Secret 還不夠。如果它曾被寫進 image、Git、terminal history 或權限過寬的 Terraform state，外層換了儲存物件也補不回已經洩漏的 credential。

## Resource Binding 迫使 Policy 分成兩份

AWS 對 resource binding 的限制很直接：user flow 可以要求 API-specific `aud`，Client Credentials M2M 不行。因此下面這個 M2M request 在 Lab 會得到穩定的 `RESOURCE_BINDING_UNSUPPORTED`。這是 Lab decision code，不是冒充 AWS endpoint 的原始 error string。

```text
grant_type=client_credentials
scope=platform/observability.query
resource=https://observability.lab.example/mcp
```

如果 Gateway 把 `aud == Observability MCP` 寫成所有 Cognito Token 的共同條件，M2M 會在 authentication layer 被拒絕。這份 Lab 採用的 contract 是：

```text
共同層：signature + iss + exp + token_use

Human：client_id + aud + sub + scope
M2M：  client_id + scope，預期沒有 aud，Human 不適用
```

下圖把兩種 app client、Token shape 與 Gateway policy 放在同一張圖裡。閱讀重點是中間那條 issuer boundary：JWKS 與 issuer trust 可以共用，兩側的 authorization input 仍然不同。

![同一個 Cognito issuer 下的 Human 與 M2M 雙路徑。Human 使用 public app client、PKCE 與 resource-bound audience，M2M 使用 confidential app client、custom scope 與 verified client_id，兩者在單一 agentgateway 以 conditional policy 分流。](https://raw.githubusercontent.com/MikeHsu0618/2026-ithelp-agent-governance-public/day-13/assets/diagrams/day-12/cognito-dual-path.png)

AWS 保證的是 Client Credentials 不能要求 resource binding，不是「任何客製過的 M2M Token 永遠不會出現 `aud`」。本篇 registration 沒有使用 pre-token trigger 改寫 `aud`，所以 Gateway 明確拒絕帶有意外 audience 的 M2M Token。若平台日後自行加入 `aud`，Token contract、Gateway policy 與回歸測試也要一起修改，不能只改 IdP。

## agentgateway 如何同時接住兩種 Token

最直覺、也最容易誤擋 M2M 的寫法，是把 `aud` 放進共同的 `jwtValidationOptions.requiredClaims`。公開設定改成只在共同層要求 `exp` 與 `iss`，再由 CEL 按 verified `client_id` 套用 Human 或 M2M 規則。

`requiredClaims` 只接受 registered claims，Cognito 用來區分 Access Token 與 ID Token 的 `token_use` 得留在 CEL。兩條規則都先檢查 `token_use == "access"`，接著才判斷各自的 client、audience 與 scope。否則 Human 路徑雖然擋住了 ID Token，M2M 路徑卻可能忘了補同一條限制。

```yaml
mcpAuthorization:
  rules:
    - >-
      jwt.token_use == "access" &&
      jwt.client_id == "sre-console" &&
      has(jwt.sub) &&
      jwt.aud == "https://observability.lab.example/mcp" &&
      jwt.scope.split(" ").exists(s, s == "platform/observability.query")
    - >-
      jwt.token_use == "access" &&
      jwt.client_id == "sre-scheduler" &&
      !has(jwt.aud) &&
      jwt.scope.split(" ").exists(s, s == "platform/observability.query")
```

這裡有個需要按版本閱讀的細節。agentgateway v1.4.1 使用 `jsonwebtoken` 驗 JWT。當 `mcpAuthentication.audiences` 已設定，但 `aud` 沒列入 `requiredClaims` 時，Token 有 `aud` 就會比對值，Token 沒有 `aud` 則不會只因缺欄位失敗。[agentgateway v1.4.1 的 JWT 實作](https://github.com/agentgateway/agentgateway/blob/v1.4.1/crates/agentgateway/src/http/jwt.rs)與 [jsonwebtoken v10.4.0 validation](https://github.com/Keats/jsonwebtoken/blob/v10.4.0/src/validation.rs)都能對回這個行為。本篇另留了一個 regression test，避免之後有人把 `aud` 誤加回共同必填欄位。

Scope 在 Cognito access token 裡是 space-delimited string，CEL 要檢查 membership，不能把整串 scope 拿來比 equality。`requiredClaims` 也只支援 RFC registered claims。自訂 claim 列在裡面會被忽略並留下 warning，值的判斷應放在 authorization policy。[agentgateway MCP authentication](https://agentgateway.dev/docs/standalone/latest/configuration/security/mcp-authn/)與 [MCP authorization](https://agentgateway.dev/docs/standalone/latest/configuration/security/mcp-authz/)將兩層責任分開。

九組 Offline Lab 另外保留了 `team` 缺失的 `CLAIM_MISSING` case，用來示範「Token 驗過，policy input 仍可能不夠」。公開 agentgateway YAML 沒有檢查 `team`，因為 Terraform 範例也沒有配置 pre-token Lambda。這個 case 不算成已完成的 Cognito claim customization。

完整設定在 [agentgateway-cognito.yaml](https://github.com/MikeHsu0618/2026-ithelp-agent-governance-public/blob/day-13/labs/02-identity-boundary/configs/agentgateway-cognito.yaml)。Pinned image 實際載入 committed JWKS、YAML 與 CEL 後得到：

```text
agentgateway v1.4.1
Configuration is valid!
```

這份設定使用 Resource Server Only mode，只讓 agentgateway 驗外部 Authorization Server 發出的 Token。agentgateway v1.4.1 的 tested-provider 清單沒有 Cognito，所以 `Configuration is valid!` 只能證明設定可解析，不能改寫成「Cognito integration PASS」。Discovery 與 client registration 也還沒有因為 YAML 通過就自動完成。

## Terraform 固定兩份 Registration

Human 與 M2M 在 Terraform 裡是兩個獨立 resource，grant、secret 與 scope 不會混在一起：

```hcl
resource "aws_cognito_user_pool_client" "human" {
  generate_secret      = false
  allowed_oauth_flows  = ["code"]
  allowed_oauth_scopes = ["openid", local.query_scope]
  callback_urls        = var.human_callback_urls
}

resource "aws_cognito_user_pool_client" "m2m" {
  generate_secret      = true
  allowed_oauth_flows  = ["client_credentials"]
  allowed_oauth_scopes = [local.query_scope]
}
```

完整範例還包含 user pool、managed-login domain、resource server、custom scope、token lifetime 與 outputs，放在 [cognito-terraform](https://github.com/MikeHsu0618/2026-ithelp-agent-governance-public/tree/day-13/labs/02-identity-boundary/configs/cognito-terraform/)。本次執行範圍如下：

```text
Terraform 1.8.2
hashicorp/aws 6.61.0
terraform validate: PASS
AWS apply: NOT PERFORMED
```

`terraform validate` 證明 HCL 與 provider schema 能對上，無法驗證 domain 是否唯一、AWS 權限、上游 federation 或 managed login。`generate_secret=true` 也會讓 M2M secret 進入 Terraform state。真正 apply 前要先處理 remote-state encryption 與 access policy，範例沒有把 secret 做成 output。

## Lab 結果：兩次 ALLOW、七次 DENY

下圖是 `make lab-02-cognito` 的實際輸出。兩條成功路徑之外，另外七個 case 分別卡在 authorization、client authentication、token 與 policy stage，排錯時不會只剩一句含糊的「Cognito 401」。

![Day 12 Cognito 雙路徑 Lab 的實際 CLI 結果。Human 與 M2M 各有一條成功 path，callback、scope、policy claim、public client、client secret 與 M2M resource binding 錯誤都被分階段拒絕。](https://raw.githubusercontent.com/MikeHsu0618/2026-ithelp-agent-governance-public/day-13/assets/screenshots/day-12/01-cognito-dual-path-results.png)

| Case | Path | Decision | Code | Stage |
| --- | --- | --- | --- | --- |
| `human_pkce_success` | Human | ALLOW | `POLICY_ALLOWED` | gateway policy |
| `human_callback_mismatch` | Human | DENY | `REDIRECT_URI_MISMATCH` | authorization |
| `human_scope_invalid` | Human | DENY | `INVALID_SCOPE` | authorization |
| `human_missing_policy_claim` | Human | DENY | `CLAIM_MISSING` | offline policy |
| `m2m_client_credentials_success` | M2M | ALLOW | `POLICY_ALLOWED` | gateway policy |
| `m2m_public_client` | M2M | DENY | `UNAUTHORIZED_CLIENT` | client authentication |
| `m2m_wrong_secret` | M2M | DENY | `INVALID_CLIENT` | client authentication |
| `m2m_openid_scope` | M2M | DENY | `INVALID_SCOPE` | token |
| `m2m_resource_binding` | M2M | DENY | `RESOURCE_BINDING_UNSUPPORTED` | token |

從 repo root 執行：

```bash
make lab-02-up
make lab-02-check
make lab-02-cognito
make lab-02-cognito-config-check
```

九組結果是 9/9 matched，完整 Lab 共有 75 tests，branch coverage 90.81%，Ruff lint／format clean。Terraform 與 agentgateway config validation 也另外通過。Compact JWT、PKCE verifier、client secret 與 private key 都不落盤，Artifact 只保存合成 claims、safe registration、SHA-256 fingerprint、decision 與 manifest。故障時可以配合 [Human／M2M 雙路徑盤點表](https://github.com/MikeHsu0618/2026-ithelp-agent-governance-public/blob/day-13/articles/day-12/cognito-dual-path-checklist.md)逐層檢查，完整的驗證紀錄則收在 [Day 12 evidence](https://github.com/MikeHsu0618/2026-ithelp-agent-governance-public/blob/day-13/assets/screenshots/day-12/evidence.md)。

公開 Lab 沒有執行 AWS apply、managed-login browser flow、真實 JWKS rotation、上游 IdP federation 或 secret rotation 演練。這些項目需要 disposable AWS environment 才能升級成 integration evidence，不能由 fixture 或 `terraform validate` 代替。

## Token 之前，還有 Discovery 與註冊

到這裡，Human 與 M2M 已能共用 Cognito issuer 和同一個 Gateway，同時保留不同的 app client、audience rule、credential lifecycle 與 audit principal。這解決的是 Token 進入 Gateway 之後的驗證與分流。

MCP client 在帶著 Token 進來以前，仍要找到 Authorization Server 並取得可用的 client registration。Resource Server Only 能發布 protected-resource metadata，卻不會替 Cognito 補上 agentgateway 尚未測試的 provider adapter，也不會自動決定 Human client 要預先註冊、使用 CIMD，或走 legacy DCR。

Day 13 會從這筆 ownership 開始。比較 LiteLLM 與 agentgateway 時，評分重點不只放在流量功能，還要把 discovery、registration、policy 與 audit 到底由誰維護算進 operating model。
