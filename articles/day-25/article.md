# Day 25｜讓 SRE Agent 真的查 Loki：Grafana MCP 接上 agentgateway

Day 1 的 SRE Agent 有一個 `query_logs` Tool，實際上只會讀取 Repo 裡準備好的 JSONL Fixture，從來沒有碰到 Loki。當時這樣做，是為了把實驗焦點留給 Prompt Injection 與 Tool Boundary。如果走到 Day 25 還沒有還掉這筆技術債，前面談的治理就始終圍著一個玩具函式打轉。

Day 20 到 Day 24 都把 LGTM 放在 Agent 外面。Agent、Gateway 與 MCP Server 送出 Telemetry，SRE 再到 Grafana 查 Loki、追 Tempo。這篇把方向轉過來：既有 LGTM 不只觀測 Agent，也能提供受控的查詢能力，讓 Agent 自己取得事故證據。

這次 Google ADK Agent 會實際呼叫 `query_loki_logs`，流量經過 agentgateway、官方 mcp-grafana、Grafana Datasource Proxy，最後查到真正的 Loki。為了讓讀者每次都走到同一條查詢路徑，Lab 用 Deterministic Callback 固定提出這次 Tool Call。ADK Runtime、MCP Handshake 和後端查詢仍由真實元件完成。模型如何選 Tool 是另一個問題，不放進這次實驗。

## Grafana MCP 在既有 LGTM 裡的位置

