# Day 26｜Agent 事件回放實戰：用 Trace ID 重建 Tool Call 與 Audit 缺口

Day 25 的 SRE Agent 已經能從 Loki Result 拿到 `trace_id`。把這串 ID 貼進 Tempo，可以沿著 Spans 找到 agentgateway、Agent Runtime 和 MCP Server，也很容易把完整的瀑布圖當成事故證據。可是當問題變成「誰授權這次 Tool Call？跑的是哪個 Agent Artifact？Approval 有沒有真的發生？」Trace 就不再足夠。

我把 Day 1 那次危險 Tool Call 拿回來重建，第一個問題甚至不是缺少 Principal，而是同一條 Trace 裡有兩個 Actions。Agent 先提出 `delete_demo_database`，後面又呼叫 `query_metrics`。只依 `trace_id` 排序，很容易讓後一個 Tool 的成功結果蓋掉前面已觸發的 Canary，這正是 Day 1 曾經修過的 Summary Bug。

更重要的是，Day 1 只留下本機 JSONL、Manifest 與 No-op Canary Receipt，沒有任何資料能證明這串 Trace ID 當時曾進入 Tempo 或 Loki。Day 26 的 [Lab 05 README](https://github.com/MikeHsu0618/2026-ithelp-agent-governance-public/blob/day-21-r3/labs/05-incident-replay/README.md) 因此把兩件事分開：一邊回放鎖定的 Day 1／Day 3 歷史 Artifacts，另一邊重新跑一筆現行 Action，驗證今天的 LGTM Pipeline 能保存什麼。兩組資料可以比較，不能合併成同一場事故。

![上半部是 Day 1 歷史 Artifact，經 replay projection 產生帶證據狀態的 Governance Event。下半部是 Day 26 另跑的新 action，由 Tempo、Loki 與 Prometheus 分別提供 request path、structured event 與 aggregate metrics。兩個 run 以虛線分開，不能混成同一場事故。](https://raw.githubusercontent.com/MikeHsu0618/2026-ithelp-agent-governance-public/day-21-r3/assets/diagrams/day-26/replay-evidence-boundary.png)

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

歷史 Replay 完成後，Lab 另送一筆新的 `normal-call`，用它自己的 Action ID 和 Trace ID 分別查 Tempo、Loki 與 Prometheus。舊紀錄回答當年留下了什麼。新請求回答今天的 Instrumentation 能查到什麼。

![Grafana Explore 的 Tempo trace 實跑畫面。查詢指定 trace ID，結果顯示 ithelp-lab-client、agentgateway、agent-runtime 與 mcp-adapter 四個 service，共八個 spans。路徑包含 Agent request、Gateway、Runtime、MCP Call 與 Tool execution。](https://raw.githubusercontent.com/MikeHsu0618/2026-ithelp-agent-governance-public/day-21-r3/assets/screenshots/day-26/grafana-tempo-action-trace.png)

Tempo 顯示 `ithelp-lab-client → agentgateway → agent-runtime → agentgateway → mcp-adapter` 的 Request Path，Loki 找到四行帶相同 `action_id` 的 Structured Events。OpenTelemetry LogRecord 可以帶 Trace ID 與 Span ID，Resource 則描述哪個 Service 送出資料，三者本來就負責不同關聯層級。

| Backend | 本次結果 | 能證明 | 不能單獨證明 |
| --- | --- | --- | --- |
| Tempo | 4 Services、8 Spans | 跨服務 Request Path 與時間關係 | Principal 已驗證、Audit 沒漏事件 |
| Loki | 4 Lines 命中 `action_id` | 各元件寫下相關 Structured Event | 儲存不可竄改、每個 Effect 都有 Receipt |
| Prometheus | Gateway Metrics 正常收集 | 整體流量與錯誤趨勢 | 某個 Action 的逐筆責任鏈 |

Prometheus 適合聚合，不需要為了事件回放加入 `action_id`。把單筆關聯硬塞進 Metric Labels，只會把 Day 23 的 Cardinality 問題帶回來。

## 重跑時確認事件檔案沒變

Day 1 與 Day 3 的 Case Directory 各有 `evidence-lock.json`。Replay 前會重新計算 Manifest、Events 與 Canary 檔案的 SHA-256，有任何差異就停止。這能避免文章、測試與輸入 Artifact 在後續編輯中悄悄漂移。

Repository Lock 是為了讓 Lab 重跑時讀到同一份輸入，Git Commit 也保留文章與設定的版本變更。它們足以處理這裡的重現需求，但不是每次 Agent 執行都會留下 Git Commit。實際呼叫仍要從 Gateway、Runtime、Tool 和後端的紀錄查。若組織另有長期保存或法遵要求，再檢查既有紀錄能否滿足。

Telemetry 適合把這些執行紀錄串起來，卻仍可能因 Sampling、Collector 故障或 Backend 保存期限而缺少資料。因此 Trace 查不到某筆動作時，要回頭確認哪一站原本應該寫入，而不是立刻把空白解讀成「沒有發生」。

## 重跑 Incident Replay

完整 Replay 與現行 Backend 驗證可從 Repo Root 執行：

```bash
make -f publication/Makefile.public lab-05-run
```

Lab 會先檢查兩組 Evidence Locks，再啟動 self-hosted LGTM Stack，輸出 Day 1 Replay、Day 3 Control Case 與 Modern Reference 三份結果。啟動、清理、Schema、完整 Commands 與 Machine-readable Evidence 都留在 Lab README。

欄位定義可直接查看 [AI Governance Event Schema v1](https://github.com/MikeHsu0618/2026-ithelp-agent-governance-public/blob/day-21-r3/labs/05-incident-replay/src/incident_replay/schemas/replay-event-v1.schema.json)，若要替自己的事件逐欄標示來源與狀態，Repo 另附 [Incident Replay 欄位指南](https://github.com/MikeHsu0618/2026-ithelp-agent-governance-public/blob/day-21-r3/articles/day-26/incident-replay-field-guide.md)。

## Trace 之後的責任

歷史 Artifact 能找回 Tool、Resource、Policy Decision 與 Canary Result。Principal、Delegation、Agent Artifact、Credential、Approval 和原始儲存完整性仍是 `UNKNOWN`。新 Action 雖然已能跨四個 Services 查詢，也改變不了舊事件的紀錄缺口。

這些空白把問題帶到 Day 27：身分在哪裡驗、Agent 從哪裡交付、Tool 在哪裡執行、最後又去哪裡查。下一篇會把前面登場的產品放回同一筆請求與交付路徑，讓讀者看出各系統負責哪段，而不是把缺的欄位直接變成產品採購清單。
