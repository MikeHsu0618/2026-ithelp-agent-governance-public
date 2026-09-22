# Day 24｜agentgateway LLM 成本觀測實戰：Dashboard 上的數字能信到哪裡？

agentgateway `1.5.0` 的 LLM Analytics 跑起來後，不用先畫 Grafana，就能看到 Calls、Token Usage 與估算成本，還可以按 Model、Provider、User 或 Group 拆開。我原本以為這篇最花時間的會是 Dashboard，實際跑完才發現，官方畫面早就有了，真正麻煩的是判斷上面的數字能拿來做什麼。

下面這張畫面來自一個故意觸發備援的 Lab。同一個 Agent Action 先打到 Primary Provider，收到 `503` 後由 Client 重送，再由 Backup Provider 成功完成。Dashboard 顯示 `2 calls`、10 個 Tokens 與 `USD 0.000066`。三個數字都是真的，卻不能直接讀成「這個 Action 完整花了 USD 0.000066」。

![agentgateway 1.5.0 內建 Analytics 實跑畫面。相同 Fallback action 產生 OpenAI 與 Anthropic 各一筆 request，畫面顯示 2 calls，但只有成功 response 提供的 10 tokens 與 USD 0.000066。](https://raw.githubusercontent.com/MikeHsu0618/2026-ithelp-agent-governance-public/day-11-r1/assets/screenshots/day-24/agentgateway-official-analytics-dashboard.png)

Day 23 已經量過高基數 Label 的代價，這篇把注意力移到 Model、Provider、Tokens 與 Cost。Fallback 只是壓力測試，它讓 Dashboard 平常不明顯的三條界線一起浮出來：一次使用者動作可能包含多次 Provider Attempts、失敗回應不一定帶 Usage、Gateway Estimate 也不等於 Provider 最後開出的帳單。

## 內建 Analytics 的資料來源

agentgateway 的 [LLM Analytics](https://agentgateway.dev/docs/standalone/latest/documentation/llm/cost-controls/dashboard/) 會把 LLM Requests 寫進資料庫，從 Provider Response 取得 Token Usage，再依 Model Catalog 的費率估算 Cost。UI 負責聚合與篩選，並不會直接去 Provider 的帳務系統抄回結算金額。

公開 Lab 使用 SQLite，重建環境時就會清掉。這適合教學與截圖，正式環境若要保留長期趨勢，仍要替資料庫安排 Persistence、Backup 與多副本資料彙整。官方 UI 可以解決大部分即時觀察需求，但不會因為畫面完整，就自動變成財務系統。

agentgateway 也提供[官方 Grafana Dashboard](https://agentgateway.dev/docs/standalone/main/integrations/observability/grafana/)，涵蓋 Requests、LLM Token／Cost／Latency、MCP、Route 與 Runtime Health。它的主要部署情境是 Kubernetes，會使用 Namespace、Gateway、Pod 等 Labels。本文的公開 Lab 是 Standalone Compose，因此保留同版官方 Dashboard 作為維運基準，不把上游 JSON 改到看似支援另一種 Topology。後面的自訂 Grafana 畫面只補官方 Analytics 不容易呈現的 Action／Attempt 關聯。

我在自己的 Grafana Claude Code Stats App 也遇過相同問題。Telemetry 有 Token Counter，不代表供應商已提供 Billed Cost，所以畫面使用 **Estimated API-equivalent Cost**，價格表也放進 Source Control。沒有對應費率的 Model 會進入 Unpriced Model Tokens，不會借用相近型號的價格。做過兩套畫面後，我最在意的不是小數點，而是命名。只要把 Estimate 寫成 Total Cost，使用者自然會把它當成帳單。

## Action 與 Attempt 的兩層帳本

Day 24 的 [Lab 04 README](https://github.com/MikeHsu0618/2026-ithelp-agent-governance-public/blob/day-11-r1/labs/04-telemetry-pipeline/README.md) 啟動兩個本機 Provider Fixtures。Client 要求的是 Virtual Model `day24-resilient-agent`，Primary 使用 OpenAI 相容格式，Backup 使用 Anthropic 格式。兩邊都回傳固定結果，不需要外部 API Key，也不會把流量送出電腦。

這裡需要先分開兩個識別：

| 層級 | 穩定識別 | 回答的問題 |
| --- | --- | --- |
| Logical Action | `action_id` | 使用者原本想完成什麼工作，最後有沒有成功 |
| Provider Attempt | `trace_id`、時間與 Provider | 這次網路請求送到哪裡，回了什麼狀態，有沒有 Usage 證據 |

一個 Action 可以有多個 Attempts。Action Success Rate 和 Provider Request Success Rate 因此是不同指標，成本也必須先保存每次 Attempt 的證據，再按 Action、Team 或 Route 聚合。若資料庫只留下最後一次成功 Response，月底即使看到異常帳單，也無法還原前面試過幾個 Provider。

圖中的兩條路徑是兩組互不串接的實驗，不是 Production 裡的雙層 Proxy。每一次實際 Data Path 都只有 Client → agentgateway → Provider。

![同一個 Agent action 經過兩次 HTTP request。第一次由 primary provider 回傳 503，第二次 client retry 才由 backup provider 成功服務，失敗 attempt 的 usage 與 cost 保持 UNKNOWN。](https://raw.githubusercontent.com/MikeHsu0618/2026-ithelp-agent-governance-public/day-11-r1/assets/diagrams/day-24/fallback-cost-evidence.png)

## Health Eviction 的實測結果

我原本把 Virtual Model 的 Failover 理解成「Primary 失敗後，同一個 Request 自動改送 Backup」。Live Run 顯示的行為不同。Primary 回 `503` 後，Gateway 會暫時 Evict 故障 Target，但當下 Request 仍以失敗結束，下一筆 Request 才會避開 Primary。

agentgateway 另有 Route-level Retry Policy，不過把 `retry` 直接放進這次使用的 Simplified LLM Policy，`1.5.0` Validator 會拒絕設定：

```text
Error: llm.policies: unknown field retry
```

這筆 Validator 結果的範圍只涵蓋本文的設定方式：Health Eviction 不能在這裡當成 Same-request Retry。公開 Lab 因此由 Client 明確重送，兩次 Requests 共用同一個 `action_id`。Production 若讓 Gateway 接手 Retry，還要另行驗證 Timeout Budget、Streaming Response 與 Idempotency，不能沿用本文結果直接推論。

Lab 共跑三種情境：

| Scenario | HTTP Attempts | Provider 順序 | 最終狀態 | Usage 證據 |
| --- | ---: | --- | --- | --- |
| `primary-success` | 1 | Primary | `200` | Input 11／Output 5 |
| `failover-without-retry` | 1 | Primary | `503` | `UNKNOWN` |
| `failover-with-retry` | 2 | Primary → Backup | `503` → `200` | Attempt 1 `UNKNOWN`，Attempt 2 Input 7／Output 3 |

內建 Analytics 截圖只查看第三組情境，所以畫面上的兩個 Calls 是 Primary `503` 和 Backup `200`。10 個 Tokens 與 `USD 0.000066` 則只來自 Backup 的成功 Response。Calls 計數涵蓋兩次 Attempts，Token 與 Cost 卻只有一張收據，這就是不能直接把三個數字視為同一份總帳的原因。

## 成本證據的三個層級

Primary `503` 在 agentgateway Access Log 與 Prometheus 裡會留下零值 Cost。這個零代表 Gateway 沒拿到能套用 Catalog 的 Usage，不能反推 Provider 一定沒有計費。請求可能在 Provider 已處理部分輸入後才失敗，也可能適用另一套結算規則。

因此，我把成本分成三層：

| 證據層 | 本篇能證明什麼 | 仍然缺少什麼 |
| --- | --- | --- |
| Provider Response Usage | 成功 Response 回傳的 Token 數 | 失敗 Request 可能沒有 Usage Payload |
| Gateway Model Catalog | 依 Served Model 與版本化費率算出的 Estimate | 合約價、Credit 與 Provider 特殊規則 |
| Provider Billing Export／Invoice | 最後結算與帳務調整 | 通常較晚取得，還要對回 Account、Route 或 Attribution Tag |

對 `failover-with-retry` 而言，目前能證明的 Known Subtotal 是 Backup 的 `USD 0.000066`。Primary Attempt 沒有 Usage，Complete Action Total 應保持 `UNKNOWN`。不能因為報表需要一個數字，就把 Unknown 當成 Zero 排除後仍命名為 Complete Total。

agentgateway 的 [Model Cost 文件](https://agentgateway.dev/docs/standalone/latest/documentation/llm/cost-controls/costs/) 也說明 Catalog Estimate 可能因價格更新、自訂費率、失敗 Request 或 Provider 規則而與帳單不同。[Invoice-grade Attribution](https://agentgateway.dev/docs/standalone/latest/documentation/llm/cost-controls/attribution/) 還取決於 Provider 是否接受 Attribution Value，並把它放進自己的 Billing Data。即時觀察與月底對帳可以共用關聯欄位，卻不是同一種證據。

## Requested Model 與 Served Model

Client 在三種情境裡送出的 `model` 都是 `day24-resilient-agent`，它代表 Agent Runtime 選擇的 Virtual Model。Primary 成功時，Response Model 是 `day24-primary`。備援成功時，真正服務 Request 的則是 `day24-backup`。

Metrics 若只保留 Requested Model，所有流量看起來都屬於同一條 Route，無法分辨 Backup 用量。只留下 Served Model 也不夠，因為原始 Routing Intent 會消失。OpenTelemetry GenAI Semantic Conventions 已提供 `gen_ai.request.model`、`gen_ai.response.model`、`gen_ai.provider.name` 與 Token Usage 等欄位，本文的 `team`、`experiment` 與 `correlation.action_id` 則是平台自己的 Attribution Schema。

日常聚合可以使用 Team、Route、Provider、Served Model、Token Type 與 Outcome。`action_id`、`trace_id`、Principal 和 Provider Request ID 繼續留在 Logs、Traces 或 Audit，避免每個 Request 都替 Prometheus 建立新 Series。成本查詢不能成為把 Day 23 高基數欄位搬回 Metrics 的理由。

## Grafana 補上的 Action 關聯

官方 Analytics 適合查看 Model 與 Provider 趨勢，自訂 Grafana 畫面則把兩組實驗的 Gateway Metrics、Loki Logs 與 Tempo Traces 放在一起。上半部顯示 Primary Calibration 與 Backup 的原生 Token／Cost Metrics，下半部使用同一個 `correlation_action_id` 找到 Primary `503` 和 Backup `200`。

![Day 24 Grafana focused extension 實拍。上半部使用 agentgateway 原生成本與 token metrics，下半部以相同 action_id 查到 primary 503 與 backup 200。](https://raw.githubusercontent.com/MikeHsu0618/2026-ithelp-agent-governance-public/day-11-r1/assets/screenshots/day-24/agentgateway-cost-fallback-dashboard.png)

畫面上的 `USD 0.00012975` 是兩筆成功 Responses 的合計，其中包含一筆獨立的 Primary Calibration，加上 Fallback Action 最後的 Backup Attempt。它能驗證兩種 Provider 格式都被 agentgateway 正確計價，卻不是某一個 Fallback Action 的價格。這也是自訂 Dashboard 必須保留 Action／Attempt 層級，而不是只畫另一張 Total Cost Stat 的原因。

完整實驗可用一條入口命令重跑：

```bash
make lab-04-cost-run
```

Runner 會檢查 1／1／2 Attempts、Primary → Backup 順序、Gateway Traces、原生 Token／Cost Metrics 與 Action Logs。啟動、清理、Query 與 Machine-readable Evidence 留在 Lab README，不在正文重播完整驗收包。

## 上線前的成本責任

官方 Analytics 已經解決大部分「目前花多少」的視覺化工作，平台團隊不需要從零維護另一套外觀相似的 Dashboard。真正需要自行負責的是數字的語意。

Price Catalog 要有版本與生效時間，Unpriced Models 和 Missing Usage 必須在報表上可見。Retry Owner、最大次數、Timeout Budget 與 Idempotency 也要寫進 Runtime Contract，尤其 Tool Call 可能產生副作用時，重送不只增加費用，還可能把動作執行兩次。月底 Chargeback 則必須再對 Provider Billing Export，Gateway Estimate 適合即時告警與 Team 趨勢，不能直接當成財務付款依據。

這篇最後留下的不是一個更漂亮的 Total，而是一條可追溯的成本鏈：Client 要求哪個 Model、Gateway 實際送出幾次 Attempts、哪個 Provider／Model 最後服務、哪些 Responses 有 Usage、哪些金額只是 Catalog Estimate，以及哪些缺口仍要等待帳單補齊。

Day 25 會把方向轉過來。前幾篇讓 LGTM 觀測 Agent 與 Gateway，下一篇則讓 Google ADK SRE Agent 經 agentgateway 與官方 Grafana MCP，真的去查 Loki。屆時要處理的不再只是成本，而是 Agent 如何分辨 Tool Call 成功、合法空結果與後端查詢失敗。
