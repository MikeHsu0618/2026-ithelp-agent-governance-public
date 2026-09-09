# Day 17 圖像 Evidence

日期：2026-09-08（Asia/Taipei）

環境：disposable kind／Kubernetes `1.34.0`、Gateway API `1.6.0`、kagent `0.10.0`、agentgateway `1.5.0`、synthetic OpenAI-compatible backend。

`01-a2a-path-results.png` 由以下實跑文字重排：

- `evidence/broken-a2a-path.txt`：`controller.a2aBaseUrl` 錯誤包含 `/api/a2a`；Agent Card `200`，Card 公告 URL 重複 prefix，兩種 invocation 都得到 `404 EXPECTED_FAIL`。
- `evidence/fixed-a2a-path.redacted.txt`：base URL 改為 host-only，經 A2A-aware route 呼叫；Agent Card、SendMessage 與 SendStreamingMessage `3/3 PASS`。
- `evidence/gateway-a2a-log.redacted.txt`：保留 route、method、status 與 A2A semantic fields；移除 timestamp、Pod IP、source port、duration 與 generated context ID。
- `evidence/agent-card.selected.json`：保留本次判讀使用的 Card 欄位，證明 A2A-aware route 將 `0.3` 與 `1.0` JSON-RPC interface 都公告為 `/agents/day16`；其餘 metadata 未納入本文結論，因此不複製成固定 fixture。

圖中的 task／context ID 使用 `<generated>`，不把單次 run 的 UUID 當成固定 fixture。公開 evidence 不含 credential、production hostname、公司 namespace 或內部網域。
