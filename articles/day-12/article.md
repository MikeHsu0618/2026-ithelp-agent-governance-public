# Day 12｜AWS Cognito 雙路徑實戰：同一個 Issuer，拆開 Human 與 M2M

同一個 Observability MCP 有兩種呼叫者。值班工程師從 CLI 登入後查資料，Scheduler 則在沒有人操作時定期執行。兩枚 Access Token 都由同一個 Cognito User Pool 簽發，我起初也很自然地把它們放進同一套 JWT 驗證規則。

真正攤開 Claims 後，兩條路徑的差異剛好落在 Gateway 不能含糊的地方。Human Token 有登入者的 `sub`，也能透過 Resource Binding 帶入目標 API 的 `aud`。Client Credentials 取得的 M2M Token 沒有 Human，Cognito 也不支援同一套 Resource Binding。若 Gateway 要求所有 Token 都有指定的 `sub` 與 `aud`，合法的 Scheduler 會被擋掉。若乾脆取消 Audience 檢查，Human 路徑又失去原本的 Resource Boundary。

所以這篇不再重講 Day 11 的 OAuth Flow，而是處理落地後真正需要拆開的東西：App Client、Token Contract、Secret Lifecycle 與 Gateway Policy。Issuer 和 JWKS 可以共用，不代表兩種 Caller 可以共用同一份身分語意。

## 同一個 User Pool，兩個 App Client

<img src="https://raw.githubusercontent.com/MikeHsu0618/2026-ithelp-agent-governance-public/day-13-r1/assets/third-party/aws/amazon-cognito-architecture-icon.png" alt="Amazon Cognito 官方 AWS Architecture Icon" width="96">

Day 6 已經交代過 Keycloak 與 Cognito 的選型。Keycloak 的 Federation、Role Claim 與 Gateway RBAC 都能在 Kubernetes 跑通，我們最後改用 Cognito，是因為當時沒有足夠的組織共識與維運人力去建立平台級 Identity Center。這個決策不代表 Cognito 比 Keycloak 強，而是我們不想為少數服務先背起另一套帳號生命週期。

換成 Cognito 後，App Client 仍要按互動方式與 Credential Lifecycle 分類。只用「Agent Client」當名稱，過幾個月後通常已看不出它代表登入者、Scheduler，還是某個 Runtime。

| 設定 | Human CLI | Scheduler M2M |
| --- | --- | --- |
| App Client | Public | Confidential |
| Grant | Authorization Code | Client Credentials |
| Durable Secret | 不應存在 | 必須保存與輪替 |
| PKCE | S256 | 不適用 |
| Callback | Exact Allowlist | 不適用 |
| Token Principal | 登入的 Human | App Client／Workload |

