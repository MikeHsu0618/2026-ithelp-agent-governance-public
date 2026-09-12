# Lab 04 — Agent Traceability Pipeline

> 狀態：Day 20 field-contract slice 已完成。Day 21 才會加入多個 producer 與五種固定情境。

這個 Lab 沿用 Day 1 的安全 Tool 名稱 `delete_demo_database`，但不再測模型會不會選到它。Day 1 已經用 Google ADK 與 Gemini live run 證明這件事。Day 20 固定執行一筆 no-op canary，觀察同一個 `action_id` 在三種資料裡各自留下什麼：

- application record：產品介面需要的 session、generation 與 Tool 摘要；
- operational trace：服務執行順序、延遲、錯誤與 trace context；
- governance event：principal、delegation、Artifact、policy、approval 與 effect evidence。

`Governed Action Field Set v0.1` 是本系列的作者定義，不是 OpenTelemetry 標準。OpenTelemetry GenAI Agent semantic conventions 目前仍是 Development；本 Lab 只在適合的 span 上使用 `gen_ai.*` 欄位，自訂治理欄位一律加上 `ithelp.governance.*` prefix。

## Commands

從 repo root 執行：

```bash
make lab-04-up
make lab-04-check
make lab-04-run
make lab-04-negative
make lab-04-down
```

要把其中一筆 run 整理成可公開 evidence，可執行：

```bash
uv run traceability-lab package-evidence \
  --artifact-dir artifacts/<run-id> \
  --backend-report .runtime/backend-report.json \
  --destination ../../assets/screenshots/day-20/evidence
```

這個命令會移除 manifest 裡的本機 `artifact_dir`，並一併輸出 backend correlation 與負向 schema 測試結果。

只測本機資料契約，不啟動 container：

```bash
uv run --directory labs/04-telemetry-pipeline \
  traceability-lab run \
  --artifact-root labs/04-telemetry-pipeline/artifacts
```

## Safe failure mode

`delete_demo_database` 不連資料庫、shell、Kubernetes 或外部 API。Tool 只回傳 `CANARY_TRIGGERED` receipt，`side_effects` 固定為 `0`。負向測試會移除 `policy.version`，確認 governance event 在送入 backend 前被 schema 擋下。

## Evidence

每次執行建立獨立目錄：

```text
artifacts/<run-id>/manifest.json
artifacts/<run-id>/application-record.json
artifacts/<run-id>/operational-trace.json
artifacts/<run-id>/governance-event.json
artifacts/<run-id>/tool-receipt.json
```

這些檔案只含合成 principal／resource，不保存 raw prompt、email、JWT、API key 或 Tool output content。`cleanup` 只移除帶有 Lab 04 marker 的 `artifacts/`。
