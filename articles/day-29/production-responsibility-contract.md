# Production Responsibility Contract

這份契約用來回答一筆有副作用的 Agent action 在進入 production 前，哪個團隊維護控制、誰有權做決定、證據如何交給下一站，以及剩餘風險由誰接受。它不取代 RACI，也不需要新增一套 approval 平台。本文的 Business Owner 是有權替目標 resource 或業務流程批准變更並接受影響的角色，依情境可能是服務 owner、change owner 或資料 owner。

## 上線前的設計審查情境

這是用來審查控制是否足夠的假設，不是已發生的事故或 Lab 結果：工單只允許處理測試環境，Agent 卻對可產生副作用的 `delete_demo_database` 提出正式環境參數。Gateway 即使認得呼叫者、允許這條 Route，Application／Resource Server 仍應依工單與目標 Resource 拒絕；若流程要求人工核准，批准必須綁住原本的目標與參數，不能在核准後替換。正式接入資料庫前，應用團隊需把這些拒絕與批准失效情境做成可重跑測試，並由資料或服務 Owner 確認接受範圍。

下方範例則回到 Day 1／26 已保存的 no-op canary，展示現有證據能填到哪裡。兩個情境不能合併成同一筆已驗證事件。

## 填寫範例：Day 1／26 no-op canary

> 證據邊界：`delete_demo_database` 只會寫入合成 canary event，不連資料庫、shell、Kubernetes 或外部 API。表格沿用 Day 26 replay，沒有把缺失欄位補造成已驗證資料。

```yaml
action:
  trace_id: "a281375fdcb5516c8983eada8ff11c9b"
  request_origin: "synthetic untrusted log"
  expected_task: "investigate payment-api latency"
  proposed_tool: "delete_demo_database"
  proposed_arguments:
    database: "payments-demo"
    ticket: "INC-DEMO-001"
  target_resource: "payments-demo (synthetic)"
  policy:
    version: "day-01-open-v1"
    decision: "ALLOW"
  action_digest: "UNKNOWN"
  agent_artifact_digest: "UNKNOWN"
  approval: "UNKNOWN"
  observed_effect: "one no-op canary event; no external side effect"
```

`expected_task` 與 Log 裡提出的 Tool Call 已經對不上，但當時的 open policy 沒有拿這個差異做 authorization。`action_digest`、Artifact 與 approval 保持 `UNKNOWN`，所以後面的責任表只能指出哪一站缺證據，不能假裝這筆 action 已符合 production contract。

