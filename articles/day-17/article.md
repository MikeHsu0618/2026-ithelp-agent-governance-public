# Day 17｜認識 A2A Protocol：Agent Card、Invocation 與 Task Lifecycle

假設一支值班 Agent 要整理異常服務，卻需要另一個團隊維護的資料庫 Agent 判讀慢查詢。後者有自己的模型、工具與工作流程，可能要跑幾分鐘，也可能中途要求補充時間範圍。呼叫端需要知道它會做什麼、任務現在到哪裡，以及最後交回什麼結果。只約定一個 HTTP Endpoint，這些互動仍得逐支 Agent 自訂。

A2A（Agent2Agent）把這段跨服務協作整理成共同合約。Client 先取得 Agent Card，再交換 Message。需要持續追蹤的工作由 Task 表達，成果則以 Artifact 交付。遠端 Agent 可以保留自己的 Runtime、Memory 和 Tool，呼叫端沿合約協作即可。

這篇先用協作場景認識合約，再回到我接 kagent 與 agentgateway 時遇過的錯誤：Agent Card 回 `200 OK`，Client 照著它公告的 URL 呼叫，卻得到 `404`。理解 Client 的完整路徑後，才看得出為什麼只監控 Card 會漏掉問題。

## A2A 讓不同 Runtime 交換任務與成果

官方角色圖把使用者、Client Agent 與 Remote Agent 分開。圖中的遠端 Agent 可以由不同團隊獨立維護。我們需要協調的是服務之間的互動，無須把每個 Agent 的內部狀態合併成同一套。

