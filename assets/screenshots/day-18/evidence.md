# Day 18 圖像 Evidence

測試日期：2026-09-10（Asia/Taipei）

環境：disposable kind／Kubernetes `1.34.0`、Gateway API `1.6.0`、kagent `0.10.1`、agentgateway `1.5.0`、Google ADK-based BYO Agent、synthetic OpenAI-compatible parent model。Lab 不使用外部 LLM API key，Tool 只回傳 action receipt，不碰 Kubernetes 或外部服務。

## `01-kagent-agents.png`

以 kagent UI 實際連到 Lab cluster 擷取。畫面顯示 `day18-lab/day18-byo` 與 `day18-lab/day18-parent`；前者由 BYO image 建立，後者為 declarative parent。Day 16 的既有 Agent 同時留在畫面，因為 Day 18 沿用同一個 disposable cluster。

原始狀態另存於 `evidence/agent-status.txt`。PNG SHA-256：`704d611440c8796e819405ce8b8e25374e72601f643677d138aa9c835ed2846d`。

## `02-byo-platform-results.png`

依 `make lab-03-runtime-byo-run` 的實際輸出排版，原始文字位於 `evidence/byo-platform-results.txt`。Approve 路徑必須回傳 `ACTION_EXECUTED resource=demo/cache actor=sre-oncaller`；Reject 路徑必須完成 task、回傳 `ACTION_SKIPPED`，且不能含有 `ACTION_EXECUTED`。

Gateway 的 redacted semantic log 位於 `evidence/gateway-a2a-log.redacted.txt`。檔案分別保留 approve 與 reject 兩條路徑，每條路徑的兩次 `message/send` 使用同一個 context，task state 也都由 `input-required` 走到 `completed`，合計四次 POST。

PNG SHA-256：`d75e9851f6bf2f434611f1dacf31e53e9e0103c5b7442b7603cb010626907e69`。

第一次執行發現的唯讀檔案系統與 Gateway route 問題記錄在 `evidence/failure-notes.md`。公開 evidence 沒有 credential、內部 hostname、真實人員資料、Pod IP 或 task／context UUID。

`evidence/pod-security.txt` 保存重建後的 ServiceAccount 與 volume 摘要。三個 workload 都沒有一般 `kube-api-access-*` volume；declarative parent 與 BYO Pod 只保留 controller 明確掛入、audience 為 `kagent` 的 projected token。檔案也記錄實際拉取的 `kagent-adk` manifest digest 與本機 image ID。
