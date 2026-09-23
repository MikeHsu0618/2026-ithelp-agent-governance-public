# Day 28｜從既有 LGTM 開始：Agent Governance 的導入順序

同樣叫 Agent，一支只幫單一團隊查 Log，另一支卻能修改正式環境，兩者不該拿到同一份安裝清單。[Day 27 的 Capability Ledger](https://github.com/MikeHsu0618/2026-ithelp-agent-governance-public/blob/day-28-r2/articles/day-27/capability-ledger.md) 把身分、流量、Agent、資料權限與觀測分回各自的系統；接下來要按這支 Agent 真正會做的事，決定先補哪一段。

我手上的現況並不平均。LGTM 是 Production 核心，有人維護，也有既有查詢和告警習慣。Cognito 的 Human／M2M 路徑已經跑通，agentgateway 也有明確的 LLM／MCP／A2A Traffic Boundary。相較之下，企業 Identity Center、跨團隊 Agent Control Plane 與 Catalog 仍缺共同需求或長期 Owner。

這篇用三個情境來排序：單一團隊的唯讀調查、開始共用流量入口的多個 Agent，以及會改變正式環境的高風險動作。每種情境都問同樣三件事：目前的控制夠不夠、誰接手新增的控制、什麼時候可以停下來。答案不會是一條所有團隊都得爬完的階梯。

![Agent Governance 以既有 Identity、Git-owned BYO Runtime 與 LGTM 為基線。Tool 有副作用時先補 Action contract。多個 Runtime 的 LLM、MCP、A2A policy 與 telemetry 開始重複或漂移後，再加入 agentgateway 作為共同 checkpoint。跨團隊 deployment、discovery 或 catalog 需求成立後才評估 kagent 與 Agent Registry。另有 Workload identity 或法遵保存要求時再檢查既有機制。](https://raw.githubusercontent.com/MikeHsu0618/2026-ithelp-agent-governance-public/day-28-r2/assets/diagrams/day-28/adoption-path.png)

## 一個團隊的唯讀 Agent，可以先停在這裡

Human 使用者走 Authorization Code／PKCE，M2M 走 Client Credentials。Agent Runtime、Tool Callback 與 Dependency 由應用 Repository 維護，執行過程透過 Alloy 進入 Loki、Tempo 與 Prometheus／Mimir 相容介面。Identity、Git-owned Runtime 與 LGTM 都有既有 Owner，也有前面 Lab 能重跑的 Contract，因此足以構成第一個停留點。

我們自己的架構已經有 agentgateway。這張導入圖保留更簡單的起點，是給尚未出現共同 Policy 問題的團隊。它不必為了跟上系列進度照抄 Gateway。

LGTM 先回答 Latency、Error、Tool Outcome 與跨服務 Correlation。設定和映像的變更則回 Git 的 PR／Commit 與部署紀錄找。讀者也可以把 LGTM 換成組織原本使用的觀測平台，重點是能沿同一筆請求查到執行結果。

如果 Agent 仍由單一團隊維護、只讀資料，也沒有共用 MCP／A2A 入口，架構可以停在這裡。前提是 Credential Scope 已受限、Tool Outcome 查得到，而且失敗有人接手。此時增加 Controller 和 CRD，還沒有對應的共享需求。

例如 Day 25 的 SRE Agent 查 Loki，第一個驗收問題不是「有沒有 Agent Catalog」，而是查詢帳號能看到哪些 Log、Tool 回傳是否帶回可追查的 `trace_id`，以及查不到資料時值班者該往哪裡查。這些事情已有 Application、Grafana 與觀測平台的責任邊界。若只因為它叫 Agent 就加一個部署控制面，反而讓一條原本能查清楚的路多出新的交接點。

## 如果 Agent 能改資料，先處理那筆動作

只要 Tool 開始能寫入、刪除、部署或批准，單純把 Trace 接進 LGTM 就不夠。執行前需要 Resource-aware Policy，執行後則要留下 Action ID、Policy Version、關鍵 Arguments、Effect Receipt，以及當時真正執行的 Commit 或 Artifact Digest。

這批控制不必等集中式平台。只有一個 Runtime 時，ADK Callback、應用自己的 Authorization 與 Git Review 仍能形成清楚的 Enforcement Path。除了確認拒絕發生在 Tool 執行前，還要能找到當時使用的映像版本與執行結果。Day 27 已把這些分別放回 Runtime、資源服務與交付流程，通常比先增設 Catalog UI 更急。

Tool 若需要人工核准，HITL 也不能只看畫面上有 Approve／Reject。上線時還要知道誰有權核准、暫停的任務如何恢復，以及這次決定如何留存。Day 18 展示了相容的 Pause／Resume 流程；是否需要共用的核准平台，可以等多個 Agent 都遇到同類需求時再決定。

這類 Agent 的停留點不取決於團隊數量，而取決於能否說清楚「這筆修改為什麼可以做」。如果工單只允許測試環境，Tool 卻送出正式環境參數，Resource Server 必須在執行前拒絕。把所有 Action 都送去人工核准，也不能代替這條可以寫進程式的業務規則。Day 29 會用這個差異檢查責任交接。

## 多個 Agent 開始各管各的 Policy，才需要共同入口

單一 Runtime 可以在應用裡完成 Policy。兩個 Agents 共用同一個 LLM Provider，也不代表中間一定需要 Gateway。真正的 Trigger 是多個 Runtime 各自重複處理 JWT、Retry、Timeout、Provider Credential、Tool Policy 與 Telemetry，設定開始分岔，事故時又缺少共同 Observation Point。

這時 agentgateway 才有清楚責任：收斂 LLM／MCP／A2A Traffic 的 Authentication、Routing、Policy 與 Telemetry。既有 Ingress 可以繼續處理 TLS、Host Routing 與 Access Log。Tool 的業務合法性、Agent Workflow，以及資料庫裡某筆 Resource 能不能修改，仍由 Runtime 或 Resource Server 決定。

Day 24 的成本也沿用這個 Boundary。Model Catalog 可以把 Token Usage 換成 Request-level Estimate，Validated Caller／Team Mapping 則提供 Showback 維度。正式 Chargeback 再補 Pricing Version、Provider Billing Attribution、Credit／Discount 與 Invoice Reconciliation。失敗 Request 沒有 Usage 時保持 `UNKNOWN`，不能為了報表完整而寫成零。

BYO Agent、Git、單一 Gateway 與 LGTM 若已能穩定交付，架構可以停在這裡。Gateway 上線後，不會自動產生下一張 kagent 或 Registry 採用單。

我們需要共同入口，是因為跨 Runtime 的流量規則和觀測資料值得在同一個地方驗收，不是因為每一個 Agent 都必須搬到同一套 Runtime。這個取捨保留應用團隊對 Tool、Workflow 與框架參數的控制，也讓平台團隊把心力放在真正共用的認證、路由和政策上。

## 真正需要跨團隊自助，才評估新的控制面

到了多個團隊都要上架 Agent 的階段，Deployment、Agent Card、Discovery 和 Catalog 才可能成為平台共同工作。這時可以重新評估 kagent 與 Agent Registry，但兩者不是一包必裝的組合。前者解決 Agent 如何部署和被找到，後者處理 Catalog 與部署宣告。兩邊各自需要維護 Controller、版本升級和例外流程的人。

Day 19 已經說明，Registry 能做部署宣告，卻不會替團隊決定誰能批准映像；完整 Agent Image 的 Digest、批准紀錄和部署核對，先進入現有 Git／映像交付流程。Identity 也遵循相同的採用原則：Keycloak 技術鏈跑通，但 IT 尚無資源承接整個企業的人員生命週期，因此目前 Human／M2M 需求由 Cognito 承擔。

有些需求甚至不屬於這條平台化路徑。若要辨認實際執行的 Pod，得另外處理 Workload Identity。若法遵對紀錄有特定保存期限或防刪改要求，先檢查 Git 的變更歷史、Kubernetes Audit Log 與既有觀測平台能否滿足，再補真正缺的部分。若成本要正式分攤，還得對上 Provider 帳單，而不只看 Gateway Estimate。這些都可以獨立啟動，不會因為部署了 kagent 或 Registry 就順便完成。

## 三種情境，各有停留點

把前面三種情境放在一起，停留條件就比較清楚。單一團隊的唯讀 Agent，只要 Credential Scope、Tool Outcome、查詢證據和維護者都明確，可以停在 Git-owned BYO Runtime 與既有 LGTM。多個 Agent 的 Auth、Route、Policy 和 Telemetry 開始漂移時，加入 agentgateway 作為共同入口。如果這些設定已有 Owner，仍不必立刻加 Deployment Control Plane。能改動正式環境的 Agent 則先補目標資源授權、實際執行版本、必要時的人工核准和執行結果，無論它是否已上架到共同 Catalog。

細項與重開評估條件留在可複製的 [Agent Governance Adoption Trigger Matrix](https://github.com/MikeHsu0618/2026-ithelp-agent-governance-public/blob/day-28-r2/articles/day-28/adoption-trigger-matrix.md)。它是選擇時的核對表，不是要求每個團隊照順序採購的成熟度模型。我們自己的架構已經走到單一 Gateway 與既有 LGTM 並用。接下來真正要問的，是高風險動作由哪一層拒絕、哪個人有權批准。

Day 29 會拿這種動作走一遍設計審查。共同入口可以擋下不合規的請求，仍不能替業務 Owner 判斷這次修改是否符合意圖。責任必須沿著同一筆 Action 交接，而不是在架構圖上統稱「平台負責」。
