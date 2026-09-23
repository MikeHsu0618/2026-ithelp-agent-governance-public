# Day 16｜kagent 與 agentgateway 的定位：Agent 平台、Runtime 與流量治理

Day 15 把既有 Ingress 與 agentgateway 的流量責任切開後，仍有一大塊工作沒有人接：Agent 使用哪個 Runtime、如何部署、怎麼被其他 Agent 找到，以及版本更新後由誰重新驗證。Gateway 能管住一筆 Request，卻不會替團隊把 Agent 生出來。這也是我們當初把 kagent 裝進 Kubernetes 的原因。

這次直接用 kagent `0.10.0` 重跑。在 Kubernetes Lab 裡，`ModelConfig` 將 LLM Request 送進 agentgateway，`RemoteMCPServer` 走 Gateway 後面的 MCP Route，kagent 產生的 Agent Service 也能接住 A2A Invocation。三條路都實際跑通，問題已經不再是 Connectivity。

真正的採用門檻，是 Declarative Runtime 能否承載團隊要寫的 Agent，以及 kagent 和 agentgateway 分別接走哪一段責任。這篇不比產品功能數量，而是把同一筆 Request 拆成 Runtime、Control Plane 與 Traffic Path。

![kagent 官方 Logo](https://raw.githubusercontent.com/MikeHsu0618/2026-ithelp-agent-governance-public/day-16-r4/assets/third-party/kagent/kagent-horizontal-color.png)

> kagent Logo 取自 [CNCF artwork repository](https://github.com/cncf/artwork/tree/main/projects/kagent/horizontal/color)，僅用來識別本文討論的專案。

## 連得通只是第一個採用條件

kagent 的 `ModelConfig` 可以把 OpenAI-compatible Base URL 指向 agentgateway，Agent 引用 `RemoteMCPServer` 後，也能由 Gateway 連到 MCP Backend。實跑時，LLM 與 MCP Request 都出現在 agentgateway Access Log，A2A Invocation 則得到 Synthetic Model 回覆的 `boundary-ok`。Routing、Header 與 Backend 已經接對。

平台能不能承載真正的 Agent，還要繼續看 Provider-specific Thinking 設定、複雜 Workflow、長任務狀態，以及 Credential 如何取得與更新。我們以前確實遇過 Provider 設定面不一致的問題，某條 Model Path 能調的參數，換另一個 Provider 未必有同等欄位。新版修好的缺口就應該記為修好，不該為了延續舊結論一直扣分。

`0.10.0` 的 OpenAI Path 已能保存 `reasoningEffort`，這一項直接記 PASS。仍待處理的是 MCP Credential Lifecycle 與多步 Workflow State。這也正是我對 kagent 一直有點「又恨又癢」的原因。它替 Kubernetes 團隊準備了 Agent Deployment、UI、Discovery 與 A2A 入口，確實省掉不少平台工作。Declarative Surface 一旦接不住需求，開發團隊最後仍會回到自建 Runtime。

這時 kagent 的價值不能再用「有沒有 Agent」判斷，而要看它接走了哪些 Control-plane 工作，又把哪些能力留給 Application Team。

## Runtime、Control Plane 與 Traffic Path

幾次討論卡在「kagent 和 agentgateway 是否重疊」後，我們改用三層拆解。

**Runtime** 執行 Agent 行為，包括 Prompt 組合、Model Loop、Memory、Workflow、Tool Call 與 HITL State。Declarative Agent 由 kagent 提供的 ADK Runtime 執行，BYO Agent 則由應用團隊自行實作。agentgateway 不會替任何一邊補出 Business Workflow。

**Control Plane** 保存並協調 Agent 的期望狀態。kagent 讀取 `Agent`、`ModelConfig` 與 `RemoteMCPServer` 等 Resource，產生 Deployment、Service、Runtime Config 與 Agent Card，也讓 UI／CLI 和其他 Agent 有共同的 Discovery 入口。

**Traffic Path** 是 Request 實際經過的地方。agentgateway 在這裡處理 LLM、MCP 或 A2A Route，以及共用的 Authentication、Authorization、Rate Limit、Backend Credential 與 Telemetry。它能看見並管住流量，卻不決定 Agent 下一步要呼叫哪個 Tool。

![kagent 管理 Agent CR、Deployment 與 discovery，應用團隊負責 Agent runtime 邏輯。Agent 發出的 LLM 與 MCP request 經同一個 agentgateway 進入 backend。Runtime、Control Plane、Traffic Path 各有自己的 source of truth。](https://raw.githubusercontent.com/MikeHsu0618/2026-ithelp-agent-governance-public/day-16-r4/assets/diagrams/day-16/runtime-control-traffic-boundary.png)

這三層也解釋了公開 Lab 為什麼不需要兩層 Proxy。Day 15 的既有 Ingress 是 Production 背景，Day 16 只需一個 agentgateway Data Plane。kagent 管理 Agent Workload，agentgateway 接住它產生的 LLM 與 MCP Traffic，已經足以驗證兩者交界。

## MCP 可以直連，也可以經過 Gateway

MCP Server 已經有 ClusterIP 時，kagent 可以讓 Agent 直接連 Service，也能設定全域 `proxy.url`，把內部 Agent-to-MCP Request 改送到 agentgateway。兩條路都合理，差別在誰負責 Policy 與 Evidence。

直接連線時，`RemoteMCPServer` 保存 Endpoint 與 Header Reference，Agent Runtime 自己建立 MCP Session。路徑較短，每個 Runtime 也得各自處理 Authentication、Timeout、Audit 與流量限制。經過 agentgateway 時，共用 Policy 可以收斂在同一個 Traffic Checkpoint，代價是 kagent Endpoint Resource 與 Gateway Route 同時存在，Source of Truth 必須寫清楚。

kagent 的 [Operational Considerations](https://kagent.dev/docs/kagent/operations/operational-considerations/) 說明，`proxy.url` 會改寫內部產生的 Agent-to-Agent 與 Agent-to-MCP URL，並加入 `x-kagent-host` 保存原始目的地。外部 `RemoteMCPServer` URL 則不會被改寫。這不是在 Agent 前憑空多塞一層 Proxy，而是讓 Control Plane 產生的 Internal Route 遵守平台 Egress Policy。

Lab 的 `RemoteMCPServer` 保存原始 Service URL：

```yaml
spec:
  protocol: STREAMABLE_HTTP
  url: http://mcp-everything.day16-lab.svc.cluster.local:3001/mcp
  headersFrom:
  - name: Authorization
    valueFrom:
      type: Secret
      name: day16-mcp-credential
      key: authorization
```

Agent 最後拿到的 Runtime Config 已改成 Gateway URL，並帶著原始 Host：

```json
{
  "url": "http://agentgateway-proxy.agentgateway-system.svc.cluster.local:80/mcp",
  "headers": {
    "Authorization": "<redacted>",
    "x-kagent-host": "mcp-everything.day16-lab.svc.cluster.local"
  }
}
```

前一份 YAML 是 kagent Control Plane 的期望狀態，後一份 JSON 是 Agent Runtime 的實際連線設定，Gateway 的 `HTTPRoute` 才是 Traffic Path 的轉送規則。三份設定都有用途，卻不能同時宣稱自己是相同 Routing Policy 的唯一來源。

## Runtime 設定與維運缺口

這次我用 kagent `0.10.0` 重新檢查最在意的 Runtime 設定。以前對 Declarative Surface 的不滿，不能直接套到現在的版本。但連得通之後，Workflow 與 Credential 仍要有人寫、有人維護。

OpenAI `ModelConfig` 現在能設定 `reasoningEffort`，CRD 與生成的 Runtime Config 都保留 `low`。這修掉了我先前在這條 OpenAI-compatible Path 上遇到的缺口。其他 Provider 要能調到什麼程度，仍要按各自的設定介面看。

`RemoteMCPServer.headersFrom` 能把同 Namespace Secret 的 Authorization Header 放進 Runtime Config。不過團隊若想改用短效 Token，Workload 如何取得、更新，以及失敗後如何復原，仍需要自己的流程。把 Header 接通，和把 Credential Lifecycle 交給平台，是兩件事。

Declarative Agent 會產生 Deployment、Service 與 Agent Card，也能回覆 Synthetic Model 的 `boundary-ok`。這表示基本部署與 Prompt／Model／Tool 接線已可使用。真正複雜的多步 Workflow、Checkpoint 或自訂 HITL，仍取決於 Runtime 能暴露多少設定，或團隊是否改走 BYO Agent。六項逐條結果放在 [Lab 03](https://github.com/MikeHsu0618/2026-ithelp-agent-governance-public/blob/day-16-r4/labs/03-gateway-runtime/README.md)，正文把力氣留給選型差異。

## Kubernetes Lab 只保留會改變判斷的結果

[Lab 03](https://github.com/MikeHsu0618/2026-ithelp-agent-governance-public/blob/day-16-r4/labs/03-gateway-runtime/README.md) 使用獨立 Kind Cluster，只留下 kagent Controller、UI、開發用 PostgreSQL、一個 Declarative Agent、一個 Synthetic LLM 與一個 MCP Fixture。Bundled Agent 與其他不相關元件全部關閉，LLM 也不需要 Gemini 或 OpenAI Key。

重跑指令如下：

```bash
make lab-03-runtime-up
make lab-03-runtime-kagent-plan
make lab-03-runtime-kagent-up
make lab-03-runtime-kagent-invoke
```

![Day 16 實際 Lab terminal card。ModelConfig、RemoteMCPServer 與 Agent 狀態通過，Agent 回覆 boundary-ok，RemoteMCPServer 發現 14 個工具，agentgateway log 同時看到 LLM 與 MCP route。靜態驗收表為四項 PASS、兩項 PARTIAL。](https://raw.githubusercontent.com/MikeHsu0618/2026-ithelp-agent-governance-public/day-16-r4/assets/screenshots/day-16/01-kagent-boundary-results.png)

實跑時，ModelConfig 與 RemoteMCPServer 都是 `Accepted=True`，Agent 同時為 `Accepted=True` 與 `Ready=True`。RemoteMCPServer 發現 14 個 Tool，A2A Invocation 回覆 `boundary-ok`，agentgateway Access Log 也分別看見 Synthetic LLM 與 MCP Route。

完整環境設定與重跑紀錄留在 Lab README。對選型最有用的觀察是：kagent 真的把 Agent 部署出來、Gateway 也確實看得到 LLM 與 MCP Traffic。尚未交給平台的 Workflow 與 Credential 更新，仍要由應用團隊自己承擔。

## 責任矩陣決定平台採用後由誰接手

經過重測後，我會把 kagent 留在 Agent Deployment、Discovery 與 Declarative Runtime 的 Control Plane，agentgateway 接手 LLM／MCP Traffic Policy 與 Traffic Telemetry。Business Logic、Advanced Workflow 和 Credential Acquisition 不會因為兩套平台都裝好就自動消失。

| 責任 | Owner | Source of Truth |
| --- | --- | --- |
| Agent Business Logic／Workflow | Application Team | Agent Source 與 Runtime Test |
| Agent Deployment | kagent | `Agent` CR 與生成的 Deployment |
| Agent Discovery | kagent | Agent Status 與 Agent Card |
| LLM／MCP Traffic Policy | agentgateway | Gateway Route／Policy |
| Credential Acquisition／Refresh | Identity Platform／Application Team | Workload Identity 與 Token Lifecycle |
| Runtime Telemetry | kagent／Application Team | Runtime Span 與 Action Event |
| Traffic Telemetry | agentgateway | Access Log、Metric 與 Trace |

完整版本放在 [Day 16 責任矩陣](https://github.com/MikeHsu0618/2026-ithelp-agent-governance-public/blob/day-16-r4/articles/day-16/responsibility-matrix.md)，每一列都附有驗收方法。它也保留一個不太漂亮但很重要的事實：同一個 Agent 可能同時有 kagent CR、生成的 Runtime Config 與 agentgateway Route。沒有 Owner 與 Source of Truth，Declarative Platform 越多，Drift 只會更難查。

## A2A 接通不會補強 Runtime 能力

這次 Lab 已透過 Agent Service 的 A2A Endpoint 呼叫 Declarative Agent，但 A2A 在本文只負責送進一筆 Request。它證明 kagent 產生的 Runtime 能接受標準 Invocation，不會替 Agent 補出原本不存在的 Workflow、Memory 或 HITL Semantics。

我們過去遇過更直接的問題：Agent Card 從外部 Route 讀得到，真正 Invocation 卻因 Base URL 重複帶上 `/api/a2a` 而走錯路。那次事故把三層差異說得很清楚。Discovery 成功、Traffic Route 存在，仍不保證 Runtime Invocation 正確。

Day 17 會沿著這條失敗路徑拆 A2A，實測 Agent Card、JSON-RPC、Base URL、Context 與 Task Lifecycle 各由誰負責。更重要的是確認一件事：Runtime 本身若太弱，A2A 再標準也只能讓別人更容易呼叫一個能力不足的 Agent。
