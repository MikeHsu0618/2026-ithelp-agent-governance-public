# Day 22 圖像與資料 Evidence

測試日期：2026-09-14（Asia/Taipei）

環境：macOS 本機 Docker、Grafana Alloy `1.18.1`、`grafana/otel-lgtm` `0.29.0`、OpenTelemetry Python `1.43.0`。Container images 與 Python base image 均以 digest 固定。

## 實際執行

```bash
make lab-04-check
make lab-04-down
make lab-04-up
make lab-04-identity
```

最終 run ID 是 `day22-2127097bf665`，action ID 是 `act-day22-2127097bf665`，Trace ID 是 `048ba36aa482505b470109a416b6e083`。61 個 pytest 全數通過，branch coverage 為 85.98%。Docker Compose、agentgateway 與 Alloy config validation 也全部通過，Loki label-name API 另外確認 `principal_ref` 沒有進入 index labels。

## 實跑時發現的兩個資料外洩點

第一輪 run `day22-46a5e03802dc` 的 Tempo、Loki 與敏感欄位刪除皆通過，但 Prometheus 收到 `principal_ref` label，backend verifier 因此回報 `prometheus_bounded_labels=FAIL`。Alloy metric transform 補上 principal、user、session、conversation 與 action ID 的明確刪除後，清空 volume 重跑才轉為 PASS。失敗與成功報告都保存在 `evidence/`。

第一次拍 Loki 畫面時，OpenTelemetry logging 自動附帶 `code.file.path`，Grafana common fields 因而顯示作者本機絕對路徑。Alloy log transform 後續刪除 `code.file.path`、`code.function.name` 與 `code.line.number`，清空 volume 後重新產生所有截圖。兩張舊 debug image 已移到 macOS Trash，沒有列入 publishable assets。

## `tempo-identity-projection.png`

Grafana Explore 以 TraceQL 查詢：

```traceql
{ trace:id = "048ba36aa482505b470109a416b6e083" }
```

畫面展開 `identity.projection` span，顯示 `ithelp.governance.action_id`、`principal.assurance`、`principal.ref`、`principal.role`、`principal.team` 與 `principal.tenant`。Backend payload 不含 `user.email`、`auth.token` 或合成敏感值。

PNG 1600 × 1000，SHA-256：`8e9b60a7c33981f5a44eeb264f203a639e9a508ccdce95625f529784ba651593`。

## `loki-identity-structured-metadata.png`

Grafana Explore 使用以下 LogQL：

```logql
{service_name="identity-projection-lab"}
  | principal_ref = "prn_66103c4906ed52ad53b3"
```

`service_name` 負責選 stream，`principal_ref` 則以 pipe 後的 structured metadata filter 查詢。畫面與 backend payload 都不再出現本機 `code.file.path`、raw email 或 token。

PNG 1600 × 1000，SHA-256：`b2ff1337076d0e9066158db87b04db3045571f53315e81175321032ff45b7b7f`。

## `prometheus-bounded-labels.png`

Grafana Explore 執行：

```promql
sum by (team, route, outcome) (ithelp_agent_actions_total)
```

回傳的合成 action 只有 `team=platform-sre`、`route=agent-runtime` 與 `outcome=allowed`。Verifier 另外直接檢查原始 Prometheus API response，確認沒有 principal、user、session、conversation 或 action ID label。

PNG 1600 × 1000，SHA-256：`a787daf52b790c1a233550256694ba8947fc100ad7920202dc97e564650e665f`。

## `identity-data-placements.png`

依本次 Lab 的 verified context、destination allowlists 與 Alloy transform 重畫。箭頭先於卡片繪製，Raw Claims、Verification Boundary、Verified Principal Context 和四種資料面都有明確位置，不使用顏色作為唯一語意。

PNG 1600 × 900，SHA-256：`4632d111a328a2fdfa0f6e64d726db112c2b5ed6a316c71871aff786ef76766e`。
