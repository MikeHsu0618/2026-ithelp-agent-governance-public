# Lab 05 — Agent Incident Replay

這個 Lab 重建兩種不同年代的 Agent 證據，但不會把它們假裝成同一場事故：

- Day 1 的 Google ADK live run：只有本機 JSONL、manifest 與 no-op canary receipt。
- Day 3 的 policy-denied run：用來證明 `DENY` 之後沒有 Tool effect 是合理結果。
- 現行 LGTM run：另跑一筆 `normal-call`，用 `trace_id` 查 Tempo、用 `action_id` 查 Loki。Prometheus 只提供 aggregate evidence。

歷史案例中的檔案源自作者 repo 的 Day 1、Day 3 實測素材。`evidence-lock.json` 會驗證這份 Lab 複本目前仍符合 SHA-256，但它不是事件發生當下的簽章、WORM storage 或 retention guarantee。

## 快速執行

在 repo 根目錄執行：

```bash
make -f publication/Makefile.public lab-05-check
make -f publication/Makefile.public lab-05-up
make -f publication/Makefile.public lab-05-run
```

三份結果會寫入 `labs/05-incident-replay/.runtime/`：

```text
day01-replay.json
day03-policy-control.json
modern-reference.json
```

Tempo 可能先回傳尚未收齊的 trace。`modern-reference.json` 會依 scenario 的 `expected_services` 重試查詢，並列出 `complete` 與 `missing_services`，避免把只有部分 spans 的第一個回應誤當成完整證據。

完成後關閉共用的 LGTM stack：

```bash
make -f publication/Makefile.public lab-05-down
```

## 單獨重建歷史案例

```bash
uv run --directory labs/05-incident-replay incident-replay historical \
  --case-dir labs/05-incident-replay/cases/day01-canary \
  --target-tool delete_demo_database \
  --output labs/05-incident-replay/.runtime/day01-replay.json
```

輸出欄位只接受四種證據狀態：

- `VERIFIED`：工具在這次 replay 能重新驗證，例如 repository lock。
- `OBSERVED`：原始 Artifact 有記錄，但沒有額外的獨立證明。
- `UNKNOWN`：資料不足，不能從空白推論成安全或不安全。
- `NOT_APPLICABLE`：例如 policy 已拒絕 Tool，effect receipt 本來就不應該存在。

Replay 也不會因為 Tool 名稱相同，就把不同動作的事件硬湊在一起。若同一個 Tool 在一條 trace 裡出現多次，卻缺少可唯一對應的 span，Lab 會直接拒絕重建；trace、span、resource、事件順序或 DENY outcome 互相矛盾時也一樣。

## 安全範圍

歷史 Tool 名稱雖然是 `delete_demo_database`，實作只會留下 no-op canary event，不會連線資料庫、執行 shell 或操作 Kubernetes。Backend 查詢也只接受 loopback HTTP origin，避免把任意 URL 當成 replay target。
