# Day 23｜JWT Claim 放進 Metrics 的代價：模擬 agentgateway 高基數陷阱

Agent Telemetry 完成後，Dashboard 很快會出現一個合理需求：既然每筆 Request 都有登入者，能不能直接按 Team Member 看流量、錯誤與成本？技術上最短的路，是從 JWT 取出 `sub`，加進 Gateway Metric Labels。PromQL 馬上能 `sum by (user_id)`，介面也很好做。

我在維運 Prometheus／Mimir 與 Loki 時，遇到這類需求不會只問欄位是不是 PII。即使 `sub` 已去識別、完全看不出 Email，只要每個人或每段 Conversation 都有不同值，Time Series 和 Log Stream 仍會跟著展開。問題不在字串長什麼樣，而是 Label Value 組合會不會持續增加。

Day 22 先用 Alloy Fixture 定義資料落點。這次讓同一批已簽章 Request 通過三個平行的 agentgateway。第一組 Metrics 只加 `team`，第二組再加 `jwt.sub`，第三組連 `conversation_id` 一起加入。最後直接查 Prometheus、Tempo 與 Loki，不拿 Python 的預期資料冒充 Gateway 結果。

## 真正的 System under Test 是 agentgateway

三組 agentgateway 都以 Public JWKS 驗證 RS256 JWT 的 Issuer、Audience、Expiry 與 Signature，再由 CEL 讀取 `jwt.team`、`jwt.sub` 和 Request Header，產生原生 `agentgateway_requests_total`、Trace 與 OTLP Access Log。

正式送流量前，先試沒有 Token 和 Audience 錯誤的請求，Gateway 都回 `401`。後面從 `jwt.sub` 取出的 `user_id`，才有明確的驗證入口。否則 Dashboard 上看似完整的身分欄位，其實可能只是任意字串。

Python 只負責建立臨時 RSA Key、替合成 Principal 簽 Token、送出固定流量，以及查詢三個 Backend。Upstream 是 Deterministic No-op Service，只回 HTTP `200`。如果 agentgateway 沒有真的驗 JWT 或投影 Claim，Verifier 就拿不到需要的 Label、Span Attribute 與 Access Log Field。

下圖的 A、B、C 是三個平行實驗組，不是三層 Proxy 串在 Production Data Path。每一組收到完全相同的 90 筆 Request，唯一改變的是 Metric Label 設計。