[mcp-grafana](https://grafana.com/docs/grafana/latest/developer-resources/mcp/introduction/) 是 Grafana 官方的 MCP Server，將 Dashboard、Alerting、Prometheus、Loki、Tempo 等能力整理成 MCP Tools。本文只開放 Loki 的 `query_loki_logs`，不碰 Dashboard 修改、Alert Rule 寫入或 Incident 操作。

它沒有取代 Loki，也不是另一套可觀測性平台。mcp-grafana 把既有資料來源整理成 Agent 能理解的 Tool Contract，agentgateway 則放在前面處理 MCP Routing、Backend Credential、Policy 與 Traffic Telemetry，避免每個 Agent 都直接持有 Grafana Endpoint 和 Credential。

![SRE 問題先交給 Google ADK Agent，再經 agentgateway、mcp-grafana 與 Grafana datasource proxy 查詢 Loki。Tool result 帶著 service_name、action_id 與 trace_id 回到 Agent，下方分開標示三段連線的授權責任。](https://raw.githubusercontent.com/MikeHsu0618/2026-ithelp-agent-governance-public/day-04-r3/assets/diagrams/day-25/sre-agent-grafana-mcp-path.png)

圖中的三段連線有不同責任。Agent 到 Gateway 要處理 Caller、Tenant 與 Scope，Gateway 到 MCP Server 要決定能呼叫哪個 Backend，mcp-grafana 到 Grafana 則受 Service Account、RBAC、Datasource 與資料範圍約束。三段都成功，只能證明這條 Service Path 可用，不能把 Grafana 最後看到的 Service Identity 說成 End-user Delegation。

公開 Lab 使用合成 Backend Token，沒有實作 End-user OAuth 或 On-behalf-of。這項邊界很重要，因為「Agent 不持有 Grafana Credential」和「Grafana 知道是哪位 Human 發起」是兩件不同的事。

## ADK 改用真正的 MCP Toolset

Day 1 直接把 Python Function 放進 `tools=[...]`。Day 25 改用 ADK 的 `McpToolset`，連到 agentgateway 暴露的 Streamable HTTP Endpoint：

```python
toolset = McpToolset(
    connection_params=StreamableHTTPConnectionParams(
        url="http://127.0.0.1:25080/mcp",
        timeout=10,
        sse_read_timeout=30,
    ),
    tool_filter=["query_loki_logs"],
)
```

`tool_filter` 只減少模型看見的 Tools，不能當成完整授權。真正的拒絕仍要落在 Runtime Callback、Gateway Policy、MCP Server 設定或 Grafana RBAC。Tool 沒出現在 Prompt 裡，不代表其他 Request Path 已經封閉。

這組實驗可從 [Lab 04 README](https://github.com/MikeHsu0618/2026-ithelp-agent-governance-public/blob/day-04-r3/labs/04-telemetry-pipeline/README.md#讓-google-adk-sre-agent-透過-grafana-mcp-查-loki) 重現。第一次 Tool Call 查 Loki，第二個 Model Turn 整理結果。我關心的是回到 Agent 手上的資料是否還保有調查所需的結構。

乾淨環境裡，ADK 最後取得一筆 `service_name=day25-sre-agent` 的 Error Log，並保留 `action_id=act-day25-adk-query` 和 `trace_id=2525...2525`。這三個欄位也能在 Loki 原始資料查回，所以結果不是 Runner 自己補出來的 Summary。

## 唯讀 Tool 仍需要資料範圍

Lab 啟動 mcp-grafana 時使用 `--disable-write`，先移除 Create、Update 等副作用工具。Backend Credential 放在 agentgateway Boundary，ADK Agent 不會直接取得它。這兩個設定解決的是寫入風險與憑證分發，還沒回答 Agent 可以讀哪些 Logs。

mcp-grafana `1.4.2` 的 `--loki-enforced-matchers` 可以把固定 Matcher 加進原生 Loki Query。Lab 將範圍限制在 `service_name=~"day25-.*"`，並關閉 API、Rendering、Sift 與 Assistant Tools。官方的 [Loki Query Enforcement 說明](https://github.com/grafana/mcp-grafana/blob/v1.4.2/README.md#loki-query-enforcement) 也提醒，若其他 Tools 能繞過原生 Loki Query Path，Matcher 就不是完整邊界。

Production 還要收斂 Grafana Service Account、Datasource 權限、Tenant 與 Gateway Policy。`--disable-write` 只能保證這個 MCP Server 不提供寫入工具，不能自動把所有讀取都變成最小權限。

## Correlation Fields 必須活到 Agent

合成 Log 只把低基數 `service_name` 放進 Loki Stream Label，`action_id` 與 `trace_id` 留在 Structured Metadata。這延續 Day 23 的取捨：單筆調查需要高基數識別，不代表每個 Action ID 都要進 Index Label。

mcp-grafana 實際回傳的關鍵部分如下：

```json
{
  "labels": {"service_name": "day25-sre-agent"},
  "structuredMetadata": {
    "action_id": "act-day25-adk-query",
    "trace_id": "25252525252525252525252525252525"
  }
}
```

鎖定的 ADK `2.7.0` 與 MCP Python SDK 組合，主要從 `content[].text` 取得 Tool Response，不保證直接提供 `structuredContent`。Runner 因此解析 Text 裡的 JSON，只把 Result、筆數、Service、Action ID 與 Trace ID 留進 Agent State。驗收重點不是 Function Call 有沒有結束，而是後續調查需要的結構是否仍存在。

這也接回我先前對 mcp-grafana 的 Upstream 修補。當時 Loki Response 沒有把 Stream Labels、Structured Metadata 與 Query-time Parsed Labels 分開帶回，`trace_id` 很容易在 Tool Result 裡消失。我替 Request 加上 `X-Loki-Response-Encoding-Flags: categorize-labels`，再解析 Response 的第三個 Values Element。修改後來以 [PR #671](https://github.com/grafana/mcp-grafana/pull/671) 合入，收錄在 [v0.11.4](https://github.com/grafana/mcp-grafana/releases/tag/v0.11.4)。本文使用的 `1.4.2` 已包含這項能力，因此只驗現行版本，不安排一場新舊版功能 PK。

這段經驗讓我更在意 Tool Result 的資料血緣。Tool Schema 能規定欄位形狀，卻不能保證關聯欄位一路活過 Datasource、MCP Server、Client SDK 與 Agent State。`trace_id` 一旦在中間退化成不可解析文字，模型仍然能寫出結論，只是 SRE 沒辦法繼續向 Tempo 查證。

## HTTP 200 的三種結果

第一次接真實鏈路時，我遇過 `initialize` 和 `tools/list` 都正常，`query_loki_logs` 也回 HTTP `200`，Body 卻出現 `invalid character '<' looking for beginning of value`。沿著 URL Path、Content-Type 與 Response Body 往下查，才發現某段 Grafana API Route 回了 HTML 登入頁。查詢改走正確的 Datasource Proxy 後，Loki JSON 才正常回來。

這是產品鏈除錯的一個分支，不是本文主題。它的價值在於把同一筆 Tool Call 的 Transport、MCP、Tool 與 Query Outcome 拆開：

![同樣收到 Client HTTP 200，Grafana API 回 HTML 會形成 Tool error，合法空查詢是 NO MATCH，只有查到帶 action_id 與 trace_id 的 Loki log 才是 USABLE。](https://raw.githubusercontent.com/MikeHsu0618/2026-ithelp-agent-governance-public/day-04-r3/assets/diagrams/day-25/grafana-mcp-four-layer.png)

| Scenario | Client HTTP | MCP | Tool | Query Outcome |
| --- | --- | --- | --- | --- |
| Upstream 回 HTML | PASS | PASS | ERROR | UNKNOWN |
| 合法空查詢 | PASS | PASS | PASS | NO_MATCH |
| 查到 Loki Log | PASS | PASS | PASS | USABLE |

HTTP Success Rate 只能看 Transport Health。空結果不是 Tool Error，Tool Error 也不能被 HTTP `200` 洗成成功任務。若要把這套判讀帶進自己的系統，Repo 裡另有可直接使用的 [MCP Tool 四層結果檢查表](https://github.com/MikeHsu0618/2026-ithelp-agent-governance-public/blob/day-04-r3/articles/day-25/mcp-outcome-checklist.md)。

## 各觀測點的責任

agentgateway 的[原生 Telemetry](https://agentgateway.dev/docs/standalone/latest/documentation/observability/) 可以看到 `tools/call`、Tool Name、Server、Route、Session 與 Latency，適合回答流量是否經過正確入口、哪個 Backend 變慢，以及錯誤集中在哪條 Route。mcp-grafana 也能輸出 MCP Operation Metrics 與 Traces，繼續拆解 Tool Execution 和 Grafana API Latency。

Query Result 是否足以完成事故調查，仍應由 Runtime 或 Application Event 判斷。Gateway 不需要理解每一種 Tool 的業務語意，也不該把完整 Arguments 與 Log Result 塞進 Metric Labels。

| 觀測點 | 適合保存的證據 | 不能自行推論的事 |
| --- | --- | --- |
| agentgateway | Route、Server、Tool、Policy、Latency、Traffic Error | Loki Result 是否足以完成調查 |
| mcp-grafana | Tool Schema、Grafana API、Datasource Query、Decode Error | Human Delegation 是否成立 |
| Google ADK Runtime | Tool Proposal、Tool Result、下一步調查判斷 | Backend Credential 是否符合最小權限 |
| Grafana／Loki | Datasource 權限、LogQL、實際 Log 與 Metadata | Agent 是否完成整個治理任務 |

四層透過 `action_id`、`trace_id`、Tool Name 與時間窗對起來，各自保存適合自己的 Evidence。這比要求單一 Dashboard 判定所有 Tool 是否「成功」更能維持責任邊界。

完整產品鏈可用一條入口命令重跑：

```bash
make lab-04-mcp-run
```

啟動、清理、版本、三種 Outcome 與 Machine-readable Evidence 都留在 Lab README。官方 agentgateway MCP Playground 的實跑畫面也保留一份，Tool Output 能看到 Loki Log、`service_name`，以及 Structured Metadata 裡的 `action_id` 和 `trace_id`。

![agentgateway 官方 MCP Playground 實跑 query_loki_logs，Tool output 含一筆 Loki log、service_name label，以及 action_id、trace_id structured metadata。](https://raw.githubusercontent.com/MikeHsu0618/2026-ithelp-agent-governance-public/day-04-r3/assets/screenshots/day-25/agentgateway-grafana-mcp-playground.png)

## Trace ID 是回放入口

Day 25 把假的 `query_logs` 換成真實的 Loki Query。SRE Agent 能透過統一 Gateway 使用既有 LGTM，也能從 Tool Result 取得 `action_id` 與 `trace_id`，繼續查其他 Telemetry。HTTP `200`、Tool Error 與合法空結果也沒有再被壓成同一個綠燈。

下一篇會沿著這個 Trace ID 回放一次 Agent Tool Call，逐欄檢查 Caller、Runtime、Policy 與 Effect。Trace 很適合當調查入口，卻不會自動補上 Sampling、Retention、授權與完整性保證。這正是 Day 26 要拆開的差距。
