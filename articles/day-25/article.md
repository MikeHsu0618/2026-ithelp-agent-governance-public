# Day 25｜讓 SRE Agent 真的查 Loki：Grafana MCP 接上 agentgateway

Day 1 的 SRE Agent 有一個 `query_logs` Tool。名字看起來很像回事，實際上只會把 Repo 裡準備好的 JSONL fixture 讀回來，連 Loki 都碰不到。當時故意這樣做，是為了把焦點留給 prompt injection 與 Tool boundary。如果三十天走到這裡還沒把它換掉，那前面談的治理終究只圍著一個玩具函式打轉。

Day 20 到 Day 24，我們一直把 LGTM 放在 Agent 外面。Agent、Gateway 與 MCP Server 送出 telemetry，SRE 再到 Grafana 看 Dashboard、查 Loki、追 Tempo。今天把方向轉過來：同一套 Grafana 與 Loki 不只用來「看 Agent」，還要能提供受控的查詢能力，讓 Agent 自己取得事故證據。

這次 [公開 Lab](https://github.com/MikeHsu0618/2026-ithelp-agent-governance-public/blob/day-25/labs/04-telemetry-pipeline/README.md#讓-google-adk-sre-agent-透過-grafana-mcp-查-loki) 會讓 Google ADK Agent 實際呼叫 `query_loki_logs`，流量經過 agentgateway、官方 mcp-grafana、Grafana datasource proxy，最後到真正的 Loki。模型決策使用 deterministic callback，把 LLM 的隨機性先移開。ADK runtime、MCP handshake、Tool Call 與後端查詢仍由真實元件執行。

## Grafana MCP 補的是 Agent 入口，不是另一套可觀測性平台

[mcp-grafana](https://grafana.com/docs/grafana/latest/developer-resources/mcp/introduction/) 是 Grafana 官方的 MCP Server。它把 Dashboard、Alerting、Prometheus、Loki、Tempo 等能力整理成 MCP Tools，讓支援 MCP 的 Client 不必各自重寫 Grafana API integration。本文只開放讀取 Loki 所需的 `query_loki_logs`，不碰 Dashboard 修改、Alert rule 寫入或 Incident 操作。

這個位置很容易被說成「替 Agent 加一個 Grafana Tool」，但架構上的價值不在多一個 Tool 名稱。Grafana MCP 沒有取代 Loki，也沒有取代原本的 LGTM。它把既有觀測資料整理成 Agent 能理解的 Tool contract，agentgateway 則放在前面處理 MCP routing、backend credential、policy 與 traffic telemetry，避免每個 Agent 都直接持有 Grafana endpoint 和 credential。

![SRE 問題先交給 Google ADK Agent，再經 agentgateway、mcp-grafana 與 Grafana datasource proxy 查詢 Loki。Tool result 帶著 service_name、action_id 與 trace_id 回到 Agent，下方分開標示三段連線的授權責任。](https://raw.githubusercontent.com/MikeHsu0618/2026-ithelp-agent-governance-public/day-25/assets/diagrams/day-25/sre-agent-grafana-mcp-path.png)

圖裡刻意把連線拆成三段，因為它們回答的問題不同。Agent 到 Gateway 要處理 caller、tenant 與 scope，Gateway 到 MCP Server 要決定哪個 backend 能被呼叫，mcp-grafana 到 Grafana 則受 Grafana credential、RBAC、datasource 與資料範圍約束。只把三段都畫成一條「已認證」箭頭，最後很容易把 service account 誤當成人類使用者的 delegation evidence。

本篇 Lab 只驗證 MCP data path，沒有假裝完成 end-user OAuth。agentgateway 注入的是合成 backend token，mcp-grafana 連的是隔離環境 Grafana。Production 若要保留使用者身分，還得另外設計 incoming OAuth、policy context 與 on-behalf-of。少了這一段，Grafana 最後看到的仍是 mcp-grafana 使用的 service identity。

## Google ADK 這次真的接上 MCP Toolset

Day 1 的 Agent 直接把 Python function 塞進 `tools=[...]`。Day 25 改用 ADK 的 `McpToolset`，連線目標就是 agentgateway 暴露的 Streamable HTTP endpoint：

```python
from google.adk.tools.mcp_tool import (
    McpToolset,
    StreamableHTTPConnectionParams,
)

toolset = McpToolset(
    connection_params=StreamableHTTPConnectionParams(
        url="http://127.0.0.1:25080/mcp",
        timeout=10,
        sse_read_timeout=30,
    ),
    tool_filter=["query_loki_logs"],
)
```

`tool_filter` 讓模型只看到這次需要的 Tool，可以減少 context 與誤用機會，但它不是完整的 authorization。真正的拒絕仍要落在 Agent Runtime callback、Gateway policy、MCP Server 設定或 Grafana RBAC，不能因為 Tool 沒出現在 prompt 裡，就認定呼叫路徑已經被封死。

這次沒有再消耗 Gemini API quota。ADK 的 `before_model_callback` 會固定提出一次 `query_loki_logs`，第二次 model turn 再整理 Tool result。我把測試範圍鎖在「ADK 能否透過真正的 MCP Toolset 走完整條產品鏈」，所以不比較 Prompt 寫法，也不拿模型選 Tool 的命中率混進來。

乾淨重建後，ADK runner 留下的摘要如下。`configured_path` 記的是這次 Lab 接起來的產品路徑，不把一串靜態名稱冒充逐 hop 的 telemetry receipt。這次 Live run 真正驗證的是：ADK 完成 `query_loki_logs` Tool Call，而且回來的資料同時對得上預期的 `service_name`、`action_id` 與 `trace_id`。若正式環境要證明每一跳都由哪些元件處理，仍要回到 Gateway access log、MCP telemetry 與後端 trace 交叉確認。

```json
{
  "runtime": "google-adk-python/2.7.0",
  "tool_name": "query_loki_logs",
  "configured_path": [
    "Google ADK",
    "agentgateway",
    "mcp-grafana",
    "Grafana",
    "Loki"
  ],
  "tool_summary": {
    "result": "USABLE",
    "lines_returned": 1,
    "service_name": "day25-sre-agent",
    "action_id": "act-day25-adk-query",
    "trace_id": "25252525252525252525252525252525"
  }
}
```

## 唯讀只是起點，查詢範圍仍要收斂

Lab 啟動 mcp-grafana 時加上 `--disable-write`，先把 create、update 類型的 Tool 關掉。agentgateway 的設定則把 MCP backend credential 放在 Gateway boundary，不讓 ADK Agent 直接拿到：

```yaml
mcp:
  port: 3000
  prefixMode: conditional
  targets:
  - name: grafana
    policies:
      backendAuth:
        key:
          value: day25-synthetic-caller-token
    mcp:
      host: http://mcp-grafana:8000/mcp
```

這樣可以集中處理 routing 與 backend authentication，卻還不能回答「這個 Agent 能讀哪些 log」。`--disable-write` 只拿掉副作用，不會自動限制讀取範圍。mcp-grafana 的 Grafana credential 若權限過大，Agent 仍可能查到不屬於它的 datasource 或 tenant。正式環境至少要再縮小 service account、datasource 權限、允許的 Tool，以及 Loki query 的 label 範圍。

mcp-grafana `1.4.2` 也提供 `--loki-enforced-matchers`，可以把固定 matcher AND 進原生 Loki query。Lab 實際把讀取範圍限在 `service_name=~"day25-.*"`，同時關閉 API、rendering、Sift 與 Assistant Tools：

```bash
--loki-enforced-matchers 'service_name=~"day25-.*"' \
--disable-api --disable-rendering --disable-sift --disable-assistant
```

不能只開 matcher 就放心，因為其他 Grafana API、rendering 或分析工具可能形成不同資料路徑。[官方的 Loki query enforcement 說明](https://github.com/grafana/mcp-grafana/blob/v1.4.2/README.md#loki-query-enforcement)也特別提醒，若要讓 matcher 成為完整的讀取邊界，必須一併關閉能繞過原生 Loki query path 的 Tool。治理的單位不是某個參數，而是所有能碰到同一份資料的 action path。

## Loki 資料回來後，關聯欄位不能跟著散掉

本次合成 log 只把低基數的 `service_name` 放進 Loki stream label，`action_id` 與 `trace_id` 放在 structured metadata。這延續 Day 23 的 cardinality 原則：要查某一次行動，不代表每個 action ID 都該進 Prometheus label 或 Loki index label。mcp-grafana 實際回傳的資料如下：

```json
{
  "line": "level=error action_id=act-day25-adk-query year=2026 msg=synthetic_checkout_timeout",
  "labels": {
    "service_name": "day25-sre-agent"
  },
  "structuredMetadata": {
    "action_id": "act-day25-adk-query",
    "detected_level": "error",
    "trace_id": "25252525252525252525252525252525"
  }
}
```

這裡也踩到一個很實際的 client 相容問題。鎖定的 ADK `2.7.0` 搭配目前 MCP Python SDK 時，Tool response 主要從 `content[].text` 進入 Agent callback，不保證直接提供 `structuredContent`。Runner 因此會解析 text 裡的 JSON，再只留下 result、筆數、service、action ID 與 trace ID。整段 log response 不會原封不動塞進 Agent state 或治理事件。

省下幾個 byte 並不是重點，我更在意「有結構的 Tool result」到了 Agent 端會不會又退化成一大段不可控文字。MCP Client、SDK 與 Server 的版本會改變 response shape，驗收時應該鎖定必要欄位，不要只檢查 function call 有沒有結束。

## 那次 upstream 修補，補的是 Agent 需要的證據

我先前在實際使用 mcp-grafana 查 Loki 時，遇過 stream labels、structured metadata 與 query-time parsed labels 沒有分開帶回的問題。對人眼看 log 也許只是少幾個欄位，對 Agent 卻會直接影響後續調查。`trace_id` 若在 Tool result 裡消失，下一步就沒辦法接著查 Tempo。把它硬塞進 index label，又會把 cardinality 問題帶回來。

當時我 fork mcp-grafana，替 Loki request 加上 `X-Loki-Response-Encoding-Flags: categorize-labels`，並解析 response 裡第三個 values element。這份修改後來以 [PR #671](https://github.com/grafana/mcp-grafana/pull/671) 合入 upstream，收錄在 [v0.11.4](https://github.com/grafana/mcp-grafana/releases/tag/v0.11.4)。文章使用的 `1.4.2` 已經包含這項能力，所以 Lab 只跑現行版本，不拿舊版與新版做一場沒有必要的 PK。

這段經驗也改變了我看 MCP Server 的方式。Tool schema 定義了輸入與輸出長什麼樣，但真正能不能接進事故調查，取決於 correlation fields 是否從資料來源一路活到 Agent。少了這些欄位，模型仍然可以產生一段很流暢的結論，只是你無法再往下驗證。

## HTTP 200 回 HTML，是接上真實鏈路後的除錯插曲

第一次把這條路徑接起來時，我曾看到 `initialize` 正常、`tools/list` 也看得到 Tool，呼叫 `query_loki_logs` 後，Client 收到 HTTP `200`，內容卻出現 `invalid character '<' looking for beginning of value`。後來逐段保存 URL path、Content-Type 與 response body，才確認某一段 Grafana API route 回到 HTML 登入頁。讓查詢改走正確的 datasource proxy 後，Loki JSON 才正常回來。

這個 incident 值得保留，但它只是 Grafana MCP 實戰裡的一個除錯分支，不是整篇文章的目的。它提醒我們，同一筆 Tool Call 至少有四種結果不能混在一起：Client HTTP、MCP contract、Tool result，以及 Agent 最後拿到的 query outcome。

![同樣收到 Client HTTP 200，Grafana API 回 HTML 會形成 Tool error，合法空查詢是 NO MATCH，只有查到帶 action_id 與 trace_id 的 Loki log 才是 USABLE。](https://raw.githubusercontent.com/MikeHsu0618/2026-ithelp-agent-governance-public/day-25/assets/diagrams/day-25/grafana-mcp-four-layer.png)

Lab 另外保留一組安全 HTML fixture，讓真正的 mcp-grafana 呼叫 Grafana datasource proxy 時收到 `200 text/html`。三種 client-facing request 都回 HTTP `200`，結果卻完全不同：

```text
scenario                 client-http  mcp      tool     query-outcome
upstream-200-html        PASS         PASS     ERROR    UNKNOWN
valid-empty-query        PASS         PASS     PASS     NO_MATCH
usable-loki-result       PASS         PASS     PASS     USABLE
```

第一列的 MCP response 本身成立，但 `result.isError=true`。第二列 Tool 沒壞，只是指定時間範圍沒有符合資料。第三列才把 Agent 後續調查需要的 correlation fields 一起帶回來。HTTP success rate 適合看 transport health，不適合直接命名成「Agent 任務成功率」。讀者若要把這套判讀帶回自己的系統，可以直接使用 [MCP Tool 四層結果檢查表](https://github.com/MikeHsu0618/2026-ithelp-agent-governance-public/blob/day-25/articles/day-25/mcp-outcome-checklist.md)。

## Gateway 看得到 Tool Call，Agent 才能判斷資料是否可用

[agentgateway 的原生 telemetry](https://agentgateway.dev/docs/standalone/latest/documentation/observability/) 能看到 `tools/call`、Tool name、server、route、session 與 latency，適合回答流量有沒有經過正確入口、哪個 MCP backend 變慢，以及錯誤集中在哪條 route。[mcp-grafana](https://github.com/grafana/mcp-grafana/blob/v1.4.2/docs/sources/developer/observability-metrics-and-tracing.md) 也能輸出自己的 MCP operation metrics 與 traces，繼續拆解 Tool execution 和 Grafana API latency。

不過 Gateway 不應該把完整 Tool arguments 與 log result 全塞進 metric labels，再替每個 domain 定義成功。`query_loki_logs` 的 `NO_MATCH`、`USABLE` 可以由 Agent Runtime 或 application event 判讀。換成建立 Ticket、修改設定或刪除資源，最後一層就必須改用 resource version、read-after-write、controller receipt 或 domain event 證明 effect。因此，實務上的分工會比較像下面這張表：

| 觀測點 | 適合回答的問題 | 不該自行推論的事 |
|---|---|---|
| agentgateway | MCP route、server、Tool name、latency、policy 與 traffic error | Loki 結果是否足以完成事故調查 |
| mcp-grafana | Tool schema、Grafana API、datasource query 與 decode error | 人類使用者是否已被正確 delegation |
| Google ADK Runtime | 模型提出哪個 Tool Call、Tool result 是否可用、下一步要查什麼 | Grafana backend credential 是否符合最小權限 |
| Grafana／Loki | datasource 權限、LogQL 執行、實際 log 與 metadata | Agent 是否完成整個治理任務 |

把責任拆開後，Dashboard 不必假裝理解每一種 Tool 的業務語意，Agent event 也不用複製 Gateway 已經保留的 transport evidence。兩邊透過 `action_id`、`trace_id`、Tool name 與時間窗對起來，就能各自保存適合自己的證據。

## 把完整 Lab 跑起來

從 Repo root 執行以下四個指令，會先驗證 Python、agentgateway、Compose 與 Alloy 設定，再清空 volume、啟動完整 data path。`lab-04-mcp-run` 會先跑三種 protocol outcome，接著啟動 Google ADK SRE Agent 查一次真正的 Loki：

```bash
make lab-04-mcp-check
make lab-04-mcp-up
make lab-04-mcp-run
make lab-04-mcp-down
```

目前這份 evidence 使用 Google ADK `2.7.0`、agentgateway `1.5.0`、mcp-grafana `1.4.2`、Alloy `1.18.1` 與固定 digest 的 LGTM image。完整設定、測試結果與 machine-readable evidence 都放在 [Lab 04 README](https://github.com/MikeHsu0618/2026-ithelp-agent-governance-public/blob/day-25/labs/04-telemetry-pipeline/README.md#讓-google-adk-sre-agent-透過-grafana-mcp-查-loki)，官方 agentgateway MCP Playground 的實跑畫面也一併保留：

![agentgateway 官方 MCP Playground 實跑 query_loki_logs，Tool output 含一筆 Loki log、service_name label，以及 action_id、trace_id structured metadata。](https://raw.githubusercontent.com/MikeHsu0618/2026-ithelp-agent-governance-public/day-25/assets/screenshots/day-25/agentgateway-grafana-mcp-playground.png)

## 查得到 Trace ID，還不等於有一份完整 Audit Trail

Day 25 終於把 Day 1 的假 `query_logs` 換成真實查詢。SRE Agent 能經過統一 Gateway 使用既有 LGTM，也能從 Loki result 拿到 `action_id` 與 `trace_id`，繼續往其他 telemetry 查證。HTTP 200、Tool error 與合法空結果也不再被壓成同一個綠燈。

下一篇會沿著這個 Trace ID 回放一次 Agent Tool Call，逐欄檢查誰提出要求、哪個 Runtime 執行、套用哪版 policy，以及最後 effect 有沒有留下收據。Trace 很適合當調查入口，但 sampling、retention、授權與完整性保證不會因為有了 Trace ID 就自動補齊。
