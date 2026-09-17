# MCP Tool 四層結果檢查表

這份表適合放進 runbook、incident note 或 post-request log schema。先按 hop 保存原始證據，再決定 Dashboard 要如何聚合。不要用一個 `success=true` 蓋掉所有層次。

| 層次 | 至少保存 | 常見判斷 | 不能直接推論 |
|---|---|---|---|
| Client HTTP | status、content type、route、latency | Client 是否收到可處理的 transport response | MCP message 合法、Tool 已成功 |
| MCP contract | JSON-RPC id、result／error、protocol version | request／response 是否符合 MCP contract | Tool 執行成功、資料可用 |
| Tool result | tool name、target、`isError`、output schema 狀態、error 摘要 | Tool 是否完成自己的工作 | 查詢一定有資料、寫入一定生效 |
| Domain outcome | read query 的 match count，或 write action 的 receipt／read-after-write／Audit event | 這次工作是否達成預期 | 可由所有 Tool 共用同一套成功條件 |

## Read-only 查詢範例

```text
HTTP 200 + MCP result + isError=true  -> UNKNOWN，先處理 Tool error
HTTP 200 + MCP result + data=[]       -> NO_MATCH，查詢成立但沒有資料
HTTP 200 + MCP result + data=[...]    -> USABLE，仍應檢查必要欄位
```

必要欄位應由每個 Tool 自己定義。以本文的 `query_loki_logs` 為例，Lab 要求至少有一筆 log，而且 `action_id`、`trace_id` 必須留在 structured metadata，不能只看到一段無法關聯的文字。

## 有副作用的 Tool

把第四層換成可驗證的 effect，不要沿用 `data=[]`：

- create／update：resource ID、version、read-after-write 或 domain event。
- delete：被刪除對象、影響筆數、再次讀取的結果。
- deployment：rollout revision、健康狀態與 controller receipt。
- approval：approver identity、decision、policy version 與 resume 後的 task state。

若這些證據不存在，Outcome 應保留 `UNKNOWN`。HTTP 200、MCP success 或一段自然語言「已完成」都不能替它補值。
