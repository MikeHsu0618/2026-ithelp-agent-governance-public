# Day 21｜Agent Telemetry Pipeline 實戰：把 Gateway、Runtime 與 MCP 的 Trace 接起來

Day 20 的 Tempo Waterfall 有兩個 Span，`invoke_agent` 底下接著 `execute_tool`。欄位 Contract 看起來完整，`action_id` 也能把 Trace 和 Governance Event 對上。不過兩個 Span 都由同一個 Python Runner 產生，Request 根本沒有跨過服務邊界。

單機 Demo 只要 Parent Span 包住 Child Span，畫面自然連得起來。Agent Runtime、Gateway 和 MCP Server 分開部署後，每個 HTTP Request 都可能把因果關係弄丟。Day 21 將它們拆成真正獨立的服務，再故意拿掉一次 `traceparent`，比較「Tool 執行成功」與「整條路徑追得到」之間的差異。

## 一條 Data Path，四個 Telemetry Producer

公開 Lab 使用單一 agentgateway。Client 先經 Gateway 呼叫 Agent Runtime，Runtime 要執行 Tool 時，再回到相同 Gateway 的 MCP Route。這樣能觀察兩段真實 Gateway Traffic，不必為了 Demo 疊出第二層 Proxy。

下圖要分成上下兩條線閱讀。上半部是 Request 實際經過的 Data Path，下半部是每個元件將訊號送進 Alloy 的 Telemetry Path。