![A2A 官方角色圖：使用者透過 Client 與 Client Agent，和多個 Remote Agent 協作。](https://raw.githubusercontent.com/MikeHsu0618/2026-ithelp-agent-governance-public/day-17-r5/assets/third-party/a2a/a2a-actors.png)

> 來源：[A2A 官方 Core Concepts](https://a2a-protocol.org/latest/topics/key-concepts/)，[原圖固定版本](https://github.com/a2aproject/A2A/blob/1ae57a673f729f743b35f2677f3adc302438695a/docs/assets/a2a-actors.png)，Apache-2.0，未修改。2026-10-01 核對。

如果這些 Agent 都在同一個應用程式內，直接使用 Framework 的 Sub-agent 或函式呼叫就很自然。當資料庫 Agent 是獨立服務、由其他團隊維護，甚至使用不同 Framework，才需要網路上的共同協作介面。[Google ADK 的 A2A 介紹](https://adk.dev/a2a/intro/)也用「本地 Sub-agent」與「遠端 Agent」區分這兩種情況。

同一個值班場景裡，MCP 和 A2A 可以同時存在：值班 Agent 透過 MCP 呼叫 `query_loki_logs` 取得資料，再透過 A2A 把慢查詢分析委派給資料庫 Agent。前者暴露工具與資料介面，後者讓遠端 Agent 自己完成工作、回報狀態和成果。兩個協定的分工可對照 [A2A 官方的 MCP 說明](https://a2a-protocol.org/latest/topics/a2a-and-mcp/)。

## 從能力宣告走到一次可追蹤的工作

以「分析這段時間的資料庫延遲」為例，五個核心元件各自承擔不同資訊：

| 元件 | 在這筆委派中代表什麼 |
| --- | --- |
| Agent Card | 資料庫 Agent 的能力、支援介面、URL 與驗證需求 |
| Message | Client 送出的分析要求，以及 Agent 要求補充時間範圍的回覆 |
| Part | Message 或 Artifact 中的文字、檔案內容／參照或結構化資料 |
| Task | 這次分析工作的 ID、目前狀態與可追蹤的執行紀錄 |
| Artifact | 最後產生的慢查詢分析報告或結構化結果 |

Task 的 `taskId` 識別一筆工作，`contextId` 則把相關互動放在同一個脈絡中。遠端 Agent 可以先回一個可直接使用的 Message，也可以建立 Task，之後用查詢、SSE 或支援的 Push Notification 回報進度。呼叫端應依 Agent Card 和回覆選擇互動方式，而非假設所有請求都會立刻完成。這些角色與元件以 [A2A 官方核心概念](https://a2a-protocol.org/latest/topics/key-concepts/)為準。

下面把長任務的互動畫成一條簡化路徑。要求補資料與交回成果發生在不同階段，Client 因此能決定何時顯示等待、何時請使用者回應，以及何時才收下報告。

![Client 先讀 Agent Card，再送分析 Message。遠端 Agent 建立 Task 並回報 Working。若需要補資料，回 Input Required，由 Client 補送 Message 後繼續。Artifact 是成果更新，Task Completed 才是工作終態。Completed 後的追加分析建立新 Task，可沿用 Context。](https://raw.githubusercontent.com/MikeHsu0618/2026-ithelp-agent-governance-public/day-17-r5/assets/diagrams/day-17/a2a-task-interaction.png)

這張圖只畫出本文需要的成功與補資料路徑。完整協定還包含失敗、取消、拒絕與等待授權等狀態。依 [Life of a Task](https://a2a-protocol.org/latest/topics/life-of-a-task/)，已進入終態的 Task 不會重開。例如使用者要求報告再增加另一個資料庫的比較，應建立新 Task，並可沿用原本的 Context。SSE 斷線後如何查詢、持久化和恢復，也仍取決於服務實作。

想用中文再走一次概念，可以接著讀 Charles Hsiao 的 [A2A 系列 #1：協作動機](https://www.charles-hsiao.com/blog/202604-a2a-agent-to-agent-part1)、[#2：核心元件](https://www.charles-hsiao.com/blog/202604-a2a-agent-to-agent-part2)、[#3：Task 與安全架構](https://www.charles-hsiao.com/blog/202604-a2a-agent-to-agent-part3)。三篇分別從協作動機、元件到狀態與安全展開。本文以下欄位與 Lab 使用 A2A `1.0`，查實作時以對應版本的官方規格為準。

## Agent Card 回 200 只代表 Discovery 可用

接 kagent 對外入口時，我遇到的 Card 內容看起來完整，Client 讀出 Interface URL 再送 Invocation 卻得到 `404`。如果監控只檢查 `/.well-known/agent-card.json`，就會把它判為正常。測試工具繞過 Card 直接呼叫已知 Controller Path，也可能成功。兩種測法都漏掉了真正的 Client 行為：先 Discovery，再照公告 URL 呼叫。

A2A Agent Card 是一份 Discovery Contract。依 [A2A Agent Discovery 規格](https://a2a-protocol.org/latest/topics/agent-discovery/)，Client 可以從 Agent Base URL 下的 `/.well-known/agent-card.json` 取得名稱、能力、Skill、Security Requirement 與支援的 Protocol Interface。

Card 讀得到，代表 DNS、TLS、Gateway Route 與 GET Path 至少有一條可用路徑。它不會替 Card 裡公告的 URL 做 Invocation Test，也不知道後面的 Runtime 能否建立 Task。當時的異常可以縮成兩行：

```text
GET  /api/a2a/day16-lab/day16-agent/.well-known/agent-card.json  -> 200
POST /api/a2a/api/a2a/day16-lab/day16-agent                     -> 404
```

第二行不是手動拼錯，而是 Client 照著 `supportedInterfaces[].url` 呼叫。Discovery 成功了，Discovery 提供的下一站卻是錯的。

![A2A client 依序通過 Discovery、Routing 與 Runtime Execution。錯誤範例在 Agent Card 公告 URL 時重複加入 api/a2a，導致 invocation 停在 Gateway 404。修正後則由 agentgateway 的 A2A route 對外公告 agents/day16，再轉到 kagent controller。](https://raw.githubusercontent.com/MikeHsu0618/2026-ithelp-agent-governance-public/day-17-r5/assets/diagrams/day-17/a2a-discovery-routing-runtime.png)

## 重複 Prefix 來自 Base URL 的語意誤判

kagent Controller 的 A2A Mux 位於 `/api/a2a/{namespace}/{name}`。`controller.a2aBaseUrl` 用來告訴 Controller 對外公告哪個 Scheme 與 Host，kagent 產生 Agent Card 時還會在後面接上自己的 A2A Path。

當時的設定把 Path 也寫進 Base URL：

```yaml
controller:
  a2aBaseUrl: https://agent.example.test/api/a2a
```

Controller 再補一次 `/api/a2a/{namespace}/{name}` 後，Card 便公告：

```text
https://agent.example.test/api/a2a/api/a2a/day16-lab/day16-agent
```

修正只需要讓 Base URL 回到 Host Boundary：

```yaml
controller:
  a2aBaseUrl: https://agent.example.test
```

kagent `0.10.0` 的 [Controller Source](https://github.com/kagent-dev/kagent/blob/v0.10.0/go/core/pkg/app/app.go) 可以對回這段組合邏輯。讀 Source 的目的不是要大家記住內部函式，而是確認設定欄位的真正語意。接上 Gateway 後，`base URL`、`prefix` 與 `full endpoint` 不能只靠名稱猜，至少要抓一次最終 Agent Card，再讓 Probe 完整走過 Discovery 和 Invocation。

## A2A 1.0 對齊 Card、Header 與 Task

[Day 17 Lab](https://github.com/MikeHsu0618/2026-ithelp-agent-governance-public/blob/day-17-r5/labs/03-gateway-runtime/README.md) 鎖定 kagent `0.10.0`，以 A2A `1.0` 比較錯誤與修正入口。Probe 是這次的測試 Client，它從 Card 的 `supportedInterfaces` 選出 `protocolVersion: "1.0"` 與 `protocolBinding: "JSONRPC"`，再帶著 `A2A-Version: 1.0` 發出 `SendMessage`。

成功與否不能只看 JSON-RPC 外層沒有 Error。Response 裡的 Task 還要同時符合三個條件：

- `status.state` 走到 `TASK_STATE_COMPLETED`。
- `contextId` 存在，後續 Turn 才能使用相同 Conversation Context。
- History 或 Artifact 真的包含預期回覆 `boundary-ok`。

kagent `0.10.0` 產生的 Card 同時公告 `0.3` 與 `1.0` JSON-RPC Interface，外部 Caller 可以用 `A2A-Version` 選擇。Client 讀到 `1.0` 仍得照 Card 上的 URL 真正發一次 Request。否則只知道它宣告了能力，不知道入口能不能接住。

## Streaming 要看事件是否走到終態

SSE Endpoint 回 `text/event-stream`，仍可能中途送出 Error，或永遠停在 Working。這次 `SendStreamingMessage` 實際收到的順序是：

```text
SUBMITTED
WORKING
AGENT_MESSAGE
ARTIFACT(last)
COMPLETED
```

五個 Event 使用同一組 `taskId` 與 `contextId`，Artifact 帶有 `lastChunk: true`，最後一個 Task State 才是 `TASK_STATE_COMPLETED`。HTTP `200`、正確 Content Type、收到文字與 Task 完成是四個不同條件。只檢查第一個 Event，很容易把半途斷線的長任務寫成成功。

這也是 A2A 比「Agent 互相打一個 HTTP API」多出來的價值。依 [A2A 1.0 Specification](https://a2a-protocol.org/latest/specification/)，Message、Task、Artifact、Streaming Update 與 Terminal State 有共同語意。Client 不需要知道遠端 Agent 使用 ADK、LangGraph 或自建 Loop，仍能以相同 Contract 追蹤工作進度。

## A2A-aware Gateway 會改寫對外 Interface

公開 Lab 先用一般 Static HTTP Backend 忠實重現舊問題。Gateway 完整轉送 kagent Controller 的 `/api/a2a/...` Path，不理解 Agent Card。Card 公告錯 URL，Client 就真的走到錯 URL。

修正後改用 agentgateway 的 A2A Backend，Public Path 縮成 `/agents/day16`，Backend 再 Rewrite 到 kagent Controller。依 [agentgateway A2A Routing](https://agentgateway.dev/docs/kubernetes/latest/documentation/agent/a2a/) 的行為，Gateway 會把 Agent Card 裡的 Interface URL 改寫成 Client 看得到的 Gateway URL。Card 因而公告 `/agents/day16`，不會洩漏 Controller 的 Internal Service Path。

這項能力不只是 HTTP Pass-through。一般 Invocation 會在 Access Log 留下 `protocol=a2a`、`a2a.method=SendMessage`、Task State 與 `contextId`，Streaming Request 也能辨識為 `SendStreamingMessage`。agentgateway 因此成為跨 Runtime 共用的 Routing 與 Traffic Telemetry Checkpoint。Task 為什麼進入某個 State，仍要回 Runtime Trace 查，兩層證據不能互相取代。

## Task State 能表達等待，不會代做 HITL

A2A `1.0` 的 Task State 包含 `TASK_STATE_INPUT_REQUIRED` 與 `TASK_STATE_AUTH_REQUIRED`。遠端 Agent 可以用標準方式告訴 Client，目前不是完成或失敗，而是在等待資料或授權。

這些狀態沒有回答誰顯示 Approve／Reject、誰驗證 Approver、Decision 存在哪裡，以及 Runtime 如何 Resume。Agent Card 能宣告 Security Scheme，Gateway 也能驗 Transport Credential，仍不會自動建立 Human → Service → Agent 的 Delegation Chain。

這次跑通的是 Completed Task。Waiting State 把「Agent 正在等」說清楚，真正的批准者、核准規則與恢復執行仍要由 Runtime 和應用流程接手。Day 18 會拿 BYO Agent 實際走一次 Pause／Resume。

## 修正 URL 後，Client 才能走完整條路

[Lab 03 的 Day 17 區段](https://github.com/MikeHsu0618/2026-ithelp-agent-governance-public/blob/day-17-r5/labs/03-gateway-runtime/README.md) 用同一支 Probe 比較修正前後。錯誤 Base URL 下，Card 回 `200`，Client 照公告 URL 送出的 SendMessage 與 SSE 都停在 `404`。改成 A2A Route 後，Card 公告 `/agents/day16`，一般 Task 與 Streaming Task 才走到 Completed。下圖保留兩次實跑的終端結果，重跑指令和完整 Probe 留在 Lab。

![Day 17 Lab terminal card。左側保留 Agent Card 成功但兩種 invocation 都因重複 prefix 得到 404 的預期失敗。右側則顯示 Agentgateway A2A route 修正 Card URL 後，SendMessage 與 SSE streaming 都通過，stream 走完 submitted、working、artifact 與 completed。](https://raw.githubusercontent.com/MikeHsu0618/2026-ithelp-agent-governance-public/day-17-r5/assets/screenshots/day-17/01-a2a-path-results.png)

完整 [Gateway Route](https://github.com/MikeHsu0618/2026-ithelp-agent-governance-public/blob/day-17-r5/labs/03-gateway-runtime/configs/day-17/a2a-route.yaml)、Probe Source 與文字結果都在 Repo。我另整理了 [A2A 路徑驗收清單](https://github.com/MikeHsu0618/2026-ithelp-agent-governance-public/blob/day-17-r5/articles/day-17/a2a-checklist.md)。遇到「Card 正常、Invocation 失敗」時，可以沿 URL、Version、Route 與 Task State 逐站排查。

## Protocol 接通後，Runtime 能力仍然原封不動

這次結果讓我更確定，kagent 與 agentgateway 不適合用「誰取代誰」來討論。kagent Controller 讓 Agent 有共同 Discovery 與 A2A 入口，agentgateway 把 Public URL、Route 與 Traffic Telemetry 收斂到同一層。A2A 則規範 Client 和 Remote Agent 如何交換 Message、Task、Artifact 與狀態。三者接起來，確實比每個 Agent 自訂 API 更好維運。

Protocol Interoperability 不會讓 Runtime 突然多出原本沒有的 Workflow、Memory、Tool Approval 或 Credential Lifecycle。Declarative Runtime 接不住需求時，A2A 做得再完整，也只是讓其他人更穩定地呼叫一個能力仍受限的 Agent。

下一步是自己寫 Agent，再用 BYO 方式接回 kagent。這樣其他 Agent 仍能找到它。至於讓它處理複雜流程要花多少工夫，得看平台究竟接走了哪些事、又把哪些留給 Runtime 作者。
