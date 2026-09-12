# Day 20 圖像與資料 Evidence

測試日期：2026-09-12（Asia/Taipei）

環境：macOS 本機 Docker、Grafana Alloy `1.18.1`、`grafana/otel-lgtm` `0.29.0`。OTEL-LGTM 內含 Grafana `13.1.0`、Loki `3.7.3`、Tempo `3.0.2`、Prometheus `3.13.1` 與 OpenTelemetry Collector `0.156.0`。兩個 image 都以 digest pin 住。

## 實際執行

```bash
make lab-04-up
make lab-04-check
make lab-04-run
make lab-04-negative
```

本次選用的 run ID 是 `day20-a669406b17ca`，action ID 是 `act-day20-a669406b17ca`，trace ID 是 `8e5bb2f2e7cd96e9f5fd0fd4fa30aebb`。`backend-report.json` 記錄 Tempo trace、Loki governance event 與兩者關聯均為 `PASS`。

`evidence/` 由 Lab 的 `package-evidence` 命令從真實 run artifact 產生。Manifest 已移除本機 `artifact_dir`，其餘 JSON 使用合成 principal、resource 與 digest，沒有 API key、JWT、email、raw prompt 或 Tool output。

## `tempo-agent-tool-trace.png`

Grafana Explore 直接查詢本次 trace ID 後擷取。畫面顯示 `invoke_agent sre-investigation-agent` 與其 child span `execute_tool delete_demo_database`，不是手工繪製的 waterfall。

PNG SHA-256：`4b564a720b46112796de3a4a6a495a89fc8668071427774a1b85d6aa0f039cad`。

## `claude-code-stats-overview.png`

作者實際操作 [`grafana-claudestats-app`](https://github.com/MikeHsu0618/grafana-claudestats-app) 的 Overview 畫面，使用測試帳號、測試用量與測試成本。圖中資料可公開，因此保留原始 Dashboard，不另外生成或改寫數字。

PNG SHA-256：`db646e732562ab08d1bdb6dc7075d2297d215687c46945aa5ade80d065644ee3`。

## `claude-code-stats-activity.png`

同一套 Grafana app 的 Activity 畫面，顯示 Code Lines Touched、Commit、Pull Request 與 Claude Active Time。這張圖用來說明 code agent 的操作脈絡已超過 Token／Latency，不把這些指標直接解讀為工程師績效。

PNG SHA-256：`e8b42b060b206f5f33aefb3eae6fe2d5b90f33500522c152f567d4b1e9683fe2`。

## `loki-governance-event.png`

Grafana Explore 以相同 trace ID 查詢 Loki。公開畫面使用 LogQL `drop` 移除 SDK 自動附加的 `code_file_path`、`code_function_name` 與 `code_line_number`，保留原始治理事件內容、`action_id`、policy、principal、delegation 與 correlation。這項處理只影響查詢結果的 labels，不會修改 Loki 裡的原始 event。

PNG SHA-256：`49263c2bd79461f609f2b960c9a93fa6f135717517248ab7bea45377f3f02b69`。

## `traceability-data-boundary.png`

依本次三份輸出 `application-record.json`、`operational-trace.json` 與 `governance-event.json` 繪製。它用來解釋三種資料的責任，不冒充 Grafana 實拍。

PNG SHA-256：`41030e75782bbebee3c635827ece4f3dee56bae672b0109c0776d58f3ac04862`。

## 負向測試

`negative-report.json` 來自 `make lab-04-negative` 使用的同一段驗證程式。測試刻意拿掉 `policy.version`，schema 以 `REJECTED` 拒絕事件。這證明欄位契約不是文章裡列好看的建議清單。

完成檢查後，使用下列命令關閉只屬於 Lab 04 的 containers 與 volumes：

```bash
make lab-04-down
```
