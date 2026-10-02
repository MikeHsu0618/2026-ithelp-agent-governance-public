# Day 25｜讓 SRE Agent 查 Loki：Grafana MCP 的查詢路徑與資料權限

請 SRE Agent 調查錯誤，最有用的回答通常不只是一句「可能是服務逾時」。我們還需要知道它看了哪個服務、哪段時間、哪些 Log，以及能不能沿結果繼續查 Trace。這些資料如果只存在模型的摘要裡，值班的人就很難核對。

既有 Grafana 和 Loki 已經有可查詢的資料，下一步是讓 Agent 在受限的範圍裡使用它們。這時要處理的事情包括：查詢工具放在哪裡、由誰持有 Grafana 憑證、Agent 可以讀哪些 Logs，以及工具回傳的結果是否足以支持後續調查。

系列最初的 `query_logs` 只讀取準備好的 JSONL Fixture，用來隔離 Prompt Injection 和工具執行的問題。本篇接上真實資料路徑：Google ADK Runtime 經 agentgateway 呼叫官方 mcp-grafana，再由 Grafana 查 Loki。先看角色和資料權限，後段再用固定的工具請求確認這條路徑。

## MCP 如何提供查詢能力

Agent Runtime 需要知道工具名稱、參數和回傳內容，才能把「查這段時間的錯誤」轉成可執行的請求。MCP 提供工具發現與呼叫介面，讓 Runtime 不必直接理解每個後端的 HTTP API。MCP Server 則負責把工具請求轉成實際的後端操作。

