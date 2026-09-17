# Day 26 evidence

- `day01-replay.json`：從鎖定的 Day 1 live Artifact 重建 `delete_demo_database` action。
- `day03-policy-control.json`：從獨立的 Day 3 policy-denied Artifact 重建 control case。
- `modern-reference.json`：2026-09-17 另跑一筆現行 `normal-call`，查詢本機 Tempo、Loki 與 Prometheus。

三份檔案不是同一個 run，也不能合併成同一場事故。Day 1／3 的 repository lock 只能驗證 Day 26 收錄的副本，沒有 event-time signature、WORM storage 或 retention guarantee。