![Day 21 Lab 的 data path 與 telemetry path。Client、agentgateway、Agent Runtime 和 MCP adapter 都是獨立 producer，訊號經 Alloy 送入 LGTM。](https://raw.githubusercontent.com/MikeHsu0618/2026-ithelp-agent-governance-public/day-06-r3/assets/diagrams/day-21/telemetry-pipeline.png)

四個 Producer 看見同一筆 Action，手上的資料卻不同：

| 元件 | 能直接知道 | 不知道 |
| --- | --- | --- |
| Lab Client | Action 開始、情境、最後 HTTP 結果 | Gateway Route、Runtime 內部步驟 |
| agentgateway | Request、Route、Upstream、Policy、HTTP Status | Agent 為何選 Tool、Tool 的 Domain Effect |
| Agent Runtime | Workflow、HITL、Fallback、準備呼叫的下游 | MCP Adapter 是否真的改到資源 |
| MCP Adapter | Tool Request、Receipt、實際副作用 | 上游完整 Planning 與 Policy 判斷 |

我在維護觀測平台時，Collector 通常不是最難的一段。Claude Code、Agent Workload 或 Gateway 都能把 OTLP 指向同一套 Alloy／LGTM，真正花時間的是 Producer 要寫什麼、欄位由誰負責，以及查詢時能否還原同一筆 Action。訊號都進 Alloy，不代表 Alloy 自動知道 Runtime 的 Approval 或 MCP 的 Effect。

## Alloy 接收訊號，不能替 Producer 補資料

agentgateway 使用 OTLP/gRPC 傳送 Trace 與 Access Log，Python 寫的 Client、Runtime 與 MCP Adapter 使用 OTLP/HTTP。Alloy 在同一個 Receiver 開啟兩種 Protocol，經過 Memory Limiter 與 Batch Processor 後送進 OTEL-LGTM。Gateway 原生 Prometheus Metrics 則由另一條 Scrape Pipeline 收集。

[agentgateway Observability 文件](https://agentgateway.dev/docs/standalone/latest/documentation/observability/) 將內建訊號分成 Metrics、Distributed Traces 與 Access Logs，官方也有可直接使用的 [Grafana Dashboard](https://agentgateway.dev/docs/standalone/main/integrations/observability/grafana/)。日常監控不必從空白重做 Request、LLM、MCP、Latency、xDS 與 Runtime Health 面板。

本篇自訂畫面只處理官方 Dashboard 沒有的跨服務問題：Gateway、Agent Runtime 與 MCP Adapter 能否對回同一筆 Action，以及 Tempo、Loki 與 Prometheus 是否各自收到該由它們回答的資料。完整 Alloy 與 agentgateway Config 放在 [Lab 04 README](https://github.com/MikeHsu0618/2026-ithelp-agent-governance-public/blob/day-06-r3/labs/04-telemetry-pipeline/README.md)，正文不再逐段複製。

兩段 Request 都實際通過 agentgateway。Route、HTTP Status、Upstream、原生 Trace、OTLP Access Log 與 `agentgateway_requests_total` 由它產生。Python 扮演 Client、Runtime 與 MCP Adapter。這次先專心處理跨服務的 Trace Context，還沒有啟用 JWT。畫面裡若出現 Runtime 填的 Team，不能把它當成 Gateway 已驗證的身分。Day 23 才會讓 JWT 通過 Gateway，再觀察 Claim 如何進入 Telemetry。

## 先把正常路徑接通

從 Repo Root 啟動 Lab，不需要 LLM API Key：

```bash
make lab-04-up
make lab-04-check
make lab-04-run
```

Runner 會送出正常呼叫，以及 Policy 拒絕、HITL、A2A 失敗和 LLM 備援等固定情境。完整預期結果與逐項驗收留在 [Lab 04 README](https://github.com/MikeHsu0618/2026-ithelp-agent-governance-public/blob/day-06-r3/labs/04-telemetry-pipeline/README.md)。文章先盯住最基本、也最容易在部署後出錯的一件事：Tool 已執行，能不能沿同一條 Trace 找到它？MCP Tool 仍是安全示範，只留下 `NO_OP_CANARY` Receipt，沒有真實副作用。

## 正常 Trace 跨過四個 Service

Normal Call 在 Tempo 裡共有四個 Service、八個 Span。Client、Runtime 與 MCP Adapter 建立自己的 Span，agentgateway 另外替 `/agent/run` 與 `/mcp/execute` 留下 Server／Upstream Span。

![Tempo 的正常 Trace 實拍。畫面由本次 Lab 產生，共有 4 個 service、8 個 span，能從 Lab Client 追到 MCP adapter。](https://raw.githubusercontent.com/MikeHsu0618/2026-ithelp-agent-governance-public/day-06-r3/assets/screenshots/day-21/tempo-cross-service-trace.png)

四個 Service 留在同一條因果鏈，靠的是每一跳都正確處理 Trace Context。Client 在送出 Request 前注入 `traceparent`，Gateway 接續後傳給 Runtime。Runtime 呼叫 MCP Route 時重新注入目前 Context，MCP Adapter 收到後取出 Parent，再建立自己的 Span。[OpenTelemetry Context Propagation](https://opentelemetry.io/docs/concepts/context-propagation/) 將跨服務 Propagation 分成傳送端序列化與接收端反序列化，少掉其中一邊，Backend 不會因為時間接近就替我們接線。

在這張 Waterfall 裡，`mcp-adapter` 與上游共享 Trace ID，也接上正確 Parent。從 Client 到 Tool 的呼叫因果關係沒有斷。至於呼叫者是誰、Tool 對資源造成什麼結果，得看各自的身分檢查與執行紀錄，不能從一條綠色 Span 猜出來。

## 拿掉 Traceparent，功能成功但責任鏈斷掉

負向實驗保留相同 Topology，只在 Runtime → MCP Request 拿掉 Trace Context：

```bash
make lab-04-broken-trace
```

HTTP Response 仍是 `200`，MCP Receipt 也回 `CANARY_TRIGGERED`。若驗收只看功能測試，這一筆會被判成成功。Backend Verifier 回頭檢查原 Trace 時，卻找不到預期的 `mcp-adapter`。

Tempo Waterfall 從四個 Service、八個 Span，變成三個 Service、五個 Span。`mcp.call` 仍掛在 Runtime 底下，真正執行 Tool 的 `mcp.tool.execute` 已落到另一個 Trace。

![拿掉 Runtime 到 MCP 的 traceparent 後，原 Trace 只剩 3 個 service、5 個 span。Tool 回成功，但 mcp-adapter 已不在這條因果鏈裡。](https://raw.githubusercontent.com/MikeHsu0618/2026-ithelp-agent-governance-public/day-06-r3/assets/screenshots/day-21/tempo-broken-context.png)

MCP 的獨立 Trace 和上游 Trace 都不是空的，這比整套 Telemetry 掛掉更容易漏看。單查 MCP 會看到 Tool 正常執行，單查上游也會看到 Runtime Outbound Span 已結束。事故發生後才以 Timestamp、Session 或模糊字串拼回兩筆紀錄，很快就會回到人工通靈。

## Loki 保存事件，Prometheus 觀察流量

同一筆 Normal Action 在 Loki 可以查到 Client、Runtime 與 MCP Adapter 各自送出的結構化 Event。四行資料共用 `action_id`，內容分別描述 Client Result、Runtime Completion、MCP Receipt 與 Runtime Accepted Event。

![Loki 以 action_id 查到四筆跨 producer event，包含 Client 結果、Runtime 狀態與 MCP no-op receipt。](https://raw.githubusercontent.com/MikeHsu0618/2026-ithelp-agent-governance-public/day-06-r3/assets/screenshots/day-21/loki-action-events.png)

Gateway Access Log 能看到 Path、Route、Upstream 與 HTTP Status，但設定沒有從 Request Body 解析 `action_id`，所以該欄位只存在 Runtime 和 MCP Event。agentgateway 可以投影已驗證 JWT Claim 或明確允許的 Header。本篇的 `action_id` 仍只在 Application Payload，尚未定義可信 Header、Overwrite Rule 與防偽邊界，不能升格成 Gateway 的 Governance Evidence。

Prometheus 的用途又不同。以下 Query 將 Gateway Request 按 Route、Status 與 Reason 聚合：

```promql
sum by (route, status, reason) (agentgateway_requests_total)
```

![Prometheus 查詢 agentgateway requests。畫面能分辨 agent-runtime 200、MCP 200、policy deny 403 與 missing A2A backend 503。](https://raw.githubusercontent.com/MikeHsu0618/2026-ithelp-agent-governance-public/day-06-r3/assets/screenshots/day-21/prometheus-agentgateway-metrics.png)

`gateway-policy-deny` 留下 `Authorization`／`403`，刻意不存在的 A2A Backend 留下 `NoHealthyBackend`／`503`。Metrics 適合回答 Route 流量、錯誤率與趨勢，不該塞入每一筆 `action_id`。單筆因果交給 Trace，離散細節交給 Log／Governance Event，聚合健康度留給 Metrics。

## 本機 Pipeline 搬回 Kubernetes 還缺什麼

公開 Lab 使用 Standalone agentgateway 與 `grafana/otel-lgtm`，目的是讓讀者在一台電腦上重現跨服務 Propagation。[Grafana OTEL-LGTM Image](https://grafana.com/docs/opentelemetry/docker-lgtm/) 的定位也是 Development、Demo 與 Testing，不代表 Production 只需一個 All-in-one Container。

回到 Kubernetes，我會把三種健康度分開看：agentgateway Control Plane 是否完成 Reconciliation、Data Plane 是否正常處理 Traffic，以及 Agent Runtime 是否完成 Workflow。它們可以在同一個 Dashboard 相鄰出現，SLO 與告警 Owner 不能混成單一綠燈。Collector 也要補 Queue、Retry、Capacity、Network Policy、TLS、Authentication 與 Backpressure。

這次 Gateway Request 能一路追到 Runtime 與 MCP Tool。刻意拿掉 `traceparent` 後，Tool 雖然執行成功，Waterfall 卻少了一段。Alloy 負責接收與轉送訊號，跨服務因果靠 Trace Context 傳遞，執行狀態則由各個 Producer 記錄。

下一個誘惑是把 `principal`、`team`、`role` 與 `tenant` 全部塞進 Telemetry，讓每種查詢都能分組。這些值從 JWT 到 Gateway，再到 Runtime 的途中，可信度不完全相同。進入 Metrics、Traces、Logs 與長期 Audit 後，敏感程度和成本也不同。Day 22 會處理這批身分資料應該落在哪裡。