[mcp-grafana](https://grafana.com/docs/grafana/latest/developer-resources/mcp/introduction/) 是 Grafana 官方的 MCP Server，將 Grafana 與資料來源的查詢、管理能力提供成 Tools。本篇只使用 Loki 的 `query_loki_logs`。它接受查詢條件，透過 Grafana 的 Datasource Proxy 呼叫資料來源，再把結果交回 Agent。

Datasource Proxy 是 Grafana 對資料來源的查詢入口。由它轉送，Agent 不必自己持有 Loki 的連線設定，但這條查詢仍受 Grafana 帳號角色、所用版本可配置的權限和後端設定約束。mcp-grafana 提供的是工具介面，實際 Log 仍由 Loki 保存。

agentgateway 位於 Runtime 和 MCP Server 之間，管理 MCP 路由、後端憑證與共同政策。Agent 只連這個入口，Gateway 再接 mcp-grafana。下圖先看請求方向，再看下方各段授權責任：同一筆查詢用了哪些身分，會影響最後能讀到什麼。

![ADK Runtime 經 agentgateway、mcp-grafana 和 Grafana Datasource Proxy 查 Loki，結果帶關聯欄位回到 Agent。下方分開標示三段連線的授權責任。](https://raw.githubusercontent.com/MikeHsu0618/2026-ithelp-agent-governance-public/day-25-r6/assets/diagrams/day-25/sre-agent-grafana-mcp-path.png)

## 入口身分與資料來源身分

使用者請 Agent 查 Logs，並不表示 Grafana 最後一定看見這位使用者。常見設計是 Gateway 持有後端憑證，MCP Server 再以 Grafana Service Account 查資料。這時入口可以知道是哪位 Caller，資料來源實際接受的卻是服務帳號。

這裡的 Grafana Service Account 是 Grafana 的服務身分，和 Kubernetes ServiceAccount 分屬不同系統。它的權限、Datasource 範圍與 Token 管理，需要由 Grafana 的管理方式決定。入口使用者登入成功，不能代替這一段的資料授權。

因此我會分開檢查三件事：Caller 能不能進這條 Agent 或 MCP Route，Gateway 能不能呼叫所選 MCP Backend，MCP Server 使用的帳號能讀哪些資料。如果需要依使用者隔離查詢，還要設計可信的使用者與資料範圍對應，不能只把 Email 傳進工具參數就算完成。

後面的公開示範使用合成 Backend Token，沒有 End-user OAuth 或 On-behalf-of，也就是沒有讓下游以原使用者的授權身分執行。它驗證 Agent 可以透過共同入口查資料，尚未驗證完整的使用者代理鏈。

## 唯讀查詢的資料範圍

Logs 可能包含其他團隊的事件、使用者資訊或系統細節。工具沒有寫入能力，只能降低修改風險，仍要決定它能讀到哪些資料。對 SRE Agent 而言，查詢時間區間、資料來源、服務集合和回傳筆數，都會影響暴露面與調查品質。

mcp-grafana 啟動時可以使用 `--disable-write`，移除 Create、Update 等副作用工具。1.4.2 的 `--loki-enforced-matchers` 則能把固定 Matcher 加進原生 Loki 查詢，例如只允許某組服務。這是把資料範圍放在工具端執行，比單純請模型「不要查其他服務」更可檢查。

[該版本的 Loki Query Enforcement 說明](https://github.com/grafana/mcp-grafana/blob/v1.4.2/README.md#loki-query-enforcement) 也列出可能繞開原生查詢路徑的其他 Tools。實際收斂權限時，必須一起檢查這些入口、Grafana 帳號權限與 Datasource 設定。只限制一條查詢工具，若仍能透過通用 API 讀同一份資料，邊界就還有缺口。

這份官方說明特別提到，OSS 沒有它所需要的逐 Datasource 或逐使用者 Label 存取控制。因此本篇用 MCP 端固定 Matcher 限定查詢範圍，沒有假設 Grafana 會自動依入口 Caller 隔離 Logs。若組織改用其他部署模式或額外權限機制，也應重新確認限制發生在哪一層。

Runtime 端的工具篩選也有不同用途。`tool_filter` 讓模型只看到選定工具，可以降低選錯的機率。真正不被允許的呼叫，則仍要由 Runtime 的執行檢查、Gateway、MCP Server 或資料來源拒絕，讓所有請求路徑都有對應控制。

## 工具結果如何支持後續調查

查詢結果需要保留的不只是 Log 文字。服務欄位讓我們知道來源，時間和查詢條件說明觀察範圍，`action_id` 與 `trace_id` 則讓調查能接到相關事件和執行路徑。若工具只回一段「共找到一筆錯誤」，值班的人仍不知道怎麼找到原始資料。

Loki 的欄位也有不同位置。Stream Labels 用於有限的來源分組，Structured Metadata 保存每筆事件的關聯值，Query-time Parsed Labels 則是查詢時才從內容解析的欄位。它們在畫面上都可能像 Key／Value，但來源與用途不同，工具應該保留這個區別。

我先前替 mcp-grafana 做過這一段修補。當時 Loki Response 沒有把幾種欄位分開帶回，Structured Metadata 裡的 `trace_id` 很容易消失。我在 Request 加上 `X-Loki-Response-Encoding-Flags: categorize-labels`，再解析回應第三個 Values Element。這項修改以 [PR #671](https://github.com/grafana/mcp-grafana/pull/671) 合入，收錄於 [v0.11.4](https://github.com/grafana/mcp-grafana/releases/tag/v0.11.4)。本篇的 1.4.2 已包含它。

這段經驗讓我在接 Tool 時，會沿著 Datasource、MCP Server、Client SDK 和 Agent State 檢查資料是否仍可使用。Schema 可以說明回傳格式，實際串接仍可能在其中一站把欄位丟掉。模型有能力根據剩餘文字寫摘要，但調查者能否查證，取決於這些欄位有沒有一路保留。

## ADK 實際取得 Loki 資料

[Lab 04 README](https://github.com/MikeHsu0618/2026-ithelp-agent-governance-public/blob/day-25-r6/labs/04-telemetry-pipeline/README.md#讓-google-adk-sre-agent-透過-grafana-mcp-查-loki) 提供完整重現。本次以 Deterministic Callback 固定模型提出的工具呼叫，讓每次都走相同查詢。Google ADK 2.7.0 的 Runtime、MCP Handshake、工具發現與 Grafana／Loki 查詢仍由真實元件執行，並沒有用固定結果代替後端。

ADK 使用 [MCP Toolset](https://adk.dev/tools-custom/mcp-tools/) 連到 Gateway 的 Streamable HTTP Endpoint。關鍵設定如下，工具篩選只保留 `query_loki_logs`：

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

工具端使用 `--disable-write`，Loki Matcher 限在 `service_name=~"day25-.*"`，並關閉 API、Rendering、Sift 和 Assistant Tools。Backend Credential 留在 Gateway 邊界，ADK 不直接取得它。這些設定一起限定本次查詢能力。

實際結果包含一筆 `service_name=day25-sre-agent` 的 Error Log，以及 Action ID 和 Trace ID。它們能從 Loki 原始資料對回，工具回應中也保留分類後的欄位：

```json
{
  "labels": {"service_name": "day25-sre-agent"},
  "structuredMetadata": {
    "action_id": "act-day25-adk-query",
    "trace_id": "25252525252525252525252525252525"
  }
}
```

鎖定的 ADK 和 MCP Python SDK 組合主要從 `content[].text` 取得工具回應，不保證直接提供 `structuredContent`。Runner 因此解析文字中的 JSON，只將結果、筆數、服務和關聯 ID 留到 Agent State，供下一步整理使用。這裡驗收的是結構是否仍在，並非只看 Function Call 有沒有結束。

下圖是 Gateway 官方 MCP Playground 的實際工具輸出。展開 Log 後，可以找到服務 Label，以及 Metadata 裡的 Action ID 和 Trace ID，對照剛才的 JSON。

![agentgateway MCP Playground 實跑 query_loki_logs，輸出包含 Loki Log、服務 Label 和 Action／Trace 關聯欄位。](https://raw.githubusercontent.com/MikeHsu0618/2026-ithelp-agent-governance-public/day-25-r6/assets/screenshots/day-25/agentgateway-grafana-mcp-playground.png)

## HTTP 回應與查詢結果的分層

我第一次接真實鏈路時，曾遇到 MCP `initialize` 和 `tools/list` 都正常，查詢也收到 HTTP `200`，Body 卻出現 `invalid character '<' looking for beginning of value`。沿 URL、Content-Type 和 Body 往下找，才發現某段 Grafana API Route 回了 HTML 登入頁。改走正確的 Datasource Proxy 後，Loki JSON 才正常回來。

這個情況讓我把驗收分成網路回應、MCP 訊息、工具結果與查詢內容。HTTP `200` 表示入口回了訊息，MCP 仍可能帶工具錯誤。工具查詢完成，也可能合法地沒有符合的 Log。這些狀態要分開，Agent 才知道該修連線、改查詢，還是帶著有效資料繼續調查。

下圖將相同入口 HTTP 狀態下的三種結果放在一起。先找 HTML 解碼失敗，再看合法空查詢，最後才是帶關聯欄位的有效 Log。

![入口同樣回 HTTP 200，仍可能是工具解碼錯誤、合法空結果，或帶關聯欄位的可用查詢結果。](https://raw.githubusercontent.com/MikeHsu0618/2026-ithelp-agent-governance-public/day-25-r6/assets/diagrams/day-25/grafana-mcp-four-layer.png)

空結果本身也是資訊，但要連同查詢時間、資料範圍和管線狀態解讀。它可能表示沒有符合條件的事件，也可能是範圍選錯或資料尚未送達。不能在沒有其他證據時，把空查詢直接寫成「服務正常」。完整分層方式留在 [MCP Tool 四層結果檢查表](https://github.com/MikeHsu0618/2026-ithelp-agent-governance-public/blob/day-25-r6/articles/day-25/mcp-outcome-checklist.md)。

## 調查與維護如何分工

Gateway 的觀測資料適合看 Route、Tool、Backend、延遲與流量錯誤。mcp-grafana 可以繼續定位工具執行和 Grafana API 的處理。查詢內容是否足以支持下一步判斷，則由 Runtime 或應用決定，資料來源權限仍由 Grafana 和後端管理。

例如工具回了格式正確的空結果，Gateway 不必替值班者判斷事故是否結束。Runtime 可以記錄查詢條件與 Outcome，值班者再沿關聯 ID 查看其他資料。這樣每一站留下自己真正知道的事，調查時也知道該找誰處理。

本篇接通的是受限的查詢能力：Agent 可以使用既有 Loki，工具結果也保留繼續查證的入口。拿到 Trace ID 之後，下一個問題是它能還原多少事實。呼叫路徑、授權依據和資料保存的完整性，仍要在事件回放時逐一確認。
