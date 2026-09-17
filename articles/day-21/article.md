# Day 21｜Agent Telemetry Pipeline 實戰：把 Gateway、Runtime 與 MCP 的 Trace 接起來

Day 20 的 Tempo waterfall 有兩個 span：`invoke_agent` 底下接著 `execute_tool`。欄位契約看起來完整，`action_id` 也能把 trace 和 Governance Event 對上。不過那兩個 span 都由同一個 Python runner 產生，request 根本還沒跨過服務邊界。

單機 Demo 裡只要 parent span 包著 child span，畫面自然會連在一起。等 Agent Runtime、Gateway 和 MCP Server 分開部署後，每個 HTTP request 都可能把原本的因果關係弄丟。Day 21 把 Lab 拆成真正獨立的服務，再故意拿掉一次 `traceparent`，看看「Tool 執行成功」和「整條路徑追得到」究竟差在哪裡。

## Lab 拓樸：一個 Gateway，四個 Telemetry producer

公開 Lab 使用單一 agentgateway。Client 先經過 Gateway 呼叫 Agent Runtime，Runtime 要執行 Tool 時，再回到同一個 Gateway 的 MCP route。這樣可以觀察兩段 Gateway traffic，又不需要為了 Demo 疊出兩層 proxy。

下圖要分開看兩條線。上半部是 request 實際走過的 data path，下半部則是各元件把資料送進 Alloy 的 telemetry path。

