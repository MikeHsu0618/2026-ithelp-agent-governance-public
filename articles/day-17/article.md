# Day 17｜認識 A2A Protocol：Agent Card、Invocation 與 Task Lifecycle

Day 16 已證明 kagent 能部署 Declarative Agent，LLM 與 MCP Traffic 也能經過 agentgateway。接著把 A2A 對外開放時，我曾遇過一個很容易誤判的狀況：Agent Card 回了 `200 OK`，內容看起來也完整。A2A Client 讀出裡面的 URL 再送出 Invocation，得到的卻是 `404`。

若監控只檢查 `/.well-known/agent-card.json`，這個 Agent 會被判定為正常。測試工具若繞過 Card，直接呼叫已知的 Controller Path，也可能得到成功結果。兩邊的綠燈加在一起，仍然沒有測到真正的 Client 行為：先做 Discovery，再照 Agent Card 公告的 Interface URL 發出 Request。

公開 Lab 把當時的錯誤配置放回 Disposable Kubernetes Cluster。壞掉的 Card 會公告一條重複 `/api/a2a` 的路徑，修正後再以同一支 Probe 驗證 Discovery、一般 Invocation、SSE Streaming 與 Task Lifecycle。這個事故剛好能看出 A2A、kagent Runtime 與 agentgateway 各自負責哪一段。

## Agent Card 回 200 只代表 Discovery 可用

