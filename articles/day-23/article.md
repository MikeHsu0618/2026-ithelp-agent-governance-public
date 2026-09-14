# Day 23｜JWT Claim 放進 Metrics 的代價：agentgateway Cardinality 實測

做完 Agent telemetry 之後，Dashboard 很快就會出現一個合理需求：既然每一筆請求都有登入者，能不能直接按 team member 看流量、錯誤與成本？技術上最短的路，是從 JWT 取出 `sub`，把它加進 Gateway 的 metric labels。PromQL 馬上能 `sum by (user_id)`，介面也很好做。

我在維運 Prometheus／Mimir 與 Loki 時，遇到這類需求不會只問欄位是不是 PII。即使 `sub` 已經去識別、完全看不出 email，只要每個人或每段 conversation 都有不同值，時間序列和 log stream 仍會跟著展開。問題不在字串長什麼樣，而在同一組 label values 會不會持續產生新的組合。

Day 22 先用 Alloy fixture 把 Metrics、Traces、Logs 與 Audit 的欄位位置拆開，那篇得到的是資料落點原則，還不是 Gateway 實測。這次我讓同一批 90 筆已簽章 request 通過三個平行的 agentgateway：第一組 metrics 只加 `team`，第二組再加 `jwt.sub`，第三組連 `conversation_id` 一起放進去。最後不讀 Python 預期值，而是回頭查 Prometheus、Tempo 與 Loki 到底收到什麼。

## System under test：JWT 到 Telemetry 的原生路徑

這次的 system under test 是 agentgateway `1.5.0`。三組 Gateway 都會用 public JWKS 驗證 RS256 JWT 的 issuer、audience、expiry 與 signature，接著由 CEL 讀取 `jwt.team`、`jwt.sub` 和 request header，再產生原生 `agentgateway_requests_total`、trace 與 OTLP access log。正式送流量前，Lab 還會用無 Token 與錯誤 audience 各打一筆，兩者都必須得到 `401`，避免只靠成功請求宣稱驗證已經生效。

Python 只負責四件事：建立本機臨時 RSA key、替合成 principal 簽 Token、送出固定流量，以及查詢三個 backend。Upstream 也是 deterministic no-op service，只回 HTTP 200，不會呼叫 LLM、資料庫、shell、Kubernetes 或外部 API。換句話說，如果 agentgateway 沒有真的驗過 JWT 或沒有把 claim 投影進 telemetry，後面的 verifier 就拿不到 PASS。

下圖的 A、B、C 是三個平行實驗組，不是把三層 proxy 串在 production data path。每一組都收到完全相同的 90 筆 request，唯一刻意改變的是 metric label 設定。

