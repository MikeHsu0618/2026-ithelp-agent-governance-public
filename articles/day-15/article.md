# Day 15｜既有 Ingress 不用拆：Agent Gateway 上線後的責任切分

把 agentgateway 接進 Kubernetes 之後，我們沒有拆掉原本的 Ingress。public host、certificate 與其他服務都還在既有入口上，為了多一條 AI route 就重做整個對外邊界，變更範圍實在太大。

真正的麻煩，是兩層開始做同一件事。它們都可以驗 Token、改 header、做 rate limit、設定 timeout，甚至重送失敗的 request。串接當天很快就通了，後續 review 卻不斷卡在功能重疊：同一項行為有兩份設定，事故發生時自然也會出現兩套說法。

後來我們把每項行為逐一指定 owner，review 才不再原地打轉。既有 Ingress 只留下 TLS、public host、基本 routing 與 access log，caller authentication、AI-aware policy、backend credential 和 audit context 則交給 agentgateway。公開 Lab 也只保留 agentgateway，專心驗證它接手後應該交付的 traffic contract。雙層架構的取捨與驗收方式，則由實務 topology 和責任矩陣交代。

## 既有入口縮到 pass-through

當時的既有元件是 Kong。簡單說，[Kong Ingress Controller](https://developer.konghq.com/kubernetes-ingress-controller/)會把 Kubernetes `Ingress`、`HTTPRoute` 等資源轉成 Kong Gateway 設定，真正接收 request、執行 plugin 並轉送 upstream traffic 的是 Kong Gateway。[官方 proxying 文件](https://developer.konghq.com/gateway/traffic-control/proxying/)也列出 routing、plugin、load balancing 與 response streaming 等行為。

Kong 本來就做得到許多流量控制，問題出在同一條 AI route 同時有兩個 owner。我們留下它，是因為 public endpoint、certificate、host routing、其他非 AI service 與既有 access log 都已經由這個入口承接。agentgateway 加進來後，前一層縮到只做下面幾件事：

- 終止 TLS，接住 public host。
- 依 host 或粗粒度 path，把 AI traffic 送進 agentgateway。
- 保留連線層資訊與既有 access log。
- agentgateway 無法服務時回 `502` 或 `503`，不開一條直達 backend 的旁路。

Caller JWT、consumer key、MCP／A2A／LLM-aware policy、backend credential 與 AI audit 都往 agentgateway 收斂。會讀寫 body 的 filter、AI route 上的應用層 retry，以及可能改變 SSE 行為的 response processing，也從前一層拿掉。本文所說的 pass-through 並非「Kong 什麼都不做」，它仍然是企業入口，只是不再解析 AI route 的 caller identity，也不替後面的治理層做第二次決策。判斷這條邊界時，不能只數一層 proxy 開了多少功能，還要看它是否讀寫了另一層負責的 identity、credential 或 body。

## 兩層設定如何把事故變複雜

假設 edge 與 agentgateway 都驗同一枚 JWT。兩邊的 JWKS cache 更新時間不同，或其中一邊少驗一個 audience，就可能出現外層放行、內層回 `401`。Client 只看到 authentication failure，值班的人卻得同時排查 IdP、兩份 policy 與 route，還要猜哪一層先拒絕。

Header mutation 也很容易把 Day 14 才拆開的 credential boundary 弄亂。Edge 若先替換 `Authorization`，agentgateway 便看不到 caller credential。兩邊各產生一個 request ID 時，trace 和 audit 也無法自然接起來。更麻煩的是 body filter 或 response buffering，普通 JSON request 可能完全正常，到了 SSE 才表現得像模型卡住。

Retry 的風險要分成架構模型和產品預設來看。如果兩層都設定「失敗後再試一次」，一次呼叫在最壞情況下可能被放大成四次。後面若接的是付款、刪除或變更設定的 Tool，代價就不只是多花一點 Token。這裡的四次呼叫是雙層應用層 retry 的風險模型，不是 Kong 收到每個 `5xx` 或 `429` 時的預設行為。Kong 官方文件說明，預設 retry 處理的是 transport-level failure，upstream 已回應 `5xx`／`429` 或 response body 已開始 streaming 時不會重送。非 idempotent request 也只有在 upstream 尚未收到 request 的特定連線失敗下才會 retry。

幾次 review 都繞回相同問題後，我們把討論順序反過來：先替每項功能指定 owner，再決定要開哪一個產品選項。兩層確實都要保留控制時，就把維度拆開，例如外層限制 IP abuse、內層計算 principal quota，避免複製同一份規則。

| 能力 | Edge／既有 Ingress | Agent Gateway |
| --- | --- | --- |
| Authentication | 限制網路來源並原樣轉送 caller `Authorization`，不重複驗同一枚 JWT | 驗 issuer、audience、principal、consumer 與 resource policy |
| Rate limit | IP、connection、通用 abuse protection | principal、client、model、Tool、provider quota |
| Routing | public host、粗粒度 path | LLM／MCP／A2A-aware routing |
| Header | forwarding 與 trace contract | audit context、backend credential、移除不可信 internal header |
| Retry | AI route 不設定應用層 retry | 只有具 idempotency contract 的 operation 才考慮開啟 |
| Telemetry | TLS、connection、host、request ID | identity、policy、model／Tool decision、backend outcome |

這張表要逼每個行為留下唯一 owner，不代表所有環境都要照著同一套拓撲部署。完整版本收在 [Edge／Ingress 與 Agent Gateway 責任矩陣](https://github.com/MikeHsu0618/2026-ithelp-agent-governance-public/blob/day-15/articles/day-15/proxy-responsibility-matrix.md)，裡面還有 timeout、SSE、error propagation 與 fail-closed，設計審查時可以直接逐列填入 owner 與驗收方法。

## 雙層 traffic path 的責任邊界

下面這張圖來自去識別化的實務 topology。它拿掉內部 host、namespace、帳號與 deployment 細節，只保留 request 必須穿過的邊界，以及每一層可以改動哪些資料。

![Client 經既有 Ingress 進入 agentgateway，再呼叫只開放內部路徑的 LLM、MCP 或 Agent backend。既有入口負責 TLS、public host、基本 routing 與 access log，原樣轉送 caller authorization、trace context 與 SSE。Agentgateway 負責 caller authentication、AI-aware policy、backend credential 與 AI telemetry。兩層資料以同一 correlation context 進入 LGTM，agentgateway 不可用時回 502 或 503，不能繞過 Gateway 直連 backend。](https://raw.githubusercontent.com/MikeHsu0618/2026-ithelp-agent-governance-public/day-15/assets/diagrams/day-15/ingress-boundary.png)

Backend 在網路與 routing 上都不接受 edge 直接打進來。Agentgateway 掛掉時，request 必須明確失敗。如果 edge 還藏著一條 fallback route 可以直連 MCP Server 或 LLM provider，最需要治理的時候反而會繞過治理點。

從 edge 傳進 agentgateway 的 `Authorization`、trace context 與 streaming response，也都有明確約定。前一層可以加入 forwarding header，卻不能先把 caller credential 換成 backend credential。Day 14 已經驗過這是兩個不同的 credential slot，雙層 proxy 不該又把它們摺回同一個 header。

兩層產生的 telemetry 最後都進既有 LGTM，但保存的問題不同。Edge log 用來回答 TLS、host、connection 與入口 request ID。Agentgateway 的 telemetry 才回答 principal、policy、model／Tool 與 backend outcome。兩邊用同一個 correlation context 串接，欄位 owner 仍然分開。Day 20 之後，我會再把這條路接回長期使用的 observability 架構。

## SSE 把隱藏的重疊設定逼出來

一般 JSON response 幾百毫秒後一次回完，兩層的 buffer、read timeout 與 retry 即使有重疊，也不一定立刻出事。SSE connection 會活得更久，模型或 Tool 執行期間又可能有明顯空檔，外層 idle timeout、response compression、body transform 與 event flush 只要有一項不合，使用者就會先看到停頓或斷線。

Agentgateway 的 [Streaming 文件](https://agentgateway.dev/docs/kubernetes/latest/documentation/llm/streaming/)說明 OpenAI、Azure 與 Anthropic 使用 SSE，Gateway 會在 chunk 抵達時往 client 轉送。若 route 另外設定 [body buffering](https://agentgateway.dev/docs/standalone/latest/configuration/traffic-management/buffer/)，response 才會先累積再送出。因此「支援 streaming」不能只看功能表，還要實測第一段 event 是否在 upstream 完成前抵達。

政策也有自己的 streaming contract。Agentgateway 的 [Guardrails 文件](https://agentgateway.dev/docs/kubernetes/latest/llm/guardrails/overview/)指出，streamed response 預設不會執行 response guard，必須另外將 `promptGuard.streaming` 設為 `Enabled`。即使啟用，已送往 client 的內容也無法再被 `Mask` 改寫，只能用 reject 類型的行為中止 stream。SSE 能順利穿透，只能證明 transport 沒被 buffer。敏感內容政策是否真的覆蓋 streaming output，必須另外測試，不能從這次的 `200 text/event-stream` 推論。

Timeout 則要當成一份完整 budget 來看。[Agentgateway Timeouts](https://agentgateway.dev/docs/standalone/latest/documentation/configuration/resiliency/timeouts/)把 route 的 `requestTimeout`、`backendRequestTimeout` 與 backend timeout 分開，前面的 edge 還有 connection、read 或 idle timeout。Outer budget 要容得下 inner budget 與合法的 event gap，telemetry 也要看得出是哪一層先截止。兩邊都填成同一個數字，只會讓 race condition 決定 client 最後收到哪個 status code。

## 公開 Lab 只驗單層 traffic contract

公開 Lab 沒有複製完整的 production topology。Production 的既有入口負責 TLS、public host 與通用 routing。[Lab 03](https://github.com/MikeHsu0618/2026-ithelp-agent-governance-public/blob/day-15/labs/03-gateway-runtime/README.md)省略這一層，只啟動一個 pinned agentgateway 與一個 synthetic OpenAI-compatible provider：

```text
Lab client → one agentgateway → synthetic provider
```

少放一層 proxy 是刻意的，因為這裡要驗的是責任切完以後，agentgateway 應該交付哪些 output。讀者不必先處理第二組 certificate、route 與 timeout，仍能重現最關鍵的流量契約。雙層 production topology 由前面的實務紀錄支撐，下面六個 HTTP 結果則全部來自可重跑的 standalone Lab，兩種證據不混在一起。

```bash
make lab-03-runtime-up
make lab-03-runtime-traffic
```

每次執行時，Runner 都會產生新的 caller key、provider key 與 RSA signing material，再啟動 pinned agentgateway `1.5.0` container。Runtime config 只放在 temporary directory，公開 artifact 保存 redacted config、JSON report、decision table 與 terminal output。Command 結束前還會掃過 evidence，確認 bearer key、private JWK 欄位與 PEM private-key marker 都沒有落盤。

Synthetic provider 對一般 request 回 `200 application/json`。當 payload 帶有 `"stream": true` 時，它先送出第一段 SSE event，等 client 確認收到後才完成剩餘內容。若 agentgateway 把整個 response buffer 完才送，這個 case 會 timeout。另一個固定模型名稱會回傳：

```http
HTTP/1.1 429 Too Many Requests
Retry-After: 7
Content-Type: application/json
```

Lab route 沒有啟用 retry。[Agentgateway Retries](https://agentgateway.dev/docs/standalone/latest/documentation/configuration/resiliency/retries/)把 `attempts: 1` 定義成只有初始 attempt，開啟 retry 時還可能 buffer 帶 body 的 request。這裡先驗「一次送達、錯誤語意不變」，等 operation 有清楚的 idempotency contract 後，再決定哪些錯誤值得重送。

## 六組流量結果：正常回應與錯誤都不能走樣

發稿前又把完整 Lab 跑了一次，27 tests 全數通過，branch coverage 維持在 85% 以上，Ruff lint／format 與公開設定檔驗證也都通過。下圖保存的是六組 traffic case 的實際輸出，最後得到 `6/6 matched`。

![Day 15 實際 Lab terminal card。單一 agentgateway 1.5.0 且 retry disabled，一般 JSON 與 SSE 得到 200，缺少或錯誤 caller credential 得到 401，上游 rate limit 保留 429，backend credential isolation 通過，六組結果皆符合預期。](https://raw.githubusercontent.com/MikeHsu0618/2026-ithelp-agent-governance-public/day-15/assets/screenshots/day-15/01-traffic-boundary-results.png)

圖片由同一次 live run 的 terminal output 重新排版。可複製指令、原始 terminal、JSON report、redacted config 與 hash 都放在 [Day 15 Screenshot Evidence](https://github.com/MikeHsu0618/2026-ithelp-agent-governance-public/blob/day-15/assets/screenshots/day-15/evidence.md)，不需要從圖片抄字。

| Case | 實際結果 | 這次能確認的邊界 |
| --- | --- | --- |
| Normal JSON | `200 application/json` | 一般 response 未被改寫 |
| SSE stream | `200 text/event-stream`，第一段 event 在 upstream 完成前抵達，`lab-`、`ok`、`[DONE]` 順序保留 | 這條單層路徑沒有等完整 response 才一次送出 |
| Missing caller credential | `401`、upstream request count `0` | strict caller auth 在 backend 前拒絕 request |
| Invalid caller credential | `401`、upstream request count `0` | 無效 key 沒有抵達 backend |
| Upstream rate limit | `429`、`Retry-After: 7`、upstream request count `1` | 錯誤與 retry hint 保留，request 沒有重送 |
| Backend credential isolation | `200`、provider `MATCHED`、caller forwarded `false` | backend 收到 Gateway credential，沒有收到 caller key |

`6/6 matched` 只涵蓋表中的六個觀察。這個 Lab 沒有測 Kong 設定、HA、吞吐、長時間 heartbeat、MCP session persistence 或 A2A streaming，因此不能拿來宣稱 production topology 已經通過完整驗收。MCP session 與 Tool policy 是另一條實務路徑，後面的 Kubernetes Lab 會改用合成 endpoint 公開重跑。在那之前，private result 不會被補寫成 public PASS。

## 把責任矩陣寫進 route review

責任矩陣要能落地，最容易漂移的項目就得直接進 route review 或 runbook。這份 contract 不綁定某一套產品，記的是雙層 traffic path 必須共同遵守的行為：

```text
AUTHORIZATION
  edge: preserve caller credential
  agentgateway: validate caller; inject backend credential

RETRY
  edge: no application-level retry on AI route
  agentgateway: disabled by default; require idempotency review before enable

TIMEOUT
  edge: outer connection / idle budget
  agentgateway: route / backend budget
  rule: outer > inner; legal streaming gap covered

ERROR
  preserve 401 / 429 / 5xx and Retry-After
  agentgateway unavailable => 502 / 503; no backend bypass

TELEMETRY
  edge: TLS / host / connection / request ID
  agentgateway: principal / policy / model-or-tool / backend outcome
```

Rate limit 若兩層都要保留，維度也要寫進設定旁邊。Edge 可以擋 IP abuse 或 connection flood，agentgateway 則按 principal、client、model、Tool 或 provider quota 計算。兩層都設定「每分鐘 100 次」卻沒有同一個 actor contract，值班時只會看到兩個來源不同的 `429`。

Header 需要一份 reserved list，列出哪些值由 edge 產生、哪些只能由 agentgateway 寫，以及 backend 可以信任哪些來源。Caller 若能自行送入 `x-audit-human` 或 `x-policy-result`，Gateway 又沒有先移除再重建，audit event 看起來再完整也只是可偽造的文字。

故障演練則要真的拔掉 agentgateway endpoint，讓 policy dependency timeout、JWKS 更新失敗與 telemetry backend 不可用各自跑一次。Telemetry 通常可以暫存或降級，authorization 與 backend bypass 卻不能共用同一套 fallback。每個情境最後回什麼 status、留下哪一筆 event，都應該在上線前跑成固定測試。

## Gateway 管得住流量，管不了 Agent runtime

這次切分最直接的收穫，是企業仍然只有一個對外入口，AI traffic 也多了一個清楚的 policy checkpoint。當 request 出問題時，同一份 correlation context 可以一路查到 edge 是否收到、agentgateway 為何拒絕，以及 backend 最後有沒有被呼叫，不必再猜兩層誰先改過 credential、header 或 response。

不過，團隊開始交付 Agent 之後，agentgateway 的責任也就到此為止。它可以管住 LLM、MCP 與 A2A traffic，卻不會替團隊實作 thinking、memory、workflow 或 HITL，更沒有接手 Agent 的 build、deployment、discovery 與日常操作。

Traffic path 到這裡算收乾淨了，選型會議卻沒有因此結束。kagent 能把 Agent deployment、discovery 與 A2A registration 包進平台，但如果 runtime 暴露的能力不足，光是把 A2A 接通仍然撐不起複雜 workflow。自己寫一個 BYO Agent 再註冊回去，也不表示它自然繼承了所有平台便利。Day 16 會把 kagent、agentgateway 與自建 runtime 拆成 runtime、control plane、traffic path 三層，逐一確認平台接住了哪些工作，又把哪些責任留給寫 Agent 的團隊。
