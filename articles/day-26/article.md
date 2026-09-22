# Day 26｜Agent 事件回放實戰：用 Trace ID 重建 Tool Call 與 Audit 缺口

Day 25 的 SRE Agent 已經能從 Loki Result 拿到 `trace_id`。把這串 ID 貼進 Tempo，可以沿著 Spans 找到 agentgateway、Agent Runtime 和 MCP Server，也很容易把完整的瀑布圖當成事故證據。可是當問題變成「誰授權這次 Tool Call？跑的是哪個 Agent Artifact？Approval 有沒有真的發生？」Trace 就不再足夠。

我把 Day 1 那次危險 Tool Call 拿回來重建，第一個問題甚至不是缺少 Principal，而是同一條 Trace 裡有兩個 Actions。Agent 先提出 `delete_demo_database`，後面又呼叫 `query_metrics`。只依 `trace_id` 排序，很容易讓後一個 Tool 的成功結果蓋掉前面已觸發的 Canary，這正是 Day 1 曾經修過的 Summary Bug。

更重要的是，Day 1 只留下本機 JSONL、Manifest 與 No-op Canary Receipt，沒有任何資料能證明這串 Trace ID 當時曾進入 Tempo 或 Loki。Day 26 的 [Lab 05 README](https://github.com/MikeHsu0618/2026-ithelp-agent-governance-public/blob/day-20-r1/labs/05-incident-replay/README.md) 因此把兩件事分開：一邊回放鎖定的 Day 1／Day 3 歷史 Artifacts，另一邊重新跑一筆現行 Action，驗證今天的 LGTM Pipeline 能保存什麼。兩組資料可以比較，不能合併成同一場事故。

![上半部是 Day 1 歷史 Artifact，經 replay projection 產生帶證據狀態的 Governance Event。下半部是 Day 26 另跑的新 action，由 Tempo、Loki 與 Prometheus 分別提供 request path、structured event 與 aggregate metrics。兩個 run 以虛線分開，不能混成同一場事故。](https://raw.githubusercontent.com/MikeHsu0618/2026-ithelp-agent-governance-public/day-20-r1/assets/diagrams/day-26/replay-evidence-boundary.png)

## Trace、Action 與 Event 的粒度

Day 1 的八筆 Events 包含共用的 `run.started`、`run.completed`，以及兩組 Tool Call：

```text
delete_demo_database
  model.tool_call -> policy.decision -> tool.executed

query_metrics
  model.tool_call -> policy.decision -> tool.executed
```

本文只回放 `delete_demo_database`，所以 Timeline 保留共用 Run Events 和目標 Tool 的三筆 Action Events。`query_metrics` 即使位於同一條 Trace，也不能加入這個 Action 的結論。

三種識別負責不同粒度：

| ID | 粒度 | 適合回答的問題 |
| --- | --- | --- |
| `trace_id` | 一次跨服務執行 | Request 經過哪些 Services，哪一段延遲或失敗 |
| `action_id` | 一個治理動作 | Tool Proposal、Policy Decision 與 Effect 是否屬於同一個 Action |
| `event_id` | 一筆治理事件 | Normalized Event 是哪筆紀錄，是否重複寫入 |

舊資料只有 `trace_id` 與 `span_id`。Replay 工具不會倒推一個不存在的原始 Action ID，而是替今天產生的 Projection 建立 `evt-replay-*`，並標示為 `RECONSTRUCTED_GOVERNANCE_EVENT`。它識別的是 Day 26 的重建結果，不是假裝 Day 1 當時就有完整事件模型。

## 每個欄位都有證據狀態

Governance Event v1 替欄位保存 `value`、`status`、`sources` 與 `reason`。四種狀態不是資料品質分數，而是限制讀者可以做出的推論：

- `VERIFIED`：這次 Replay 能重新驗證，例如輸入檔符合 Repository Lock。
- `OBSERVED`：原始 Artifact 有這個值，但沒有獨立來源背書。
- `UNKNOWN`：當時沒有留下足夠資料，不能把空白解釋成安全、未發生或不存在。
- `NOT_APPLICABLE`：流程走到這裡本來就不該產生該欄位。

Day 1 重建後，Tool、Policy 與 Canary 都有來源，Identity 與 Approval 則沒有：

| 欄位 | 值 | 狀態 | 原因 |
| --- | --- | --- | --- |
| `trace_id` | `a281375f...11c9b` | `OBSERVED` | Manifest 與 Event Stream 都有記錄 |
| `target.tool` | `delete_demo_database` | `OBSERVED` | Proposal、Policy 與 Execution Event 能對上 |
| `policy.decision` | `ALLOW` | `OBSERVED` | Runtime 寫下決策，沒有獨立 Decision Receipt |
| `result.effect_receipt` | `CANARY_TRIGGERED` | `OBSERVED` | No-op Canary 另有 Artifact |
| `identity.principal` | `null` | `UNKNOWN` | 沒有 Verified Human 或 Service Principal |
| `agent.artifact_digest` | `null` | `UNKNOWN` | 沒記 Image Digest 或 Deployment Revision |
| `approval` | `null` | `UNKNOWN` | 無法分辨沒做 Approval，還是做過但未記錄 |
| `backend_presence.tempo` | `null` | `UNKNOWN` | 沒有舊 Trace 的 Tempo Receipt |

這張表故意不把每格填滿。從 Username、Pod Name 或 Model Name 猜出一個 Principal，只會讓資料看起來完整，不能增加可信度。Runtime 寫下 `ALLOW` 也只證明它曾輸出這個值，沒有獨立 Policy Receipt 時仍屬 `OBSERVED`。

## DENY Action 的合理空白

Day 3 的 `POLICY_DENIED` 是一組重要對照。模型仍提出 `delete_demo_database`，Keyword Guard 也因混淆字串而放行，但 Tool Allowlist 在執行前做出 `DENY`。Timeline 因此沒有 `tool.executed`，Canary 檔也是空的。

這時 Effect Receipt 應是 `NOT_APPLICABLE`，因為 Policy 已經終止執行路徑。若 Decision 是 `ALLOW`，卻找不到 Tool Result 或 Effect Receipt，才應標成 `UNKNOWN`。要求所有 Actions 都填入 Effect，只會逼實作者替被拒絕的動作補造一張 Receipt，反而抹掉控制真正生效的事實。

不同 Tool 需要不同 Effect Evidence。讀取類 Tool 可以保存 Response Digest 或 Query Outcome，修改 Kubernetes 資源則要看 Resource Version、Controller Status 或 Read-after-write。建立工單應留下 Ticket ID 與後端 API Receipt。HTTP `200`、Span End 或 Function Return 都只是執行過程，不能自動證明 Domain Effect。

## 現行 LGTM 的回放能力

歷史 Replay 完成後，Lab 另送一筆新的 `normal-call`。它有獨立的 Action ID 和 Trace ID，再分別查 Tempo、Loki 與 Prometheus。這不是替 Day 1 補件，而是驗收現行 Instrumentation。

![Grafana Explore 的 Tempo trace 實跑畫面。查詢指定 trace ID，結果顯示 ithelp-lab-client、agentgateway、agent-runtime 與 mcp-adapter 四個 service，共八個 spans。路徑包含 Agent request、Gateway、Runtime、MCP Call 與 Tool execution。](https://raw.githubusercontent.com/MikeHsu0618/2026-ithelp-agent-governance-public/day-20-r1/assets/screenshots/day-26/grafana-tempo-action-trace.png)

Tempo 顯示 `ithelp-lab-client → agentgateway → agent-runtime → agentgateway → mcp-adapter` 的 Request Path，Loki 找到四行帶相同 `action_id` 的 Structured Events。OpenTelemetry LogRecord 可以帶 Trace ID 與 Span ID，Resource 則描述哪個 Service 送出資料，三者本來就負責不同關聯層級。

| Backend | 本次結果 | 能證明 | 不能單獨證明 |
| --- | --- | --- | --- |
| Tempo | 4 Services、8 Spans | 跨服務 Request Path 與時間關係 | Principal 已驗證、Audit 沒漏事件 |
| Loki | 4 Lines 命中 `action_id` | 各元件寫下相關 Structured Event | 儲存不可竄改、每個 Effect 都有 Receipt |
| Prometheus | Gateway Metrics 正常收集 | 整體流量與錯誤趨勢 | 某個 Action 的逐筆責任鏈 |

Prometheus 適合聚合，不需要為了事件回放加入 `action_id`。把單筆關聯硬塞進 Metric Labels，只會把 Day 23 的 Cardinality 問題帶回來。

## Repository Lock 的證明範圍

Day 1 與 Day 3 的 Case Directory 各有 `evidence-lock.json`。Replay 前會重新計算 Manifest、Events 與 Canary 檔案的 SHA-256，有任何差異就停止。這能避免文章、測試與輸入 Artifact 在後續編輯中悄悄漂移。

Repository Lock 是 Day 26 才建立的，只能證明目前副本和 Lock 相符，不能倒過來證明 Day 1 事件發生後從未被修改。更強的 Audit Integrity 還需要 Event-time Signature 或 Hash Chain、Append-only／WORM Storage、Writer Permission、Export Audit、Retention 與 Legal Hold。這些條件不存在時，`VERIFIED` 只描述本次可重算的 Hash，不代表不可否認性。

Telemetry 也有相同限制。Sampling、Collector Failure、Exporter Retry 與不同 Backend Retention 都會造成缺口。OpenTelemetry 很適合統一資料模型與 Correlation，沒有承諾每個 Backend 一定完整收到、永久保存或無法刪改。

## 重跑 Incident Replay

完整 Replay 與現行 Backend 驗證可從 Repo Root 執行：

```bash
make -f publication/Makefile.public lab-05-run
```

Lab 會先檢查兩組 Evidence Locks，再啟動 self-hosted LGTM Stack，輸出 Day 1 Replay、Day 3 Control Case 與 Modern Reference 三份結果。啟動、清理、Schema、完整 Commands 與 Machine-readable Evidence 都留在 Lab README。

欄位定義可直接查看 [AI Governance Event Schema v1](https://github.com/MikeHsu0618/2026-ithelp-agent-governance-public/blob/day-20-r1/labs/05-incident-replay/src/incident_replay/schemas/replay-event-v1.schema.json)，若要替自己的事件逐欄標示來源與狀態，Repo 另附 [Incident Replay 欄位指南](https://github.com/MikeHsu0618/2026-ithelp-agent-governance-public/blob/day-20-r1/articles/day-26/incident-replay-field-guide.md)。

## Trace 之後的責任

Day 26 能從歷史 Artifact 找回 Tool、Resource、Policy Decision 與 Canary Result。Principal、Delegation、Agent Artifact、Credential、Approval 和原始儲存完整性仍然是 `UNKNOWN`。現行 LGTM 可以把新的 Action 串過四個 Services，沒有資格回頭替舊事件補造不存在的證據。

這些 `UNKNOWN` 會直接成為 Day 27 的輸入。下一篇不再增加產品或 Lab，而是把治理能力的來源、證據、Owner 與升級負擔放進同一份 Capability Ledger。Trace 能幫 SRE 找到問題，最後仍需要有人對缺失的控制與證據負責。
