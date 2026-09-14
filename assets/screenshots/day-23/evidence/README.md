# Day 23 evidence

本目錄保存 Day 23 的可公開 Lab 證據。數字來自 `agentgateway_requests_total` 與 Loki API；Tempo 則用本輪 request 的 `trace_id` 直接取回 Gateway span。無 Token 與錯誤 audience 也都由真實 Gateway 回傳 `401`。臨時 RSA private key、Authorization header 與 JWT 不會複製到這裡。
