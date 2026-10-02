# Day 16｜kagent 與 agentgateway 的定位：Agent 平台、Runtime 與流量治理

Day 15 把既有 Ingress 與 agentgateway 的流量責任切開後，仍有一大塊工作沒有人接：Agent 使用哪個 Runtime、如何部署、怎麼被其他 Agent 找到，以及版本更新後由誰重新驗證。Gateway 能管住一筆 Request，卻不會替團隊把 Agent 生出來。這也是我們當初把 kagent 裝進 Kubernetes 的原因。

如果你已經用 ADK 或 LangGraph 寫出一支 Agent，接下來仍要替它準備 Image、Deployment、Service、模型設定和工具連線。另一個團隊要呼叫它時，也需要知道入口在哪裡。kagent 把這些工作收進 Kubernetes 的 Resource 與控制流程，讓平台團隊能沿用熟悉的部署與操作方式。

這篇先認識 kagent 和 Agent Framework 的分工，再看我們用 `0.10.0` 跑過的 LLM、MCP 與 A2A 路徑。採用時要判斷的，是平台能接走多少工作，以及團隊需要的 Agent 行為能否在它提供的介面中表達。

![kagent 官方 Logo](https://raw.githubusercontent.com/MikeHsu0618/2026-ithelp-agent-governance-public/day-16-r8/assets/third-party/kagent/kagent-horizontal-color.png)

> kagent Logo 取自 [CNCF artwork repository](https://github.com/cncf/artwork/tree/main/projects/kagent/horizontal/color)，僅用來識別本文討論的專案。

## kagent 把 Agent 帶進 Kubernetes 的管理方式

[kagent](https://kagent.dev/docs/kagent/0.x/concepts/architecture/) 是開源的 Kubernetes-native Agent 平台。對開發者而言，可以宣告 Prompt、Model 與 Tool，交給內建 Runtime 執行，也可以提供自己的 Agent Image。對平台團隊而言，`Agent`、`ModelConfig`、`RemoteMCPServer` 讓 Agent 設定成為可審查的 Kubernetes Resource，由 Controller 協調部署，UI 與 CLI 提供操作入口。

官方的 0.x 架構圖先呈現四個角色：Controller、執行 Agent 的 Backend，以及 CLI／Dashboard。這是一張產品總覽，還沒有展開每支 Agent 的 Pod 或 Gateway 路徑。

![kagent 官方 0.x 架構圖：Controller 與 Backend 互動，CLI 與 Dashboard 提供管理和使用入口。](https://raw.githubusercontent.com/MikeHsu0618/2026-ithelp-agent-governance-public/day-16-r8/assets/third-party/kagent/kagent-0x-architecture.png)

> 來源：[kagent 官方架構文件的固定版本](https://github.com/kagent-dev/website/blob/c053e7cb66ec14b6c8767f38042451b33612accc/docs-site/content/kagent/0.x/concepts/architecture.md)，Apache-2.0，原圖未修改。2026-10-01 核對。本文實跑仍為 kagent `0.10.0`。

## Google ADK、LangGraph 與 kagent 的選擇層次

Google ADK 提供寫 Agent 的程式元件：模型迴圈、Tool、Callback、Session，以及 Sequential、Parallel、Loop 等工作流程。這些元件決定 Agent 收到任務後怎麼執行。kagent 的 Python Runtime 建在 ADK 上，把 Kubernetes Resource 轉成 Runtime Config，再接上 MCP 與 A2A 整合。透過這條路徑使用 Declarative Agent 時，開發者用 YAML 表達需求，平台再建構 ADK Agent。不過 kagent 也有 Go Runtime，本篇 `0.10.0` Lab 實際產生的是 Go Runtime，不能用這組結果證明 Python 套件的行為。Day 18 才會以 Python ADK BYO Agent 實跑接入。

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

## Runtime、Control Plane 與 Traffic Path

幾次討論卡在「kagent 和 agentgateway 是否重疊」後，我們改用三層拆解。

**Runtime** 執行 Agent 行為，包括 Prompt 組合、Model Loop、Memory、Workflow、Tool Call 與 HITL State。Declarative Agent 由 kagent 提供的 Runtime 執行，BYO Agent 則由應用團隊自行實作。agentgateway 不會替任何一邊補出 Business Workflow。

**Control Plane** 保存並協調 Agent 的期望狀態。kagent 讀取 `Agent`、`ModelConfig` 與 `RemoteMCPServer` 等 Resource，產生 Deployment、Service、Runtime Config 與 Agent Card，也讓 UI／CLI 和其他 Agent 有共同的 Discovery 入口。

**Traffic Path** 是 Request 實際經過的地方。agentgateway 在這裡處理 LLM、MCP 或 A2A Route，以及共用的 Authentication、Authorization、Rate Limit、Backend Credential 與 Telemetry。它能看見並管住流量，卻不決定 Agent 下一步要呼叫哪個 Tool。

![kagent 管理 Agent CR、Deployment 與 discovery，應用團隊負責 Agent runtime 邏輯。Agent 發出的 LLM 與 MCP request 經同一個 agentgateway 進入 backend。Runtime、Control Plane、Traffic Path 各有自己的 source of truth。](https://raw.githubusercontent.com/MikeHsu0618/2026-ithelp-agent-governance-public/day-16-r8/assets/diagrams/day-16/runtime-control-traffic-boundary.png)

[agentgateway 官方的 Kubernetes 架構圖](https://agentgateway.dev/docs/kubernetes/latest/documentation/about/architecture/)把 Controller 到 Proxy 的設定流與 Client 到 Backend 的請求流分開（2026-09-26 查閱）。上圖再加上 kagent 管理的 Agent Runtime，因為我們要決定的是 Agent 誰來部署、它發出的 LLM／MCP 流量又由誰處理。兩張圖看的層次不同，放在一起比較，較不容易把 Controller 畫成每筆請求都會經過的一站。

這三層也解釋了公開 Lab 為什麼不需要兩層 Proxy。Day 15 的既有 Ingress 是 Production 背景，Day 16 只需一個 agentgateway Data Plane。kagent 管理 Agent Workload，agentgateway 接住它產生的 LLM 與 MCP Traffic，已經足以驗證兩者交界。

## MCP 可以直連，也可以經過 Gateway

MCP Server 已經有 ClusterIP 時，kagent 可以讓 Agent 直接連 Service，也能設定全域 `proxy.url`，把內部 Agent-to-MCP Request 改送到 agentgateway。兩條路都合理，差別在誰負責 Policy 與 Evidence。

直接連線時，`RemoteMCPServer` 保存 Endpoint 與 Header Reference，Agent Runtime 自己建立 MCP Session。路徑較短，每個 Runtime 也得各自處理 Authentication、Timeout、Audit 與流量限制。經過 agentgateway 時，共用 Policy 可以收斂在同一個 Traffic Checkpoint，代價是 kagent Endpoint Resource 與 Gateway Route 同時存在，Source of Truth 必須寫清楚。

kagent 的 [Operational Considerations](https://kagent.dev/docs/kagent/operations/operational-considerations/) 說明，`proxy.url` 會改寫內部產生的 Agent-to-Agent 與 Agent-to-MCP URL，並加入 `x-kagent-host` 保存原始目的地。外部 `RemoteMCPServer` URL 則不會被改寫。這不是在 Agent 前憑空多塞一層 Proxy，而是讓 Control Plane 產生的 Internal Route 遵守平台 Egress Policy。

這組分工可以對照 [Lab 03](https://github.com/MikeHsu0618/2026-ithelp-agent-governance-public/blob/day-16-r8/labs/03-gateway-runtime/README.md) 的 Day 16 設定。`RemoteMCPServer` 保存原始 Service URL：

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

## 用同一組接線檢查 Runtime 設定

我們以前在 kagent `0.9.9` 的宣告式設定遇過 Provider 參數不一致：某條模型路徑能調的設定，換另一個 Provider 未必有同等欄位。到了本次 `0.10.0` Lab，OpenAI `ModelConfig` 已能保存 `reasoningEffort=low`，生成的 Go Runtime 設定也保留這個值。這項舊缺口在測到的路徑上已修好，其他 Provider 則仍要按各自介面核對。

同一組設定也讓我們看清 Credential 的邊界。`RemoteMCPServer.headersFrom` 能把同 Namespace Secret 的 Authorization Header 放進 Runtime Config。若要改用短效 Token，取得、更新與失敗恢復還需要自己的流程。程式讀得到 Secret，和平台會替它更新憑證，是不同的採用條件。

在獨立 Kind Cluster 裡，kagent 建立 Agent，A2A 呼叫得到合成模型的 `boundary-ok`，agentgateway Access Log 則看得到 LLM 與 MCP 兩條流量。前面的 YAML、生成設定與流量觀察，至此對上了同一條路徑。下圖把這幾份結果放在一起，重點是設定是否真的進到執行程式，以及請求是否走過預定入口。

![Day 16 在獨立 Kubernetes 環境的實跑結果：kagent 建立 Agent，A2A 呼叫成功，agentgateway 記下 LLM 與 MCP 兩條流量。完整狀態與重跑指令見 Lab README。](https://raw.githubusercontent.com/MikeHsu0618/2026-ithelp-agent-governance-public/day-16-r8/assets/screenshots/day-16/01-kagent-boundary-results.png)

完整狀態、指令與 Runtime 類型見 [Day 16 evidence](https://github.com/MikeHsu0618/2026-ithelp-agent-governance-public/blob/day-16-r8/assets/screenshots/day-16/evidence.md)。這次使用合成 LLM 與 MCP Fixture 檢查基本接線，沒有驗收複雜 Workflow、Checkpoint 或自訂 HITL。這些需求能否由宣告欄位表達，或必須改走 BYO，仍是團隊採用時要做的判斷。

這也是我對 kagent 一直有點「又恨又癢」的原因。它準備了 Agent Deployment、UI、Discovery 與 A2A 入口，確實省掉不少平台工作。宣告介面接不住需求時，開發團隊仍會回到自建 Runtime。採用的價值要連同剩餘程式工作一起算，接著才有辦法分配 Owner。

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

完整版本放在 [Day 16 責任矩陣](https://github.com/MikeHsu0618/2026-ithelp-agent-governance-public/blob/day-16-r8/articles/day-16/responsibility-matrix.md)，每一列都附有驗收方法。它也保留一個不太漂亮但很重要的事實：同一個 Agent 可能同時有 kagent CR、生成的 Runtime Config 與 agentgateway Route。沒有 Owner 與 Source of Truth，Declarative Platform 越多，Drift 只會更難查。

## 從 Agent 服務走向對外 A2A 入口

這次 A2A 呼叫直接送到 Agent Service，尚未經過對外 Gateway Route。若其他團隊要從公開入口使用這支 Agent，還得確認它公告的 URL 與實際轉送路徑能對得起來。

我們過去遇過更直接的問題：Agent Card 從外部 Route 讀得到，真正 Invocation 卻因 Base URL 重複帶上 `/api/a2a` 而走錯路。那次事故把三層差異說得很清楚。Discovery 成功、Traffic Route 存在，仍不保證 Runtime Invocation 正確。

Day 17 會沿著這條失敗路徑拆 A2A，從 Client 如何讀取 Agent Card，到實際送出工作與追蹤 Task，確認服務公告和真正入口如何一起驗收。
