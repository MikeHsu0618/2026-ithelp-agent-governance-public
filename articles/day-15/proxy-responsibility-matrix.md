# Edge／Ingress 與 Agent Gateway 責任矩陣

這份表不要求一定使用兩層 proxy。它用來檢查既有入口不能立刻退場時，同一項功能是否出現兩個 owner。公開 Lab 只有一層 agentgateway，也適用右欄的驗收方式。

| 能力 | Edge／既有 Ingress | Agent Gateway | Runtime／backend | 驗收重點 |
| --- | --- | --- | --- | --- |
| Public endpoint／TLS | certificate、public listener、host | 只接受預定來源，內層 TLS 依環境需要 | 不直接暴露 public endpoint | Backend 沒有繞過 Gateway 的公開路徑 |
| Generic routing | host、粗粒度 path、非 AI 服務入口 | LLM／MCP／A2A protocol-aware routing | 業務 endpoint | 同一個 path rewrite 只設定一次 |
| Caller authentication | 限制網路來源並原樣轉送 `Authorization`，不重複驗同一枚 JWT | 驗 JWT、consumer key、issuer、audience 與 resource policy | 驗業務資源權限 | 缺 Token、錯 Token 在 backend 前得到 `401` |
| Backend credential | 不注入 provider key | 移除 caller credential，注入 backend 專用 credential | 只接受 backend credential | Caller key／JWT 不抵達 provider |
| WAF／IP abuse | WAF、IP／連線層保護 | principal、client、model、Tool 維度限制 | 業務 quota | 兩層使用不同維度，不重複扣同一 quota |
| LLM／MCP／A2A policy | 不解析 AI protocol | model、prompt／Tool metadata、MCP／A2A-aware policy | semantic validation、business authorization、HITL | Gateway ALLOW 不取代 backend 的業務授權 |
| Header mutation | 只維護 forwarding／trace contract | 寫入 audit context、backend auth，移除不可信內部 header | 只信任約定來源 | 建一份 reserved-header 清單與 owner |
| Streaming／body | 不 buffer response、不做會改寫 SSE 的 body filter | 維持 protocol streaming，需要 buffer 的 policy 明確列例外，streaming response guard 另做相容性驗收 | 正確 flush event／heartbeat | 第一段 event 在 upstream 完成前抵達，policy 是否涵蓋 streamed output 另外測試 |
| Timeout | outer connection／idle budget，需容納 streaming heartbeat | backend／route budget | model、Tool、workflow deadline | 外層 budget 大於內層，逾時來源能從 telemetry 判斷 |
| Retry | 不設定 AI route 的應用層 retry，產品原有的 transport retry 另列設定與條件 | 只有明確可重試且具 idempotency 的 operation 才開 | Tool side effect 實作 idempotency | `429` 在目前設定只抵達上游一次，保留 `Retry-After` |
| Error propagation | 保留 `401`、`429`、`5xx` 與關鍵 headers | 保留上游錯誤語意或使用穩定 error contract | 回傳可分類錯誤 | 不把 provider `429` 改成模糊 `502` |
| Telemetry／audit | connection、TLS、host、request ID | principal、client、Agent、policy、model／Tool decision | business outcome | 同一 correlation ID 能串 edge、Gateway、runtime |
| Gateway failure | 回 `502／503`，fail closed | 不可用時明確失敗 | 不接受 edge 直接繞入 | 災難演練確認沒有 bypass route |

## 設計審查時先找四種重疊

1. 兩層都驗同一枚 JWT，卻使用不同 JWKS cache／audience 規則。
2. 兩層都重試帶 side effect 的 Tool Call。
3. 兩層都改 `Authorization`、trace 或 audit headers。
4. 兩層都對同一 principal 做 rate limit，造成重複扣量與難以解釋的 `429`。

Kong 預設只針對特定 transport-level failure retry，不會因 upstream 回了 `5xx` 或 `429` 就自動重送。表裡的雙層 retry 是通用架構檢查：若 edge 透過自訂設定、plugin 或外部機制加入應用層 retry，必須和 agentgateway 的 retry policy 一起計算，不能只看其中一份設定。

兩層都保留控制不一定有錯。IP abuse 與 principal quota 就適合拆在不同位置，但 owner、維度與 output property 必須寫清楚，並且進入測試。
