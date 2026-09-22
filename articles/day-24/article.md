# Day 24｜agentgateway LLM 成本觀測實戰：Dashboard 上的數字能信到哪裡？

agentgateway `1.5.0` 的 LLM Analytics 跑起來後，不用先畫 Grafana，就能看到 calls、token usage 與估算成本，還可以按 model、provider、user 或 group 拆開。我原本以為 Day 24 最麻煩的會是 Dashboard，實際跑過才發現，畫面早就有了，花時間的是判斷上面的數字可以拿來做什麼。

下面這張官方畫面來自其中一組 Lab 流量。它列出 `2 calls`，OpenAI 與 Anthropic 各收到一筆 request，總成本是 `USD 0.000066`。光看 Dashboard 很容易理解成「兩次呼叫總共花了這些錢」，但這兩個 calls 其實是同一個 Agent action 的兩次嘗試，而且只有成功的那次帶回 usage。

![agentgateway 1.5.0 內建 Analytics 實跑畫面。相同 Fallback action 產生 OpenAI 與 Anthropic 各一筆 request，畫面顯示 2 calls，但只有成功 response 提供的 10 tokens 與 USD 0.000066。](https://raw.githubusercontent.com/MikeHsu0618/2026-ithelp-agent-governance-public/day-30/assets/screenshots/day-24/agentgateway-official-analytics-dashboard.png)

Day 23 已經決定哪些 identity 欄位適合放進 Metrics。Day 24 接著把 model、provider、token usage 與費率接進來，實際盤點 agentgateway 內建 Analytics、官方 Grafana Dashboard 和 Provider 帳單之間的界線。主模型故障後切換備援只是其中一個壓力測試，因為它最容易讓一個看似完整的總額露出缺口。

## agentgateway 內建的成本畫面

agentgateway `1.5.0` 的 [LLM Analytics](https://agentgateway.dev/docs/standalone/latest/documentation/llm/cost-controls/dashboard/)不需要 Grafana 或 Prometheus。Gateway 把每一筆 LLM request 寫進本機資料庫，再用 model catalog 對 token usage 計價，UI 就能按 model、provider、user、group 或 user agent 分組查看 cost、tokens 與 calls。

要讓內建畫面出現資料，Day 24 在原本的 model catalog 之外，補上 admin UI 與 request-log database，並把管理介面綁在本機 port：

```yaml
config:
  adminAddr: 0.0.0.0:15000
  database:
    url: sqlite:///tmp/day24-client-retry.db?mode=rwc
  modelCatalog:
  - file: /etc/agentgateway/costs.json
```

SQLite 放在容器的 `/tmp`，每次重建 Lab 都會清掉，適合教學與截圖。正式環境若需要保留歷史資料，就要改用持久卷或 PostgreSQL，還得考慮多副本資料如何彙整。不能因為 UI 已經出現曲線，就把單一 Pod 的暫存資料庫當成企業成本平台。

除了這個內建 Analytics，agentgateway 也維護一份[官方 Grafana Dashboard](https://agentgateway.dev/docs/standalone/main/integrations/observability/grafana/)，涵蓋 requests、LLM token／cost／latency、MCP、route、xDS 與 runtime health。Kubernetes Helm 開啟 `monitoring.enabled` 後，還會建立 ServiceMonitor、PodMonitor 與 Dashboard ConfigMap。Repo 已收錄與 Lab 同版的官方 JSON，日常維運不必從空白重畫。

公開 Lab 是 standalone Compose，沒有官方 Grafana 面板預期的 Kubernetes namespace、Gateway name、Pod 與 container metrics，所以我沒有為了讓所有 panel 亮起來而改寫上游 JSON。本文的 Grafana extension 只處理官方畫面回答不了的 action／attempt 關係與成本缺口。

## Dashboard 上的成本從哪裡來

內建 Analytics 不是直接去 Provider 帳務系統抄一個金額。Gateway 先保存 LLM request，從 response 取得 input／output token usage，再依 model catalog 的費率算出 cost，最後才由 UI 聚合。這條資料路徑很適合即時觀察 Team 用量、模型分布和成本趨勢，但每一層都有自己的證據限制。

只要 response 帶回 usage，計算很直接。例如正常通過 primary 的請求回傳 11 個 input tokens 與 5 個 output tokens，套用 Lab 裡版本化的費率後，Gateway estimate 是 `USD 0.00006375`。這個數字能用來做即時告警與內部趨勢，還不能直接取代月底收到的 Provider invoice。

我在自己的 Grafana Claude Code Stats App 裡也遇過相同情況。Claude Code telemetry 有 token counter，不代表供應商已經提供 billed cost，所以介面使用 **Estimated API-equivalent Cost**，價格表也放進 source control。沒有對應費率的 model 會進入 Unpriced Model Tokens，不會偷偷借用相近型號的價格。做過兩套畫面後，我最在意的反而是命名：只要把 estimate 寫成 cost total，讀者很容易把它當成帳單。

## 用失敗備援測觀測邊界

正常的成功請求很難看出資料缺口，所以 Lab 另外讓主模型故意回 `503`，再由 client 重送同一個 Agent action，讓備援模型接手。這組流量採用 LLM Fallback：主模型失敗後，後續 request 改走另一個可用模型。內建 Analytics 數得到兩次呼叫，卻只有備援模型的成功 response 能提供 token usage 與成本。

### 同一個 action，兩張 Provider 收據

Lab 的 principal 固定為 `user/sre-oncaller`，API key metadata 將它映射到 `team=platform`。Client 要求的是 virtual model `day24-resilient-agent`，背後有兩個 target：primary 使用 OpenAI 相容格式，backup 使用 Anthropic 格式。兩個 Provider 都是本機 deterministic fixture，不需要外部 API key，也不會把測試流量送出電腦。

圖中的兩個 agentgateway 方塊不是雙層 Proxy。為了隔離 health eviction state，Lab 啟動兩組互不串接的實驗：一組只看沒有 retry 的結果，另一組讓 client 對相同 `action_id` 發出第二次 request。每一筆實際 data path 都只有 Client → Gateway → Provider。

![同一個 Agent action 經過兩次 HTTP request。第一次由 primary provider 回傳 503，第二次 client retry 才由 backup provider 成功服務，失敗 attempt 的 usage 與 cost 保持 UNKNOWN。](https://raw.githubusercontent.com/MikeHsu0618/2026-ithelp-agent-governance-public/day-30/assets/diagrams/day-24/fallback-cost-evidence.png)

這次我把帳拆成兩層，避免一開始就寫下一個看似完整的 action total：

| 層級 | 穩定識別 | 能回答的問題 |
|---|---|---|
| logical action | `action_id` | 使用者原本想完成哪個工作，最後是否成功 |
| provider attempt | `trace_id`、時間、provider | 這次網路請求送到哪裡，得到什麼狀態，是否有 usage 證據 |

一個 action 可以有多個 attempts，因此 Action success rate 與 Provider request success rate 是兩個不同數字。成本也得先保存每次 attempt 的證據，才能按 action、team 或 route 聚合。若資料庫只剩最後一次成功 response，月底看到異常帳單時，很難再查清楚前面到底重試了幾家 Provider。

### Virtual Model 的 Eviction 行為

agentgateway 的 [Virtual Models 文件](https://agentgateway.dev/docs/standalone/latest/documentation/llm/virtual-models/)會依 priority 選擇 failover target，並以 health eviction 暫時排除故障 model。本篇設定的核心如下：

```yaml
llm:
  models:
  - name: day24-primary
    visibility: internal
    provider: openAI
    params:
      baseUrl: http://primary-provider:8080/v1
      model: day24-primary
    health:
      eviction:
        consecutiveFailures: 1
        duration: 60s
  - name: day24-backup
    visibility: internal
    provider: anthropic
    params:
      baseUrl: http://backup-provider:8080
      model: day24-backup
    health:
      eviction:
        consecutiveFailures: 1
        duration: 60s
  virtualModels:
  - name: day24-resilient-agent
    routing:
      failover:
        targets:
        - model: day24-primary
          priority: 0
        - model: day24-backup
          priority: 1
```

我一開始把它理解成「primary 失敗後，同一個 request 會自動改送 backup」。Live run 的結果不是這樣。Primary 回 `503` 後，Gateway 將它 eviction，當下這筆 request 仍然結束，下一筆 request 才會避開 primary，改由 backup 服務。

agentgateway 另外有 [route-level Retry policy](https://agentgateway.dev/docs/standalone/latest/documentation/configuration/resiliency/retries/)，但把 `retry` 直接塞進這次使用的 simplified LLM `llm.policies`，`1.5.0` validator 會拒絕設定：

```text
Error: llm.policies: unknown field retry
```

這個結果只適用於本文的配置方式，不代表 agentgateway 的所有模式都無法 retry。公開 Lab 沒有再加一層 Proxy 來湊出「單次 request 完成 Fallback」，而是由 client 明確重試，兩次 request 共用同一個 `action_id`。若 production 打算讓 Gateway 接手 retry，就要用該版本支援的 route 或 advanced configuration，重新驗證 timeout budget、streaming response 與 idempotency。

### 三種流量的實測結果

Traffic runner 會送出一筆正常流量、一筆沒有重試的故障，以及一筆由 client 重試成功的 Fallback：

| Scenario | HTTP attempts | Provider 順序 | 最終狀態 | usage 證據 |
|---|---:|---|---|---|
| `primary-success` | 1 | primary | `200` | input 11／output 5 |
| `failover-without-retry` | 1 | primary | `503` | `UNKNOWN` |
| `failover-with-retry` | 2 | primary → backup | `503` → `200` | attempt 1 `UNKNOWN`，attempt 2 input 7／output 3 |

內建 Analytics 截圖只查看 `client-retry` Gateway，所以畫面是兩個 calls 與一筆 backup cost。下面這張 Grafana extension 則聚合兩組實驗，除了 primary calibration 與 backup 的原生成本指標，也能用同一個 `correlation_action_id` 在 Loki 找到 primary `503` 和 backup `200`。Tempo 裡同樣保留兩個 trace IDs。

![Day 24 Grafana focused extension 實拍。上半部使用 agentgateway 原生成本與 token metrics，下半部以相同 action_id 查到 primary 503 與 backup 200。](https://raw.githubusercontent.com/MikeHsu0618/2026-ithelp-agent-governance-public/day-30/assets/screenshots/day-24/agentgateway-cost-fallback-dashboard.png)

## Gateway estimate 與 Provider 帳單

正常請求與故障切換都跑過後，Dashboard 上已經有足夠資料觀察模型用量，卻仍然不能把所有數字混成一筆帳。Gateway estimate、缺少 usage 的 request，以及 Provider 最後結算的金額，需要分開保存與命名。

### USD 0.00012975 少了什麼

Grafana extension 顯示的數字來自兩筆成功 responses：一筆是獨立的 primary calibration，另一筆是 Fallback action 最後的 backup attempt。

```text
primary success calibration
= 11 input × USD 1.25 / 1M
+  5 output × USD 10.00 / 1M
= USD 0.00006375

backup success
= 7 input × USD 3.00 / 1M
+ 3 output × USD 15.00 / 1M
= USD 0.00006600

successful-response estimate
= USD 0.00012975
```

`USD 0.00012975` 不是 Fallback action 的價格，因為其中包含另一筆 calibration request。對 `failover-with-retry` 而言，目前能證明的 known subtotal 只有 backup 的 `USD 0.00006600`。Primary 失敗 attempt 沒回 usage，complete total 仍是 `UNKNOWN`。

### Gateway 的零值不等於 Provider 免費

Primary 回 `503` 時，agentgateway access log 裡的 `agw_ai_usage_cost_total` 是 `0`，Prometheus 也會看到零值 cost series。這個零代表 Gateway 沒拿到能套用 catalog 的 usage，不能反推 Provider 一定沒有計費。失敗可能發生在 Provider 已經處理部分輸入之後，也可能套用另一套結算規則。

Verifier 因此把三種成本證據分開：

| 證據層 | 本篇能證明什麼 | 還缺什麼 |
|---|---|---|
| provider response usage | 成功 response 回傳的 token 數 | 失敗 request 可能沒有 payload |
| Gateway model catalog | 依 served provider／model 與版本化費率計算 | 不含合約價、credit 與 Provider 的特殊計費規則 |
| provider billing export／invoice | 最終結算與帳務調整 | 通常較晚取得，還要對回 account、route 或 attribution tag |

agentgateway 的 [Model Cost 文件](https://agentgateway.dev/docs/standalone/latest/documentation/llm/cost-controls/costs/)也提醒，catalog 計算可能因價格更新、自訂費率、失敗 request 或 Provider 規則而與帳單不同。如果要做到 invoice-grade attribution，Gateway 的 action／attempt evidence 還得與 Provider billing export 對帳。官方提供的 [Invoice-grade attribution](https://agentgateway.dev/docs/standalone/latest/documentation/llm/cost-controls/attribution/)也依賴 Provider 是否接受 attribution value 並把它放進自己的 billing data，不能把每一家供應商都視為同一種整合。

## requested model 與 served model

Client 送出的 `model` 一直是 `day24-resilient-agent`，它代表產品或 Agent Runtime 選擇的 virtual model。Primary 成功時，response model 是 `day24-primary`，Fallback 成功後則是 `day24-backup`。

Metrics 若只保留 requested model，所有流量看起來都屬於同一個 route，無法分辨 backup 用量。只留下 response model 也不夠，因為原始 routing intent 會消失。OpenTelemetry GenAI semantic conventions 已提供 `gen_ai.request.model`、`gen_ai.response.model`、`gen_ai.provider.name` 與 token usage 等欄位，本文的 `team`、`experiment` 與 `correlation.action_id` 則是平台自己的 attribution schema。

日常聚合維度可以保留 `team`、route、provider、served model、token type 與 outcome。`action_id`、`trace_id`、principal 和 provider request ID 繼續放在 Logs、Traces 或 Audit，避免每一筆 request 都替 Prometheus 建立新 series。Day 23 已經量過高基數 identity label 的代價，不能因為成本查詢方便就把它們搬回 Metrics。

## 上線前的成本責任

官方 Analytics 解決了大部分「我現在花多少」的可視化工作，平台團隊不必再維護另一套外觀相似的 Dashboard。剩下要自行設計的是資料與責任：

- Price catalog 要有版本與生效時間。合約價、區域價、cache、batch、long-context 與 reasoning token 都可能改變計算結果。
- Retry owner、最大次數、timeout budget 與 idempotency 必須寫清楚。會產生副作用的 Tool 或 streaming response，重試可能造成重複動作與重複計費。
- `UNKNOWN` 要出現在報表裡，連同缺少 usage 的 request 比例與 unpriced model coverage 一起監控。把未知項目排除在總額之外，不能同時把它們從畫面上藏起來。
- 月底 chargeback 要對回 Provider billing export。Gateway catalog cost 適合即時告警與 Team 趨勢，不等於財務最後付款的數字。
- `team` 必須來自驗證過的 Identity 或受控 API key metadata，不能相信 caller 隨手傳來的 header。

完整 Lab 可以從 Repo root 執行：

```bash
make lab-04-cost-check
make lab-04-cost-up
make lab-04-cost-run
make lab-04-cost-down
```

啟動後可在 `http://127.0.0.1:28095/ui/llm/analytics` 查看 agentgateway 內建 Analytics。`lab-04-cost-run` 會查 Prometheus、Loki、Tempo 與兩個 Provider receipt endpoints。只有 1／1／2 attempts、primary → backup 順序、四條 Gateway traces、原生 token／cost metrics 與 action logs 全部吻合，backend report 才會得到 `overall: PASS`。設定檔、可複製的查詢與 machine-readable evidence 都放在 [Lab 04 README](https://github.com/MikeHsu0618/2026-ithelp-agent-governance-public/blob/day-30/labs/04-telemetry-pipeline/README.md)。

## 下一個綠燈：HTTP 200

Day 24 跑完後，我反而不想再追求一個更漂亮的 Total。成功 response 的 catalog cost 可以即時使用，失敗 attempt 沒有 usage 就保留 `UNKNOWN`，Provider invoice 則交給後續對帳。三種數字分開，Dashboard 才不會替它沒有的證據做保證。

前幾篇都是讓 LGTM 觀測 Agent 與 Gateway，下一篇會把方向轉過來：讓 Day 1 的 Google ADK SRE Agent 經 agentgateway 與 Grafana MCP，真的去查既有 Loki，而不是繼續使用 synthetic `query_logs`。接上產品鏈後仍會遇到 HTTP 200 裝著 HTML、合法空結果與 correlation fields 遺失等問題，但它們會放回「Agent 如何可靠使用觀測資料」這條主線裡處理。
