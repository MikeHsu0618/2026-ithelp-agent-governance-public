# Day 27｜Agent Governance 選型檢查表：功能有沒有、誰負責、怎麼驗收

Day 26 回放了那筆危險 Tool Call。Tool、Policy Decision 與 Canary Result 都找得到，Principal、Delegation、Agent Artifact、Approval 和原始紀錄完整性卻仍是 `UNKNOWN`。這些空格不會因為再安裝一套平台就自動補齊，每一格背後都有不同的資料來源、控制點與長期 Owner。

我最早評估 AI Gateway 時，也做過常見的產品比較表：Routing、Virtual Key、MCP、A2A、RBAC、Telemetry 依序打勾。表格很快就能填滿，最後的決策卻常和勾勾數量相反。Keycloak 的技術鏈跑通後，我們仍改用 Cognito。Agent Registry 已能 Reconcile Desired State，我們也沒有立刻採用。LGTM 從未宣稱自己是 Agent Governance 平台，反而成為整套架構最穩定的核心。

問題不在比較表少了更多功能，而是比較單位錯了。Keycloak、agentgateway、kagent、Registry 與 LGTM 解的是不同問題，硬排成同一張排行榜，只會把採用後的責任藏在總分後面。Day 27 不再增加產品或 Lab，而是把前 26 天的實測與取捨整理成 Capability Ledger。

