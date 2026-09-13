# Day 21 圖像與資料 Evidence

測試日期：2026-09-12（Asia/Taipei）

環境：macOS 本機 Docker、agentgateway `1.5.0`、Grafana Alloy `1.18.1`、`grafana/otel-lgtm` `0.29.0`。Container images 與 Python base image 均以 digest 固定。OTEL-LGTM 在本次 Lab 提供 Grafana、Tempo、Loki、Prometheus 與 OpenTelemetry Collector。

## 實際執行

```bash
make lab-04-up
make lab-04-check
make lab-04-run
make lab-04-broken-trace
```

正常 run ID 是 `day21-e4de675e6747`。五種情境的 HTTP 結果、Tempo service 集合、Loki action event 與 Prometheus agentgateway metrics 全部通過 verifier，去除本機路徑後的結果保存在 `evidence/`。

負向 run ID 是 `day21-4d43a5b0706d`。它只在 normal call 的 Runtime -> MCP request 拿掉 Trace Context。HTTP 與 Tool receipt 維持成功，backend verifier 則正確回報 `mcp-adapter` 缺失與 `overall=FAIL`。

發稿前另做一次 `--build --force-recreate` 的乾淨重建驗收，並補上 backend 啟動期間的重試。正常 run `day21-52c3b00468f6` 維持五種情境全部通過，負向 run `day21-aea9f4be0630` 也只在 normal call 回報缺少 `mcp-adapter`。本文圖片仍保留上面兩筆原始 run，因為畫面中的 topology、查詢與輸出欄位沒有改動；最後重建用來確認讀者從乾淨容器啟動時能得到相同結論。

## `tempo-cross-service-trace.png`

Grafana Explore 直接查詢正常 run 的 trace `ec7a1fbe3e67b7742704664a72ec0d69`。畫面顯示 4 個 services、8 個 spans，依序包含 Lab Client、第一段 agentgateway、Agent Runtime、第二段 agentgateway 與 MCP adapter。

PNG 1600 × 1000，SHA-256：`1163d57b8460d1d13adf5ce2b14fde484f2eb93b5d37ee9bb15474737cf984e2`。

## `tempo-broken-context.png`

Grafana Explore 查詢負向 run 的 trace `638acf9b07a0f5a994649e7d27281dc2`。原 Trace 只剩 3 個 services、5 個 spans；MCP Tool 的執行 span 落到另一個 Trace，因此畫面與 verifier 都找不到 `mcp-adapter`。

PNG 1600 × 1000，SHA-256：`fea220e9f19bd48f123de23b549405b3cd8ef2594493670beaab97396abc07a3`。

## `loki-action-events.png`

Grafana Explore 使用以下 LogQL 查詢正常 run 的 action `act-normal-call-141052bb`：

```logql
{service_name=~"agentgateway|agent-runtime|mcp-adapter|ithelp-lab-client"}
  |= "act-normal-call-141052bb"
```

畫面顯示 4 筆結構化事件，來自 Lab Client、Agent Runtime 與 MCP adapter。agentgateway access log 沒有從 request body 自動取得 action ID，因此不在這個 action query 裡。

PNG 1600 × 1000，SHA-256：`e8415eba749660f86ac9187b7338492a6931e2855fa1ff5ac7bf7af2f6fc2c01`。

## `prometheus-agentgateway-metrics.png`

Grafana Explore 使用本機 Prometheus 執行：

```promql
sum by (route, status, reason) (agentgateway_requests_total)
```

畫面顯示正常 Runtime／MCP `200`、Gateway Authorization `403`、不存在 A2A backend 的 `503`，以及 Runtime 向上游回傳的 `502`。數值包含同一次撰稿期間重跑的三組 fixture，不作 production 流量或 SLO 解讀。

PNG 1600 × 1000，SHA-256：`077846df92688da1b4e3db86d87f40fe3d50e210a6f06c0070ce72a113d2b8ae`。

## `telemetry-pipeline.png`

依實際 Compose topology 與驗證過的 Alloy／agentgateway 設定重畫。箭頭先於卡片繪製，流量與 telemetry 使用不同路徑，不靠顏色名稱傳達唯一語意。

PNG 1600 × 900，SHA-256：`79f6b79e31bd964d63887e028088b3c0b48187d81f31f1b050b6ea5053995e98`。

完成檢查後使用：

```bash
make lab-04-down
```

這個命令只移除 Lab 04 的 Compose resources、volumes，以及帶有 Lab marker 的 `artifacts/`。
