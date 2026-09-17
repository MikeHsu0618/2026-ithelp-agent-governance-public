# Day 25 evidence

驗證日期：2026-09-16（Asia/Taipei）

System under test 是 Google ADK `2.7.0`、pinned agentgateway `1.5.0`、官方 mcp-grafana `1.4.2`、Grafana datasource proxy 與 LGTM Loki。ADK 的 model decision 使用 deterministic callback；MCP Toolset、Gateway、MCP Server 與 Loki query 都是真實執行。mcp-grafana 啟用 `--loki-enforced-matchers 'service_name=~"day25-.*"'`，並關閉官方列出的 API、rendering、Sift 與 Assistant bypass Tools。

```bash
make lab-04-mcp-check
make lab-04-mcp-up
make lab-04-mcp-run
make lab-04-mcp-down
```

乾淨 volume 的 live run 得到三種 client-facing HTTP `200`：

```text
scenario                 client-http  mcp      tool     query-outcome
upstream-200-html        PASS         PASS     ERROR    UNKNOWN
valid-empty-query        PASS         PASS     PASS     NO_MATCH
usable-loki-result       PASS         PASS     PASS     USABLE
```

Raw verifier 完成後，Google ADK SRE Agent 另跑一次 `query_loki_logs`。`assets/screenshots/day-25/evidence/sre-agent-run.json` 會記錄設定路徑 ADK → agentgateway → mcp-grafana → Grafana → Loki；它不是逐 hop receipt。Live run 的通關條件是結果為 `USABLE`、`lines_returned=1`，而且 `service_name`、`action_id`、`trace_id` 都與本次 synthetic request 相符。

Raw verifier 的可用結果同樣只含一筆 log。Loki stream label 是 `service_name=day25-mcp-outcome`，`action_id` 與 `trace_id` 則由 mcp-grafana `1.4.2` 放進 `structuredMetadata`。HTML 情境的 fixture receipt 確認 Grafana datasource proxy path 實際回傳 HTTP `200` 與 `text/html`，client-facing MCP response 則是 `isError=true`。

測試結果為 97 passed、branch coverage 82.08%。兩份 agentgateway config、Compose 與 Alloy config 均通過產品 validator。公開 evidence 不含 Authorization header、MCP session ID、真實帳號、內部 endpoint、本機 ADC 或 production data。
