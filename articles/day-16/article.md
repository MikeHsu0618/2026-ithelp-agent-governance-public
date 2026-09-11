# Day 16｜kagent × agentgateway 實測：Runtime、Control Plane、Traffic Path 各管哪一段

Day 15 把既有 Ingress 與 agentgateway 的流量責任切開之後，還有一大塊工作沒有人接：Agent 要用哪個 Runtime、如何部署、怎麼被其他 Agent 找到，以及版本更新後由誰重新驗證。Gateway 能管住一筆 request，卻不會替團隊把 Agent 生出來。這也是我們當初把 kagent 裝進 Kubernetes 的原因。

這篇直接用 kagent `0.10.0`。在 Kubernetes Lab 裡，`ModelConfig` 已經能把 LLM request 送進 agentgateway，`RemoteMCPServer` 也能走 Gateway 後面的 MCP route，A2A invocation 則由 kagent 產生的 Agent Service 接住。三條路都有實際結果，不靠產品架構圖猜。

我們之前確實踩過 provider 設定面不一致的坑：某條 model path 能調的參數，換一個 provider 就未必有同等欄位。新版已經補掉一部分，現在選型時，修好的缺口就不該繼續扣分。真正要驗收的是 declarative runtime 能不能承載團隊想寫的 Agent，以及 kagent 和 agentgateway 各自該接哪一段責任。Day 16 因此不比功能數量，而是把同一筆 request 拆成 Runtime、Control Plane 與 Traffic Path。

