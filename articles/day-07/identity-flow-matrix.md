# Human、Service、Agent、Workload Identity Flow Matrix

這張表用於 Agent／MCP 架構 review。Human、Service、Agent、Workload 是四類責任，不是四個固定欄位。每一類可以依角色、credential hop 或呼叫順序保留多筆資料，但不能在沒有證據時，把同一個 identifier 複製到其他類別。

狀態值只有三種：

- 有值：能指出 identifier 的來源、角色與驗證方式。
- `NOT_APPLICABLE`：這條 flow 本來就沒有該角色，例如純排程工作沒有 Human。
- `UNKNOWN`：該角色理應存在，但目前的 credential、Gateway 或 audit 沒有留下足夠證據。

`UNKNOWN` 不能用 deployment name、email header、Agent 顯示名稱或其他「看起來合理」的值補滿。

## 四種常見 flow

| Review item | Human 使用 MCP Client | Service 排程 Agent | Human 委派 Agent | Agent 呼叫另一個 A2A Agent |
| --- | --- | --- | --- | --- |
| Human | requester 的 federated `sub` | `NOT_APPLICABLE` | requester 與 approver 分開保存 | 依 delegation context 判定，沒有證據時不得猜 |
| Service | public OAuth client context，不能冒充 authenticated Service principal | 通過 client authentication 的 confidential client | interactive client 與 Agent runtime service 依 hop 保存 | 發出 A2A request 的 calling service |
| Agent | 沒有 Agent 參與時為 `NOT_APPLICABLE` | Agent artifact ID + version | 依決策順序保存 Agent chain | caller Agent 與 remote Agent 依順序保存 |
| Workload | 本機 client process，無可驗證 identity 時為 `UNKNOWN` | Kubernetes ServiceAccount 或其他 workload attestation | 執行 Agent 的 runtime workload | caller 與 remote workload 由各自環境驗證 |
| 主要 credential | Authorization Code + PKCE access token | Client Credentials access token | Human access token + runtime credential | HTTP／transport credential，A2A payload 不取代 caller authentication |
| credential 能證明什麼 | IdP 驗證的 Human，以及參與流程的 public client context | 獲准使用該 credential 的 Service | 各 hop 的 caller，不能自動生成完整 actor chain | transport caller，Agent Card 描述 remote Agent 與驗證需求 |
| 主要 decision point | Gateway 驗 Token，MCP／resource 驗 action 與 resource | Gateway 驗 client 與 scope，resource 做最終授權 | Gateway 驗 caller，delegation policy 驗 Human→Agent 關係 | A2A server 驗 transport caller，再按 skill／action 授權 |
| Audit 至少要留 | Human `sub`、client context、resource、action | client、Agent、Workload、resource、action | requester、approver、services、Agent chain、Workload、delegation、action | calling service／workload、caller Agent、remote Agent、task／action |

## Review 時逐類追問

| 責任類別 | 第一個問題 | 可接受的來源 | 常見誤填 |
| --- | --- | --- | --- |
| Human | 誰提出、委派或核准這個目的？ | federated `sub`、明確 approval event | email、display name、固定字串 `sre-oncaller` |
| Service | 每個 credential hop 由哪個 application／service client 參與？ | OAuth client ID + authentication 狀態、service identity | 把 public `client_id` 當 authenticated Service、provider API key owner、team 名稱 |
| Agent | 哪一版決策邏輯提出 action 與 arguments？ | Agent artifact ID／name + version、受控 Agent metadata | Pod name、模型名稱、沒有版本的 UI 顯示名稱 |
| Workload | 哪個程序實際持有 credential 並送出 request？ | bound ServiceAccount token、Pod 關聯、SPIFFE ID 或其他 attestation | deployment label、共用 client secret |

## 每一筆資料還要附上證據強度

同樣是 `client_id`，public client context 與完成 client authentication 的 confidential client，證據強度並不相同。ServiceAccount 名稱也可能被很多 Pods 共用，所以有值不代表已經能定位單次執行。

設計 review 至少要把下列資訊寫在 identifier 旁邊：

- 來源：Token claim、Gateway authentication、Agent artifact、Kubernetes audit 或 approval event。
- 驗證方式：signature、client authentication、bound token、attestation 或僅為 asserted metadata。
- 適用 hop：它在哪一段 request path 生效。
- 角色或順序：requester／approver、calling／remote、Agent chain sequence。

## Policy input 與 Audit 不必完全相同

四類責任都值得保存，不表示每條 policy 都必須吃完所有資料。M2M rate limit 可能只看 authenticated Service，高風險 Tool approval 會看 Human、Agent、Workload 與 resource，resource server 仍應驗自己的 audience 與 action permission。

設計 review 應先寫出完整 responsibility chain，再由每個 decision point 挑出必要欄位。若從現有 JWT 有哪些 claims 反推身分模型，很容易把「現在拿得到」誤當成「治理真正需要知道」。
