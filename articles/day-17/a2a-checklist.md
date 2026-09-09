# A2A 路徑驗收清單

這份清單用來避免「Agent Card 回 `200`」或「POST 回 `200`」被單獨當成整條 A2A path 已通過。每一列都要留下實際結果；沒有證據的欄位標 `NOT_TESTED`，不要靠架構圖補完。

| 檢查點 | 最低證據 | 常見誤判 |
| --- | --- | --- |
| Agent Card URL | `/.well-known/agent-card.json` 的實際 HTTP status | Service Ready 就等於 discovery Ready |
| Interface | `supportedInterfaces` 中實際選到的 URL、binding 與 version | Card 內有 URL 就假設外部 client 可達 |
| Version | request 的 `A2A-Version` 與對應 wire format | Card 同時列新舊版就視為內部已完成 migration |
| Routing | Client 照 Card URL 呼叫後命中的 Gateway route／backend | 直接打已知 internal URL 的 smoke test 代替 client path |
| SendMessage | JSON-RPC error、`result.task`、terminal state 與 artifact | HTTP `200` 就當 task 成功 |
| Streaming | `text/event-stream`、event 順序、task/context 一致、`lastChunk` 與 terminal state | 收到第一段文字就結束測試 |
| Identity | Gateway 驗證出的 caller、remote Agent 與 delegation evidence | trace ID 或 Agent name 當成已驗證 principal |
| Trace | Gateway traffic span 與 Runtime action span 的關聯欄位 | access log 存在就宣稱能重建決策 |
| Failure | discovery、route、protocol、runtime error 能分層辨認 | 所有非 200 都歸類為 Agent 壞掉 |
| HITL | approver identity、decision、resume 與 timeout 都有實測 | `INPUT_REQUIRED`／`AUTH_REQUIRED` state 等於 approval workflow 已完成 |