![kagent 官方 Logo](https://raw.githubusercontent.com/MikeHsu0618/2026-ithelp-agent-governance-public/day-19/assets/third-party/kagent/kagent-horizontal-color.png)

> kagent Logo 取自 [CNCF artwork repository](https://github.com/cncf/artwork/tree/main/projects/kagent/horizontal/color)，僅用來識別本文討論的專案。本文與 CNCF、kagent 或 agentgateway 均無隸屬或贊助關係。

## 路徑跑得通，仍沒有跨過採用門檻

這次的 Kubernetes 路徑大致長這樣：kagent 的 `ModelConfig` 把 OpenAI-compatible base URL 指向 agentgateway，Agent 引用 `RemoteMCPServer`，再由 Gateway 連到 MCP fixture。實跑時，LLM 與 MCP request 都出現在 agentgateway access log，A2A invocation 也得到合成模型回覆的 `boundary-ok`。Routing、header 與 backend 已經接對，問題不在 connectivity。

這些結果先回答了「能不能連」。要判斷平台能不能承載我們想寫的 Agent，還得繼續檢查 provider-specific thinking 設定、較複雜的 workflow、長任務狀態，以及不靠長效靜態 JWT 的 credential 取得與更新。

舊坑有修好就算修好，我不打算拿它繼續扣分。`0.10.0` 的 OpenAI path 已能保存 `reasoningEffort`，這項直接記 PASS。後面要看的，是現行設定與實跑仍回答不了的部分：MCP credential 要怎麼取得與更新，以及多步 workflow 的狀態由誰保存。

這正是我對 kagent 一直有點「又恨又癢」的地方。它替 Kubernetes 團隊準備了 Agent deployment、UI、discovery 與 A2A 入口，確實省掉不少平台工作。可是 declarative surface 一旦接不住需求，開發團隊最後還是得改成自己寫 Runtime。此時留下 kagent 的價值，就不能再用「有沒有 Agent」判斷，而要看它還接走了哪些 control-plane 工作。

## Runtime、Control Plane 與 Traffic Path 是三份不同的責任

幾次討論都卡在「兩個產品是不是功能重疊」之後，我們才把問題改成三層來看。**Runtime** 執行 Agent 自己的行為，包括 prompt 組合、model loop、memory、workflow、Tool Call 與 HITL state。Declarative Agent 由 kagent 提供的 ADK runtime 執行，BYO Agent 則由應用團隊自己實作。agentgateway 不會替任何一邊補出 business workflow。

**Control Plane** 保存並協調 Agent 的期望狀態。kagent 讀取 `Agent`、`ModelConfig` 與 `RemoteMCPServer` 等資源，產生 Deployment、Service、runtime config 和 Agent Card，也讓 UI／CLI 與其他 Agent 有共同的 discovery 入口。

**Traffic Path** 才是 request 實際經過的地方。agentgateway 在這裡處理 LLM、MCP 或 A2A route，以及共用的 authentication、authorization、rate limit、backend credential 與 telemetry。它可以看見並管住流量，卻不負責決定 Agent 下一步要呼叫哪個 Tool。

![kagent 管理 Agent CR、Deployment 與 discovery，應用團隊負責 Agent runtime 邏輯。Agent 發出的 LLM 與 MCP request 經同一個 agentgateway 進入 backend。Runtime、Control Plane、Traffic Path 各有自己的 source of truth。](https://raw.githubusercontent.com/MikeHsu0618/2026-ithelp-agent-governance-public/day-19/assets/diagrams/day-16/runtime-control-traffic-boundary.png)

這個拆法也解釋了為什麼公開 Lab 不需要兩層 proxy。Day 15 的既有 Ingress 是實務環境背景，Day 16 只需要一個 agentgateway data plane。kagent 管理 Agent workload，agentgateway 接住它產生的 LLM 與 MCP traffic，已經足以驗證兩者的交界。

## 同一個 MCP Server 可以有兩條合理路徑

假設 MCP Server 已經有 ClusterIP，kagent 可以讓 Agent 直接連 Service，也可以設定全域 `proxy.url`，把內部 Agent-to-MCP request 改送到 agentgateway。兩條路都能工作，差別不在多一個箭頭，而在誰負責政策與證據。

直接連線時，`RemoteMCPServer` 保存 endpoint 與 header reference，Agent runtime 自己建立 MCP session。路徑較短，但每個 Runtime 都得各自處理 auth、timeout、audit 與流量限制。經過 agentgateway 時，共用政策可以收斂在同一個 traffic checkpoint。代價是 kagent 的 endpoint 資源和 Gateway route 同時存在，團隊必須明確指定哪一邊才是 routing 與 policy 的 source of truth。

kagent 的 [Operational considerations](https://kagent.dev/docs/kagent/operations/operational-considerations/) 對這個交界有很具體的行為：`proxy.url` 只改寫內部產生的 Agent-to-Agent 與 Agent-to-MCP URL，並加入 `x-kagent-host`，讓 proxy 知道原始目的地。外部 RemoteMCPServer URL 不會被改寫。這裡不是在 Agent 前面憑空多塞一層 proxy，而是讓 control plane 產生的 internal route 遵守平台的 egress policy。

本次 Lab 的 `RemoteMCPServer` 仍然保存原始 Service URL：

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

Agent 真正拿到的 runtime config 則已經變成：

```json
{
  "url": "http://agentgateway-proxy.agentgateway-system.svc.cluster.local:80/mcp",
  "headers": {
    "Authorization": "<redacted>",
    "x-kagent-host": "mcp-everything.day16-lab.svc.cluster.local"
  }
}
```

前一份 YAML 是 kagent control plane 的期望狀態，後一份 JSON 是 Agent runtime 的實際連線設定，Gateway 的 `HTTPRoute` 才是 traffic path 的轉送規則。三份設定都有用途，但不能讓三邊同時宣稱自己是同一項 routing policy 的 owner。

## 直接驗收 0.10.0：四項通過，兩項仍待補

kagent `0.10.0` 在 2026 年 9 月 4 日發佈，完整變更可以看 [v0.10.0 release](https://github.com/kagent-dev/kagent/releases/tag/v0.10.0)。本次六項驗收全部以這個版本的 API 與實跑結果為準。

目前的 OpenAI `ModelConfig` 可以設定 `reasoningEffort`，本次 CRD 與生成的 Go runtime config 也都保留了 `low`。不過這項 PASS 只適用於被實測的 OpenAI-compatible path，不代表每個 provider 都暴露相同的 thinking surface。依 `0.10.0` API，Gemini config 目前主要是 `maxOutputTokens`，Bedrock 和 OpenAI 則各有不同的 provider-specific 欄位。做平台評估時，不能看到「有 reasoning」就替所有 provider 一起打勾。

`RemoteMCPServer.headersFrom` 可以從同 namespace 的 Secret 或 ConfigMap 取 header，這次也確實把 Authorization 放進 runtime config。它解決的是值從哪裡讀，不是 workload 如何取得短效 Token、何時 refresh、失敗後怎麼復原。本次 YAML 沒有宣告 issuer 或 STS，也沒有跑 client credentials、projected ServiceAccount token 或交換流程，所以這一列只能記成 PARTIAL。這是本次 Lab 的證據邊界，不是把 kagent 其他可能的身分整合一筆勾銷。

Declarative Agent 也成功產生 Deployment、Service、Agent Card，並回覆合成模型的 `boundary-ok`。這足以證明 prompt、model、tool 與 deployment wiring 已經連通，卻不能拿來宣稱任意多步 workflow、checkpoint、rollback 或自訂 HITL 都有相同表達能力。進階 workflow 同樣保留 PARTIAL，等到後面有真正的多步案例再測。

| 驗收項目 | 結果 | 本次能證明的範圍 |
| --- | --- | --- |
| Declarative runtime | PASS | `Agent` CR 產生 Go runtime Deployment 與 Service，狀態為 Ready |
| LLM 經 agentgateway | PASS | ModelConfig base URL 指向 Gateway，實際 request 命中 LLM route 並得到 `200` |
| MCP proxy rewrite | PASS | runtime URL 被改寫並帶 `x-kagent-host`，Gateway log 看到 MCP request |
| OpenAI reasoning effort | PASS | `reasoningEffort: low` 通過 CRD，並出現在生成設定 |
| MCP credential lifecycle | PARTIAL | Secret-backed header 有作用，沒有因此證明 acquisition／refresh |
| Advanced workflow | PARTIAL | prompt、model、tool wiring 可用，未驗證任意多步 workflow |

`4 PASS / 2 PARTIAL` 只是六個事先寫好的驗收結果，不是替 kagent 或 agentgateway 打產品分數，所以這張表不另外算總分。

## 公開 Lab 在獨立 kind cluster 重跑

[Lab 03](https://github.com/MikeHsu0618/2026-ithelp-agent-governance-public/blob/day-19/labs/03-gateway-runtime/README.md) 新增 Day 16 Kubernetes slice。這次使用 kind `0.30.0` 建立 Kubernetes `1.34.0` 叢集，操作端的 kubectl 同樣鎖在 `1.34.x`，其餘元件則是 Gateway API `1.6.0`、kagent `0.10.0` 與 agentgateway `1.5.0`。所有 bundled agents、kmcp、kagent-tools 與 Grafana MCP 都關閉，只留下 kagent controller、UI、開發用 PostgreSQL、一個 declarative Agent、一個 synthetic LLM 和一個 MCP fixture。

Lab 會建立自己的 `kind-ithelp-day16` context，所有 `kubectl` 與 Helm command 都強制使用獨立 kubeconfig。Runner 若看到其他 context 或 `~/.kube/config` 就拒絕執行，因此不會沿用讀者目前指向 UAT／production 的 context。

```bash
make lab-03-runtime-up
make lab-03-runtime-kagent-plan
make lab-03-runtime-kagent-up
make lab-03-runtime-kagent-invoke
```

MCP fixture image 在本機依 lockfile build，再載入 kind node，不會在 Pod 啟動時臨時抓一串浮動的 npm dependencies。Synthetic LLM 只回 OpenAI-compatible 固定結果，不需要 Gemini 或 OpenAI key，也不會呼叫外部服務。kagent 與 agentgateway 的 Helm chart version、Gateway API release URL、Node／Python base image digest，以及 MCP package version 都固定在設定檔或 Makefile。

![Day 16 實際 Lab terminal card。ModelConfig、RemoteMCPServer 與 Agent 狀態通過，Agent 回覆 boundary-ok，RemoteMCPServer 發現 14 個工具，agentgateway log 同時看到 LLM 與 MCP route。靜態驗收表為四項 PASS、兩項 PARTIAL。](https://raw.githubusercontent.com/MikeHsu0618/2026-ithelp-agent-governance-public/day-19/assets/screenshots/day-16/01-kagent-boundary-results.png)

實跑結果中，ModelConfig `Accepted=True`，RemoteMCPServer `Accepted=True` 並發現 14 個 tools，Agent 也同時是 `Accepted=True` 與 `Ready=True`。透過 A2A 呼叫 Agent 後，合成模型回覆 `boundary-ok`，agentgateway access log 也分別留下 `synthetic-llm` 與 `mcp-everything` route。圖片只是方便閱讀，完整 command、原始文字、redacted runtime config 和 machine-readable report 都跟著 repo 一起提供。

Lab 結束後可以刪掉它建立的 cluster：

```bash
make lab-03-runtime-kagent-down
```

Cleanup 先驗證 kubeconfig 的 current context 必須精確等於 `kind-ithelp-day16`，再刪除名稱完全相同的 kind cluster。全域 kubeconfig 不在這條路徑裡。

## 把選型結果寫成責任矩陣

經過這次重測，我會把 kagent 留在 Agent deployment、discovery 與 declarative runtime 的 control plane，agentgateway 則接手 LLM／MCP traffic policy 與 traffic telemetry。Agent business logic、進階 workflow 和 credential acquisition 不會因為兩套平台都裝好就自動消失，仍要指定 Application Team 或 Identity Platform 負責。

| 責任 | Owner | Source of truth |
| --- | --- | --- |
| Agent business logic／workflow | Application Team | Agent source 與 runtime tests |
| Agent deployment | kagent | `Agent` CR 與生成的 Deployment |
| Agent discovery | kagent | Agent status 與 Agent Card |
| LLM traffic policy | agentgateway | Gateway route／policy |
| MCP traffic policy | agentgateway | Gateway route／policy |
| Credential acquisition／refresh | Identity Platform／Application Team | workload identity 與 token lifecycle |
| Runtime telemetry | kagent／Application Team | runtime span 與 action event |
| Traffic telemetry | agentgateway | access log、metric 與 trace |

完整版本放在 [Day 16 責任矩陣](https://github.com/MikeHsu0618/2026-ithelp-agent-governance-public/blob/day-19/articles/day-16/responsibility-matrix.md)，每一列都附有驗收方法。這份表也保留一個不漂亮但很重要的事實：同一個 Agent 可能同時有 kagent CR、生成的 runtime config 和 agentgateway route。沒有 owner 與 source of truth，宣告式平台越多，drift 只會更難查。

## A2A 接通，不代表 Runtime 突然變強

這次 Lab 已經透過 Agent Service 的 A2A endpoint 呼叫 declarative Agent，但 A2A 在本文只用來送進一筆 request，沒有再繞進 agentgateway。它證明 kagent 產生的 Runtime 能以 A2A 接受 invocation，沒有替 Agent 補出原本不存在的 workflow、memory 或 HITL semantics。A2A 經 Gateway 的 route 會和錯誤前綴一起留到 Day 17。

我們過去也遇過更直接的問題：Agent Card 從外部 route 讀得到，真正 invocation 卻因 base URL 重複帶上 `/api/a2a` 而走錯路。那次事故把三層差異說得很清楚：discovery 成功、traffic route 存在，仍然不保證 Runtime invocation 一定正確。

Day 17 會沿著這條失敗路徑拆 A2A。除了 Agent Card 與 JSON-RPC 格式，還要實測 base URL、context、task lifecycle 與 Gateway route 各由誰負責。更重要的是確認一件事：如果 Runtime 本身太弱，A2A 再標準也只能讓別人更容易呼叫一個能力不足的 Agent。