![Day 21 Lab 的 data path 與 telemetry path。Client、agentgateway、Agent Runtime 和 MCP adapter 都是獨立 producer，訊號經 Alloy 送入 LGTM。](https://raw.githubusercontent.com/MikeHsu0618/2026-ithelp-agent-governance-public/day-25/assets/diagrams/day-21/telemetry-pipeline.png)

四個 producer 看的是同一筆 action，手上的資料卻不相同：

| 元件 | 它能直接知道的事 | 它不知道的事 |
|---|---|---|
| Lab Client | action 開始、預期情境、最後收到的 HTTP 結果 | Gateway 選了哪條 route、Runtime 內部走了哪些步驟 |
| agentgateway | request、route、upstream、policy decision、HTTP status | Agent 為什麼決定呼叫 Tool、Tool 產生了什麼 domain effect |
| Agent Runtime | workflow、HITL、fallback、準備呼叫哪個下游 | MCP adapter 是否真的改到目標資源 |
| MCP adapter | Tool request、receipt、實際副作用 | 上游完整的 planning 與 policy 判斷 |
| Alloy | 收到哪些 logs、metrics、traces，以及要送去哪裡 | principal 是否可信、`ALLOW` 用的是哪份組織規則 |

我在維護觀測平台時，collector 通常不是最難的一段。Claude Code、Agent workload 或 Gateway 都能把 OTLP 指向同一套 Alloy／LGTM，真正花時間的是 producer 要寫什麼、欄位由誰負責，以及查詢時能不能把同一筆 action 還原出來。Alloy 不會因為大家都接上來了，就自動知道 Runtime 的 approval 或 MCP 的 effect。

## Alloy 同時接 OTLP 與 Gateway metrics

agentgateway 會用 OTLP/gRPC 送 trace 與 access log，Python 寫的 Client、Runtime、MCP adapter 則使用 OTLP/HTTP。Alloy 在同一個 receiver 開啟兩種 protocol，讓收到的 OTLP 訊號依序通過 memory limiter 與 batch processor，再送到 OTEL-LGTM。Gateway 原生的 Prometheus metrics 稍後會由另一條 scrape pipeline 處理。

```alloy
otelcol.receiver.otlp "lab" {
  grpc {
    endpoint = "0.0.0.0:4317"
  }

  http {
    endpoint = "0.0.0.0:4318"
  }

  output {
    logs    = [otelcol.processor.memory_limiter.lab.input]
    metrics = [otelcol.processor.memory_limiter.lab.input]
    traces  = [otelcol.processor.memory_limiter.lab.input]
  }
}
```

agentgateway 的 data-plane metrics 走另一條路。Alloy 直接 scrape `agentgateway:15020`，再寫進 Lab 內的 Prometheus：

```alloy
prometheus.scrape "agentgateway" {
  targets = [{
    "__address__" = "agentgateway:15020",
    "job"         = "agentgateway-data-plane",
  }]
  forward_to = [prometheus.remote_write.lgtm.receiver]
}
```

Gateway 本身的 trace 與 access log 都指向 Compose 裡的 Alloy service：

```yaml
frontendPolicies:
  tracing:
    host: alloy:4317
    protocol: grpc
    randomSampling: true
  accessLog:
    otlp:
      host: alloy:4317
```

[agentgateway 的官方 Observability 文件](https://agentgateway.dev/docs/standalone/latest/documentation/observability/)把內建訊號分成 metrics、distributed traces 與 access logs。官方的 [Docker Compose trace 範例](https://agentgateway.dev/docs/standalone/latest/documentation/observability/traces/configs/)也是用 service name 加上 `4317` 找 OTLP receiver，access log 則可依 [OTLP export 設定](https://agentgateway.dev/docs/standalone/latest/documentation/observability/access-logs/export/)送到 collector。文件只解決設定格式，這篇還會拿真正的 Tempo、Loki 與 Prometheus query 驗收資料有沒有抵達。

如果目標只是監控 agentgateway，本身不必從空白建立 Dashboard。官方維護的 [Grafana Dashboard](https://agentgateway.dev/docs/standalone/main/integrations/observability/grafana/)已涵蓋 request、LLM、MCP、latency、xDS 與 runtime health，Kubernetes Helm chart 也能建立 Dashboard ConfigMap、ServiceMonitor 與 PodMonitor。Day 21 的自訂畫面只處理官方面板沒有的跨服務問題：把 Gateway、Agent Runtime 與 MCP adapter 對回同一個 action，並同時檢查 Tempo 與 Loki。這張實驗畫面不是要取代官方日常維運面板。

## agentgateway 的原生訊號與本篇邊界

兩段 request 都實際通過 pinned agentgateway `1.5.0`，route、HTTP status、upstream、原生 trace、OTLP access log 與 `agentgateway_requests_total` 也都由 Gateway 本身產生。Python 在這篇扮演 Client、Agent Runtime 與 MCP adapter，讓每個服務能在安全的 no-op 情境下建立自己的 span 與事件，沒有另外產生一份 JSON 冒充 Gateway log。

Day 21 沒有啟用 JWT，所以畫面不能證明 `principal` 已經由 Gateway 驗證，更不能把 Runtime 自己寫入的 team 當成 Gateway claim。agentgateway 現行設定能在 JWT 驗證後，透過 [CEL 讀取 `jwt.sub` 或自訂 claims](https://agentgateway.dev/docs/kubernetes/latest/documentation/security/jwt/setup/)，再把值加入 [access log fields](https://agentgateway.dev/docs/standalone/latest/documentation/observability/access-logs/export/)、traces 或 [Prometheus metric labels](https://agentgateway.dev/docs/standalone/latest/observability/metrics/overview/)。這項能力會在 Day 23 用真實 JWT 與三組 Gateway 設定實跑，避免在 Pipeline 篇把 propagation、identity 和 cardinality 三個問題擠成同一場實驗。

## 五種情境共用同一套 Pipeline

從 Repo root 啟動 Lab，不需要任何 LLM API key：

```bash
make lab-04-up
make lab-04-check
make lab-04-run
```

完整設定、測試和清理方式都在 [Lab 04 README](https://github.com/MikeHsu0618/2026-ithelp-agent-governance-public/blob/day-25/labs/04-telemetry-pipeline/README.md)。`make lab-04-run` 會真的送出五筆 request，再逐筆查詢 backend，而不是把預期結果直接寫進資料庫。

| Scenario | 預期結果 | 原 Trace 應出現的 service |
|---|---|---|
| normal call | `CANARY_TRIGGERED` | Client、Gateway、Runtime、MCP |
| Gateway policy deny | `DENIED` | Client、Gateway |
| HITL approved | `APPROVED_AND_EXECUTED` | Client、Gateway、Runtime、MCP |
| A2A routing failure | `ROUTING_FAILED` | Client、Gateway、Runtime |
| LLM fallback | `FALLBACK_SUCCEEDED` | Client、Gateway、Runtime、MCP |

五種情境會成為後面幾篇共用的 baseline。HITL、A2A 與 fallback 的內部邏輯使用 deterministic fixture，Day 21 不重新展開 Day 17、18 的協定細節，也不呼叫真正的 Provider。MCP Tool 仍是安全的 `delete_demo_database`，receipt 固定回 `NO_OP_CANARY` 與 `side_effects=0`。

Verifier 逐筆比對 HTTP 結果、Tempo service 集合與 Loki event，最後也確認 Prometheus 已抓到 Gateway metrics。本次執行的五筆 correlation 全部通過：

```json
{
  "overall": "PASS",
  "prometheus_agentgateway_metrics": "PASS",
  "scenarios": [
    {"scenario": "normal-call", "correlation": "PASS"},
    {"scenario": "gateway-policy-deny", "correlation": "PASS"},
    {"scenario": "hitl-approved", "correlation": "PASS"},
    {"scenario": "a2a-routing-failure", "correlation": "PASS"},
    {"scenario": "llm-fallback", "correlation": "PASS"}
  ]
}
```

## 正常 Trace 跨過四個 service

正常呼叫在 Tempo 裡共有 4 個 service、8 個 span。除了 Client、Runtime 和 MCP adapter 自己建立的 span，agentgateway 還替 `/agent/run` 與 `/mcp/execute` 各留下 server／upstream span。

![Tempo 的正常 Trace 實拍。畫面由本次 Lab 產生，共有 4 個 service、8 個 span，能從 Lab Client 追到 MCP adapter。](https://raw.githubusercontent.com/MikeHsu0618/2026-ithelp-agent-governance-public/day-25/assets/screenshots/day-21/tempo-cross-service-trace.png)

四個 service 能留在同一條因果鏈，靠的是每一跳都正確處理 Trace Context。Client 送出 request 前注入 `traceparent`，Gateway 接續後再傳給 Runtime。Runtime 呼叫 MCP route 時重新注入目前 context，MCP adapter 收到後取出 parent，再建立自己的 span。[OpenTelemetry 對 Context Propagation 的說明](https://opentelemetry.io/docs/concepts/context-propagation/)也把跨服務 propagation 分成傳送端的序列化與接收端的反序列化。少掉其中一邊，後端不會憑 request 時間接近就替我們接線。

這張 Tempo waterfall 證明的是 causal path。`mcp-adapter` 出現在最下面，代表它的 span 與上游共享同一個 Trace ID，也有正確的 parent。它無法證明 `user/sre-oncaller` 經過驗證，更不能靠綠色 span 判斷資料庫真的被刪除。Day 20 定義的 principal assurance 與 effect evidence，仍要由知道來源的元件另外寫入。

## 漏掉 traceparent，Tool 成功但 Trace 少一段

負向實驗保留相同 topology，只在 normal call 的 Runtime -> MCP request 拿掉 Trace Context：

```bash
make lab-04-broken-trace
```

HTTP response 仍然是 `200`，MCP receipt 也回 `CANARY_TRIGGERED`。如果驗收只看功能測試，這一筆會被判成成功。Backend verifier 回頭檢查原 Trace 時，卻找不到預期的 `mcp-adapter`：

```json
{
  "overall": "FAIL",
  "scenarios": [
    {
      "scenario": "normal-call",
      "trace_services": [
        "agent-runtime",
        "agentgateway",
        "ithelp-lab-client"
      ],
      "missing_services": ["mcp-adapter"],
      "tempo_trace": "FAIL"
    }
  ]
}
```

Tempo 畫面也從正常路徑的 4 services／8 spans，變成 3 services／5 spans。`mcp.call` 仍掛在 Runtime 底下，真正執行 Tool 的 `mcp.tool.execute` 已經落到另一個 Trace。

![拿掉 Runtime 到 MCP 的 traceparent 後，原 Trace 只剩 3 個 service、5 個 span。Tool 回成功，但 mcp-adapter 已不在這條因果鏈裡。](https://raw.githubusercontent.com/MikeHsu0618/2026-ithelp-agent-governance-public/day-25/assets/screenshots/day-21/tempo-broken-context.png)

MCP 的獨立 Trace 和上游 Trace 都不是空的，反而比整套 telemetry 掛掉更容易漏看。單查 MCP 會看到 Tool 正常執行，單查上游也會看到 Runtime 的 outbound span 已結束。事故發生後才用 timestamp、session 或模糊字串拼回兩筆紀錄，很快就會回到人工通靈。

## Loki 保留事件，Prometheus 觀察流量

同一筆 normal action 在 Loki 可以查到 Client、Runtime 與 MCP adapter 各自送出的結構化事件。下圖裡四行資料共用 `action_id`，內容依序包含 Client 最後看到的結果、Runtime completion、MCP receipt 與 Runtime accepted event。

![Loki 以 action_id 查到四筆跨 producer event，包含 Client 結果、Runtime 狀態與 MCP no-op receipt。](https://raw.githubusercontent.com/MikeHsu0618/2026-ithelp-agent-governance-public/day-25/assets/screenshots/day-21/loki-action-events.png)

這次 Gateway access log 能看到 path、route、upstream 與 HTTP status，但設定沒有從 request body 解析 `action_id`，因此該欄位只存在於 Runtime 和 MCP 事件。agentgateway 可以透過 CEL 投影驗證後的 JWT claims 或明確允許的 header。本篇的 `action_id` 目前只放在應用 payload，尚未定義可信 header、覆寫規則與防偽邊界。在這些條件確定前，不能因為 body 裡有同名欄位就把它升格成 Gateway 的治理證據。

Prometheus 的用途又不同。以下查詢把 Gateway request 按 route、status 與 reason 聚合：

```promql
sum by (route, status, reason) (agentgateway_requests_total)
```

![Prometheus 查詢 agentgateway requests。畫面能分辨 agent-runtime 200、MCP 200、policy deny 403 與 missing A2A backend 503。](https://raw.githubusercontent.com/MikeHsu0618/2026-ithelp-agent-governance-public/day-25/assets/screenshots/day-21/prometheus-agentgateway-metrics.png)

`gateway-policy-deny` 留下 `Authorization`／`403`，刻意不存在的 A2A backend 則留下 `NoHealthyBackend`／`503`。Metrics 很適合回答 route 的流量、錯誤率和趨勢，卻不該塞入每一筆 `action_id`。單筆因果關係交給 Trace，細節與離散事件交給 Log／Governance Event，聚合健康度留在 Metrics，這個分工會直接影響 Day 23 的 cardinality。

## 從本機 Compose 搬回 Kubernetes

公開 Lab 使用 standalone agentgateway 與 `grafana/otel-lgtm`，目的是讓讀者在一台電腦上重現跨服務 propagation。[Grafana 對 OTEL-LGTM image 的定位](https://grafana.com/docs/opentelemetry/docker-lgtm/)也是 development、demo 與 testing。它不是我實務上的 Kubernetes topology，更不等於 production 只需要一個 all-in-one container。

回到 Kubernetes，我會把三種健康度分開看：agentgateway control plane 是否完成 reconciliation、data plane 是否正常處理 traffic，以及 Agent Runtime 是否完成 workflow。三者可以在同一個 Dashboard 相鄰出現，SLO 與告警 owner 仍然不該混成一個綠燈。Collector 也要補上 queue、retry、容量、網路政策、TLS、認證與 backpressure，公開 Lab 的 loopback Compose 沒有替這些問題背書。

Day 20 留下的問題到這裡有了可驗收的答案：從 Gateway request 可以一路追到 Runtime 與 MCP Tool，而且 verifier 能抓到中途少掉的 service。Alloy 幫我們統一接收與轉送訊號，Trace Context 負責保存跨服務因果，每個 producer 再補上自己真正知道的狀態。

路徑接通後，下一個誘惑是把 `principal`、`team`、`role`、`tenant` 全部塞進 telemetry，方便每一種查詢都能分組。這些值從 JWT 到 Gateway、再到 Runtime 的途中，可信度不完全相同。進入 Metrics、Traces、Logs 與長期 Audit 後，敏感程度和成本也不同。Day 22 要處理的，就是這批身分資料到底該落在哪裡。
