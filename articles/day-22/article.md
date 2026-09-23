# Day 22｜Agent 身分資料分流：Metrics、Traces、Logs 與 Audit 的欄位邊界

Day 21 把 Gateway、Agent Runtime 與 MCP Adapter 的 Trace 接起來後，同一筆 Action 已經能跨服務查回來。接著做 Dashboard 時，很自然會有人問：「能不能按 Team Member 篩選？」最省事的做法，是把 JWT 裡的 `sub`、Email、Team 與 Role 原樣複製到 Span、Log 和 Metric。

我在做 Claude Code Stats 類型的使用分析時，也需要按 Team、Member、Model 與 Activity 切資料。篩選本身很實用，麻煩在於底下四種資料面不是同一種資料庫。Email 放進 Trace、成為 Loki Index Label，或進入 Prometheus Label，帶來的信任、暴露面與成本完全不同。

Day 22 沿用昨天的 Alloy／LGTM Pipeline，故意把 Email、Token、Principal 與 Session 塞進 OTLP，再直接查 Tempo、Loki 與 Prometheus。目的不是做另一張 agentgateway Dashboard，而是確認身分通過驗證後，哪些欄位能進 Metrics，哪些只能留在 Trace、Log Metadata 或 Audit。

## Raw Claims、Verified Context 與 Projection

JWT 裡有 `sub` 或 `team`，不表示後面的服務可以直接相信這兩個值。Gateway 先檢查 Signature、Issuer、Audience 與 Expiry，按 Claim Mapping 建立 `VerifiedPrincipalContext`，後續元件才知道這份身分資訊由哪個入口接受。JWT／JWKS 的檢查方式已在 Day 8 展開，這篇接著處理驗過之後的資料去向。

通過驗證後，也不該把整包 Claims 繼續往下傳。Runtime 要的是能執行 Policy 的 Principal Context，Telemetry Producer 要的是符合查詢目的的 Attributes，Audit 則需要 Issuer、Audience、Policy 與 Effect Evidence。三個階段使用不同型別與 Allowlist，資料才不會因為「後面也許用得到」一路擴散。

