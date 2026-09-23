# Day 15｜導入 AI Gateway 與原有 Gateway 的職責切分

把 agentgateway 接進 Kubernetes 後，我們沒有拆掉原本的 Ingress。Public Host、Certificate 與其他服務都還在既有入口上，為了多一條 AI Route 就重做整個對外邊界，變更範圍太大，也沒有必要。

麻煩出在兩層都能做相同的事。它們都能驗 Token、改 Header、Rate Limit、設定 Timeout，甚至重送失敗的 Request。串接當天很快就通了，後續 Review 卻一直卡在功能重疊。相同行為有兩份設定，事故發生時也會出現兩套說法。

最後讓討論停止打轉的方法，不是比較哪個產品功能比較強，而是逐項指定唯一 Owner。既有入口保留 TLS、Public Host、粗粒度 Routing 與 Access Log。Caller Authentication、AI-aware Policy、Backend Credential 與 Audit Context 則交給 agentgateway。公開 Lab 不複製兩層 Proxy，只驗證 Agent Gateway 接手後必須交付的 Traffic Contract。

## 既有入口留著，但縮成 Pass-through

當時的既有元件是 Kong。[Kong Ingress Controller](https://developer.konghq.com/kubernetes-ingress-controller/) 會把 Kubernetes `Ingress`、`HTTPRoute` 等 Resource 轉成 Kong Gateway 設定，真正接收 Request、執行 Plugin 並轉送 Upstream Traffic 的則是 Kong Gateway。

Kong 本來就能處理許多流量控制。它繼續留在架構裡，是因為 Public Endpoint、Certificate、Host Routing、其他非 AI Service 與既有 Access Log 已經由這層承接。導入 agentgateway 後，AI Route 上只保留幾項入口責任：

- 終止 TLS，接住 Public Host。
- 依 Host 或粗粒度 Path，把 AI Traffic 送進 agentgateway。
- 保留 Connection-level 資訊與既有 Access Log。
- agentgateway 無法服務時回 `502` 或 `503`，不開直達 Backend 的旁路。

Caller JWT、Consumer Key、MCP／A2A／LLM-aware Policy、Backend Credential 與 AI Audit 都往 agentgateway 收斂。前一層也拿掉會讀寫 Body 的 Filter、AI Route 上的 Application Retry，以及可能改變 SSE 行為的 Response Processing。

這裡的 Pass-through 不等於「Kong 什麼都不做」。它仍是企業入口，只是不再解釋 AI Route 的 Caller Identity，也不替後面的治理層做第二次決策。判斷邊界時，不能只數每層開了多少功能，還要看它是否改動另一層負責的 Identity、Credential 或 Body。

## 兩層重複設定會放大排錯成本

假設 Edge 與 agentgateway 都驗同一枚 JWT。兩邊的 JWKS Cache 更新時間不同，或其中一邊少驗一個 Audience，就可能出現外層放行、內層回 `401`。Client 只看到 Authentication Failure，值班的人卻要同時排查 IdP、兩份 Policy 與 Route。

Header Mutation 也會破壞 Day 14 才拆開的 Credential Boundary。Edge 如果先替換 `Authorization`，agentgateway 就看不到 Caller Credential。兩邊各產生一個 Request ID 時，Trace 與 Audit 也很難自然接起來。普通 JSON Request 也許看不出問題，Response Buffering 或 Body Filter 到了 SSE 才會讓模型看起來像卡住。

Retry 更需要分清楚產品預設與架構風險。若兩層都設定「失敗後再試一次」，一次呼叫在最壞情況下可能放大成四次。後面若接的是付款、刪除或修改設定的 Tool，代價就不只是多花一些 Token。這個四次呼叫是雙層 Application Retry 的風險模型，不是 Kong 遇到每個 `5xx` 或 `429` 都會自動重送。Kong 的預設行為主要處理特定 Transport Failure，Response Body 已開始 Streaming 後也不會任意重試。

幾次 Review 都繞回相同問題後，我們把順序反過來。先替每項功能指定 Owner，再決定開啟哪個產品選項。兩層都需要保留控制時，就拆成不同維度，例如外層限制 IP Abuse，內層計算 Principal Quota，而不是複製同一份 Rule。

## 責任矩陣替每個行為留下唯一 Owner

| 能力 | Edge／既有 Ingress | Agent Gateway |
| --- | --- | --- |
| Authentication | 限制網路來源並原樣轉送 Caller `Authorization` | 驗 Issuer、Audience、Principal、Consumer 與 Resource Policy |
| Rate Limit | IP、Connection、通用 Abuse Protection | Principal、Client、Model、Tool、Provider Quota |
| Routing | Public Host、粗粒度 Path | LLM／MCP／A2A-aware Routing |
| Header | Forwarding 與 Trace Contract | Audit Context、Backend Credential、移除不可信 Internal Header |
| Retry | AI Route 不設定 Application Retry | 只有具 Idempotency Contract 的 Operation 才考慮開啟 |
| Telemetry | TLS、Connection、Host、Request ID | Identity、Policy、Model／Tool Decision、Backend Outcome |

這張表的用途是逼每個行為留下唯一 Owner，不是要求所有環境都部署相同拓撲。完整版本放在 [Edge／Ingress 與 Agent Gateway 責任矩陣](https://github.com/MikeHsu0618/2026-ithelp-agent-governance-public/blob/day-19-r2/articles/day-15/proxy-responsibility-matrix.md)，另外包含 Timeout、SSE、Error Propagation 與 Fail-closed，可直接帶進 Route Review。

下面的架構圖來自去識別化的實務 Topology，只保留 Request 經過的邊界與每一層可以改動的資料。

![Client 經既有 Ingress 進入 agentgateway，再呼叫只開放內部路徑的 LLM、MCP 或 Agent backend。既有入口負責 TLS、public host、基本 routing 與 access log，原樣轉送 caller authorization、trace context 與 SSE。Agentgateway 負責 caller authentication、AI-aware policy、backend credential 與 AI telemetry。兩層資料以同一 correlation context 進入 LGTM，agentgateway 不可用時回 502 或 503，不能繞過 Gateway 直連 backend。](https://raw.githubusercontent.com/MikeHsu0618/2026-ithelp-agent-governance-public/day-19-r2/assets/diagrams/day-15/ingress-boundary.png)

Backend 在 Network 與 Routing 上都不接受 Edge 直接呼叫。agentgateway 掛掉時，Request 必須明確失敗。如果 Edge 還藏著一條 Fallback Route 可以直連 MCP Server 或 LLM Provider，最需要治理的時候反而會繞過治理點。

兩層 Telemetry 也回答不同問題。Edge Log 用來看 TLS、Host、Connection 與入口 Request ID，agentgateway 才記錄 Principal、Policy、Model／Tool 與 Backend Outcome。兩邊用同一個 Correlation Context 串接，欄位 Owner 仍要分開。到了 Day 20 之後，這條資料路徑會再接回既有 LGTM 架構。

## SSE 是最容易看出邊界混亂的流量

一般 JSON Response 很快一次回完，兩層的 Buffer、Read Timeout 與 Retry 即使重疊，也不一定立刻出事。SSE Connection 會活得更久，模型或 Tool 執行期間又可能有空檔。外層 Idle Timeout、Response Compression、Body Transform 或 Event Flush 只要有一項不合，使用者就會先看到停頓或斷線。

agentgateway 的 [Streaming 文件](https://agentgateway.dev/docs/kubernetes/latest/documentation/llm/streaming/) 說明 OpenAI、Azure 與 Anthropic 會使用 SSE，Gateway 在 Chunk 抵達時向 Client 轉送。若 Route 額外啟用 [Body Buffering](https://agentgateway.dev/docs/standalone/latest/configuration/traffic-management/buffer/)，Response 才會先累積再送出。因此「支援 Streaming」不能只看功能表，必須實測第一段 Event 是否在 Upstream 完成前抵達。

Streaming Policy 也有自己的限制。Response Guard 沒有啟用時，SSE 順利穿透只代表 Transport 沒被 Buffer，不能推論敏感內容政策也已覆蓋 Stream。已經送到 Client 的 Chunk 更不可能事後收回。Transport、Content Policy 與 Timeout Budget 是三份不同的驗收。

Timeout 則要當成完整 Budget。Edge 的 Connection／Idle Timeout 必須容得下 agentgateway Route、Backend Timeout 與合法 Event Gap，Telemetry 也要看得出哪一層先截止。兩層都填相同數字，只會讓 Race Condition 決定 Client 最後收到哪個 Status Code。

## 公開 Lab 只驗 Agent Gateway 的 Traffic Contract

Production 有兩層 Gateway，公開 [Lab 03](https://github.com/MikeHsu0618/2026-ithelp-agent-governance-public/blob/day-19-r2/labs/03-gateway-runtime/README.md) 刻意只啟動一個 Pinned agentgateway 與一個 Synthetic OpenAI-compatible Provider：

```text
Lab client → one agentgateway → synthetic provider
```

少一層 Proxy 是為了隔離變因。讀者不用先處理第二組 Certificate、Route 與 Timeout，仍能驗證 Caller Authentication、Backend Credential、SSE、Error Propagation 與 Retry Count。雙層 Topology 由前面的實務經驗與責任矩陣支撐，單層 Lab 不冒充整套 Production 驗收。

Synthetic Provider 對一般 Request 回 `200 application/json`。SSE Case 會先送出第一段 Event，等 Client 確認收到後才完成剩餘內容。若 Gateway 把 Response Buffer 完才送，這個 Case 就會 Timeout。另一個固定 Model 則回傳 `429` 與 `Retry-After: 7`，用來確認錯誤語意沒有在中途被改寫或重送。

![Day 15 實際 Lab terminal card。單一 agentgateway 1.5.0 且 retry disabled，一般 JSON 與 SSE 得到 200，缺少或錯誤 caller credential 得到 401，上游 rate limit 保留 429，backend credential isolation 通過，六組結果皆符合預期。](https://raw.githubusercontent.com/MikeHsu0618/2026-ithelp-agent-governance-public/day-19-r2/assets/screenshots/day-15/01-traffic-boundary-results.png)

六組 Case 最後收斂成四份 Contract：

| Contract | Lab 結果 |
| --- | --- |
| Caller Authentication | Missing／Invalid Credential 都在 Backend 前回 `401` |
| Streaming | 第一段 SSE Event 在 Upstream 完成前抵達，Event 順序保留 |
| Error Propagation | `429` 與 `Retry-After: 7` 原樣回傳，Upstream 只收到一次 Request |
| Credential Isolation | Provider 收到 Gateway Credential，Caller Key 沒有穿透 |

從 Repo Root 可以重跑：

```bash
make lab-03-runtime-up
make lab-03-runtime-traffic
```

完整六組結果、Redacted Config 與原始 Terminal 收在 [Day 15 Screenshot Evidence](https://github.com/MikeHsu0618/2026-ithelp-agent-governance-public/blob/day-19-r2/assets/screenshots/day-15/evidence.md)。Lab 沒有測 Kong 設定、HA、吞吐、長時間 Heartbeat、MCP Session Persistence 或 A2A Streaming，因此不能拿來宣稱 Production Topology 已完成驗收。

## Route Review 應該留下可執行的 Contract

責任矩陣若只出現在文章裡，很快又會漂移。最容易重疊的項目應直接進 Route Review 或 Runbook：

```text
AUTHENTICATION
  edge: preserve caller credential
  agentgateway: validate caller and inject backend credential

RETRY
  edge: no application retry on AI route
  agentgateway: require idempotency review before enable

TIMEOUT
  edge: outer connection / idle budget
  agentgateway: route / backend budget
  rule: outer budget must cover inner budget and legal stream gaps

ERROR
  preserve 401 / 429 / 5xx and Retry-After
  agentgateway unavailable => 502 / 503, no backend bypass
```

Rate Limit 也要寫清楚維度。Edge 可以擋 IP Abuse 或 Connection Flood，agentgateway 則按 Principal、Client、Model、Tool 或 Provider Quota 計算。兩層都設定「每分鐘 100 次」卻沒有共同 Actor Contract，值班時只會看到兩個來源不同的 `429`。

Header 則需要 Reserved List，標示哪些值由 Edge 產生、哪些只能由 agentgateway 寫，以及 Backend 可以信任哪些來源。Caller 若能自行送入 `x-audit-human` 或 `x-policy-result`，Gateway 又沒有先移除再重建，再完整的 Audit Event 都只是可偽造的文字。

## Traffic 治理完成後，下一個缺口在 Agent Runtime

這次切分讓企業保留既有對外入口，AI Traffic 也多了一個清楚的 Policy Checkpoint。Request 出問題時，同一份 Correlation Context 能一路查到 Edge 是否收到、agentgateway 為何拒絕，以及 Backend 最後有沒有被呼叫，不必再猜哪一層先改過 Credential、Header 或 Response。

agentgateway 的責任也到此為止。它可以管理 LLM、MCP 與 A2A Traffic，卻不會替團隊實作 Thinking、Memory、Workflow 或 HITL，也不接手 Agent 的 Build、Deployment、Discovery 與日常操作。

Day 16 會把 kagent、agentgateway 與自建 Runtime 拆成 Runtime、Control Plane、Traffic Path 三層。接下來要確認的不是另一個 Gateway 功能，而是平台替 Agent Team 接住了哪些工作，又把哪些責任留在 Runtime 裡。
