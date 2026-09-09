# Day 17｜Agent Card 讀得到，A2A Invocation 卻卡在錯誤路徑

Day 16 已經證明 kagent 能部署 declarative Agent，LLM 與 MCP traffic 也能經過 agentgateway。接著把 A2A 對外開放時，我曾遇過一個很容易誤判的狀況：Agent Card 回了 `200 OK`，內容看起來也像一張完整的 Card。A2A client 讀出裡面的 URL 再送出 invocation，得到的卻是 `404`。

如果監控只檢查 `/.well-known/agent-card.json`，這個 Agent 會被判定為正常。若測試工具繞過 Card，直接把 request 打到自己知道的 controller path，同樣可能得到成功結果。兩邊的綠燈加在一起，還是沒有測到真正的 client 行為：先做 discovery，再照 Agent Card 公告的 interface URL 發出請求。

這次公開 Lab 把當時的錯誤配置放回 disposable Kubernetes cluster。壞掉的 Card 會公告一條重複 `/api/a2a` 的路徑，修正之後，再用同一個 probe 驗 Agent Card、一般 invocation、SSE streaming 與 task lifecycle。這個案例剛好可以把 A2A、kagent runtime 和 agentgateway 各自負責的部分拆清楚。

## Agent Card 的 200 OK 只證明 Discovery

