# Day 16｜kagent 與 agentgateway 的定位：Agent 平台、Runtime 與流量治理

Day 15 把既有 Ingress 與 agentgateway 的流量責任切開後，仍有一大塊工作沒有人接：Agent 使用哪個 Runtime、如何部署、怎麼被其他 Agent 找到，以及版本更新後由誰重新驗證。Gateway 能管住一筆 Request，卻不會替團隊把 Agent 生出來。這也是我們當初把 kagent 裝進 Kubernetes 的原因。

如果你已經用 ADK 或 LangGraph 寫出一支 Agent，接下來仍要替它準備 Image、Deployment、Service、模型設定和工具連線。另一個團隊要呼叫它時，也需要知道入口在哪裡。kagent 把這些工作收進 Kubernetes 的 Resource 與控制流程，讓平台團隊能沿用熟悉的部署與操作方式。

這篇先認識 kagent 和 Agent Framework 的分工，再看我們用 `0.10.0` 跑過的 LLM、MCP 與 A2A 路徑。採用時要判斷的，是平台能接走多少工作，以及團隊需要的 Agent 行為能否在它提供的介面中表達。

![kagent 官方 Logo](https://raw.githubusercontent.com/MikeHsu0618/2026-ithelp-agent-governance-public/day-16-r7/assets/third-party/kagent/kagent-horizontal-color.png)

> kagent Logo 取自 [CNCF artwork repository](https://github.com/cncf/artwork/tree/main/projects/kagent/horizontal/color)，僅用來識別本文討論的專案。

## kagent 把 Agent 帶進 Kubernetes 的管理方式

[kagent](https://kagent.dev/docs/kagent/0.x/concepts/architecture/) 是開源的 Kubernetes-native Agent 平台。對開發者而言，可以宣告 Prompt、Model 與 Tool，交給內建 Runtime 執行，也可以提供自己的 Agent Image。對平台團隊而言，`Agent`、`ModelConfig`、`RemoteMCPServer` 讓 Agent 設定成為可審查的 Kubernetes Resource，由 Controller 協調部署，UI 與 CLI 提供操作入口。

官方的 0.x 架構圖先呈現四個角色：Controller、執行 Agent 的 Backend，以及 CLI／Dashboard。這是一張產品總覽，還沒有展開每支 Agent 的 Pod 或 Gateway 路徑。

![kagent 官方 0.x 架構圖：Controller 與 Backend 互動，CLI 與 Dashboard 提供管理和使用入口。](https://raw.githubusercontent.com/MikeHsu0618/2026-ithelp-agent-governance-public/day-16-r7/assets/third-party/kagent/kagent-0x-architecture.png)

> 來源：[kagent 官方架構文件的固定版本](https://github.com/kagent-dev/website/blob/c053e7cb66ec14b6c8767f38042451b33612accc/docs-site/content/kagent/0.x/concepts/architecture.md)，Apache-2.0，原圖未修改。2026-10-01 核對。本文實跑仍為 kagent `0.10.0`。

## Google ADK、LangGraph 與 kagent 的選擇層次

Google ADK 提供寫 Agent 的程式元件：模型迴圈、Tool、Callback、Session，以及 Sequential、Parallel、Loop 等工作流程。這些元件決定 Agent 收到任務後怎麼執行。本篇使用的 kagent Python Runtime 建在 ADK 上，再把 Kubernetes Resource 轉成 Runtime Config，接上 MCP 與 A2A 整合。因此選用 kagent 的 Declarative Agent 時，你已經間接使用 ADK，只是透過 YAML 表達 Agent。

直接寫 ADK 程式，可以控制 Callback 與流程組合。改用 Declarative Agent，則把一部分程式與接線工作交給平台。ADK 有某個 API，不代表 kagent 的 CRD 已把該 API 全部暴露出來。這個差距，才是評估進階 Workflow 或 Provider-specific 設定時要檢查的地方。依據是 [ADK 核心概念](https://adk.dev/get-started/about/)與 [kagent `0.10.0` 的 ADK 整合套件](https://github.com/kagent-dev/kagent/tree/v0.10.0/python/packages/kagent-adk)。

幾個常被放在一起比較的名字，其實解決不同層次的工作：

| 選項 | 寫 Agent 時主要控制什麼 | 部署到團隊平台時需要接上的工作 |
| --- | --- | --- |
| Google ADK | Agent、Tool、Callback、Session 與工作流程 | Image、服務入口、環境設定及狀態儲存的部署整合 |
| LangGraph | Graph、State、Checkpoint、Interrupt 與恢復執行 | 選擇自建或託管部署，再接上團隊的身分、入口與操作流程 |
| CrewAI | Crew 中的角色、Task 與協作流程 | 將程式與相依套件交付到執行環境，接上服務與維運流程 |
| kagent Declarative Agent | CRD 暴露的 Prompt、Model、Tool 等設定 | 平台產生 Workload 與發現入口。仍要設計權限和 Credential Lifecycle |
| kagent BYO Agent | 保留所選 Framework 的程式控制能力 | 作者提供符合平台合約的 Image，kagent 接手部署與平台接入 |

這份比較把開發介面與平台工作分開，讓選擇能對應團隊目前要補的能力。[LangGraph 官方定位](https://docs.langchain.com/oss/python/langgraph/overview)強調有狀態、可持續執行的編排。[CrewAI 的 Crew 概念](https://docs.crewai.com/en/concepts/crews)則從角色與任務分工出發。團隊已經有其中一套程式時，可以沿 BYO 路徑評估接入，不必先把內部流程重寫成另一套宣告格式。

對 Kubernetes 團隊，kagent 的吸引力是讓 Agent 和既有 Workload 用相近的方式交付、觀察與管理。若團隊只需要單支應用裡的 Agent Loop，直接用 Framework 也能成立。到了多團隊需要共同部署與發現入口時，平台層的工作才開始有集中處理的價值。

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

![kagent 管理 Agent CR、Deployment 與 discovery，應用團隊負責 Agent runtime 邏輯。Agent 發出的 LLM 與 MCP request 經同一個 agentgateway 進入 backend。Runtime、Control Plane、Traffic Path 各有自己的 source of truth。](https://raw.githubusercontent.com/MikeHsu0618/2026-ithelp-agent-governance-public/day-16-r7/assets/diagrams/day-16/runtime-control-traffic-boundary.png)

[agentgateway 官方的 Kubernetes 架構圖](https://agentgateway.dev/docs/kubernetes/latest/documentation/about/architecture/)把 Controller 到 Proxy 的設定流與 Client 到 Backend 的請求流分開（2026-09-26 查閱）。上圖再加上 kagent 管理的 Agent Runtime，因為我們要決定的是 Agent 誰來部署、它發出的 LLM／MCP 流量又由誰處理。兩張圖看的層次不同，放在一起比較，較不容易把 Controller 畫成每筆請求都會經過的一站。

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

Declarative Agent 會產生 Deployment、Service 與 Agent Card，也能回覆 Synthetic Model 的 `boundary-ok`。這表示基本部署與 Prompt／Model／Tool 接線已可使用。真正複雜的多步 Workflow、Checkpoint 或自訂 HITL，仍取決於 Runtime 能暴露多少設定，或團隊是否改走 BYO Agent。六項逐條結果放在 [Lab 03](https://github.com/MikeHsu0618/2026-ithelp-agent-governance-public/blob/day-16-r7/labs/03-gateway-runtime/README.md)，正文把力氣留給選型差異。

## 部署跑通後，Runtime 責任仍在原處

在獨立 Kind Cluster 裡，kagent 確實建立了 Declarative Agent，A2A 呼叫得到 `boundary-ok`，agentgateway 的 Access Log 也看得到 Agent 發出的 LLM 與 MCP 流量。這排除了「兩套元件根本接不起來」的疑問，卻沒有改變我們最在意的採用條件：複雜 Workflow 與 Credential 更新仍由誰設計和維護。

![Day 16 在獨立 Kubernetes 環境的實跑結果：kagent 建立 Agent，A2A 呼叫成功，agentgateway 記下 LLM 與 MCP 兩條流量。完整狀態與重跑指令見 Lab README。](https://raw.githubusercontent.com/MikeHsu0618/2026-ithelp-agent-governance-public/day-16-r7/assets/screenshots/day-16/01-kagent-boundary-results.png)

[Lab 03](https://github.com/MikeHsu0618/2026-ithelp-agent-governance-public/blob/day-16-r7/labs/03-gateway-runtime/README.md) 留有部署設定、指令和逐項狀態。它使用合成 LLM 與 MCP Fixture 觀察接線，沒有拿 API Key 或業務資料做演示。對我們的選型而言，連線已經成立，下一步要談的是平台採用後，哪一組團隊接住尚未消失的 Runtime 工作。

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

完整版本放在 [Day 16 責任矩陣](https://github.com/MikeHsu0618/2026-ithelp-agent-governance-public/blob/day-16-r7/articles/day-16/responsibility-matrix.md)，每一列都附有驗收方法。它也保留一個不太漂亮但很重要的事實：同一個 Agent 可能同時有 kagent CR、生成的 Runtime Config 與 agentgateway Route。沒有 Owner 與 Source of Truth，Declarative Platform 越多，Drift 只會更難查。

## A2A 接通不會補強 Runtime 能力

這次 Lab 已透過 Agent Service 的 A2A Endpoint 呼叫 Declarative Agent，但 A2A 在本文只負責送進一筆 Request。它證明 kagent 產生的 Runtime 能接受標準 Invocation，不會替 Agent 補出原本不存在的 Workflow、Memory 或 HITL Semantics。

我們過去遇過更直接的問題：Agent Card 從外部 Route 讀得到，真正 Invocation 卻因 Base URL 重複帶上 `/api/a2a` 而走錯路。那次事故把三層差異說得很清楚。Discovery 成功、Traffic Route 存在，仍不保證 Runtime Invocation 正確。

Day 17 會沿著這條失敗路徑拆 A2A，實測 Agent Card、JSON-RPC、Base URL、Context 與 Task Lifecycle 各由誰負責。更重要的是確認一件事：Runtime 本身若太弱，A2A 再標準也只能讓別人更容易呼叫一個能力不足的 Agent。
