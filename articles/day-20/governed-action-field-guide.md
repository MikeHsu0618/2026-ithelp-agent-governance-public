# Governed Action Field Set v0.1 放置指南

這份表是 Day 20 公開 Lab 的作者定義，不是 OpenTelemetry semantic convention。它的用途是先定義跨 Agent Runtime、Gateway 與 Tool 都能理解的責任資料，再決定每個 producer 應該送出哪些訊號。

| 欄位 | 必填 | 主要來源 | 放置建議 | 判讀重點 |
| --- | --- | --- | --- | --- |
| `event_id` | 是 | Event producer | Governance Event | 單一事件的不可重複識別，不能拿來取代跨事件的 action ID |
| `action_id` | 是 | Agent Runtime／入口協調層 | Application Record、Trace、Governance Event | 串起一次 Agent action 的穩定 key |
| `trace_id`／`span_id` | 是 | OpenTelemetry SDK | Trace、Governance Event | 串起執行路徑，但不能單獨證明身分或授權 |
| `principal.id`／`kind` | 是 | 已驗證的 IdP／Gateway context | Governance Event，Trace 可投影非敏感值 | 必須和 UI hint、request body 裡自稱的 user 分開 |
| `principal.assurance`／`source` | 是 | 驗證邊界 | Governance Event | 說明 `VERIFIED`、`ASSERTED` 或 `UNKNOWN` 的依據 |
| `delegation.on_behalf_of` | 是 | Agent Runtime／delegation service | Governance Event | 分開 end user 與目前執行者 |
| `delegation.actor_chain` | 是 | 各 hop 累積並受邊界驗證 | Governance Event | Human → Agent → Workload 的 ordered chain |
| `workload.*` | 是 | Runtime／workload identity | Governance Event | 本 Lab 只有 fixture assertion，因此標成 `ASSERTED` |
| `agent.name`／`version` | 是 | Runtime deployment metadata | Trace、Governance Event | 版本字串用來定位 release，不能取代 digest |
| `agent.artifact_digest` | 是 | Registry／deployment admission | Governance Event | 要能回到實際執行 Artifact，而不是可變 tag |
| `target.tool`／`resource` | 是 | Tool invocation／Gateway | Trace、Governance Event | Tool 名稱不足以授權，還要知道 resource |
| `policy.id`／`version` | 是 | Policy decision point | Governance Event | 沒有版本就無法重建當時套用的規則 |
| `policy.decision`／`enforcement_point` | 是 | Enforcement point | Governance Event，Trace 可投影 bounded value | 記錄哪個邊界真的做了 `ALLOW`／`DENY` |
| `approval.status` | 是 | HITL／workflow engine | Governance Event | 沒有審批流程時用 `NOT_APPLICABLE`，不要假裝 `APPROVED` |
| `result.status` | 是 | Runtime／Tool adapter | Application Record、Governance Event | 流程狀態，不代表真實副作用已完成 |
| `result.effect` | 是 | Tool／domain system receipt | Governance Event | 記錄副作用種類、狀態與數量。缺證據時應是 `UNKNOWN`，不是成功 |

## 三種資料各自保留什麼

| 資料 | 適合保存 | 不應單獨拿來證明 |
| --- | --- | --- |
| Application Record | session、generation、UI actor hint、Tool request/result summary | verified identity、policy enforcement、不可否認的 effect |
| Operational Telemetry | latency、error、call graph、service／span、有限的 correlation attributes | 完整 delegation、長期 Audit integrity、每個 domain effect |
| Governance Event | principal assurance、actor chain、Artifact、resource、policy、approval、effect evidence | 所有 raw prompt、完整 Tool output 或高基數操作明細 |

Machine-readable schema 位於 [`labs/04-telemetry-pipeline/src/traceability_lab/schemas/governed-action-v0.1.schema.json`](../../labs/04-telemetry-pipeline/src/traceability_lab/schemas/governed-action-v0.1.schema.json)。
