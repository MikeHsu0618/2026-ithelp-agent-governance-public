# Day 27｜Agent Governance 選型總帳：把產品功能換算成維運責任

[前一篇](https://ithelp.ithome.com.tw/articles/10412919)重新回放了 Day 1 那筆被不可信 Log 誘導的 Tool Call。結果一半很清楚：哪個 Tool 被呼叫、policy 如何判斷、canary 最後有沒有觸發。另一半仍然是 `UNKNOWN`，包括 principal、delegation、Agent artifact、approval 和原始紀錄是否完整。這些空格不會因為再裝一套平台就自動補齊，每一格背後都有不同的資料來源、控制點與維運責任。

我最早做 AI Gateway 選型時，也用過很典型的功能比較表：產品放在欄位，routing、virtual key、MCP、A2A、RBAC、telemetry 依序打勾。表格很快就能填滿，最後做出的決策卻常和勾勾數量相反。Keycloak 的完整路徑跑通了，我們仍然改用 Cognito。Agent Registry 已能把 desired state reconcile 進 kagent，我們也沒有立刻採用。LGTM 從未宣稱自己是 Agent Governance 平台，反而成了這套架構裡最穩定的核心。

這些功能表都以產品為比較單位。Keycloak、agentgateway、kagent、Registry 與 LGTM 解的是不同問題，硬排成同一張排行榜，採用後要接手的工作反而看不見。Day 27 不再增加新產品或第六套 Lab，改把前 26 天的實測與實務取捨整理成一份 Capability Ledger。

下面這張圖是總帳的讀法。產品名稱只會出現在 `Current Source`，不再佔據比較表的欄位。同一列還必須寫出 evidence、owner、升級後的重驗範圍，以及現在仍然存在的 gap。

![Day 26 留下 principal、delegation、artifact 與 approval 等 evidence gap。這些問題先轉成 capability，再記錄 current source、evidence、owner、revalidation、gap 和 decision。產品名稱只出現在實作來源，不作為比較表欄位。](https://raw.githubusercontent.com/MikeHsu0618/2026-ithelp-agent-governance-public/day-30/assets/diagrams/day-27/capability-ledger-method.png)

## 從產品比較表改成 Capability Ledger

Day 26 的 `identity.principal` 是 `UNKNOWN`。IdP 可以驗證 Human 或 Service，Gateway 可以驗 Token 與 policy，Runtime 則記錄目前執行者。三者都有 Identity 相關功能，卻沒有一個產品名稱能直接補上這個欄位。其他缺口也有同樣的問題：

| Day 26 的缺口 | 要盤點的能力 | 不能直接用哪個產品名稱代答 |
|---|---|---|
| `identity.principal` | Human／Service／Workload identity 與 lifecycle | Keycloak 或 Cognito |
| `delegation` | Subject、current actor、target 與 credential binding | OAuth、A2A 或 Gateway |
| `agent.artifact_digest` | Artifact identity、promotion 與 admission | Registry 或 Git |
| `approval` | Approver authentication、decision 與 resume contract | HITL 或 kagent |
| Audit 完整性 | Event semantics、access、retention 與 tamper evidence | OpenTelemetry 或 LGTM |

右欄的產品或協定都可能參與解法，但沒有一個名稱能獨自證明左欄已經成立。總帳因此以 capability 為列，再問目前實作來源是產品內建、自建整合、既有平台，還是只有文件宣稱。

## Capability Ledger 的七個欄位

如果 kagent 那一列只寫「支援 HITL」，Lab 03 已經可以打勾，但 approver authorization 沒有測過、Runtime 作者仍要維護 resume contract，這兩件事就會被藏掉。這份 Ledger 因此固定保留七項資訊：Capability、Current Source、Evidence、Owner、Revalidation Surface、Gap 與 Decision。版本只在它會改變判斷時出現，否則記錄驗證日期即可。

這個系列同時用了實務環境的端到端紀錄、公開 Lab、設定驗證與官方文件。實務 E2E 可以支撐當時的選型，合成 Lab 讓讀者重跑相同 contract，官方文件則只證明產品公開承諾的行為。三者能回答的問題不同，不能全部壓成一個 `PASS` 分數。

`Owner` 寫的是升級、事故與例外發生時要接手的人，不是最初安裝套件的人。Cognito app client 可以由 Terraform 建立，callback、scope、claim mapping 與離職停權仍要有人長期維護。agentgateway 能集中 policy，也不會替 Application Team 定義每一個 Tool argument 的業務合法性。

## 五種決策狀態

功能加權表會讓 routing、UI 或 protocol support 的分數，抵銷 Identity lifecycle 沒有 owner、Audit integrity 未驗證這類缺口。加總後的數字看起來精確，卻無法告訴我哪一項可以上線。Capability Ledger 因此只保留五種決策狀態，不做總分：

| 狀態 | 在本文的意思 |
|---|---|
| `KEEP` | 已在使用，證據和 owner 足以支持該列寫明的範圍 |
| `ADOPT` | 缺口已由前文證明，現在值得補進正式基線 |
| `DEFER` | 能力有價值，但需求、owner 或前置條件尚未成立 |
| `REJECT` | 在明確情境下不採用，並留下重新評估的條件 |
| `UNKNOWN` | 證據不足，不能用偏好或文件把答案補滿 |

`REJECT` 與 `DEFER` 都要附 reopen condition。前者只拒絕目前這種實作與組織情境，後者則等需求、owner 或前置控制補齊。條件改變後，原本的 evidence 也要重新驗收。

## Capability Ledger v1

下表是目前的摘要。完整版本另外列出 owner、upgrade／fork surface、remaining gap 與 reopen condition，放在 [Agent Governance Capability Ledger](https://github.com/MikeHsu0618/2026-ithelp-agent-governance-public/blob/day-30/articles/day-27/capability-ledger.md)。要匯入試算表或改成自己的架構，可以直接下載 [CSV 版本](https://github.com/MikeHsu0618/2026-ithelp-agent-governance-public/blob/day-30/articles/day-27/capability-ledger.csv)。

| Capability | Current Source | Evidence | Decision |
|---|---|---|---|
| Human identity／app lifecycle | Amazon Cognito User Pools + agentgateway JWT policy | 實務 E2E（去識別化）+ Lab 02 contract | `KEEP` |
| M2M／Service access | Cognito Client Credentials + runtime service credential | 實務 E2E（去識別化）+ Lab 02 contract | `KEEP` |
| Workload instance identity | 尚無已驗證的 attestation source | Day 7 boundary；未做 live E2E | `UNKNOWN` |
| Human → Runtime → Tool delegation | Delegation Context v0.1；尚無統一 exchange service | Lab 02 | `DEFER` |
| LLM／MCP／A2A traffic enforcement | agentgateway | 實務紀錄 + Lab 03／04 | `KEEP` |
| Agent runtime／business logic | BYO Google ADK | Lab 01／03／04 | `KEEP` |
| Deployment／discovery control plane | kagent candidate | Lab 03，含未測邊界 | `DEFER` |
| HITL pause／resume contract | BYO Runtime + kagent-compatible adapter | Lab 03 通過 approve／reject；authz 未驗 | `DEFER` |
| Artifact identity／promotion | Git + immutable OCI digest；admission 尚未完成 | Lab 03 | `ADOPT` |
| Cross-team catalog／reconciliation | Agent Registry candidate | `0.3.3` 評估 + `0.4.0` Lab | `DEFER` |
| Telemetry／correlation | Alloy + LGTM + agentgateway telemetry | Lab 04 + 長期維運經驗 | `KEEP` |
| Governance Event／incident replay | Governance Event v1 + replay tooling | Lab 05 | `ADOPT` |
| Tamper-evident Audit storage | 尚無已驗證實作 | Day 26 保留 `UNKNOWN` | `UNKNOWN` |
| Cost attribution | Gateway catalog estimate；Provider invoice 尚未對帳 | Lab 04 為 `PARTIAL` | `KEEP` |

`REJECT` 沒有出現在這張 capability 摘要裡，因為 Identity、Traffic 或 Audit 這些能力本身不會被拒絕，被拒絕的是特定實作方案。完整總帳另外記錄了 AI 專用 Keycloak Identity Center 與當時 LiteLLM evaluation profile 的適用情境。至於 `ADOPT`，也不一定代表增加產品。這裡採用的是 immutable digest 與 Governance Event contract。`UNKNOWN` 則照原樣保留，不會因為 OpenTelemetry 已經有 trace，就宣稱 Audit 已經完成。

## Identity：技術驗收通過，Owner 仍未成立

[Day 6](https://ithelp.ithome.com.tw/articles/10405965) 的 Keycloak 路徑已經跑通 federated login、OIDC、JWT role、agentgateway per-tool RBAC 與 MCP。若只看功能表，它幾乎沒有輸的理由。當時卡住的是企業 Identity Center 的 operating model：IT 團隊暫時沒有足夠共識和人力，把 onboarding、offboarding、下游服務與 SaaS 入口一起接進來。

只為幾個 AI 服務維護 Operator、資料庫、realm、client、mapper 與升級，會得到一套技術上完整、組織上卻不掌握真實 lifecycle 的 Identity Center。因此，Ledger 對「AI 專用 Keycloak Identity Center」記為目前情境下的 `REJECT`，reopen condition 是企業級 lifecycle owner 與整合範圍真的成立，而不是等下一個功能出現。

[Day 12](https://ithelp.ithome.com.tw/articles/10407593) 跑過的 Cognito Human／M2M 路徑則記為 `KEEP`。這個選擇減少了自建 control plane，callback、scope、claim、client secret 與 Gateway policy 仍由團隊維護，所以這些項目全部留在 revalidation surface。

這個 `KEEP` 只涵蓋 Service access。Client Credentials 能指出哪個 confidential client 取得 Token，不能證明是哪一個 Pod 或 Runtime instance 使用它。本系列還沒有對 Kubernetes ServiceAccount、workload-bound Token 或 SPIFFE 類機制做 live E2E，因此 Workload instance identity 另外保留為 `UNKNOWN`，沒有偷塞進 M2M 那一列。

## Traffic、Runtime 與 Control Plane 分開記帳

[Day 13](https://ithelp.ithome.com.tw/articles/10407809) 的 Gateway 選型最能看出總帳和產品分數的差別。LiteLLM 的 routing、virtual key、budget、spend 與 UI 都很實用，但當時的 Kubernetes operating model 需要額外的 team／user identity mapping 和 GitOps glue。我們對該方案的 `REJECT` 限定在這個 operating model。後來發生的供應鏈事件是新增風險，不能倒寫成原始決策理由。

agentgateway 目前記為 `KEEP`，因為 LLM、MCP 與 A2A traffic 的 policy、routing 和 telemetry 確實落在同一個 data-plane boundary，Kubernetes control plane 也較符合既有 Git ownership。這個 `KEEP` 不包含 Identity Provider、Agent workflow、Tool business policy 或 Audit storage，它只對自己真正接手的能力負責。

[Day 18](https://ithelp.ithome.com.tw/articles/10409155) 驗證了 kagent 可以替 BYO Agent 處理 deployment、discovery、Agent-as-Tool 入口與相容的 HITL pause／resume。同一輪測試也留下另一條邊界：Runtime dependency、memory、Tool policy、filesystem、approver authorization 和 framework upgrade 仍由 Agent 作者負責。

目前的帳分成三列。BYO Google ADK runtime 是 `KEEP`。kagent 的 deployment／discovery control plane 是 `DEFER`。HITL pause／resume contract 也先 `DEFER`，因為 approver authentication 與 authorization 尚未驗證。等組織真的需要 self-service discovery、統一部署或共享 HITL 操作面，再拿同一套 BYO、A2A、HITL 與 actor propagation fixture 重驗。在那之前，多一套 controller、CRD 與升級責任沒有足夠的需求支撐。

## Artifact：Catalog、Reconciliation 與 Trust

我們曾部署並拆除 Agent Registry `0.3.3`，主要衝突是 PostgreSQL／REST state 與既有 Git source of truth。到了 `0.4.0`，它已重作成 declarative control plane，Lab 也驗證 catalog、deployment reconciliation 與 undeploy。這裡必須保留版本號，因為前後兩版的控制面已經不是同一種設計。

[Day 19](https://ithelp.ithome.com.tw/articles/10409470) 同時留下兩個採用風險：預設 permissive auth 接受匿名寫入，相同的 `approved` tag 也能換到另一個 image。這表示 controller 綠燈只證明 desired state 已經收斂，沒有證明 artifact 不可變、promotion 經過授權，或 Registry 已成為組織承認的 source of truth。

帳本因此留下兩列。Cross-team Registry 維持 `DEFER`，要等 catalog owner、Git／Registry write path、Authn／Authz、promotion 與 audit 一起確定後才重開評估。Immutable digest 與 promotion evidence 不必等 Registry，直接記為 `ADOPT`。這樣可以先補 Artifact 信任基線，又不用立刻接下一套 catalog control plane。

## Telemetry 與 Audit 的責任邊界

Alloy、Loki、Grafana、Tempo 與 Prometheus／Mimir 相容介面是我們原本就在維運的核心，Day 20 到 Day 26 只是把 Agent runtime、agentgateway 與 MCP traffic 接進來。這條路已經能回答 latency、error、route、Tool Call、cost estimate 與跨服務 correlation，所以 Telemetry 記為 `KEEP`。

Day 26 也說明了它不能回答的部分。Trace sampling、export failure、backend retention 和 access policy 都會改變 evidence completeness。沒有 event-time signature、append-only storage 或 WORM policy，也不能把一筆 Loki log 升格成不可否認的 Audit record。Governance Event schema 與 replay workflow 已在 Lab 05 驗證，適合記為 `ADOPT`。Tamper-evident Audit storage 仍是 `UNKNOWN`，要等 owner、保存目的、存取模型與完整性機制真的被驗證，才能改變狀態。

成本也採用相同寫法。[Day 24](https://ithelp.ithome.com.tw/articles/10411731) 的 Gateway estimate 可以保留，Provider 沒回 usage 的失敗 attempt 仍不能硬算完整總額。`KEEP` 現有估算能力，不等於 invoice-grade attribution 已經 `VERIFIED`。Ledger 的 gap 欄要留下 pricing version、billable usage 與 Provider invoice reconciliation，不能用 Dashboard 上有美元符號就把帳結掉。

## Upgrade／Fork Surface 與重驗範圍

前面的重測已經出現過兩種很具體的版本變化：agentgateway `1.4.x` 到 `1.5.0` 改了缺少 `iss`／`aud` 時的 JWT 驗證行為，Agent Registry `0.3.3` 到 `0.4.0` 則換掉了控制面設計。舊版曾經跑綠，無法回答新版是否仍有相同行為。升級時仍得先列出受影響的 contract，再決定哪些路徑要重跑。

Identity 變更要重驗 callback、scope、claim、audience 與 Gateway policy。agentgateway 升級要看 CRD／Gateway API、route、policy、telemetry schema 和官方 Dashboard。kagent 或 Agent Registry 升級則要重跑 BYO、A2A、HITL、actor propagation、artifact mutation 與 authz fixture。LGTM 這一側也不能只確認 Pod Ready，Alloy transform、Loki metadata、Tempo correlation、retention 與查詢結果都在 revalidation surface 裡。

如果某項能力找不到 owner，也說不出升級後怎麼驗，今天跑綠的 Demo 還不足以讓它成為 `KEEP`。我現在看選型時，會把這兩欄擺在功能之前，因為套件升級或凌晨出事後，最後仍是團隊要重跑驗收、判讀差異並決定能不能繼續上線。

## 從能力總帳排出導入順序

目前的總帳留下四種結果。Cognito、agentgateway、BYO Runtime 與 LGTM 維持現況。Artifact promotion 與 Governance Event contract 納入下一版基線。kagent、Agent Registry、HITL 和完整 delegation platform 等需求與 owner 成立後再評估。Workload instance identity 與 Audit integrity 仍沒有足夠證據下結論。

這份總帳還沒回答先做哪一列。Artifact promotion 已經有明確缺口與可執行的 owner，集中式 kagent／Registry control plane 卻仍缺少跨團隊需求。兩者不能只按風險名稱排序。Day 28 會從既有 LGTM、Identity 與單一 Gateway 出發，再看 Agent 是否已產生副作用、共用服務是否增加，以及真正的 Owner 有沒有出現，排出可以停留、也可以繼續前進的導入路徑。