![同一批 90 筆 request 通過三組平行 agentgateway。Metrics 依序只加入 team、加入 user_id、再加入 conversation_id，Tempo 與 Loki 保留單筆身分查詢。](https://raw.githubusercontent.com/MikeHsu0618/2026-ithelp-agent-governance-public/day-19-r2/assets/diagrams/day-23/cardinality-experiment.png)

流量矩陣固定為 30 位合成使用者、3 個 Team，每人 3 段 Conversation。每組 Gateway 處理 90 筆 Request，所以整次實驗共有 270 次成功請求，另有兩筆預期被拒絕的 Authentication Guard。所有 Principal 都使用 `user/sre-oncaller-000` 這類 Lab 名稱，不對應真實帳號。

## 三組 Gateway 只改 Metric Labels

三份設定使用相同 Route、JWT Policy、Authorization Rule、Backend、Trace 與 Access Log。差異只有 `config.metrics.fields.add`。

Bounded 組只讓 `team` 進 Metrics，這也是預計長期保留的版本：

```yaml
config:
  metrics:
    fields:
      add:
        team: jwt.team
```

Per-user 組再加入 `user_id: jwt.sub`，Per-conversation 組則增加從 `x-conversation-id` Header 讀取的 `conversation_id`。`team` 與 `sub` 都來自已驗證 JWT，Conversation ID 只是 Correlation Input，不能因為進了 Metrics 就升格成可信身分。

三組都使用 agentgateway 原生 [Metric Field Projection](https://agentgateway.dev/docs/standalone/latest/observability/metrics/overview/)，Alloy 再 Scrape `agentgateway_requests_total`。這裡沒有讓 Python 另建一個 `requests_total` 模仿 Gateway。

Runtime 會在 Ignored Directory 產生 Private Key，只有 Public JWKS 掛進 Container。JWT、Authorization Header 與 Private Key 都不進公開 Evidence。這些執行安全細節保留在 [Lab 04 README](https://github.com/MikeHsu0618/2026-ithelp-agent-governance-public/blob/day-19-r2/labs/04-telemetry-pipeline/README.md)，正文專注在 Label Design。

## Prometheus 實際得到 3、30、90 條 Series

流量跑完後，Verifier 對三個 Scrape Job 使用相同 Query，只替換 Job Name：

```promql
count(
  agentgateway_requests_total{
    route="default/cardinality-run",
    status="200"
  }
)
```

三組實際結果為 3、30、90。數字來自 Prometheus 已建立的 Label Sets，不是預先填好的理論值。

| 實驗組 | Request | 額外 Label | 實測 Series | 相對 Bounded |
| --- | ---: | --- | ---: | ---: |
| Bounded | 90 | `team` | 3 | 1x |
| Per-user | 90 | `team`、`user_id` | 30 | 10x |
| Per-conversation | 90 | `team`、`user_id`、`conversation_id` | 90 | 30x |

Grafana 上的三個 Bar Gauge 直接查原生 `agentgateway_requests_total`。下方 Access Logs 則是三組 Gateway 實際送進 Alloy 的 OTLP Log，不是拿 Report JSON 做成靜態圖。

![Day 23 Grafana 實拍。三組 agentgateway 原生 metrics 分別出現 3、30、90 條 series，下方同時顯示 Gateway OTLP access logs。](https://raw.githubusercontent.com/MikeHsu0618/2026-ithelp-agent-governance-public/day-19-r2/assets/screenshots/day-23/agentgateway-cardinality-dashboard.png)

這不是 `team × user × conversation` 的笛卡兒積。每位使用者只屬於一個 Team，加入 `team + user_id` 後是實際出現的 30 組。每段 Conversation 也只屬於一位使用者，所以第三組是 90 組，而不是 3 × 30 × 90。

真實系統還有 Route、Method、Status、Backend、Model、Provider、Region 與 Retry Outcome。這次固定其他條件，是為了量出 `user_id` 和 `conversation_id` 的邊際成本，不代表 Production 只會有 90 條 Series。[Prometheus Label 實務](https://prometheus.io/docs/practices/naming/) 同樣提醒，Label 組合會造成高基數，值集合不受控時應改用其他資料層。

## 單筆 Principal 留在 Tempo 與 Loki

Metrics 不保存 `user_id`，不等於事故調查只能看 Team Aggregate。三組 Gateway 的 Access Log 都將驗證後 Subject 與 Team 寫入 OTLP Log Field，Trace 也保留 `jwt.sub`。

流量產生器替每筆 Request 加入唯一 W3C `traceparent`，並將第一筆合法 Request 的 `trace_id` 保存到 Run Report。用該 ID 在 Tempo 查回同一條 Trace，Gateway Span 裡的 `jwt.sub` 是 `user/sre-oncaller-000`。單筆調查於是可以沿 Trace 回到 Gateway 當時處理的請求，不必把每個使用者都做成 Metric Label。

Sampling 仍是限制。目標 Request 沒留下 Trace 時，不能拿 Metric 猜出不存在的執行路徑。這時應調整 Sampling Policy，或使用保留較完整事件的資料層。

Loki 端則先以低基數 `service_name` 選 Stream，再用 Structured Metadata 過濾單一使用者：

```logql
{service_name="agentgateway"}
  | identity_user_id = "user/sre-oncaller-000"
```

Verifier 另外查 Loki Label Name 與 Series API。270 筆 Gateway Access Log 只建立一條 `service_name=agentgateway` Stream，`identity_user_id` 和 `correlation_conversation_id` 都沒有成為 Index Label。

[Loki Label Cardinality](https://grafana.com/docs/loki/latest/get-started/labels/cardinality/) 建議 Label 使用有限且可預期的值，[Structured Metadata](https://grafana.com/docs/loki/latest/get-started/labels/structured-metadata/) 則適合 User ID、Order ID 這類高基數欄位。資料依然會被保存，因此 Tenant、查詢角色、Retention、刪除流程與容量規劃都不能省略。

## Cardinality Budget 也要管理 Value Lifecycle

我不會把「禁止 `user_id`」寫成唯一規則，因為 `team` 也可能失控。Claim Mapping 若允許任意 Tenant 自訂 Team、把 Project ID 塞進 Team，或離職後的值永遠不收斂，原本看似 Bounded 的 Label 一樣持續增加。

能不能進 Metrics，至少要回答四件事：

| 檢查項目 | `team` | `user_id` | `conversation_id` |
| --- | --- | --- | --- |
| Value Owner | Identity／Platform 維護集合 | Identity Lifecycle | 應用每次建立 |
| 預期值域 | 小且可盤點 | 隨人數增加 | 隨使用量增加 |
| 主要查詢 | SLO、容量、成本歸屬 | 單人調查／分析 | 單次對話重建 |
| 建議位置 | Metric Label | Trace／Log Metadata／Audit | Trace／Log Metadata／Audit |

Production Review 還要加入 Metric Name、既有 Labels、尖峰 Active Series、Retention、Tenant Quota、Query Owner 與刪除方式。只限制 Label Keys 不夠，允許的 Values、來源與 Lifecycle 也要有人負責。

若真的需要長期做 Per-user 使用分析，我會把它當成另一種分析資料產品，明確規劃 Schema、權限與成本，而不是順手把 Operational Metric 變成使用者明細表。Dashboard 可以先用 Bounded Metrics 找到異常時間與 Route，再跳到 Trace 或用 Log Metadata 縮小範圍。

## 重跑三組 Gateway 設定

完整實驗可以從 Repo Root 重跑：

```bash
make lab-04-cardinality-check
make lab-04-cardinality-up
make lab-04-cardinality-run
make lab-04-cardinality-down
```

Runner 會對三組設定送相同流量，再查 Prometheus 實際建立的 Series。Tempo 查詢則使用這次 Request 的 Trace ID。完整 Gateway YAML、查詢與 Collector 設定都留在 [Lab 04 README](https://github.com/MikeHsu0618/2026-ithelp-agent-governance-public/blob/day-19-r2/labs/04-telemetry-pipeline/README.md)。同一批請求只因 Metric 多放了身分欄位，就讓常駐的時序資料從 3 組長到 30、90 組。

## 下一篇開始算 Fallback 的成本

這次 agentgateway 同時處理 Traffic、驗證 JWT、執行 Policy，並將選定 Claims 投影到 Metrics、Traces 與 Access Logs。Gateway 已提供加欄位的能力，Platform Team 接下來要負責 Label Allowlist、Value Owner 與 Backend Budget。

目前的取捨是讓 `team` 留在 `agentgateway_requests_total` 做聚合，`user_id` 與 `conversation_id` 留在 Trace、Loki Structured Metadata 或 Governance Event。這保住單筆調查能力，也不會讓每位使用者與每段 Conversation 變成常駐 Series。

下一個要加入的 Bounded Dimensions 是 Model、Provider、Route 與 Fallback Outcome。它們看起來比 `user_id` 安全，語意卻更麻煩。使用者要求的 Model、Gateway 實際送到的 Provider、最後服務的 Model 與計費來源可能不是同一個值。Day 24 會從 agentgateway 原生 LLM Telemetry 出發，判斷 Dashboard 上的成本數字能信到哪裡。