![同一批 90 筆 request 通過三組平行 agentgateway。Metrics 依序只加入 team、加入 user_id、再加入 conversation_id，Tempo 與 Loki 保留單筆身分查詢。](https://raw.githubusercontent.com/MikeHsu0618/2026-ithelp-agent-governance-public/day-23/assets/diagrams/day-23/cardinality-experiment.png)

流量矩陣固定為 30 位合成使用者、3 個 team，每人 3 段 conversation。每組 Gateway 都處理 90 筆，所以整次實驗共有 270 次成功請求，另有兩筆預期被拒絕的 auth guard。principal 使用 `user/sre-oncaller-000` 這類明確的 Lab 名稱，不對應任何真實帳號。

## 三組 Gateway 只差 Metric labels

三份設定都使用相同的 route、JWT policy、authorization rule、backend 與 access log 欄位。以下是共同的驗證邊界：

```yaml
routes:
- name: cardinality-run
  gateways: [lab]
  matches:
  - path:
      exact: /cardinality/run
  policies:
    jwtAuth:
      mode: strict
      issuer: https://identity.invalid/day23
      audiences: [agentgateway-cardinality-lab]
      jwks:
        file: /runtime/jwks.json
    authorization:
      rules:
      - allow: 'jwt.token_use == "access" && jwt.scope == "agent.invoke"'
```

`identity.invalid` 是保留給文件與測試的網域。`make lab-04-cardinality-up` 每次都在 ignored 的 `.runtime/day23/` 產生新 private key，檔案權限固定為 `0600`，只有 public JWKS 會掛進 Gateway container。JWT、Authorization header 與 private key 都不會複製到公開 evidence。

這次 auth guard 的結果也寫進 run report，只保存 status，不保存 Token：

```json
{
  "missing_token_status": 401,
  "wrong_audience_status": 401,
  "successful_requests": 270
}
```

[agentgateway 的 JWT 文件](https://agentgateway.dev/docs/kubernetes/latest/documentation/security/jwt/setup/)把驗證後的 claims 暴露給 CEL，除了 `jwt.sub`，自訂 claim 也可以用相同方式讀取。這次 `team` 放在已簽章 JWT 內，所以 Gateway 取得的是驗證後 claim。`conversation_id` 則來自 request header，只能視為 correlation input，不能因為進了 metrics 就自動升格成可信身分。

第一組只讓 `team` 進入 metric labels，這也是預計長期保留的低基數版本：

```yaml
config:
  metrics:
    fields:
      add:
        team: jwt.team
```

第二組在相同設定上增加 `user_id`，用來觀察 team-member filter 會付出多少 series 成本：

```yaml
config:
  metrics:
    fields:
      add:
        team: jwt.team
        user_id: jwt.sub
```

第三組連每次對話的 `conversation_id` 都放進 labels，刻意把單筆查詢需求推到最極端：

```yaml
config:
  metrics:
    fields:
      add:
        conversation_id: 'request.headers["x-conversation-id"]'
        team: jwt.team
        user_id: jwt.sub
```

這裡沒有用 Python 另建一個 `requests_total` 來模仿 Gateway。三組都由 agentgateway 的 [`config.metrics.fields.add`](https://agentgateway.dev/docs/standalone/latest/observability/metrics/overview/) 把 CEL expression 加到原生 route metrics，Alloy 再以 Prometheus scrape 收走 `agentgateway_requests_total`。

## Prometheus 實測：3、30、90 條 Series

流量跑完後，verifier 對三個 scrape job 使用同一種查詢，只換掉 job 名稱。以 bounded 組為例：

```promql
count(
  agentgateway_requests_total{
    job="agentgateway-bounded",
    route="default/cardinality-run",
    status="200"
  }
)
```

三組查詢得到 3、30、90，差距來自實際出現的 label sets，並不是 verifier 事先填好的理論值：

| 實驗組 | 每組 request | 額外 label | Prometheus 實測 series | 相對 bounded |
|---|---:|---|---:|---:|
| bounded | 90 | `team` | 3 | 1x |
| per-user | 90 | `team`、`user_id` | 30 | 10x |
| per-conversation | 90 | `team`、`user_id`、`conversation_id` | 90 | 30x |

Grafana 畫面上的三個 bar gauge 直接查同一個 `agentgateway_requests_total`。下方 access logs 則來自三組 Gateway 實際送進 Alloy 的 OTLP log，並不是把 backend report JSON 做成靜態圖。

![Day 23 Grafana 實拍。三組 agentgateway 原生 metrics 分別出現 3、30、90 條 series，下方同時顯示 Gateway OTLP access logs。](https://raw.githubusercontent.com/MikeHsu0618/2026-ithelp-agent-governance-public/day-23/assets/screenshots/day-23/agentgateway-cardinality-dashboard.png)

Backend report 會把實際 traffic matrix 推導出的 expected value，與 Prometheus 回傳的 observed value 逐項比對：

```json
{
  "expected_series": {
    "bounded": 3,
    "user": 30,
    "conversation": 90
  },
  "observed_series": {
    "bounded": 3,
    "user": 30,
    "conversation": 90
  },
  "growth_vs_bounded": {
    "user": 10.0,
    "conversation": 30.0
  },
  "series_match_executed_traffic": "PASS"
}
```

這三個數字不是 `team × user × conversation` 的笛卡兒積。每位使用者在這次 fixture 只屬於一個 team，所以加入 `team + user_id` 後仍是 30 組，不會變成 3 × 30。每段 conversation 又只屬於一位使用者，因此第三組是實際出現的 90 組，也不是 3 × 30 × 90。

到了真實系統，route、method、status、backend、model、provider、region 和 retry outcome 都可能和自訂欄位共同形成 label set。這次把其他條件固定，是為了量出 `user_id` 與 `conversation_id` 的邊際影響，不代表 production 只會有 90 條 series。[Prometheus 的命名與 label 實務](https://prometheus.io/docs/practices/naming/)也提醒，label 組合可能造成高 cardinality，值集合不受控時應改用其他設計。

## 單筆 Principal 留在 Tempo 與 Loki

拿掉 metrics 裡的 `user_id`，不代表事故調查只能看 team aggregate。三組 Gateway 的 access log 都使用相同 CEL projection，把驗證後的 subject 與 team 寫進 OTLP log fields：

```yaml
frontendPolicies:
  tracing:
    host: alloy:4317
    protocol: grpc
    randomSampling: true
  accessLog:
    otlp:
      host: alloy:4317
      fields:
        add:
          correlation.conversation_id: 'request.headers["x-conversation-id"]'
          identity.team: jwt.team
          identity.user_id: jwt.sub
```

日常調查仍然可以用下面的 TraceQL，找出有 `jwt.sub` 的 Gateway span：

```traceql
{ span.jwt.sub != nil }
```

Lab 驗收不能只用這條搜尋式，因為 TraceQL search 需要等資料進入可搜尋區塊，而且不限時間時可能撈到上一輪結果。流量產生器因此替每筆 request 加入唯一的 W3C `traceparent`，並把第一筆合法請求的 `trace_id` 寫進 run report。Verifier 直接用這個 ID 向 Tempo 取回同一條 trace，再確認裡面的 `jwt.sub` 確實是 `user/sre-oncaller-000`。這能證明 identity 是由本輪 agentgateway span 留下來的，不是 Python 補值，也不是舊資料剛好命中。

實際調查仍要接受 sampling 的限制。如果目標請求沒有留下 trace，就不能拿 metric 猜出一條不存在的執行路徑，這時要回頭檢查 sampling policy，或使用保留較完整事件的資料層。Loki 端則先用低基數 `service_name` 選 stream，再用 OTLP structured metadata 過濾單一使用者：

```logql
{service_name="agentgateway"}
  | identity_user_id = "user/sre-oncaller-000"
```

Verifier 另外查 Loki 的 label-name 與 series API。本次 270 筆 Gateway access logs 只有一條以 `service_name=agentgateway` 建立的 stream，`identity_user_id` 與 `correlation_conversation_id` 都沒有成為 index labels：

```json
{
  "authentication_guards": "PASS",
  "gateway_identity_log": "PASS",
  "gateway_jwt_trace": "PASS",
  "loki_identity_not_indexed": "PASS",
  "loki_index_labels": ["service_name"],
  "loki_stream_count": 1,
  "tempo_matched_principal": "user/sre-oncaller-000",
  "tempo_trace_id": "16814ec30a7e46eba6e151d052cbfd04",
  "overall": "PASS"
}
```

[Loki 的 label cardinality 文件](https://grafana.com/docs/loki/latest/get-started/labels/cardinality/)建議 labels 使用有限而且可預期的值。[structured metadata](https://grafana.com/docs/loki/latest/get-started/labels/structured-metadata/)則是 user ID、order ID 這類高基數欄位比較適合的位置。資料依然會被保存，因此 Loki tenant、查詢角色、retention、刪除流程與容量規劃都要納入設計。這項作法只避免為每位使用者建立 index stream，不等於把 identity 當成一般無敏感性的 log field。

## Cardinality Budget：Label Value 也需要 Owner

我不會把「禁止 `user_id`」寫成唯一規則，因為 `team` 也可能失控。如果 claim mapping 允許任意 tenant 自訂 team、把專案 ID 塞進 team，或離職後的值永遠不收斂，原本看似 bounded 的 label 一樣會持續增加。能不能進 metrics，至少要同時回答四件事：

| 檢查項目 | `team` | `user_id` | `conversation_id` |
|---|---|---|---|
| value owner | Identity／Platform 維護集合 | Identity lifecycle | 應用每次建立 |
| 預期值域 | 小且可盤點 | 隨人數增加 | 隨使用量增加 |
| 主要查詢 | SLO、容量、成本歸屬 | 單人調查／分析 | 單次對話重建 |
| 建議位置 | Metric label | Trace／Log metadata／Audit | Trace／Log metadata／Audit |

Production review 還要把 metric 名稱、既有 labels、尖峰 active series、retention、tenant quota、查詢 owner 和刪除方式放進同一張表。只限制 label keys 不夠，允許的 values、來源與生命週期也要有人負責。若真的需要長期做 per-user 使用分析，我會把它當成另一種分析資料產品，明確規劃 schema、權限與成本，而不是順手把 operational metric 變成使用者明細表。

從 aggregate 回到單筆請求時，常見做法是讓 dashboard 先以 bounded metrics 找到異常時間與 route，再跳到 trace 或用 log metadata 縮小範圍。OpenTelemetry 的 [exemplar data model](https://opentelemetry.io/docs/specs/otel/metrics/data-model/)也能在 metric datapoint 和 trace 之間建立抽樣連結，不過這次 Lab 沒有實測 exemplars，所以它只是一個後續設計選項，不列入本篇 PASS。

## 重現實驗與兩次驗收修正

完整流程可以從 Repo root 一次執行，結束後也會刪掉 containers、network 與暫存 volume：

```bash
make lab-04-cardinality-check
make lab-04-cardinality-up
make lab-04-cardinality-run
make lab-04-cardinality-down
```

`lab-04-cardinality-check` 會分別用 pinned agentgateway binary 驗證三份設定，再檢查 Alloy config、Compose render、pytest、Ruff 與 format。`lab-04-cardinality-run` 先驗兩筆 `401`，再送出 270 次合法 request，最後查 Prometheus、Loki 與 Tempo。只有 auth guards、三組 series、Gateway identity log、JWT trace 和 Loki index boundary 全部符合預期時，`overall` 才會是 `PASS`。

這次第一次啟動時，靜態 validator 全部通過，Alloy runtime 卻拒絕 Prometheus scrape 設定，原因是我把 `scrape_interval` 設成 2 秒，仍沿用預設 10 秒 timeout。設定檔語法沒有錯，執行語意卻不成立。最後把 timeout 明確設為 1 秒，加入 regression test 後才重新跑完整 traffic。這個小坑也提醒我：config validation 是必要檢查，但不能拿來代替 live evidence。

第二次修正發生在 Tempo verifier。最初我用 TraceQL 綁死 `user/sre-oncaller-000`，重新建環境後可能因採樣而找不到。改成搜尋任意 `jwt.sub` 後，下一輪又發現 search 尚未索引本次 span，卻有機會命中舊資料。最後我讓 request 自帶唯一 `traceparent`，直接回查本輪已知 trace ID，才同時排除採樣對象、搜尋延遲與舊資料三個變因。若只保留第一次漂亮的 PASS，這兩個 flaky assumption 都會跟著讀者進 Repo。

完整指令、三份 Gateway YAML、Grafana Dashboard 和 machine-readable evidence 都放在 [Lab 04 README](https://github.com/MikeHsu0618/2026-ithelp-agent-governance-public/blob/day-23/labs/04-telemetry-pipeline/README.md)。截圖只幫忙看出 3／30／90 的差距，PromQL、TraceQL、LogQL 與原始 JSON 都保留成可以複製的文字。

## 從 Cardinality 接到 Fallback 成本

這次實驗裡，agentgateway 同時處理流量、驗證 JWT、執行 policy，並把選定的 claims 投影到 metrics、traces 與 access logs。Gateway 已經提供加欄位的能力，Platform Team 接下來要負責的是 label allowlist、value owner 與 backend budget。

對目前這條路徑，我會讓 `team` 留在 `agentgateway_requests_total` 做聚合，`user_id` 與 `conversation_id` 留在 Trace、Loki structured metadata 或治理事件。這個取捨保住了單筆調查能力，也不會讓每位使用者與每段 conversation 都變成常駐 metric series。

下一個要加入的 bounded dimensions 是 model、provider、route 與 fallback outcome。它們看起來比 `user_id` 安全，語意卻更麻煩：使用者要求的 model、Gateway 最後送到的 provider、實際服務的 model 和計費來源可能不是同一個值。Day 24 會先看 agentgateway 原生 LLM telemetry 真正留下哪些證據，再決定 fallback 成本要算給誰。Provider 沒回 usage 的地方會保留 `UNKNOWN`，不讓 Python 補出一張過度完整的帳單。