A2A 的 Agent Card 是 discovery contract。依目前的 [A2A Agent Discovery 規格](https://a2a-protocol.org/latest/topics/agent-discovery/)，client 可以從 Agent base URL 下的 `/.well-known/agent-card.json` 取得名稱、能力、skills、security requirements 與支援的 protocol interface。

Card 讀得到，代表 DNS、TLS、Gateway route 與 GET path 至少有一條可用路徑。它並沒有替 Card 裡的每一個 URL 做連線測試，也不知道後面的 Runtime 能不能建立 task。當時出問題的組合可以縮成這兩步：

```text
GET  /api/a2a/day16-lab/day16-agent/.well-known/agent-card.json  -> 200
POST /api/a2a/api/a2a/day16-lab/day16-agent                     -> 404
```

第二行不是手動亂接的 URL，而是 client 照著 Card 的 `supportedInterfaces[].url` 呼叫。也就是說，Discovery 本身成功了，Discovery 提供的下一站卻是錯的。

![A2A client 依序通過 Discovery、Routing 與 Runtime Execution。錯誤範例在 Agent Card 公告 URL 時重複加入 api/a2a，導致 invocation 停在 Gateway 404。修正後則由 agentgateway 的 A2A route 對外公告 agents/day16，再轉到 kagent controller。](https://raw.githubusercontent.com/MikeHsu0618/2026-ithelp-agent-governance-public/day-17/assets/diagrams/day-17/a2a-discovery-routing-runtime.png)

## 重複的 `/api/a2a` 來自兩邊都以為路徑還沒加

kagent controller 的 A2A mux 位於 `/api/a2a/{namespace}/{name}`。`controller.a2aBaseUrl` 的用途不是設定完整 route，而是告訴 controller 對外應該公告哪個 scheme 與 host。kagent 產生 Agent Card 時，還會在這個值後面接上自己的 A2A path。

當年的設定把 path 也寫進 base URL：

```yaml
controller:
  a2aBaseUrl: https://agent.example.test/api/a2a
```

於是 controller 再補一次 `/api/a2a/{namespace}/{name}`，Card 最後變成：

```text
https://agent.example.test/api/a2a/api/a2a/day16-lab/day16-agent
```

修正不需要在 Gateway 疊另一組猜測規則，只要讓 base URL 回到 host boundary：

```yaml
controller:
  a2aBaseUrl: https://agent.example.test
```

kagent `0.10.0` 的 [controller 啟動程式](https://github.com/kagent-dev/kagent/blob/v0.10.0/go/core/pkg/app/app.go) 會把 `APIPathA2A` 接在 `A2ABaseUrl` 後面，registrar 再加 namespace 與 Agent name。這個細節不是要讀者背 source code，而是提醒平台設定的 `base URL`、`prefix`、`full endpoint` 不能只靠欄位名稱猜。接 Gateway 時，至少要把最終 Agent Card 抓出來看一次。

## A2A 1.0 需要對齊 Card、Header 與 Wire Format

本篇直接驗 A2A `1.0`，沒有把新舊 JSON-RPC method 混在同一段範例裡。Probe 會從 Card 的 `supportedInterfaces` 選出 `protocolVersion: "1.0"` 與 `protocolBinding: "JSONRPC"`，並明確送出：

```http
A2A-Version: 1.0
Content-Type: application/json
Accept: application/json
```

一般呼叫使用 `SendMessage`。Message role 是 `ROLE_USER`，成功回應中的 Task 位於 `result.task`，而不是只要 JSON-RPC 外層沒有 error 就算完成。Lab 還會檢查三個值：

- `status.state` 必須走到 `TASK_STATE_COMPLETED`。
- `contextId` 必須存在，後續 turn 才有共同的 conversation context。
- Agent 的 history 或 artifact 必須真的包含預期回覆 `boundary-ok`。

kagent `0.10.0` 產生的 Card 同時公告 `0.3` 與 `1.0` JSON-RPC interface，外部 caller 可以用 `A2A-Version` 選擇。這是 migration compatibility，不代表整條內部路徑已經只剩一個版本。回查同一版的 [A2A registrar source](https://github.com/kagent-dev/kagent/blob/v0.10.0/go/core/internal/a2a/a2a_registrar.go)，managed Agent 的 controller-to-runtime forwarding 仍保留 `0.3` interface 的相容處理。對平台驗收來說，Card 寫了 `1.0` 與外部 `1.0` request 實際跑通是兩份證據，不能只留前一份。

## Streaming 要驗事件順序，不只看 Content-Type

SSE endpoint 回 `text/event-stream` 仍可能在中途送出 error，或永遠停在 working。這次 `SendStreamingMessage` 的驗收會逐一解析 SSE `data:` event，實際收到的順序如下：

```text
SUBMITTED
WORKING
AGENT_MESSAGE
ARTIFACT(last)
COMPLETED
```

五個 event 使用同一組 `taskId` 與 `contextId`，artifact 帶有 `lastChunk: true`，最後一個 task state 才是 `TASK_STATE_COMPLETED`。`HTTP 200`、正確 Content-Type、收到文字與 task 完成是四個不同條件，只檢查其中一項，很容易把半途斷線的長任務寫成成功。

這也是 A2A 比「Agent 之間互相打一個 HTTP API」多出來的價值。依 [A2A 1.0 Specification](https://a2a-protocol.org/latest/specification/)，message、task、artifact、streaming update 與 terminal state 都有共同語意。Client 不需要知道遠端 Agent 用 ADK、LangGraph 或自建 loop，仍能用同一套外部 contract 追蹤工作進度。

## Agentgateway 的 A2A Route 不只是 HTTP Pass-through

公開 Lab 保留兩條 route。第一條使用一般 static HTTP backend，完整轉送 kagent controller 的 `/api/a2a/...` path，目的是忠實重現當年的問題：Gateway 不改 Agent Card，Card 裡公告錯 URL，client 就真的走到錯 URL。

第二條改用 agentgateway `1.5.0` 的 `AgentgatewayBackend.spec.a2a`，公開路徑縮成 `/agents/day16`，後端再 rewrite 到 kagent controller：

```yaml
apiVersion: agentgateway.dev/v1alpha1
kind: AgentgatewayBackend
metadata:
  name: day17-kagent-a2a
spec:
  a2a:
    host: kagent-controller.kagent.svc.cluster.local
    port: 8083
---
apiVersion: gateway.networking.k8s.io/v1
kind: HTTPRoute
metadata:
  name: day17-kagent-a2a
spec:
  rules:
  - matches:
    - path:
        type: PathPrefix
        value: /agents/day16
    filters:
    - type: URLRewrite
      urlRewrite:
        path:
          type: ReplacePrefixMatch
          replacePrefixMatch: /api/a2a/day16-lab/day16-agent
```

現在的 [agentgateway A2A routing](https://agentgateway.dev/docs/kubernetes/latest/documentation/agent/a2a/) 會把 Agent Card 裡的 interface URL 改寫成 client 看得到的 Gateway URL。本次抓到的 Card 因此公告 `/agents/day16`，而不是洩漏 controller 的內部 service path。這項行為是 A2A-aware Gateway 的實際價值，不只是把 HTTP request 往後送。

同一筆一般 invocation 也在 access log 留下 `protocol=a2a`、`a2a.method=SendMessage`、`a2a.response.outcome=success`、`a2a.task.state=TASK_STATE_COMPLETED` 與 `a2a.context.id`。Streaming request 則可辨識為 `SendStreamingMessage`。Gateway 因而成為跨 Runtime 共用的 routing 與 traffic telemetry checkpoint，但 task 內部為何進入某個 state，仍要回 Runtime trace 查。

## Task State 能表達等待，不能替平台執行 HITL

A2A `1.0` 的 task state 包含 `TASK_STATE_INPUT_REQUIRED` 與 `TASK_STATE_AUTH_REQUIRED`。它們很重要，因為遠端 Agent 可以用標準方式告訴 client：「目前不是完成或失敗，而是在等資料或授權。」不過這只是跨 Agent 的狀態語意，還沒有回答誰顯示 Approve／Reject、誰驗證 approver、decision 放在哪裡，以及 Runtime 要如何 resume。

同樣地，Agent Card 可以宣告 security scheme，transport credential 也能在 Gateway 驗證，但它們不會自動建立 Day 9 那條 Human → Service → Agent 的 delegation chain。A2A 解決的是不同 Agent 如何交換 message、task 與 artifact，business authorization、approval workflow、memory 和 execution sandbox 仍有各自的 owner。

這次 Lab 只把真正跑到的 `TASK_STATE_COMPLETED` 標成 PASS。`INPUT_REQUIRED` 與 `AUTH_REQUIRED` 在本文屬於規格邊界說明，不會因為規格有定義，就寫成 kagent HITL 已經驗證完成。這個差別會留到 Day 18，用 BYO Agent 實際測 approve、reject 與 resume。

## 公開 Lab 先重現錯誤，再用同一支 Probe 修回來

[Lab 03 的 Day 17 區段](https://github.com/MikeHsu0618/2026-ithelp-agent-governance-public/blob/day-17/labs/03-gateway-runtime/README.md) 沿用 Day 16 的 disposable kind cluster、kagent `0.10.0`、agentgateway `1.5.0` 與 synthetic LLM，不需要任何 LLM API key。下面一條命令會先放入錯誤 base URL，再恢復 host-only 設定並重跑正向路徑：

```bash
make lab-03-runtime-a2a
```

錯誤設定的結果不是測試壞掉，而是預期中的 failure reproduction：

```text
Agent Card                     HTTP 200 PASS
A2A 1.0 / SendMessage          HTTP 404 EXPECTED_FAIL
A2A 1.0 / SSE stream           HTTP 404 EXPECTED_FAIL

advertised-url=.../api/a2a/api/a2a/day16-lab/day16-agent
stream-events=NOT_REACHED

matched 3/3
```

修正設定後，同一個 client 不更換判斷標準：

```text
Agent Card                     HTTP 200 PASS
A2A 1.0 / SendMessage          HTTP 200 PASS
A2A 1.0 / SSE stream           HTTP 200 PASS

advertised-url=.../agents/day16
task-state=TASK_STATE_COMPLETED
agent-reply=boundary-ok
stream-events=SUBMITTED > WORKING > AGENT_MESSAGE > ARTIFACT(last) > COMPLETED
stream-last-chunk=true

matched 3/3
```

![Day 17 Lab terminal card。左側保留 Agent Card 成功但兩種 invocation 都因重複 prefix 得到 404 的預期失敗。右側則顯示 Agentgateway A2A route 修正 Card URL 後，SendMessage 與 SSE streaming 都通過，stream 走完 submitted、working、artifact 與 completed。](https://raw.githubusercontent.com/MikeHsu0618/2026-ithelp-agent-governance-public/day-17/assets/screenshots/day-17/01-a2a-path-results.png)

圖片只用來快速比對，完整 command、[Gateway route](https://github.com/MikeHsu0618/2026-ithelp-agent-governance-public/blob/day-17/labs/03-gateway-runtime/configs/day-17/a2a-route.yaml)、probe source 與文字 evidence 都在 repo。我另外整理了一份可帶回其他環境使用的 [A2A 路徑驗收清單](https://github.com/MikeHsu0618/2026-ithelp-agent-governance-public/blob/day-17/articles/day-17/a2a-checklist.md)，把 Agent Card、version、routing、streaming、identity、trace 與 HITL 分開勾選。驗收完成後，仍由 Day 16 的 cleanup target 刪除 Lab 自己建立的 cluster：

```bash
make lab-03-runtime-kagent-down
```

## A2A 接通之後，Runtime 能力仍然原封不動

這次結果讓我更確定，kagent 與 agentgateway 不該用「誰取代誰」來討論。kagent controller 讓 Agent 有共同的 discovery 與 A2A 入口，agentgateway 把公開 URL、route 與 traffic telemetry 收斂到同一層。A2A 則規範 client 與 remote Agent 如何交換 message、task、artifact 和狀態。三者接起來，確實比每個 Agent 自訂一套 API 好維運。

可是協定互通不會讓 Runtime 突然多出原本沒有的 workflow、memory、Tool approval 或 credential lifecycle。如果 declarative runtime 接不住需求，A2A 做得再完整，也只是讓其他人更穩定地呼叫一個能力仍然受限的 Agent。

這就帶到下一個更實際的選擇：自己寫 Agent，再用 BYO 方式註冊回 kagent。Day 18 不會只看 Dashboard 找不找得到、CLI 能不能呼叫，而是把 declarative Agent 與 BYO Agent 放在同一張能力表，逐項驗 discovery、Agent-as-Tool、HITL、memory、skills、sandbox、identity 與 telemetry。A2A 解決了接頭，接頭後面能不能真正工作，還得由 Runtime 的實測回答。
