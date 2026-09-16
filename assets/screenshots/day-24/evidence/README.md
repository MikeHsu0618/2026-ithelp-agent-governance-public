# Day 24 evidence

Machine-readable evidence 與 Grafana extension 來自 2026-09-15 的乾淨 Lab run `day24-20260915T024138Z`。內建 Analytics 截圖取自重新啟用 request-log database 後的乾淨 run `day24-20260915T032852Z`，兩次執行的三個 scenario 結果相同。每次啟動前都移除舊 containers、volumes 與 telemetry data，runner 隨後送出流量，verifier 再查詢 Prometheus、Loki、Tempo 與 primary／backup provider receipts。

- `cost-fallback-run.json`：client 觀察到的 scenario 結果，已移除本機 artifact 絕對路徑；
- `backend-report.json`：backend correlation 與原生 agentgateway metric 驗收；
- `../agentgateway-official-analytics-dashboard.png`：agentgateway `1.5.0` 內建 Analytics 的 Provider／Requests 視圖，顯示 OpenAI 與 Anthropic 各一筆 request，以及 `USD 0.000066 / 10 tokens / 2 calls`；
- `../agentgateway-cost-fallback-dashboard.png`：同一輪資料的 Grafana focused extension 截圖。

所有 principal、API key metadata、model、provider 與 action ID 都是固定的公開 Lab fixture。Evidence 不包含 Authorization header、API key、prompt 內容、真實帳號或外部 Provider 帳單。
