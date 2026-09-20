# Day 28｜從既有 LGTM 開始：Agent Governance 的導入順序

[Day 27 的 Capability Ledger](https://github.com/MikeHsu0618/2026-ithelp-agent-governance-public/blob/day-28/articles/day-27/capability-ledger.md) 一共有十四列：六列 `KEEP`、兩列 `ADOPT`、四列 `DEFER`，還有兩列 `UNKNOWN`。只看狀態，最刺眼的 `UNKNOWN` 好像應該先處理。照產品架構圖走，又很容易先裝 kagent、Registry 或另一套 Identity Center。這兩種排序都沒有回答一件事：誰現在有能力把它接進值班、升級和事故流程？

我手上的現況其實很不平均。LGTM 已經是 production 核心，有人維護，也有既有查詢和告警習慣。Cognito 的 Human／M2M 路徑已經跑通。agentgateway 也有明確的 LLM／MCP／A2A traffic boundary。相較之下，統一 Identity Center、跨團隊 Agent control plane 與 Catalog 都還缺共同需求或長期 owner。

這篇的導入圖改用幾個可以單獨判斷的 trigger：Tool 是否產生副作用、共同 traffic policy 是否開始漂移、Artifact 是否跨環境流動、團隊是否需要 self-service、成本是否進入正式分攤，以及證據是否有完整性或保存義務。每一個 trigger 都要同時找到 owner 與驗收證據。條件尚未成立時，現有架構就是可以被正式接受的停留點。

![Agent Governance 以既有 Identity、Git-owned BYO Runtime 與 LGTM 為基線。Tool 有副作用時先補 Action contract。多個 Runtime 的 LLM、MCP、A2A policy 與 telemetry 開始重複或漂移後，再加入 agentgateway 作為共同 checkpoint。跨團隊 deployment、discovery 或 catalog 需求成立後才評估 kagent 與 Agent Registry。Workload identity 和 tamper-evident Audit 依個別需求開啟。](https://raw.githubusercontent.com/MikeHsu0618/2026-ithelp-agent-governance-public/day-28/assets/diagrams/day-28/adoption-path.png)

## 最小可維運基線：Identity、Git-owned Runtime 與 LGTM

Human 使用者走 Authorization Code／PKCE，M2M 走 Client Credentials。Agent runtime、Tool callback 與 dependency 由應用 repository 維護。執行過程透過 Alloy 進入 Loki、Tempo 與 Prometheus／Mimir 相容介面。這三邊都有 owner，也都有前面 Lab 能重跑的 contract，因此可以組成判斷是否要再加控制的最小基線。

這張圖不是目前 production topology 的快照。我們的環境已經出現跨 Runtime 的共同 traffic boundary，所以 agentgateway 也在現行架構裡，位置相當於圖中的第二個停留點。保留前一層，是讓還沒有共同 policy 問題的團隊不用照抄 Gateway。

組織本來就會操作這套 LGTM，新的 Agent span、Tool event 或 Gateway metric 可以沿用既有 collector、retention、query 與 on-call 流程，所以我們先從這裡接。它先回答 latency、error、Tool outcome 和跨服務 correlation。Audit integrity 仍留在另一列，沒有被一張 Grafana Dashboard 自動補完。

這個起點只描述我們的現況。讀者可以換成自己已經有 owner 的 IdP、application repository 與 telemetry backend，判斷方式不變：先使用組織真的會維護的系統，再看下一個 trigger 是否值得增加控制面。

如果 Agent 仍是單一團隊維護、只讀資料、沒有共用的 MCP／A2A 入口，基線可以先停在這裡。停留條件是 credential scope 已受限、Tool outcome 能查到，而且失敗有人接手。此時增加一組 controller 和 CRD，還沒有對應的共享需求。

## Tool 副作用決定第一批控制

Day 1 的 `delete_demo_database` 是 no-op canary，但它示範了實際的判斷點。只要 Tool 開始能寫入、刪除、部署或批准，單純把 trace 接進 LGTM 已經不夠。執行前要有 resource-aware allowlist 或 policy，執行後要留下 action ID、policy version、Tool arguments、effect receipt，以及當時實際執行的 commit 或 Artifact digest。

這批控制不必等集中式平台。只有一個 Runtime 時，ADK callback、應用自己的 authorization 與 Git review 仍可以形成清楚的 enforcement path。驗收時要確認 DENY 發生在 Tool 執行前，而且事故回放找得到當時的 decision。Day 27 因此把 immutable digest、promotion evidence 與 Governance Event contract 記成 `ADOPT`，它們比 Catalog UI 更早進入基線。

當有副作用的 Tool 需要人工批准，HITL 也不能只看畫面上有 Approve／Reject。導入前還要驗 approver authentication、authorization、task／context continuity、decision receipt 與 resume callback。Day 18 只跑通相容的 pause／resume contract，這些 production 邊界尚未完成，所以共享 HITL control plane 仍是 `DEFER`。

## 共同 Policy 開始漂移，才需要 Agent Gateway

單一 Runtime 可以在應用內完成 policy。即使兩個 Agent 使用同一個 LLM provider，也不表示中間一定要多放一層 Gateway。Gateway 的 trigger 出現在多個 Runtime 各自重複處理 JWT、retry、timeout、provider credential、Tool policy 與 telemetry，設定開始分岔，事故時又缺少一致的 observation point。

這些責任需要共同 checkpoint 時，我們才加入 agentgateway。它收斂 LLM／MCP／A2A traffic 的 authentication、routing、policy 與 telemetry，既有 Ingress 仍可保留 TLS、host routing 與 access log。Tool 的業務合法性、Agent workflow 和資料庫裡某筆資源能不能改，依然由 Runtime 或 Resource Server 判斷。

Day 24 的成本資料也沿用這個 boundary。Model catalog 可以把 token usage 換成每筆請求的 cost，validated caller／team mapping 則提供 showback 維度。到了正式 chargeback，還要補 pricing version、Provider billing attribution、credit／discount 與 invoice reconciliation。失敗請求若沒有 usage，也要明確保留為 `UNKNOWN`。這一段提升的是成本證據的精度，仍然沿用原本的 Gateway 與 Observability boundary。

如果團隊使用 BYO Agent、Git 部署與單一 Gateway 已經能穩定交付，架構可以停在這裡。kagent 或 Registry 並不會因為 Gateway 已上線就成為下一個必選元件。

## Identity 只擴到目前能維護的範圍

Keycloak 曾在 Kubernetes 跑通 federated login、JWT role、agentgateway per-tool RBAC 與 MCP。技術驗收通過後，企業 Identity Center 的共同 owner 仍未成立，IT 團隊也暫時沒有足夠人力，把 joiner／mover／leaver、下游服務與 SaaS 入口一起接進來。最後的選擇是 Cognito。

目前 Human／M2M 路徑有明確需求，也有 production 驗證，因此 Cognito 保持 `KEEP`。統一 Identity Center 要等企業 lifecycle scope、IT／Identity owner 和 migration 資源同時成立。在只有少數 AI 服務的階段，managed identity bridge 可以直接記成正式決策，不必假裝它只是過渡方案。

Workload instance identity 則沒有被 Cognito Client Credentials 解掉。當政策需要分辨實際 Pod／Runtime instance、要移除長效 client secret，或 Audit 必須綁到 workload attestation 時，才重開 Kubernetes ServiceAccount、workload-bound Token 或 SPIFFE 類機制的選型。Day 27 保留 `UNKNOWN`，是因為目前沒有 live E2E 可以支持任何一種答案。

## Artifact trust 早於 Catalog

Agent Registry `0.4.0` 已能做 catalog 與 declarative reconciliation，Day 19 也實際跑過 deploy、更新與 undeploy。相同的 `approved` tag 仍可指向不同 image，說明 reconciliation 成功沒有回答 Artifact 是否不可變，也沒有留下 promotion 經誰批准的證據。

導入順序因此先放 immutable digest、build provenance、promotion record 和必要的 admission policy。這些控制可以沿用 Git、OCI registry 與現有交付流程，不必先建立 Agent Catalog。等跨團隊真的需要搜尋 Agent、宣告 desired state、統一部署與下架，再決定 Registry 是否值得成為新的 source of truth。

Git、immutable digest 與 promotion record 可以形成一條可驗收的 Artifact path。Catalog UI 要等搜尋、跨團隊 lifecycle 與 reconciliation 需求出現後再加。即使有了畫面，signature、promotion authorization 與 runtime admission 仍要另外驗證。

## 跨團隊 Self-service 才重開平台評估

kagent 已證明可以接手 deployment、discovery、Agent-as-Tool 入口，以及相容的 HITL pause／resume。它沒有接走 BYO Runtime 的 dependency、memory、filesystem、Tool policy 或 framework upgrade。A2A 能讓自寫 Agent 被其他 Agent 找到和呼叫，也不會自動把這些 runtime 責任搬進平台。

當多個團隊開始重複處理 deployment、Agent Card、discovery 或 approval 操作面，而且 Platform Team 願意維護 CRD、controller、版本升級與例外流程，kagent 才有清楚的採用理由。Registry 的 trigger 另外判斷：它需要 catalog owner、Git／Registry write path、Authn／Authz 與 promotion model 一起成立。兩套 control plane 不必綁在同一張採購單上。

若這些條件都沒有出現，正式目標就停在 BYO Runtime + Git + agentgateway + LGTM。這套組合有明確 owner、重驗路徑和事故證據，沒有必要預先排一個「之後再平台化」的待辦。

## Audit 與 Workload Identity 是平行分支

Operational telemetry 的 retention、sampling 和存取模型，是為除錯與維運設計。若事件必須支援不可否認、legal hold、privileged deletion detection 或長期證據保存，就要另外指定 Security／Risk owner，評估 event-time signature、hash chain、append-only 或 WORM storage。這條分支由保存義務觸發，與團隊有沒有採用 kagent、Registry 無關。

Workload identity 處理 instance attribution、credential binding 與 rotation。當 per-instance policy 或 secretless authentication 成為需求，就另外選定 trust domain 與驗證路徑。證據還沒跑出來以前，Capability Ledger 繼續寫 `UNKNOWN`，不會因為 Agent 數量增加就自行變成 `ADOPT`。

## Trigger、控制與停留條件

下面是正文的精簡版。完整表格另放在 [Agent Governance Adoption Trigger Matrix](https://github.com/MikeHsu0618/2026-ithelp-agent-governance-public/blob/day-28/articles/day-28/adoption-trigger-matrix.md)，可以直接換成自己的 owner 與 evidence。

| Trigger | 先補的控制 | 合理停留點 |
|---|---|---|
| 單一團隊、只讀 Agent | Human／M2M identity、Tool outcome、LGTM correlation | Git-owned BYO Runtime + LGTM |
| Tool 開始有副作用 | Action contract、resource policy、immutable Artifact、Governance Event | 單一 Runtime 的 callback／authorization |
| 多個 Runtime 的 auth、policy 或 telemetry 開始重複／漂移 | agentgateway 的 auth、route、policy、telemetry | BYO Runtime + Git + Gateway + LGTM |
| Showback／chargeback 成為正式需求 | Validated caller／team、pricing version、Provider billing attribution、invoice reconciliation | 尚未正式分攤時，保留 Gateway cost + `PARTIAL` gap |
| 跨團隊 deployment／discovery／HITL | 分開評估 kagent 與 approval contract | 沒有 owner 就維持既有交付方式 |
| 跨團隊 catalog／reconciliation | Source of truth、promotion、Registry authz | Git + immutable OCI digest |
| Per-instance attribution 或 secretless auth | Workload identity 與 credential binding | 維持 `UNKNOWN`，直到 live E2E 成立 |
| 完整性或長期保存義務 | Tamper-evident Audit event 與 storage | LGTM 繼續負責 operational telemetry |

這張表不會替所有團隊產生同一份 roadmap。它只要求每一次擴張都能回答三件事：什麼事件觸發新增控制、誰接手長期維運，以及什麼證據能讓團隊安全地停在這一層。

## 共同控制之後的責任

照這條路徑導入，共同控制會由不同角色接手。IT／Identity 維護使用者與服務的 lifecycle，Platform Team 提供 traffic checkpoint、telemetry pipeline、Artifact promotion 或 deployment control plane，Application Team 則保留 Tool 與 Resource 的業務規則。把這些責任都寫成「平台負責」，只會在出事時重新拆一次。

以一筆會改寫 production 狀態的 action 為例，IdP 證明呼叫者，Gateway 驗證 credential、route 與共用 policy，Runtime 判斷目標資源和參數，Tool 執行後再把 operational receipt 送進 LGTM。整條技術路徑都可能正常運作，Business Owner 仍要確認這個動作是否符合業務意圖，並接受批准後留下的 residual risk。

Day 29 會沿用同一筆有副作用的 action，整理成 Production Responsibility Contract。下一個問題不再是要不要多裝一套平台，而是 credential、policy、Tool decision 與 residual risk 在 IT／Identity、Platform、Application、Security 和 Business Owner 之間怎麼交接。