![Day 26 留下 principal、delegation、artifact 與 approval 等 evidence gap。這些問題先轉成 capability，再記錄 current source、evidence、owner、revalidation、gap 和 decision。產品名稱只出現在實作來源，不作為比較表欄位。](https://raw.githubusercontent.com/MikeHsu0618/2026-ithelp-agent-governance-public/day-15-r1/assets/diagrams/day-27/capability-ledger-method.png)

## 產品名稱不能替 Evidence Gap 作答

Day 26 的 `identity.principal` 是 `UNKNOWN`。IdP 能驗證 Human 或 Service，Gateway 能驗 Token 與 Policy，Runtime 則知道目前執行哪個 Agent。三者都和 Identity 有關，卻沒有任何一個產品名稱能直接補上那個欄位。

其他缺口也一樣：

| Replay 缺口 | 真正要盤點的能力 | 常被誤當成答案的名稱 |
| --- | --- | --- |
| `identity.principal` | Human／Service／Workload Identity 與 Lifecycle | Keycloak、Cognito |
| `delegation` | Subject、Current Actor、Target 與 Credential Binding | OAuth、A2A、Gateway |
| `agent.artifact_digest` | Artifact Identity、Promotion 與 Admission | Registry、Git |
| `approval` | Approver Authentication、Decision 與 Resume Contract | HITL、kagent |
| Audit 完整性 | Event Semantics、Access、Retention 與 Tamper Evidence | OpenTelemetry、LGTM |

右欄都可能參與解法，沒有一個名稱能獨自證明中間那項能力已成立。Ledger 因此以 Capability 為列，產品只出現在 `Current Source`，接著再問 Evidence、Owner、Revalidation Surface、Remaining Gap 與 Decision。

## 用 Human Identity 完整讀一列

Capability Ledger 不該變成另一張欄位更多的產品表。最容易看懂的方法，是先完整走過一列。

| 欄位 | Human Identity／App Lifecycle |
| --- | --- |
| Current Source | Amazon Cognito User Pools + agentgateway JWT Policy |
| Evidence | 去識別化實務 E2E + Lab 02 Contract |
| Owner | Platform Team 維護 App Client、Claim 與 Gateway Policy，人員 Lifecycle 仍在上游 IT |
| Revalidation | Callback、Scope、Claim、Audience、Secret Rotation 與 Gateway Policy |
| Remaining Gap | Workload Instance Identity 不在此列，Client Credentials 不能證明是哪個 Pod 使用 |
| Decision | `KEEP` |

這一列的價值不在寫下 Cognito，而是把「目前能相信到哪裡」和「升級後誰要重驗」放在一起。[Day 6](https://ithelp.ithome.com.tw/articles/10405965) 的 Keycloak 路徑曾經跑通 Federated Login、JWT Role、agentgateway Per-tool RBAC 與 MCP，技術能力不是淘汰原因。當時缺的是企業 Identity Center 的 Operating Model：IT 團隊尚未取得足夠共識與人力，把 Joiner／Mover／Leaver、下游服務與 SaaS 入口一起納入。

只為少數 AI 服務維護 Operator、Database、Realm、Client、Mapper 與升級，會得到一套功能完整、卻不掌握真實人員 Lifecycle 的 Identity Center。因此「AI 專用 Keycloak Identity Center」在當時情境是 `REJECT`，重新評估條件是企業級 Lifecycle Owner 與整合範圍成立，不是再多一項功能。

Cognito 的 Human／M2M 路徑則是 `KEEP`，但這個決策沒有吸收 Workload Identity。Client Credentials 能指出哪個 Confidential Client 取得 Token，不能證明是哪個 Pod 或 Runtime Instance 使用。本系列沒有對 Kubernetes ServiceAccount、Workload-bound Token 或 SPIFFE 做 Live E2E，所以那項能力另外保持 `UNKNOWN`。

## 五種決策不做加權總分

Routing、UI 或 Protocol Support 的分數，不應抵銷 Identity Lifecycle 沒有 Owner、Audit Integrity 未驗證這類缺口。Ledger 不做總分，只保留五種狀態：

| 狀態 | 意思 |
| --- | --- |
| `KEEP` | 已在使用，Evidence 和 Owner 足以支撐該列寫明的範圍 |
| `ADOPT` | 缺口已被證明，值得補進正式基線 |
| `DEFER` | 能力有價值，但需求、Owner 或前置條件尚未成立 |
| `REJECT` | 在明確情境下不採用，並留下 Reopen Condition |
| `UNKNOWN` | Evidence 不足，不能靠偏好或文件補滿 |

`REJECT` 和 `DEFER` 都需要 Reopen Condition。前者拒絕目前的實作與組織情境，後者等待需求或前置控制成立。條件改變後，舊 Evidence 也不能直接沿用。

## 本系列目前的能力摘要

完整版本放在 [Agent Governance Capability Ledger](https://github.com/MikeHsu0618/2026-ithelp-agent-governance-public/blob/day-15-r1/articles/day-27/capability-ledger.md)，另有可匯入試算表的 [CSV 版本](https://github.com/MikeHsu0618/2026-ithelp-agent-governance-public/blob/day-15-r1/articles/day-27/capability-ledger.csv)。正文只留下會改變決策的能力群組：

| Capability | Current Source | Evidence | Decision |
| --- | --- | --- | --- |
| Human／Service Identity | Cognito + agentgateway JWT Policy | 實務 E2E + Lab 02 | `KEEP` |
| Workload Instance Identity | 尚無已驗證 Attestation Source | 未做 Live E2E | `UNKNOWN` |
| LLM／MCP／A2A Traffic Enforcement | agentgateway | 實務紀錄 + Lab 03／04 | `KEEP` |
| Agent Runtime／Business Logic | BYO Google ADK | Lab 01／03／04 | `KEEP` |
| Deployment／Discovery Control Plane | kagent Candidate | Lab 03，含未測邊界 | `DEFER` |
| Artifact Identity／Promotion | Git + Immutable OCI Digest | Lab 03 | `ADOPT` |
| Cross-team Registry | Agent Registry Candidate | `0.3.3` 評估 + `0.4.0` Lab | `DEFER` |
| Telemetry／Correlation | Alloy + LGTM + Gateway Telemetry | Lab 04 + 長期維運經驗 | `KEEP` |
| Governance Event／Replay | Event v1 + Replay Tooling | Lab 05 | `ADOPT` |
| Tamper-evident Audit Storage | 尚無已驗證實作 | Day 26 | `UNKNOWN` |

這張摘要刻意沒有替產品排名。`ADOPT` 也不一定表示增加平台，Immutable Digest 與 Governance Event Contract 就能直接補進現有流程。`UNKNOWN` 則原樣保留，不會因為已經有 Trace 就宣稱 Audit 完成。

## Traffic、Runtime 與 Control Plane 分開記帳

[Day 13](https://ithelp.ithome.com.tw/articles/10407809) 的 Gateway 選型最能顯示這種差異。LiteLLM 的 Routing、Virtual Key、Budget 與 UI 都有用，但當時的 Kubernetes Operating Model 需要額外維護 Team／User Identity Mapping 與 GitOps Glue。我們拒絕的是該方案在當時需求下的維運模型。後來的供應鏈事件是新增風險，不能倒寫成原始理由。

agentgateway 記為 `KEEP`，範圍只涵蓋 LLM、MCP、A2A Traffic 的 Policy、Routing 與 Telemetry。它不會因此取得 IdP、Agent Workflow、Tool Business Policy 或 Audit Storage 的 Owner 身分。

kagent 則拆成不同能力。[Day 18](https://ithelp.ithome.com.tw/articles/10409155) 證明它能提供 BYO Agent Deployment、Discovery、Agent-as-Tool 入口與相容的 HITL Pause／Resume。Runtime Dependency、Memory、Tool Policy、Filesystem、Approver Authorization 與 Framework Upgrade 仍由 Agent 作者負責。因此 BYO Runtime 是 `KEEP`，kagent Deployment／Discovery 和 HITL Contract 暫時是 `DEFER`。需要 Self-service Discovery 或統一操作面時，再用同一套 BYO、A2A、HITL 與 Actor Propagation Fixture 重驗。

這樣記帳後，「kagent 有沒有 HITL」不再是完整答案。真正的採用條件是組織是否需要那個 Control Plane，以及 Authentication、Authorization 與 Resume Contract 由誰維護。

## Registry、Artifact 與 Trust 分開處理

Agent Registry `0.3.3` 曾因 PostgreSQL／REST State 與既有 Git Source of Truth 衝突而被拆除。`0.4.0` 已改成 Declarative Control Plane，Lab 也驗證 Catalog、Deployment Reconciliation 與 Undeploy。版本號在此必須保留，因為前後兩版不是同一種控制面。

[Day 19](https://ithelp.ithome.com.tw/articles/10409470) 仍留下兩個採用風險：預設 Permissive Auth 接受匿名寫入，相同 `approved` Tag 也能指向另一個 Image。Controller 綠燈只能證明 Desired State 已收斂，不能證明 Artifact 不可變、Promotion 經過授權，或 Registry 已成為組織承認的 Source of Truth。

Ledger 因而把 Cross-team Registry 留在 `DEFER`，等 Catalog Owner、Git／Registry Write Path、Authn／Authz、Promotion 與 Audit 一起確定。Immutable Digest 與 Promotion Evidence 則直接 `ADOPT`，先補 Artifact 信任基線，不必等新平台落地。

## Telemetry 與 Audit 各自承擔的範圍

Alloy、Loki、Grafana、Tempo 與 Prometheus／Mimir 是既有核心，Day 20–26 只是把 Agent Runtime、agentgateway 與 MCP Traffic 接進來。它們已能回答 Latency、Error、Route、Tool Call、Cost Estimate 與跨服務 Correlation，因此 Telemetry 是 `KEEP`。

Trace Sampling、Export Failure、Backend Retention 和 Access Policy 仍會影響 Evidence Completeness。沒有 Event-time Signature、Append-only Storage 或 WORM Policy，也不能把 Loki Log 升格成不可否認的 Audit Record。Governance Event Schema 與 Replay Workflow 可以 `ADOPT`，Tamper-evident Audit Storage 則繼續 `UNKNOWN`。

成本採用同樣寫法。[Day 24](https://ithelp.ithome.com.tw/articles/10411731) 的 Gateway Estimate 可保留，Provider 沒回 Usage 的 Attempt 仍不能硬算成完整總額。`KEEP` 即時估算能力，不等於 Invoice-grade Attribution 已經通過驗收。

## 升級之後要重新驗什麼

「現在跑綠」不是永久屬性。agentgateway `1.4.x` 到 `1.5.0` 曾改變缺少 `iss`／`aud` 時的 JWT 驗證行為，Agent Registry `0.3.3` 到 `0.4.0` 更換了控制面設計。Ledger 的 Revalidation Surface 要把這種變化變成明確責任。

Identity 變更重驗 Callback、Scope、Claim、Audience 與 Gateway Policy。agentgateway 升級檢查 Route、Policy、Telemetry Schema 與官方 Dashboard。kagent 或 Agent Registry 則重跑 BYO、A2A、HITL、Actor Propagation、Artifact Mutation 與 Authz Fixture。LGTM 也不能只看 Pod Ready，Alloy Transform、Loki Metadata、Tempo Correlation、Retention 與 Query Result 都是 Contract 的一部分。

找不到 Owner，也說不出升級後怎麼驗的能力，今天的 Demo 還不足以成為 `KEEP`。這兩欄比功能數量更接近平台團隊真正要承擔的成本。

## 從 Ledger 排出導入順序

目前的 Ledger 建議維持 Cognito、agentgateway、BYO Runtime 與 LGTM，將 Artifact Promotion 和 Governance Event Contract 納入下一版基線。kagent、Agent Registry、HITL 與完整 Delegation Platform 等需求和 Owner 成立後再評估。Workload Instance Identity 與 Audit Integrity 仍缺少足夠 Evidence。

Ledger 知道缺什麼，還沒回答先做哪一項。Artifact Promotion 已有明確 Gap 與可執行 Owner，集中式 kagent／Registry Control Plane 則仍缺跨團隊需求，兩者不能只按風險名稱排序。Day 28 會從既有 LGTM、Identity 與單一 Gateway 出發，依副作用、共享範圍與 Owner 排出一條可以停留、也可以繼續前進的導入路徑。
