# Day 22｜Agent 身分資料分流：Metrics、Traces、Logs 與 Audit 的欄位邊界

Day 21 把 Gateway、Agent Runtime 與 MCP adapter 的 Trace 接起來後，同一筆 action 已經可以跨服務查回來。接下來做 Dashboard 時，很自然會有人再加一句：「能不能按 team member 篩選？」最省事的作法，是把 JWT 裡的 `sub`、email、team 與 role 原樣複製到 span、log 和 metric。

我在做 Claude Code Stats 類型的使用分析時，也需要按 team、member、model 與 activity 切資料。篩選功能本身很實用，麻煩在於底下四種資料面不是同一種資料庫。email 放進 Trace、成為 Loki index label，或進入 Prometheus label，帶來的信任、暴露面與成本完全不同。

Day 22 沿用昨天的 Alloy／LGTM Pipeline，增加一條 identity projection 實驗。Lab 會故意把 email、token、principal 與 session 塞進 OTLP，然後直接查 Tempo、Loki 和 Prometheus，確認真正落地的欄位和設計是否一致。

agentgateway 已有官方 Grafana Dashboard，常態的 requests、LLM／MCP traffic 與 latency 不需要由這個系列重畫。Day 22 的畫面刻意只展示官方面板不會替組織決定的資料治理問題：JWT claim 經過驗證後，哪些欄位能進 Metrics，哪些只能留在 Trace、Log metadata 或 Audit。這張 field-placement view 是治理 extension，不是另一套 agentgateway 維運 Dashboard。

## Raw Claims、Verified Context 與 Telemetry Projection

JWT 裡有值，只代表 IdP 把它放進 token。等 Gateway 完成 signature、issuer、audience、expiry 與 claim mapping 的驗證後，應用程式才能建立 `VerifiedPrincipalContext`，記下目前接受的是哪個 principal，以及這份判斷有什麼 assurance。Day 8 已經用 JWKS Lab 展開完整 token validation，這篇不會再用一個 claims dictionary 假裝驗證完成。

通過驗證後也不該把整包 claims 繼續往下傳。Runtime 要的是可執行 policy 的 principal context，Telemetry producer 要的是符合查詢目的的 attributes，而 Audit 還需要 issuer、audience、policy 與 effect evidence。三個階段使用不同型別和 allowlist，資料才不會因為「後面可能用得到」一路擴散。

