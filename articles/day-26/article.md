# Day 26｜Agent 事件回放實戰：用 Trace ID 重建 Tool Call 與 Audit 缺口

Day 25 的 SRE Agent 已經能從 Loki result 拿到 `trace_id`。拿到這串 ID 之後，最直覺的做法是貼進 Tempo，沿著 span 找到 agentgateway、Agent Runtime 和 MCP Server，再把畫面截下來當成事故證據。這條路很適合除錯，但如果有人接著問：「是誰授權這次 Tool Call？當時跑的是哪個 Agent artifact？Approval 有沒有真的發生？」一張完整的瀑布圖仍然答不出來。

我把 Day 1 那次 `CANARY_TRIGGERED` 的 live run 拿回來重建，才發現問題甚至比缺幾個欄位更麻煩。那條 trace 裡一共有八筆 event，Agent 先提出 `delete_demo_database`，接著又呼叫 `query_metrics`。如果只依 `trace_id` 把所有紀錄排成一列，很容易把兩個 Tool 的結果合成一個 action。更現實的是，Day 1 當時只有本機 JSONL、manifest 與 no-op canary receipt，根本沒有證據能證明這串 ID 曾經進過 Tempo 或 Loki。

所以今天的 [公開 Lab](https://github.com/MikeHsu0618/2026-ithelp-agent-governance-public/blob/day-27/labs/05-incident-replay/README.md) 不會把舊 JSON 塞進 Tempo，再假裝當年就有完整 telemetry。它做兩件分開的事：先從鎖定的歷史 Artifact 誠實回放 Day 1 與 Day 3，再另跑一筆現行 action，驗證現在的 LGTM pipeline 能留下哪些證據。兩邊可以比較，不能合併成同一場事故。

![上半部是 Day 1 歷史 Artifact，經 replay projection 產生帶證據狀態的 Governance Event。下半部是 Day 26 另跑的新 action，由 Tempo、Loki 與 Prometheus 分別提供 request path、structured event 與 aggregate metrics。兩個 run 以虛線分開，不能混成同一場事故。](https://raw.githubusercontent.com/MikeHsu0618/2026-ithelp-agent-governance-public/day-27/assets/diagrams/day-26/replay-evidence-boundary.png)

## 一條 Trace 裡不只一個 Action

`trace_id` 描述的是一次分散式執行路徑，不保證裡面只有一個 Tool Call。Day 1 的八筆 event 可以拆成下面兩組：

```text
delete_demo_database
  model.tool_call -> policy.decision -> tool.executed

query_metrics
  model.tool_call -> policy.decision -> tool.executed
```

前後還有共用的 `run.started` 與 `run.completed`。今天要回放的是 `delete_demo_database`，因此 timeline 只保留共用 run event 和目標 Tool 的三筆 action event，不能因為 `query_metrics` 也在同一條 trace，就把它的 `SUCCESS` 當成整次執行的結論。這正是 Day 1 曾經踩過的 summary bug：後面的成功結果一度蓋掉前面已經觸發的 canary。

實務上我會把三種 ID 分開使用：

| ID | 粒度 | 適合回答的問題 |
|---|---|---|
| `trace_id` | 一次跨服務執行 | 請求經過哪些 service、哪一段延遲或失敗？ |
| `action_id` | 一個治理動作 | 這次 Tool Call、policy decision 與 effect 是否屬於同一個 action？ |
| `event_id` | 一筆治理事件 | 這筆 normalized event 是哪一筆紀錄，是否重複寫入？ |

舊資料只有 `trace_id` 與 `span_id`，所以 Lab 不會倒推一個「原始 action ID」。它會另外產生 `evt-replay-*`，明確標成 `RECONSTRUCTED_GOVERNANCE_EVENT`。這個 ID 只識別今天產生的 projection，不會冒充 Day 1 當時就存在的事件編號。

## 回放時，未知也要原樣保留

Lab 的 Governance Event v1 為每個欄位附上 `value`、`status`、`sources` 與 `reason`。狀態只有四種：

- `VERIFIED`：本次 replay 能重新驗證，例如輸入檔符合 repository lock 的 SHA-256。
- `OBSERVED`：原始 Artifact 有這個值，但沒有另一個獨立來源替它背書。
- `UNKNOWN`：當時沒有留下足夠資料，不能從空白推論成安全、未發生或不存在。
- `NOT_APPLICABLE`：依流程本來就不該有這筆資料，例如 policy 已經拒絕 Tool，自然沒有 effect receipt。

Day 1 重建後的關鍵欄位如下：

| 欄位 | 值 | 狀態 | 原因 |
|---|---|---|---|
| `trace_id` | `a281375f...11c9b` | `OBSERVED` | manifest 與 event stream 都有記錄 |
| `target.tool` | `delete_demo_database` | `OBSERVED` | proposal、policy 與 execution event 都能對上 |
| `policy.decision` | `ALLOW` | `OBSERVED` | Runtime 寫下決策，但沒有獨立 decision receipt |
| `result.effect_receipt` | `CANARY_TRIGGERED` | `OBSERVED` | no-op canary 另有一筆 Artifact |
| `identity.principal` | `null` | `UNKNOWN` | 沒有 verified human 或 service principal |
| `agent.artifact_digest` | `null` | `UNKNOWN` | 沒記 image digest 或 deployment revision |
| `approval` | `null` | `UNKNOWN` | 不知道沒有 approval，還是有做但沒記錄 |
| `backend_presence.tempo` | `null` | `UNKNOWN` | 不能證明舊 trace 曾送進 Tempo |

以下是實際輸出的兩個欄位。差異不在 `null`，而是為什麼它只能是 `UNKNOWN`：

```json
{
  "identity": {
    "principal": {
      "value": null,
      "status": "UNKNOWN",
      "sources": [],
      "reason": "No verified human or service principal was recorded for the original run."
    }
  },
  "policy": {
    "decision": {
      "value": "ALLOW",
      "status": "OBSERVED",
      "sources": ["events.jsonl:policy.decision"],
      "reason": "The runtime emitted the policy decision, but no independent decision receipt exists."
    }
  }
}
```

這種寫法看起來沒有把表格填滿，卻比事後從 username、pod name 或 model name 猜身分可靠。Day 4 講過的 Confused Deputy 問題，在鑑識階段仍然成立。請求聲稱自己是誰，不等於平台已經驗證誰，Runtime 名稱也不能拿來證明 workload identity。

## `DENY` 之後沒有執行紀錄，反而是合理結果

Day 3 的 `POLICY_DENIED` 是一組很有用的 control case。它有自己的 trace ID `b24163e4...f06b9`，和 Day 1 不是同一場 run。模型仍提出 `delete_demo_database`，keyword guard 也因為混淆字串而放行，但 Tool allowlist 在 action boundary 做出 `DENY`，因此 timeline 裡沒有 `tool.executed`，canary 檔也是空的。

如果 replay 工具要求每個 action 都必須有 effect receipt，這筆事件不是被標成壞資料，就是有人補造一個 `DENIED` receipt 讓 schema 好看。Lab 選擇 `NOT_APPLICABLE`：policy decision 已經終止執行路徑，沒有 effect 才符合預期。相反地，若 decision 是 `ALLOW`，卻找不到 Tool result 或 effect receipt，狀態才應該是 `UNKNOWN`，並留給事故調查繼續追。

這個區分也適用於其他 Action。讀取類 Tool 可能用 response digest 或 query outcome 作 receipt。修改 Kubernetes 資源時，還得看 resource version、controller status 或 read-after-write。若動作是建立工單，則應保留 ticket ID 與後端 API receipt。`HTTP 200`、span 結束或 Tool function return 都只是過程，不會自動變成 domain effect 的證明。

## 現行 LGTM 能多回答哪些問題

歷史 replay 跑完後，Lab 04 會另送一筆新的 `normal-call`。這次產生獨立的 `action_id=act-normal-call-735491db` 與 `trace_id=c37ea024...75c56`，再分別查 Tempo、Loki 與 Prometheus。它不是 Day 1 的補件，而是對現行 instrumentation 做一次驗收。

![Grafana Explore 的 Tempo trace 實跑畫面。查詢指定 trace ID，結果顯示 ithelp-lab-client、agentgateway、agent-runtime 與 mcp-adapter 四個 service，共八個 spans。路徑包含 Agent request、Gateway、Runtime、MCP Call 與 Tool execution。](https://raw.githubusercontent.com/MikeHsu0618/2026-ithelp-agent-governance-public/day-27/assets/screenshots/day-26/grafana-tempo-action-trace.png)

這張圖能證明該 trace 在 Tempo 出現，也能看見 `ithelp-lab-client → agentgateway → agent-runtime → agentgateway → mcp-adapter` 的 request path。Loki 另外找到四行帶同一個 `action_id` 的 structured event。這符合 OpenTelemetry 的設計。LogRecord 可以帶 `TraceId` 與 `SpanId`，讓 log 和 trace 以 execution context 關聯，而 `Resource` 描述的是哪個 service 送出資料。[OpenTelemetry Logs Data Model](https://opentelemetry.io/docs/specs/otel/logs/data-model/)也明確把這些欄位分開定義。

[agentgateway 官方 observability 文件](https://agentgateway.dev/docs/standalone/latest/documentation/observability/)列出的三種原生訊號正是 metrics、distributed traces 與 access logs，LLM 和 MCP traffic 還有各自的語意欄位。這些訊號放在一起很有用，但用途仍不同：

| Backend | 本次結果 | 能證明 | 不能單獨證明 |
|---|---|---|---|
| Tempo | 4 services、8 spans | 跨服務 request path 與時間關係 | principal 已驗證、Audit 沒漏事件 |
| Loki | 4 lines 命中 `action_id` | 各元件真的寫下相關 structured event | 儲存不可竄改、每一筆 effect 都存在 |
| Prometheus | 246 條 `agentgateway_.*` series | Gateway metrics 正被收集，可看整體趨勢 | 某個 action 的逐筆責任鏈 |

Prometheus 的 `246` 是符合查詢的 time series 數，不是這筆 action 有 246 個事件。把 aggregate metric 強行對到單一 action，和把 `user_id` 塞進 metric label 一樣，最後只會把 Day 23 的 cardinality 問題帶回來。

## SHA-256 Lock 只保護今天手上的副本

Day 1 與 Day 3 的 case directory 都有一份 `evidence-lock.json`。Replay 開始前會重新計算 manifest、events 與 canary 檔案的 SHA-256，只要有一個 byte 不同，工具就直接停止。這能防止文章、測試和輸入 Artifact 悄悄漂移，也讓讀者知道自己重建的是哪一份資料。

不過這份 lock 是 Day 26 才建立的，它只能證明「現在 repo 裡的副本和 lock 相符」，不能倒過來證明 Day 1 事件發生後從未被修改。要把 Audit 提升到更強的完整性保證，還需要考慮事件發生時的簽章或 hash chain、append-only／WORM storage、寫入者權限、讀取與匯出稽核、retention policy，以及 legal hold。沒有這些條件時，本文只使用 `VERIFIED` 描述 repository lock，不使用「不可否認」這類過度宣稱。

同一個原則也適用於 telemetry。Trace 有 sampling，Collector 或 exporter 可能失敗，Tempo、Loki、Prometheus 和 Audit Store 也可能採用不同 retention。OpenTelemetry 很適合統一資料模型與 correlation，但它沒有承諾每個 backend 一定完整收到、永久保存或防止有權限的人刪改資料。

## 把 Lab 完整跑一次

從 repo root 執行以下四個指令。Lab 05 會先驗證 Python tests、schema、格式與兩組 evidence lock，再啟動 Lab 04 的 self-hosted LGTM stack。若本機既有服務占用 Day 20 的預設 port，Day 26 會使用獨立的 `26000`–`26990` 範圍，不需要停掉別的專案。

```bash
make -f publication/Makefile.public lab-05-check
make -f publication/Makefile.public lab-05-up
make -f publication/Makefile.public lab-05-run
make -f publication/Makefile.public lab-05-down
```

結果會放在 `labs/05-incident-replay/.runtime/`：

```text
day01-replay.json
day03-policy-control.json
modern-reference.json
```

如果只想檢查歷史 Artifact，不必啟動 Docker：

```bash
uv run --directory labs/05-incident-replay incident-replay historical \
  --case-dir labs/05-incident-replay/cases/day01-canary \
  --target-tool delete_demo_database \
  --output labs/05-incident-replay/.runtime/day01-replay.json
```

完整欄位定義放在 [AI Governance Event Schema v1](https://github.com/MikeHsu0618/2026-ithelp-agent-governance-public/blob/day-27/labs/05-incident-replay/src/incident_replay/schemas/replay-event-v1.schema.json)，讀者也可以搭配 [Incident Replay 欄位指南](https://github.com/MikeHsu0618/2026-ithelp-agent-governance-public/blob/day-27/articles/day-26/incident-replay-field-guide.md)，替自己的事件逐欄標示來源與證據狀態。

## Trace 找得到，責任仍要有人接手

Day 26 最後重建出來的答案並不對稱。Tool、resource、policy decision 與 canary result 可以從歷史 Artifact 找回。Principal、delegation、Agent artifact、credential、approval 和原始儲存完整性仍然是 `UNKNOWN`。現行 LGTM 已經能把一筆新 action 串過四個 service，也沒有資格回頭替舊事件補上不存在的證據。

這個結果會直接帶到 Day 27。下一篇不再增加新的產品或 Lab，而是把 Identity、Delegation、Gateway、Runtime、Artifact、HITL、Telemetry、Audit 和 Cost Attribution 做成一份能力帳本。每一列都要寫清楚能力來自產品內建、自建整合還是既有平台，也要記錄證據在哪裡、升級後由誰重新驗證。少了 owner，再完整的 trace 最後也只是一張很好看的事故截圖。
