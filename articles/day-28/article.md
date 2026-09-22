# Day 28｜從既有 LGTM 開始：Agent Governance 的導入順序

[Day 27 的 Capability Ledger](https://github.com/MikeHsu0618/2026-ithelp-agent-governance-public/blob/day-08-r1/articles/day-27/capability-ledger.md) 同時留下 `KEEP`、`ADOPT`、`DEFER` 與 `UNKNOWN`。只看風險，最刺眼的 `UNKNOWN` 好像應該優先處理。照產品架構圖走，又很容易先裝 kagent、Registry 或另一套 Identity Center。這兩種排序都忽略同一件事：誰現在有能力把新增控制接進值班、升級和事故流程？

我手上的現況並不平均。LGTM 是 Production 核心，有人維護，也有既有查詢和告警習慣。Cognito 的 Human／M2M 路徑已經跑通，agentgateway 也有明確的 LLM／MCP／A2A Traffic Boundary。相較之下，企業 Identity Center、跨團隊 Agent Control Plane 與 Catalog 仍缺共同需求或長期 Owner。

導入順序因此不該是一座所有團隊都要爬完的成熟度階梯。這篇改用實際 Trigger 排序：Tool 是否產生副作用、共同 Policy 是否開始漂移、Artifact 是否跨環境流動、團隊是否需要 Self-service、成本是否進入正式分攤，以及證據是否有完整性義務。Trigger 尚未成立時，現有架構可以是正式停留點，不是「還沒做完」。

![Agent Governance 以既有 Identity、Git-owned BYO Runtime 與 LGTM 為基線。Tool 有副作用時先補 Action contract。多個 Runtime 的 LLM、MCP、A2A policy 與 telemetry 開始重複或漂移後，再加入 agentgateway 作為共同 checkpoint。跨團隊 deployment、discovery 或 catalog 需求成立後才評估 kagent 與 Agent Registry。Workload identity 和 tamper-evident Audit 依個別需求開啟。](https://raw.githubusercontent.com/MikeHsu0618/2026-ithelp-agent-governance-public/day-08-r1/assets/diagrams/day-28/adoption-path.png)

## 最小可維運基線

Human 使用者走 Authorization Code／PKCE，M2M 走 Client Credentials。Agent Runtime、Tool Callback 與 Dependency 由應用 Repository 維護，執行過程透過 Alloy 進入 Loki、Tempo 與 Prometheus／Mimir 相容介面。Identity、Git-owned Runtime 與 LGTM 都有既有 Owner，也有前面 Lab 能重跑的 Contract，因此足以構成第一個停留點。

這張圖不是我們 Production Topology 的快照。我們已經遇到跨 Runtime 的共同 Traffic Boundary，所以 agentgateway 也在現行架構裡。圖仍保留前一層，是因為沒有共同 Policy 問題的團隊，不需要為了跟上系列進度照抄 Gateway。

LGTM 先回答 Latency、Error、Tool Outcome 與跨服務 Correlation。Audit Integrity 留在另一項 Capability，沒有被 Grafana Dashboard 自動補完。讀者也可以把 LGTM 換成組織已經有 Owner 的 Telemetry Backend，判斷方式不變。

如果 Agent 仍由單一團隊維護、只讀資料，也沒有共用 MCP／A2A 入口，架構可以停在這裡。前提是 Credential Scope 已受限、Tool Outcome 查得到，而且失敗有人接手。此時增加 Controller 和 CRD，還沒有對應的共享需求。

## Tool 產生副作用後的第一批控制

只要 Tool 開始能寫入、刪除、部署或批准，單純把 Trace 接進 LGTM 就不夠。執行前需要 Resource-aware Policy，執行後則要留下 Action ID、Policy Version、關鍵 Arguments、Effect Receipt，以及當時真正執行的 Commit 或 Artifact Digest。

這批控制不必等集中式平台。只有一個 Runtime 時，ADK Callback、應用自己的 Authorization 與 Git Review 仍能形成清楚的 Enforcement Path。驗收要確認 `DENY` 發生在 Tool 執行前，事故回放也找得到當時 Decision。Day 27 因此先 `ADOPT` Immutable Digest、Promotion Evidence 與 Governance Event Contract，它們比 Catalog UI 更早進入基線。

Tool 若需要人工核准，HITL 也不能只看畫面上有 Approve／Reject。Production 還要驗 Approver Authentication、Authorization、Task／Context Continuity、Decision Receipt 與 Resume Callback。Day 18 只跑通相容的 Pause／Resume Contract，共享 HITL Control Plane 因此仍是 `DEFER`。

## Policy 漂移才是 Gateway Trigger

單一 Runtime 可以在應用裡完成 Policy。兩個 Agents 共用同一個 LLM Provider，也不代表中間一定需要 Gateway。真正的 Trigger 是多個 Runtime 各自重複處理 JWT、Retry、Timeout、Provider Credential、Tool Policy 與 Telemetry，設定開始分岔，事故時又缺少共同 Observation Point。

這時 agentgateway 才有清楚責任：收斂 LLM／MCP／A2A Traffic 的 Authentication、Routing、Policy 與 Telemetry。既有 Ingress 可以繼續處理 TLS、Host Routing 與 Access Log。Tool 的業務合法性、Agent Workflow，以及資料庫裡某筆 Resource 能不能修改，仍由 Runtime 或 Resource Server 決定。

Day 24 的成本也沿用這個 Boundary。Model Catalog 可以把 Token Usage 換成 Request-level Estimate，Validated Caller／Team Mapping 則提供 Showback 維度。正式 Chargeback 再補 Pricing Version、Provider Billing Attribution、Credit／Discount 與 Invoice Reconciliation。失敗 Request 沒有 Usage 時保持 `UNKNOWN`，不能為了報表完整而寫成零。

BYO Agent、Git、單一 Gateway 與 LGTM 若已能穩定交付，架構可以停在這裡。Gateway 上線後，不會自動產生下一張 kagent 或 Registry 採用單。

## 不必綁成同一包的平台能力

企業 Identity Center、Artifact Trust、Deployment Control Plane、Workload Identity 與 Audit Storage 各有自己的 Trigger，不該因為「要做 Agent Platform」就一起導入。

Keycloak 曾跑通 Federated Login、JWT Role、agentgateway Per-tool RBAC 與 MCP。技術驗收通過後，企業 Identity Center 的 Lifecycle Owner 和跨團隊整合範圍仍未成立，所以我們選擇 Cognito。Human／M2M 有明確需求與 Production 驗證，Cognito 因而是正式 `KEEP`，不是等待升級成自建 Identity Center 的過渡品。

Artifact 這一側，Agent Registry `0.4.0` 已能做 Catalog 與 Declarative Reconciliation，但相同 `approved` Tag 仍可指向不同 Image。導入順序應先補 Immutable Digest、Build Provenance、Promotion Record 與必要的 Admission Policy。這些控制能沿用 Git、OCI Registry 與現有交付流程，不必等 Catalog。

kagent 的 Trigger 則是跨團隊 Self-service。當不同團隊重複處理 Deployment、Agent Card、Discovery 或 Approval 操作面，而且 Platform Team 願意維護 CRD、Controller、Upgrade 與 Exception Flow，kagent 才有清楚採用理由。Registry 另外需要 Catalog Owner、Git／Registry Write Path、Authn／Authz 與 Promotion Model。兩套 Control Planes 不必綁在同一張 Roadmap。

若這些需求都沒有出現，BYO Runtime + Git + agentgateway + LGTM 就是可以正式接受的目標架構，不需要預先留下「之後再平台化」的待辦。

## Workload、Audit 與成本的平行分支

有些能力不是下一個共同平台階段，而是由特定義務觸發：

| Trigger | 需要補的能力 | 在條件成立前的處理 |
| --- | --- | --- |
| 需要分辨實際 Pod／Runtime，或移除長效 Secret | Workload Identity、Credential Binding、Rotation | 保持 `UNKNOWN`，不把 Client Credentials 當 Instance Identity |
| 事件需要不可否認、Legal Hold 或 Privileged Deletion Detection | Event-time Signature、Append-only／WORM Storage、Security／Risk Owner | LGTM 繼續負責 Operational Telemetry |
| Showback／Chargeback 成為正式流程 | Pricing Version、Provider Attribution、Invoice Reconciliation | 保留 Gateway Estimate 與 `PARTIAL` Gap |

Workload Identity 是否採用 Kubernetes ServiceAccount、Workload-bound Token 或 SPIFFE，要等 Trust Domain 與 Live E2E 確定。Tamper-evident Audit 也不會因為組織導入 kagent 或 Registry 就自然成立。這些分支可以和 Control Plane 評估平行進行。

## Trigger、控制與停留條件

完整版本放在 [Agent Governance Adoption Trigger Matrix](https://github.com/MikeHsu0618/2026-ithelp-agent-governance-public/blob/day-08-r1/articles/day-28/adoption-trigger-matrix.md)。正文保留最常見的八種情境：

| Trigger | 先補的控制 | 合理停留點 |
| --- | --- | --- |
| 單一團隊、只讀 Agent | Human／M2M Identity、Tool Outcome、LGTM Correlation | Git-owned BYO Runtime + LGTM |
| Tool 開始有副作用 | Action Contract、Resource Policy、Immutable Artifact、Governance Event | 單一 Runtime Callback／Authorization |
| 多個 Runtime 的 Policy 或 Telemetry 開始漂移 | agentgateway 的 Auth、Route、Policy、Telemetry | BYO Runtime + Git + Gateway + LGTM |
| 正式成本分攤 | Validated Team、Pricing Version、Provider Billing | Gateway Estimate 保留 `PARTIAL` Gap |
| 跨團隊 Deployment／Discovery／HITL | 分開評估 kagent 與 Approval Contract | 沒有 Owner 就維持既有交付方式 |
| 跨團隊 Catalog／Reconciliation | Source of Truth、Promotion、Registry Authz | Git + Immutable OCI Digest |
| Per-instance Attribution／Secretless Auth | Workload Identity | Live E2E 成立前保持 `UNKNOWN` |
| 完整性或長期保存義務 | Tamper-evident Audit Event 與 Storage | LGTM 負責 Operational Telemetry |

這張表不會替每個團隊產生相同 Roadmap。它要求每次擴張都回答：哪個事件觸發新增控制、誰接手長期維運、用什麼 Evidence 驗收，以及哪些條件允許架構停在這一層。

## 共同控制之後的責任交接

控制集中後，Owner 仍然分散。IT／Identity 維護 Human 與 Service Lifecycle，Platform Team 提供 Traffic Checkpoint、Telemetry Pipeline、Artifact Promotion 或 Deployment Control Plane，Application Team 保留 Tool 與 Resource 的業務規則。把它們全部寫成「平台負責」，出事時仍得重新拆一次。

一筆會改寫 Production 狀態的 Action 可能經過完全正常的技術路徑：IdP 證明 Caller，Gateway 驗證 Credential、Route 與共同 Policy，Runtime 判斷目標 Resource 和 Parameters，Tool 執行後將 Receipt 送進 LGTM。Business Owner 仍要確認這個動作符合業務意圖，並接受核准後留下的 Residual Risk。

Day 29 會沿用這筆有副作用的 Action，把 Credential、Policy、Tool Decision、Approval 與 Residual Risk 整理成 Production Responsibility Contract。下一個問題不再是多裝哪套平台，而是每一段控制由誰決定、誰執行、誰對最後結果負責。