![Raw claims 經驗證後轉為 principal context，再分別投影到 Metrics、Traces、Logs 與 Audit。](https://raw.githubusercontent.com/MikeHsu0618/2026-ithelp-agent-governance-public/day-27/assets/diagrams/day-22/identity-data-placements.png)

公開 Lab 使用 deterministic fixture，把 issuer 與 audience 檢查後的 subject 轉成 HMAC-SHA256 `principal.ref`。這個 reference 方便跨 Trace、Log 與 Audit 關聯，仍然是可重新連結的 pseudonym，不等於匿名化。Repo 裡的固定 key 也只為了讓讀者得到相同結果，不能直接搬進 production。

## Gateway 原生 Projection 與 Collector 防線

Day 22 的 Python producer 是刻意縮小問題的 fixture。它先產生一批已標記為 verified 的合成欄位，再檢查 Alloy 能否按目的刪除或保留 attributes。這段 live evidence 的 system under test 是 collector transformation 與 backend 落地結果，JWT signature、issuer、audience 與 claims mapping 並未在這個 fixture 重新實作。

在真實 request path 上，agentgateway 會先以 `jwtAuth` 驗證 issuer、audience 與 JWKS，接著由 CEL 讀取 `jwt.sub`、`jwt.team` 等 claims。以下是 Day 23 Lab 的精簡版本，access log 裡的兩個 identity 欄位都由 Gateway 產生：

```yaml
frontendPolicies:
  accessLog:
    otlp:
      host: alloy:4317
      fields:
        add:
          identity.user_id: jwt.sub
          identity.team: jwt.team

routes:
- name: cardinality-run
  policies:
    jwtAuth:
      mode: strict
      issuer: https://identity.invalid/day23
      audiences: [agentgateway-cardinality-lab]
      jwks:
        file: /runtime/jwks.json
```

[agentgateway 的 JWT 文件](https://agentgateway.dev/docs/kubernetes/latest/documentation/security/jwt/setup/)說明了驗證後 claims 與 CEL 的使用方式，[access-log OTLP 設定](https://agentgateway.dev/docs/standalone/latest/documentation/observability/access-logs/export/)則提供自訂欄位的出口。Gateway 在這裡負責「這個 claim 來自已驗證 Token」與第一輪最小化，Alloy 接手後再刪一次明確禁止欄位，處理不同 backend 的格式與保留需求。兩層控制解的問題不同，不能拿 collector 的紅線規則補救一個根本沒有驗證過的 caller identity。

Day 23 會把上面這段補成 runtime evidence：臨時 RS256 JWT 真的通過三組 agentgateway，由 Gateway 把 claims 加進 metrics、traces 與 access logs，再查 Prometheus、Tempo 與 Loki。兩篇各自測一層，Day 22 看 destination placement 與 collector 防線，Day 23 則改變 Gateway labels，量出每項設計的 backend 成本。

## 四個目的地不共用同一份 attributes map

我會先從每種資料要回答的問題回推欄位。Metrics 看整體健康度與趨勢，Trace 重建單筆因果，Logs 保存可搜尋的事件細節，Audit 則要回答誰代表誰、哪份政策允許什麼動作，以及最後產生了什麼效果。

| 資料面 | Lab 保留的身分欄位 | 明確排除 | 主要用途 |
|---|---|---|---|
| Metrics | `team` | principal、user、session、conversation、`action_id` | team／route／outcome 的聚合趨勢 |
| Traces | `principal.ref`、assurance、team、primary role、tenant、`action_id` | raw token、email | 單筆 action 的因果與責任線索 |
| Logs | `principal.ref`、team、`action_id`，以 structured metadata 保存 | raw token、email、本機 code path | 事件搜尋與除錯 |
| Audit | actor ref、roles、tenant、issuer、audience、assurance、`action_id` | raw token | 責任鏈、policy decision 與 effect evidence |

完整版本放在 [Identity field placement matrix](https://github.com/MikeHsu0618/2026-ithelp-agent-governance-public/blob/day-27/labs/04-telemetry-pipeline/identity-field-placement.md)，裡面另外列了 role、tenant、session 與 conversation ID。這份表不是法規範本，真正落地前仍要加入資料分類、存取角色、保留期限、刪除流程與所在區域。

## Metrics 只保留有限集合的維度

Metrics 最容易被「順手多放一個 label」拖垮。`team=platform-sre`、`route=agent-runtime` 和 `outcome=allowed` 都來自受控集合，適合拿來看流量與成功率。`principal.ref`、`action_id` 和 `session.id` 幾乎每筆都不同，一旦進入 label，就會跟 action 數量一起製造新 series。

這次 Lab 的第一輪實跑，剛好把問題演了一次。Python producer 故意送出 `principal.ref`，Alloy 當時只刪 email 與 token，Prometheus 真的收到了 `principal_ref` label，backend verifier 因此失敗：

```json
{
  "overall": "FAIL",
  "prometheus_bounded_labels": "FAIL",
  "tempo_safe_projection": "PASS",
  "loki_safe_projection": "PASS"
}
```

修補不是叫 Dashboard 別用這個 label，而是在 metric datapoint 離開 Alloy 前就移除高基數 identity attributes。只靠查詢端約定不用某個 label，污染 series 仍然已經產生，所以 Lab 把限制放在 collector 出口：

```alloy
metric_statements {
  context = "datapoint"
  statements = [
    `delete_key(attributes, "conversation.id")`,
    `delete_key(attributes, "ithelp.governance.action_id")`,
    `delete_key(attributes, "principal.ref")`,
    `delete_key(attributes, "session.id")`,
    `delete_key(attributes, "user.id")`,
  ]
}
```

清空 Prometheus volume 後重新執行，同一個 Counter 只能按三個預定維度聚合。圖裡的 PromQL 與回傳 series 都只剩 team、route、outcome：

```promql
sum by (team, route, outcome) (ithelp_agent_actions_total)
```

![Prometheus 實拍。Day 22 的 Agent action metric 只以 team、route 與 outcome 聚合。](https://raw.githubusercontent.com/MikeHsu0618/2026-ithelp-agent-governance-public/day-27/assets/screenshots/day-22/prometheus-bounded-labels.png)

Day 23 會把這件事做成壓力實驗，逐步加入 `user_id` 與 `conversation_id`，直接量 Prometheus series 和 Loki stream 的增幅。今天先把欄位邊界定下來，明天才有一條可以被驗證的 cardinality budget。

## Trace 保留 pseudonymous principal，不保存 raw credential

Trace 的工作是重建一筆 action 經過哪些服務、policy 與 Tool，所以 `principal.ref` 和 `action_id` 在這裡有價值。Tempo 實拍裡還能看到 assurance、team、role 與 tenant，事故調查時可以判斷這筆 action 採用哪種身分來源，不必先把 email 當作搜尋鍵。

![Tempo 實拍。identity projection span 保留 action ID、principal reference、assurance、team 與 role，沒有 raw email 或 token。](https://raw.githubusercontent.com/MikeHsu0618/2026-ithelp-agent-governance-public/day-27/assets/screenshots/day-22/tempo-identity-projection.png)

[OpenTelemetry 的 user attribute registry](https://opentelemetry.io/docs/specs/semconv/registry/attributes/user/)雖然定義了 `user.id`、`user.email`、`user.name`、`user.roles` 與 `user.hash`，這些欄位目前仍標為 Development。Semantic Convention 告訴我們名稱如何對齊，不會替組織決定哪個直接識別資訊可以進 backend。本文使用自訂 `principal.ref`，就是要把「可關聯的治理主體」和「產品介面顯示的 email」分開。

Trace Context 也不適合順便承載身分內容。[OpenTelemetry 對 Baggage 的安全提醒](https://opentelemetry.io/docs/concepts/signals/baggage/)特別指出，Baggage 可能傳到不受信任的下游，也可能被記錄，因此不該放 PII、credential 或 API key。Day 21 需要跨服務傳的是 `traceparent`。principal context 應由已定義的可信邊界傳遞，不能只圖方便就把 raw JWT 塞進 Baggage。

## Loki 用 Structured Metadata 查單筆 principal

Loki 的第一段查詢只用低基數 `service_name` 選 stream，再用 pipe 後面的 `principal_ref` 篩選 structured metadata。這個順序保留單筆 principal 的查詢能力，也避免把每個 principal 都變成一條新 stream：

```logql
{service_name="identity-projection-lab"}
  | principal_ref = "prn_66103c4906ed52ad53b3"
```

![Loki 實拍。查詢先以 service_name 選 stream，再用 principal_ref structured metadata 過濾單筆事件。](https://raw.githubusercontent.com/MikeHsu0618/2026-ithelp-agent-governance-public/day-27/assets/screenshots/day-22/loki-identity-structured-metadata.png)

[Loki 的原生 OTLP ingestion](https://grafana.com/docs/loki/latest/send-data/otel/)會把未映射成 index label 的 attributes 存成 structured metadata，點號也會正規化成底線。因此 OTLP 的 `principal.ref` 在 LogQL 裡會變成 `principal_ref`。[Grafana 對 structured metadata 的定位](https://grafana.com/docs/loki/latest/get-started/labels/structured-metadata/)正是保存 user ID 等高基數 metadata，查詢時可以過濾，但不為每個值建立 index。

沒有 index 不代表資料變得不敏感，也不代表儲存免費。Backend 仍然收到了可關聯 principal 的值，所以 Loki tenant、查詢權限、retention 與刪除流程都要納入治理。如果根本沒有單筆使用者查詢需求，producer 連 structured metadata 都不必送。

## Audit 保存責任證據，不保存整顆 JWT

Audit 和 operational telemetry 的保留目的不同。Lab 另外輸出 `audit-event.json`，保留 actor reference、roles、tenant、issuer、audience、assurance 與 action ID。等 Day 26 做事件重建時，還會把 policy version、resource、approval 與 effect evidence 接回來，回答執行責任，而不是只看一條綠色 span。

完整責任鏈不需要保存 bearer token。raw JWT 會擴大 credential 暴露面，也把原始 claims 的生命週期綁進長期 Audit。若事件調查真的需要判斷兩次使用是否來自同一顆 token，可以另外設計一次性 fingerprint、存取權限與保留期限，不該把 JWT 本體當作方便的附件。

Audit 也不一定和 Loki 共用相同 retention。實務上我會把 operational logs 的查詢角色、治理事件的讀取角色，以及法遵或事件調查的匯出流程分開。資料格式可以透過 `action_id` 關聯，backend 的權限與保存責任不必因此綁成一套。

## Alloy 清理已知欄位，但不替來源建立信任

Lab 在 `memory_limiter` 和 `batch` 中間加入 [`otelcol.processor.transform`](https://grafana.com/docs/alloy/latest/reference/components/otelcol/otelcol.processor.transform/)。它使用 OTTL 分別處理 span、log 與 datapoint，raw email 和 token 在三種訊號都會刪除。Metric 另外清掉 principal、user、session、conversation 與 action ID。

```alloy
otelcol.processor.transform "identity_projection" {
  error_mode = "propagate"

  trace_statements {
    context = "span"
    statements = [
      `delete_key(attributes, "user.email")`,
      `delete_key(attributes, "auth.token")`,
    ]
  }

  log_statements {
    context = "log"
    statements = [
      `delete_key(attributes, "user.email")`,
      `delete_key(attributes, "auth.token")`,
      `delete_key(attributes, "code.file.path")`,
    ]
  }
}
```

`code.file.path` 是在拍 Loki 畫面時才發現的。Python logging SDK 自動帶出本機絕對路徑，雖然不是 identity claim，卻同樣沒有必要公開。清掉它之後，Grafana 的 common fields 才不會把 Repo 所在目錄一起交出去。這個插曲也說明只盤點自己手動加入的 attributes 還不夠，SDK 與 collector 自動補的 resource／code metadata 也要查看真正的 backend payload。

Alloy 還有專門的 [`otelcol.processor.redaction`](https://grafana.com/docs/alloy/latest/reference/components/otelcol/otelcol.processor.redaction/)，但目前在 Alloy 標為 experimental，啟用時要提高 stability level。公開 Lab 選擇已正式提供的 transform processor，讓預設命令可以直接 validate。代價是明確的 key deletion 只認得已列出的欄位，不能保證抓到未來新加的 `customer_email` 或某段自由文字裡的 PII。

因此 producer 仍是第一道防線。Raw claims 不進 Telemetry API，每個 destination 都使用自己的 allowlist，Alloy 再清一次已知禁止欄位。Collector 可以降低誤送造成的傷害，不能替 Gateway 驗證 token，也不能取代 backend RBAC、retention、資料盤點與告警。

## Lab 故意污染三種訊號，再查三個 Backend

從 Repo root 啟動昨天的 Compose，接著執行 identity projection。整條路徑不需要 API key，也不會另外啟動一套只為截圖存在的 backend：

```bash
make lab-04-up
make lab-04-check
make lab-04-identity
```

`make lab-04-identity` 會送出一個 synthetic span、log 與 Counter。送進 Alloy 前，三者刻意含有 `user.email` 和 `auth.token`。Metric 另外帶 `principal.ref` 與 `session.id`，逼 verifier 確認這些值沒有成為 Prometheus labels。Tempo 與 Loki 則必須保留安全的 principal reference 和 action ID，否則一味把欄位刪光也不算通過。

乾淨 volume 的最後結果如下。Verifier 查的是三個 backend API，不是只比對 producer 寫出的預期 JSON：

```json
{
  "forbidden_fields_absent": "PASS",
  "loki_principal_not_indexed": "PASS",
  "loki_safe_projection": "PASS",
  "overall": "PASS",
  "prometheus_bounded_labels": "PASS",
  "tempo_safe_projection": "PASS"
}
```

整個 Lab 目前有 61 個 pytest，branch coverage 85.98%。Docker Compose、agentgateway config 與 Alloy 1.18.1 config 也都經過實際 validator。Verifier 還會查 Loki label-name API，確認 `principal_ref` 沒有進入 index labels。Tool 仍是 no-op canary，不需要 LLM key，也不會連資料庫、shell、Kubernetes 或外部 API。

## Kubernetes 環境還要補 Secret、權限與保留政策

公開 Compose 把資料送進同一個 OTEL-LGTM，方便在一台電腦看懂 projection。回到 Kubernetes，HMAC key 必須進 Secret 管理並規劃 rotation，tenant 與 team mapping 要有 owner，Alloy config 也要走 review、測試與 rollout，否則一個錯誤 attributes map 就可能同時污染多個 backend。

Tempo、Loki、Prometheus 與 Audit store 的讀取角色不應因為共用 `action_id` 就自動相同。Identity 查詢通常比 service-level metrics 更敏感，retention 也未必一致。先定義「誰能查單一 principal、保留多久、如何匯出與刪除」，再決定欄位落點，會比資料進去後才補遮罩省事得多。

Day 22 把 raw claims、verified principal context 與 telemetry projection 分開，也讓四種資料面各自留下足夠但不過量的身分線索。這篇實跑的是 Alloy 與 backend，還沒有拿 Gateway 原生 metric 驗證 bounded dimension 的代價。Day 23 會讓同一批已驗證 JWT 通過三組 agentgateway，分別加入 `team`、`user_id` 與 `conversation_id`，直接查 `agentgateway_requests_total` 的 series 數，再確認單一 principal 留在 Tempo 與 Loki metadata 仍然查得到。