A2A Agent Card 是一份 Discovery Contract。依 [A2A Agent Discovery 規格](https://a2a-protocol.org/latest/topics/agent-discovery/)，Client 可以從 Agent Base URL 下的 `/.well-known/agent-card.json` 取得名稱、能力、Skill、Security Requirement 與支援的 Protocol Interface。

Card 讀得到，代表 DNS、TLS、Gateway Route 與 GET Path 至少有一條可用路徑。它不會替 Card 裡公告的 URL 做 Invocation Test，也不知道後面的 Runtime 能否建立 Task。當時的異常可以縮成兩行：

```text
GET  /api/a2a/day16-lab/day16-agent/.well-known/agent-card.json  -> 200
POST /api/a2a/api/a2a/day16-lab/day16-agent                     -> 404
```

第二行不是手動拼錯，而是 Client 照著 `supportedInterfaces[].url` 呼叫。Discovery 成功了，Discovery 提供的下一站卻是錯的。

![A2A client 依序通過 Discovery、Routing 與 Runtime Execution。錯誤範例在 Agent Card 公告 URL 時重複加入 api/a2a，導致 invocation 停在 Gateway 404。修正後則由 agentgateway 的 A2A route 對外公告 agents/day16，再轉到 kagent controller。](https://raw.githubusercontent.com/MikeHsu0618/2026-ithelp-agent-governance-public/day-15-r1/assets/diagrams/day-17/a2a-discovery-routing-runtime.png)

## 重複 Prefix 來自 Base URL 的語意誤判

kagent Controller 的 A2A Mux 位於 `/api/a2a/{namespace}/{name}`。`controller.a2aBaseUrl` 用來告訴 Controller 對外公告哪個 Scheme 與 Host，kagent 產生 Agent Card 時還會在後面接上自己的 A2A Path。

當年的設定把 Path 也寫進 Base URL：

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

本篇直接驗 A2A `1.0`。Probe 從 Card 的 `supportedInterfaces` 選出 `protocolVersion: "1.0"` 與 `protocolBinding: "JSONRPC"`，再帶著 `A2A-Version: 1.0` 發出 `SendMessage`。

成功與否不能只看 JSON-RPC 外層沒有 Error。Response 裡的 Task 還要同時符合三個條件：

- `status.state` 走到 `TASK_STATE_COMPLETED`。
- `contextId` 存在，後續 Turn 才能使用相同 Conversation Context。
- History 或 Artifact 真的包含預期回覆 `boundary-ok`。

kagent `0.10.0` 產生的 Card 同時公告 `0.3` 與 `1.0` JSON-RPC Interface，外部 Caller 可以用 `A2A-Version` 選擇。這是 Migration Compatibility，不代表整條內部路徑只剩單一版本。對平台驗收來說，「Card 寫了 1.0」與「外部 1.0 Request 實際跑通」是兩份不同的證據。

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

A2A 解決的是不同 Agent 如何交換 Message、Task 與 Artifact。Business Authorization、Approval Workflow、Memory 和 Execution Sandbox 仍有各自的 Owner。本篇只把實際跑到的 `TASK_STATE_COMPLETED` 標為通過，不會因為規格定義了 Waiting State，就寫成 kagent HITL 已經完成驗收。

## 同一支 Probe 先重現，再驗證修正

[Lab 03 的 Day 17 區段](https://github.com/MikeHsu0618/2026-ithelp-agent-governance-public/blob/day-15-r1/labs/03-gateway-runtime/README.md) 沿用 Day 16 的 Disposable Kind Cluster、kagent、agentgateway 與 Synthetic LLM，不需要外部 LLM API Key。一條命令會先放入錯誤 Base URL，再恢復 Host-only 設定並重跑正向路徑：

```bash
make lab-03-runtime-a2a
```

負向與正向結果使用完全相同的 Probe 和判斷標準：

| 階段 | Agent Card | SendMessage | SSE | 公告 URL |
| --- | --- | --- | --- | --- |
| 錯誤 Base URL | `200` | `404` | `404` | 重複 `/api/a2a/api/a2a/...` |
| 修正後 A2A Route | `200` | `200`，Task Completed | `200`，事件走到 Completed | `/agents/day16` |

![Day 17 Lab terminal card。左側保留 Agent Card 成功但兩種 invocation 都因重複 prefix 得到 404 的預期失敗。右側則顯示 Agentgateway A2A route 修正 Card URL 後，SendMessage 與 SSE streaming 都通過，stream 走完 submitted、working、artifact 與 completed。](https://raw.githubusercontent.com/MikeHsu0618/2026-ithelp-agent-governance-public/day-15-r1/assets/screenshots/day-17/01-a2a-path-results.png)

完整 [Gateway Route](https://github.com/MikeHsu0618/2026-ithelp-agent-governance-public/blob/day-15-r1/labs/03-gateway-runtime/configs/day-17/a2a-route.yaml)、Probe Source 與文字 Evidence 都在 Repo。我另外整理了 [A2A 路徑驗收清單](https://github.com/MikeHsu0618/2026-ithelp-agent-governance-public/blob/day-15-r1/articles/day-17/a2a-checklist.md)，把 Agent Card、Version、Routing、Streaming、Identity、Trace 與 HITL 分開勾選。讀者不需要從圖片抄指令，也不必把 Kubernetes 環境驗收細節塞進閱讀主線。

## Protocol 接通後，Runtime 能力仍然原封不動

這次結果讓我更確定，kagent 與 agentgateway 不適合用「誰取代誰」來討論。kagent Controller 讓 Agent 有共同 Discovery 與 A2A 入口，agentgateway 把 Public URL、Route 與 Traffic Telemetry 收斂到同一層。A2A 則規範 Client 和 Remote Agent 如何交換 Message、Task、Artifact 與狀態。三者接起來，確實比每個 Agent 自訂 API 更好維運。

Protocol Interoperability 不會讓 Runtime 突然多出原本沒有的 Workflow、Memory、Tool Approval 或 Credential Lifecycle。Declarative Runtime 接不住需求時，A2A 做得再完整，也只是讓其他人更穩定地呼叫一個能力仍受限的 Agent。

下一步就是自己寫 Agent，再用 BYO 方式註冊回 kagent。Day 18 會把 Declarative Agent 與 BYO Agent 放在同一張能力表，實際看 Discovery、A2A、HITL、Memory、Skill、Sandbox、Identity 與 Telemetry 中，哪些能沿用平台，哪些仍由自建 Runtime 負責。
