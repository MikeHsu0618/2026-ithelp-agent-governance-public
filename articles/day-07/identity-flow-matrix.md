# Human、Service、Agent、Workload Identity Flow Matrix

這張表用於 Agent／MCP 架構 review。Human、Service、Agent、Workload 是四類責任，不是四個固定欄位。同一類可以因為核准流程、credential hop 或多 Agent 協作而出現多次，也可能在某條 flow 裡根本不存在。

Review 時不要為了填滿表格而猜值。每個 identifier 都要能說明來源、驗證方式和適用的 request hop。流程本來沒有某個角色，與架構應該留下證據、實際卻沒記錄，是兩種不同情況。Day 9 再把這個差別放進正式資料結構。

## 三種常見 Flow

| Review item | Human 直接使用 MCP Client | Service 排程 Agent | Human 委派 Agent |
| --- | --- | --- | --- |
| Human | requester 的 federated `sub` | 沒有互動式 Human caller | requester 與 approver 分開記錄 |
| Service | public OAuth client 只作 application context | 通過 client authentication 的 confidential client | interactive client 與 Agent runtime service 依 credential hop 記錄 |
| Agent | 沒有 Agent 參與 | Agent artifact ID + version | 依決策順序記錄 Agent artifact |
| Workload | 本機 client process。沒有可驗證 identity 時，明列證據缺口 | Kubernetes ServiceAccount 或其他 workload evidence | 執行 Agent 的 runtime workload |
| 主要 credential | Authorization Code + PKCE access token | Client Credentials access token | Human access token，加上 runtime 自己取得的下游 credential（若有） |
| credential 能證明什麼 | IdP 驗證的 Human，以及參與流程的 public client context | 通過驗證並獲准使用 scope 的 Service | 各 hop 的 caller，不能自動生成完整責任鏈 |
| 主要 decision point | Gateway 驗 Token，MCP／resource 驗 action 與 resource | Gateway 驗 client 與 scope，resource 做最終授權 | Gateway 驗 caller，delegation policy 處理 Human→Agent 關係 |
| Audit 至少要留 | Human `sub`、client context、resource、action | client、Agent、Workload、resource、action | requester、approver、services、Agent chain、Workload、delegation、action |

## 四類責任的 Review 問題

| 責任類別 | Review 問題 | 可接受的來源 | 常見誤填 |
| --- | --- | --- | --- |
| Human | 誰提出、委派或核准這個目的？ | federated `sub`、明確 approval event | email、display name、固定字串 `sre-oncaller` |
| Service | 每個 credential hop 由哪個 application／service client 參與？ | OAuth client ID 加上 authentication 狀態、service identity | 把 public `client_id` 當 authenticated Service、provider API key owner、team 名稱 |
| Agent | 哪一版決策邏輯提出 action 與 arguments？ | Agent artifact ID／name + version、受控 Agent metadata | Pod name、模型名稱、沒有版本的 UI 顯示名稱 |
| Workload | 哪個程序實際持有 credential 並送出 request？ | bound ServiceAccount token、Pod 關聯或其他 attestation | deployment label、共用 client secret |

## Identifier 旁邊需要保存的證據

同樣是 `client_id`，public client context 與完成 client authentication 的 confidential client，證據強度並不相同。ServiceAccount 名稱也可能被多個 Pods 共用，所以欄位有值，不等於已經能定位單次執行。

設計 review 至少要替每筆 identifier 補上以下資訊：

- 來源：Token claim、Gateway authentication、Agent artifact、Kubernetes audit 或 approval event。
- 驗證方式：signature、client authentication、bound token、attestation 或僅為 asserted metadata。
- 適用 hop：這筆資料在哪一段 request path 生效。
- 角色或順序：requester／approver，以及 Agent chain 的決策順序。

## Policy Input 與 Audit 不需要相同

Audit 保存完整 responsibility chain，讓事後重建知道目的、credential 和執行責任如何轉手。每個 policy decision point 只取會改變當下結果的欄位。

M2M rate limit 可能只使用 authenticated Service，高風險 Tool approval 會看 Human、Agent、Workload 與 resource，resource server 仍然要驗自己的 audience 與 action permission。先畫出完整責任，再替每個 decision point 選資料，比從現有 JWT claims 反推身分模型可靠。