[Cognito App Client 文件](https://docs.aws.amazon.com/cognito/latest/developerguide/user-pool-settings-client-apps.html) 將沒有 Client Secret 的應用視為 Public Client，有 Secret 的應用視為 Confidential Client。Client Credentials 只能使用 Confidential Client，而且不能和 Authorization Code 或 Implicit Grant 放在同一個 App Client。這不是偏好的命名方式，而是 Cognito Registration 從一開始就要求兩份設定。

## Human Token 保留登入者與目標 Resource

Human CLI 使用沒有 Durable Secret 的 Public App Client，走 Authorization Code + PKCE。Callback 必須精確列入 Allowlist，Scope 也要同時出現在 Resource Server 與 App Client 設定中：

```text
app client: sre-console
secret:     none
grant:      authorization_code
callback:   http://127.0.0.1:8765/callback
scope:      openid platform/observability.query
resource:   https://observability.lab.example/mcp
```

Day 11 已經談過 `localhost` 與 `127.0.0.1` 的 Callback 坑。來到 Cognito 後，新的重點是 `resource`。[AWS Resource Binding 文件](https://docs.aws.amazon.com/cognito/latest/developerguide/cognito-user-pools-define-resource-servers.html#cognito-user-pools-resource-binding) 說明 Managed Login 的 Authorization Code User Flow 可以把 Resource URL 寫入 Access Token 的 `aud`。下游除了驗證 Token 來自哪個 User Pool，也能確認它是不是簽給自己的。

Lab 中的 Human Token 保留以下 Claims：

```json
{
  "iss": "https://cognito-idp.ap-northeast-1.amazonaws.com/ap-northeast-1_LabPool",
  "aud": "https://observability.lab.example/mcp",
  "sub": "user/sre-oncaller",
  "client_id": "sre-console",
  "scope": "platform/observability.query",
  "token_use": "access"
}
```

`sub` 指向登入者，`client_id` 保留入口，`aud` 限制目標服務。Cognito Access Token 不保證 Header 一定有 `typ=at+jwt`，因此驗證時不能為了套用通用 JWT Profile 而自行補造 Provider 沒有承諾的欄位。這條路徑改用 Cognito 的 `token_use=access` 區分 Access Token 與 ID Token，再檢查 Audience、Client 與 Scope。

## M2M Token 代表 Scheduler，不代表某個人

Scheduler 不經過 Browser、Callback 或 Human Consent。它使用另一個 Confidential App Client，以 Client Credentials 取得 App-only Token：

```text
app client: sre-scheduler
secret:     required
grant:      client_credentials
scope:      platform/observability.query
```

[Cognito M2M 文件](https://docs.aws.amazon.com/cognito/latest/developerguide/cognito-user-pools-define-resource-servers.html#cognito-user-pools-define-resource-servers-m2m) 將這條路徑限制在 Resource Server 定義的 Custom Scope。Token Endpoint 只回 Access Token，不回 ID Token 或 Refresh Token。這份 Lab 使用的 Claims 也刻意維持最小集合：

```json
{
  "iss": "https://cognito-idp.ap-northeast-1.amazonaws.com/ap-northeast-1_LabPool",
  "client_id": "sre-scheduler",
  "scope": "platform/observability.query",
  "token_use": "access"
}
```

這裡沒有登入者，Audit 的 Human 欄位應記成 `NOT_APPLICABLE`，Machine Actor 則由驗證過的 `client_id` 映射成 `client/sre-scheduler`。即使未來 Token 多出 `sub`，也不能只憑欄位名稱把 Machine Subject 當成人類身分。

M2M 路徑同時多了一份長期責任：Client Secret 必須保存、輪替與停用。Cognito App Client 可以重疊保留新舊 Secret，讓 Workload 先切換到新值，再撤掉舊值。不過把 Secret 放進 Kubernetes Secret 並不代表問題已經解決。如果它曾進入 Image Layer、Git、Terminal History 或權限過寬的 Terraform State，外面再包一層 Secret Object 也補不回已經外洩的 Credential。

## Gateway 依 Client 分流 Policy

Cognito 對 Resource Binding 的限制讓兩份 Policy 無法再假裝相同。Human User Flow 可以要求 API-specific `aud`，Client Credentials M2M 不支援這個參數。因此共同驗證層只處理兩邊都成立的條件，再依已驗證的 `client_id` 進入不同的 Authorization Rule：

```text
共同條件：signature + iss + exp + token_use=access

Human：client_id + sub + aud + scope
M2M：  client_id + scope，Human 不適用
```

![同一個 Cognito issuer 下的 Human 與 M2M 雙路徑。Human 使用 public app client、PKCE 與 resource-bound audience，M2M 使用 confidential app client、custom scope 與 verified client_id，兩者在單一 agentgateway 以 conditional policy 分流。](https://raw.githubusercontent.com/MikeHsu0618/2026-ithelp-agent-governance-public/day-13-r1/assets/diagrams/day-12/cognito-dual-path.png)

在 agentgateway 設定裡，`aud` 不能放進兩條路徑共同必填的 Claims。兩條 CEL Rule 先確認 `token_use == "access"`，再各自處理 Human 與 M2M：

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

Scope 在 Cognito Access Token 裡是以空白分隔的字串，Policy 要檢查其中是否包含指定值，不能把整串 Scope 做 Equality。`requiredClaims` 與 Authorization Policy 也負責不同事情。前者確認標準 Claim 是否存在，Provider-specific Claim 的值與路徑分流應留在 CEL Rule。

這份範例明確拒絕帶有意外 `aud` 的 M2M Token，因為本篇沒有使用 Pre-token Trigger 改寫它。若平台未來決定替 M2M 加入 Audience，Token Contract、Gateway Policy 與 Regression Test 都要一起更新，不能只改 IdP 後就期待 Gateway 自行理解新語意。

完整 Gateway 設定放在 [agentgateway-cognito.yaml](https://github.com/MikeHsu0618/2026-ithelp-agent-governance-public/blob/day-13-r1/labs/02-identity-boundary/configs/agentgateway-cognito.yaml)。設定驗證只證明 YAML 與 Policy 能被指定版本載入，不代表 Cognito Live Integration 已經完成。真正的 JWKS Rotation、Managed Login 與 Provider Compatibility 仍需要可拋棄的 AWS 環境測試。

## Terraform 只負責固定兩份 Registration

Terraform 範例將 Human 與 M2M 建成兩個獨立 `aws_cognito_user_pool_client`。Human 設定 `generate_secret=false` 與 Authorization Code，M2M 則設定 `generate_secret=true` 與 Client Credentials。完整 HCL 放在 [cognito-terraform](https://github.com/MikeHsu0618/2026-ithelp-agent-governance-public/tree/day-13-r1/labs/02-identity-boundary/configs/cognito-terraform/)，正文不再逐段複製。

本輪只執行 `terraform validate`，沒有對 AWS Apply。這代表 HCL 與 Provider Schema 能對上，不能證明 Domain 唯一性、AWS 權限、Federation 或 Managed Login 已完成。`generate_secret=true` 也會讓 M2M Secret 進入 Terraform State，正式套用以前仍要處理 Remote State Encryption 與存取權限。

## Lab 驗證兩份 Contract 不會互相誤收

[Day 12 Lab](https://github.com/MikeHsu0618/2026-ithelp-agent-governance-public/blob/day-13-r1/labs/02-identity-boundary/README.md) 以九個案例覆蓋兩條成功路徑，以及 Callback、Scope、Client Type、Secret、Resource Binding 與 Policy Input 錯誤。正文只保留幾個真正會改變設計判斷的結果：

| 情境 | 結果 | 它證明的事 |
| --- | --- | --- |
| Human PKCE + Resource Binding | ALLOW | Human Token 能以 `sub`、`aud` 與 Scope 綁定登入者和目標 API |
| M2M Client Credentials | ALLOW | Scheduler 由 `client_id` 表示，不要求 Human Claim |
| Public Client 嘗試 M2M | DENY | 兩種 App Client 不能只靠不同 Grant Name 區分 |
| M2M 要求 Resource Binding | DENY | Human 的 Audience Contract 不能直接套到 M2M |
| 任一路徑缺少必要 Policy Input | DENY | Signature 通過仍不代表 Authorization 資料足夠 |

![Day 12 Cognito 雙路徑 Lab 的實際 CLI 結果。Human 與 M2M 各有一條成功 path，callback、scope、policy claim、public client、client secret 與 M2M resource binding 錯誤都被分階段拒絕。](https://raw.githubusercontent.com/MikeHsu0618/2026-ithelp-agent-governance-public/day-13-r1/assets/screenshots/day-12/01-cognito-dual-path-results.png)

從 Repo Root 可以重跑 Fixture、Gateway 設定與 Terraform 驗證：

```bash
make lab-02-up
make lab-02-check
make lab-02-cognito
make lab-02-cognito-config-check
```

完整九組結果、Safe Registration 與 Decision Event 收在 [Day 12 evidence](https://github.com/MikeHsu0618/2026-ithelp-agent-governance-public/blob/day-13-r1/assets/screenshots/day-12/evidence.md)，排錯時可配合 [Human／M2M 雙路徑盤點表](https://github.com/MikeHsu0618/2026-ithelp-agent-governance-public/blob/day-13-r1/articles/day-12/cognito-dual-path-checklist.md)。這些結果來自 Offline Policy Simulation 與 Config Validation，沒有冒充 AWS Apply、Managed Login、Live Token、JWKS Rotation 或 Secret Rotation 演練。

## Token 驗過之後，還有平台責任要接

做到這裡，Human 與 M2M 已能共用 Cognito Issuer、JWKS 與同一個 Gateway，同時保留不同的 App Client、Audience Rule、Credential Lifecycle 與 Audit Principal。這解決的是 Token 進入 Gateway 後的驗證與分流。

MCP Client 在送出 Token 前，仍要找到 Authorization Server，也要取得可用的 Client Registration。Resource Server Only Mode 不會自動替平台處理 Pre-registration、Client Metadata、Discovery 與 Provider Adapter。這些工作由誰維護，已經不是單一 JWT Rule 能回答的問題。

下一篇會把視角從 Token 拉回平台選型。我們當初從 LiteLLM 轉向 agentgateway，真正改變決定的不是又多了一個 Routing 功能，而是 Kubernetes 交付、Declarative API、Policy、Audit、Discovery 與升級責任開始一起進入 Operating Model。