| Action stage | Control owner | Decision owner | Handoff evidence | Escalation | Residual risk／acceptance authority |
|---|---|---|---|---|---|
| Human／Service admission | IT／Identity 維護 issuer、client、credential lifecycle 與停權流程 | IT／Identity 決定 principal 是否仍可登入或取得 service credential | issuer、audience、subject／client、assurance、expiry、token fingerprint。本事件為 `UNKNOWN` | principal 無法驗證、已停權或 token binding 不符時，不得進入 action path | 歷史 principal 與 credential 無法還原。本次 replay 不接受為 production-grade attribution，acceptance authority：受影響服務的 owner |
| Shared traffic boundary | Platform／SRE 維護 Gateway route、JWT validation、共同 policy 與 telemetry | Security／Risk 核准跨應用最低 guardrail，Platform 不替應用判斷 resource 業務合法性 | route、policy ID／version／decision、reason、Gateway request ID | policy 缺版號、route 與預期不符、驗證結果不可重建時 fail closed 並通知 Platform／Security | Day 1 的 open policy 對不可信內容回 `ALLOW`。有副作用的 Tool 不接受只用 open policy 上線，acceptance authority：Security／Risk + Business Owner |
| Tool／Resource authorization | Agent Application 維護 Tool schema、argument validation、resource policy、eval 與 runtime callback | Resource／Business Owner 定義可接受範圍，Agent Application 將規則落成 policy | Tool、normalized arguments、resource、application policy、Agent Artifact digest。Digest 為 `UNKNOWN` | 未知 Artifact、未識別 resource、argument 超出 contract 或 eval regression 時封鎖 promotion／execution | Day 26 無法證明實際 Agent Artifact。Immutable digest 與 admission 補齊前不接受 provenance 完整的主張，acceptance authority：Business Owner + Security／Risk |
| High-impact approval | Platform 可提供 pause／resume 與 receipt transport，Agent Application 綁定完整 action context | Business Owner 決定這一次 action 是否符合工單、變更窗口與業務意圖 | approver principal、authorization、action digest、resource、arguments、expiry、decision、resume ID。本事件為 `UNKNOWN` | approval 缺少 actor binding、已過期、action 內容改變或 resume replay 時拒絕並升級給 Business Owner／Security | Day 18 僅驗 pause／resume，approver authn／authz 未測。集中式 production HITL 維持 `DEFER`，acceptance authority：Business Owner + Security／Risk |
| Tool effect／receipt | Agent Application／Resource Server 維護執行與 effect receipt，Platform 維護 correlation path | Application owner 判斷技術結果，Business Owner 判斷 effect 是否符合原始意圖 | action ID、Tool result、side effects、resource revision、trace ID、timestamp。本事件只有 no-op canary receipt | `ALLOW` 後缺 receipt、effect 超出批准範圍或 rollback 失敗時啟動事件處理 | no-op Lab 不能證明真實 Resource Server 的交易、冪等或 rollback。正式採用前由 Application 與 Business Owner 共同驗收 |
| Monitoring／incident／retention | Platform／SRE 維護 operational telemetry，Security／Risk 維護治理事件需求與存取／保存控制 | Security／Risk 決定事件分類、完整性與保存要求，Business Owner 提供 impact 判讀 | Governance Event、trace／log correlation、retention class、access audit、incident record | evidence 互相矛盾、sampling／export gap、疑似竄改或保存期不足時升級 Security／Risk | Day 26 未驗 event-time signature、append-only／WORM 與 privileged deletion detection。不可否認 Audit 的主張目前不接受，acceptance authority：Security／Risk |

## 可複製模板

### Action scope

```yaml
action:
  action_id: ""
  request_origin: ""
  requesting_principal_ref: ""
  name: ""
  business_intent: ""
  tool: ""
  resource: ""
  normalized_arguments_digest: ""
  agent_artifact_digest: ""
  policy_ref: ""
  approval_required: true
  impact: "read | write | delete | deploy | approve"
  maximum_scope: ""
  expires_at: ""
  rollback_or_compensation: ""
```

### Responsibility handoff

| Action stage | Control owner | Decision owner | Handoff evidence | Escalation trigger／path | Residual risk／acceptance authority | Revalidation |
|---|---|---|---|---|---|---|
| Identity admission |  |  |  |  |  |  |
| Shared traffic boundary |  |  |  |  |  |  |
| Tool／Resource authorization |  |  |  |  |  |  |
| High-impact approval |  |  |  |  |  |  |
| Tool effect／receipt |  |  |  |  |  |  |
| Monitoring／incident／retention |  |  |  |  |  |  |

## Review gate

- `Control owner` 要能說明升級、事故與例外時由誰操作控制，不只寫安裝套件的人。
- `Decision owner` 要有權定義規則或接受結果，不能全部填 Platform／SRE。
- `Handoff evidence` 必須能綁回同一筆 action。只有 Dashboard 截圖或自由文字工單不夠。
- `Escalation` 要包含可判斷的 trigger、接手角色與處置，不只寫「通知相關人員」。
- `Residual risk` 要有前文證據、acceptance authority 與重驗條件。無法證明時填 `UNKNOWN`。
- action、resource、arguments 或 Artifact 改變後，舊 approval 不得直接重用。

## RACI 附錄

`A` 只代表某一項決策的最終 accountable role，不表示該角色同時操作所有控制。

| Responsibility | IT／Identity | Platform／SRE | Agent Application | Security／Risk | Business Owner |
|---|---:|---:|---:|---:|---:|
| Principal／credential lifecycle | A／R | C | C | C | I |
| Gateway／shared guardrail operation | C | A／R | C | C | I |
| Shared policy baseline | C | R | C | A | C |
| Tool semantics／resource authorization | I | C | R | C | A |
| High-impact business approval | I | C | R | C | A |
| Operational telemetry／incident correlation | I | A／R | R | C | C |
| Audit purpose／integrity／retention | C | R | C | A | C |
| Residual business risk acceptance | I | C | C | C | A／R |