![Raw claims 經驗證後轉為 principal context，再分別投影到 Metrics、Traces、Logs 與 Audit。](https://raw.githubusercontent.com/MikeHsu0618/2026-ithelp-agent-governance-public/day-29-r2/assets/diagrams/day-22/identity-data-placements.png)

Lab 將驗證後的 Subject 轉成 HMAC-SHA256 `principal.ref`。這個 Reference 方便跨 Trace、Log 與 Audit 關聯，仍然是可以重新連結的 Pseudonym，不是匿名化。Repo 中的固定 Key 只為了讓讀者重現相同結果，正式環境必須改由 Secret 管理並規劃 Rotation。

真正的 Request Path 應由 agentgateway 先驗 JWT，再透過 CEL 讀取 `jwt.sub`、`jwt.team` 等 Claims。Gateway 負責確認來源可信與第一輪最小化，Alloy 接手後依 Destination 再刪一次已知禁止欄位。Collector 的 Redaction 不能補救一個根本沒有驗證過的 Caller Identity。

這份 Lab 先讓讀者看清楚同一個身分欄位落到不同資料庫會有什麼後果。下一篇再換成由 agentgateway 驗 JWT、投影 Claim 的實際流量，量出 Metric Series 的差異。

## 四種資料面不能共用 Attributes Map

我會先從每種資料要回答的問題回推欄位。Metrics 看整體健康度與趨勢，Trace 重建單筆因果，Logs 保存可搜尋的事件細節，Audit 則回答誰代表誰、哪份 Policy 允許什麼動作，以及最後產生什麼效果。

| 資料面 | 保留的身分欄位 | 明確排除 | 主要用途 |
| --- | --- | --- | --- |
| Metrics | `team` | Principal、User、Session、Conversation、`action_id` | Team／Route／Outcome 的聚合趨勢 |
| Traces | `principal.ref`、Assurance、Team、Primary Role、Tenant、`action_id` | Raw Token、Email | 單筆 Action 的因果與責任線索 |
| Logs | `principal.ref`、Team、`action_id`，存為 Structured Metadata | Raw Token、Email、本機 Code Path | 事件搜尋與除錯 |
| Audit | Actor Ref、Roles、Tenant、Issuer、Audience、Assurance、`action_id` | Raw Token | 責任鏈、Policy Decision 與 Effect Evidence |

完整版本放在 [Identity field placement matrix](https://github.com/MikeHsu0618/2026-ithelp-agent-governance-public/blob/day-29-r2/labs/04-telemetry-pipeline/identity-field-placement.md)，另外列出 Role、Tenant、Session 與 Conversation ID。這張表不是法規範本，落地前仍要加入資料分類、存取角色、Retention、刪除流程與資料所在區域。

## Metrics 只保留有限集合的維度

Metrics 最容易被「順手多放一個 Label」拖垮。`team=platform-sre`、`route=agent-runtime` 與 `outcome=allowed` 來自受控集合，適合觀察流量與成功率。`principal.ref`、`action_id` 與 `session.id` 幾乎每筆都不同，一旦進入 Label，Series 數量就會跟 Action 一起成長。

第一次 Live Run 正好重現這個問題。Python Producer 故意送出 `principal.ref`，Alloy 當時只刪 Email 與 Token，Prometheus 真的收到了 `principal_ref` Label，`prometheus_bounded_labels` 因此失敗。

修正位置不在 Dashboard，而是 Metric Datapoint 離開 Alloy 以前。若只約定查詢不要使用某個 Label，污染的 Series 早已產生。Lab 因此在 Collector 出口刪除 Conversation、Action、Principal、Session 與 User Attributes，再清空 Prometheus Volume 重跑。

最後同一個 Counter 只能按三個預定維度聚合：

```promql
sum by (team, route, outcome) (ithelp_agent_actions_total)
```

![Prometheus 實拍。Day 22 的 Agent action metric 只以 team、route 與 outcome 聚合。](https://raw.githubusercontent.com/MikeHsu0618/2026-ithelp-agent-governance-public/day-29-r2/assets/screenshots/day-22/prometheus-bounded-labels.png)

這次失敗很值得保留，因為它說明高基數不是架構圖上的抽象風險。Producer 多送一個 Attribute，Collector 少刪一個 Key，Backend 就真的建立新 Series。Day 23 會將這件事放大成 3、30、90 個 Identity 的壓力實驗。

## Trace 保留可關聯 Principal，不留 Credential

Trace 用來重建一筆 Action 經過哪些 Service、Policy 與 Tool，因此 `principal.ref` 和 `action_id` 在這裡有價值。Tempo 實拍還保留 Assurance、Team、Role 與 Tenant，事故調查能判斷這筆 Action 使用哪種身分來源，不必先拿 Email 當搜尋鍵。

![Tempo 實拍。identity projection span 保留 action ID、principal reference、assurance、team 與 role，沒有 raw email 或 token。](https://raw.githubusercontent.com/MikeHsu0618/2026-ithelp-agent-governance-public/day-29-r2/assets/screenshots/day-22/tempo-identity-projection.png)

[OpenTelemetry User Attributes](https://opentelemetry.io/docs/specs/semconv/registry/attributes/user/) 定義了 `user.id`、`user.email`、`user.name`、`user.roles` 與 `user.hash`，目前仍標示為 Development。Semantic Convention 對齊的是欄位名稱，不會替組織決定哪些直接識別資料可以進 Backend。本文使用 `principal.ref`，就是要把「可關聯的治理主體」與產品介面顯示的 Email 分開。

Trace Context 也不適合夾帶身分內容。[OpenTelemetry Baggage 的安全提醒](https://opentelemetry.io/docs/concepts/signals/baggage/) 指出，Baggage 可能傳到不受信任的下游，也可能被記錄，所以不該放 PII、Credential 或 API Key。Day 21 跨服務需要的是 `traceparent`，Principal Context 應走已定義的可信邊界，不能為了方便把 Raw JWT 塞進 Baggage。

## Loki 用 Structured Metadata 查單筆 Principal

Loki 查詢先用低基數 `service_name` 選 Stream，再以 Pipe 後面的 `principal_ref` 篩選 Structured Metadata：

```logql
{service_name="identity-projection-lab"}
  | principal_ref = "prn_66103c4906ed52ad53b3"
```

![Loki 實拍。查詢先以 service_name 選 stream，再用 principal_ref structured metadata 過濾單筆事件。](https://raw.githubusercontent.com/MikeHsu0618/2026-ithelp-agent-governance-public/day-29-r2/assets/screenshots/day-22/loki-identity-structured-metadata.png)

[Loki 原生 OTLP Ingestion](https://grafana.com/docs/loki/latest/send-data/otel/) 會把沒有映射成 Index Label 的 Attributes 存成 Structured Metadata，點號也會正規化成底線。因此 OTLP 的 `principal.ref` 在 LogQL 變成 `principal_ref`。這保留單筆 Principal 的查詢能力，不會為每個人建立一條新 Stream。

沒有 Index 不代表資料不敏感，也不代表儲存免費。Backend 仍收到可關聯 Principal，所以 Loki Tenant、查詢權限、Retention 與刪除流程都要納入治理。若根本沒有單筆使用者查詢需求，Producer 連 Structured Metadata 都不必送。

## Audit 保存責任證據，不保存整顆 JWT

Audit 與 Operational Telemetry 的目的不同。Lab 另外輸出 `audit-event.json`，保留 Actor Reference、Roles、Tenant、Issuer、Audience、Assurance 與 Action ID。Day 26 做事件重建時，還會接回 Policy Version、Resource、Approval 與 Effect Evidence，回答執行責任，而不只看綠色 Span。

完整責任鏈不需要 Bearer Token。Raw JWT 會擴大 Credential 暴露面，也把原始 Claims Lifecycle 綁進長期 Audit。若事件調查真的需要判斷兩次使用是否來自相同 Token，可以另設 Fingerprint、存取權限與保存期限，不該把 JWT 本體當附件。

Audit 也不一定和 Loki 使用相同 Retention。我會分開 Operational Logs 的查詢角色、Governance Event 的讀取角色，以及法遵或事件調查的 Export Flow。資料能用 `action_id` 關聯，不表示 Backend 權限與保存責任必須綁成一套。

## Alloy 是第二道防線，不是信任來源

Lab 在 Memory Limiter 與 Batch Processor 中間加入 Alloy Transform，分別處理 Span、Log 與 Datapoint。Email 和 Token 在三種訊號都被移除，Metric 另外清掉 Principal、User、Session、Conversation 與 Action ID。

拍 Loki 畫面時，Backend 還暴露了 Python Logging SDK 自動附加的本機 `code.file.path`。它不是 Identity Claim，卻同樣沒有公開必要。清掉後，Grafana Common Fields 才不會把 Repo 所在目錄一起交出去。只盤點手動加入的 Attributes 還不夠，SDK 與 Collector 自動補入的 Resource／Code Metadata 也要看真正落地的 Payload。

明確刪 Key 的 Transform 只能處理已知欄位，無法保證抓到未來新增的 `customer_email` 或自由文字裡的 PII。Producer 仍是第一道防線。Raw Claims 不進 Telemetry API，每個 Destination 使用自己的 Allowlist，Alloy 再清一次已知禁止欄位。Collector 可以降低誤送的傷害，不能替 Gateway 驗 Token，也不能取代 Backend RBAC 與資料盤點。

## Lab 直接查三個 Backend 的落地結果

從 Repo Root 啟動既有 Compose，再執行 Identity Projection：

```bash
make lab-04-up
make lab-04-check
make lab-04-identity
```

Producer 送出 Synthetic Span、Log 與 Counter。三者進 Alloy 前刻意含有 `user.email` 和 `auth.token`，Metric 另外帶 `principal.ref` 與 `session.id`。Tempo 與 Loki 必須保留安全的 Principal Reference 和 Action ID，Prometheus 則不得收到高基數 Identity Label。Verifier 查詢三個 Backend API，而不是比對 Producer 自己寫出的預期 JSON。

最終結果確認 Forbidden Fields 全部消失、`principal_ref` 沒有成為 Loki Index Label、Tempo／Loki 保留安全 Projection，Prometheus Label 則只剩受控維度。完整 Result、Alloy Config 與 Test Evidence 都在 Lab Repo，正文不再列出 Test Count、Coverage 與 Validator Metadata。

## Kubernetes 還要補權限與 Retention

公開 Compose 將資料送進同一個 OTEL-LGTM，方便在一台電腦看懂 Projection。回到 Kubernetes，HMAC Key 必須進 Secret 管理並規劃 Rotation，Tenant 與 Team Mapping 要有 Owner，Alloy Config 也要經過 Review、Test 與 Rollout。錯誤的 Attributes Map 可能同時污染多個 Backend。

Tempo、Loki、Prometheus 與 Audit Store 的讀取角色，不應因為共用 `action_id` 就自動相同。Identity 查詢通常比 Service-level Metrics 更敏感，Retention 也未必一致。先定義誰能查單一 Principal、保留多久、如何 Export 與刪除，再決定欄位落點，會比資料進去後才補遮罩省事。

Day 22 已將 Raw Claims、Verified Principal Context 與 Telemetry Projection 分開，也讓四種資料面各自留下足夠但不過量的身分線索。Day 23 會讓同一批已驗證 JWT 通過三組 agentgateway，分別加入 `team`、`user_id` 與 `conversation_id`，直接量出 Series 與 Stream 的增幅。
