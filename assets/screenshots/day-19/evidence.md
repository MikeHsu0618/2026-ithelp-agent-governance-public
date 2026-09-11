# Day 19 圖像 Evidence

測試日期：2026-09-10（Asia/Taipei）

環境：disposable kind／Kubernetes `1.34.0`、kind `0.30.0`、Agent Registry `0.4.0`、kagent `0.10.1`。Lab 沒有使用外部 LLM API key，也沒有加入 Argo CD、agentgateway 或 production credential。Agent Registry chart 的 bundled PostgreSQL 只供這次 dev／eval Lab 使用。

## 實際執行

```bash
make lab-03-runtime-registry-up
make lab-03-runtime-registry-run
```

原始 terminal output 位於 `evidence/terminal.txt`，結構化結果位於 `evidence/registry-boundary-report.json`。Registry Agent 與第一次完成 reconciliation 的 Deployment status 分別保存為 redacted JSON，已移除 row UID、resource version、credential、token 與 cluster 連線資料。

兩個本機 image tag 指向同一份測試 image。這次實驗驗證的是同一個 `approved` catalog tag 能改變 desired image reference，而且 controller 會把 reference 更新到 kagent；它沒有證明兩份 image bytes 不同，也沒有把這項結果包裝成 Artifact signature 測試。

## `01-agent-registry-catalog.png`

以瀏覽器連到 Lab cluster 的 Agent Registry UI 擷取。畫面顯示 `day19byo` 與 `approved` tag，描述為同一個 catalog tag 已換成另一個 image reference。

PNG SHA-256：`d96dd644b5b6634a4ceba1b6a2707b0a749f202c77f4ef6f60655e2bac23d62e`。

## `02-agent-registry-deployed.png`

在 apply `desiredState: undeployed` 並確認 kagent Agent 已移除後擷取。Deployed 頁面顯示 `0 resources running`，同時保留 `day19byo` 的 deployment record；此畫面只說明 catalog／record 與 runtime resource lifecycle 可以分開觀察。

PNG SHA-256：`8733d255e412e0aace311818701d42e8bb8b1dc5fa786152cdd0b142cb127f5b`。

## `03-agent-registry-boundary-results.png`

依 `make lab-03-runtime-registry-run` 的實際輸出在 Carbon 排版。圖片只為改善閱讀，沒有冒充 macOS terminal，且正文與 `evidence/terminal.txt` 都保留可複製文字。

PNG SHA-256：`b710a112fb01cb8b95f3ae2086fa302439889a2ebc30932d6b0e02d81a7b5c62`。

完成檢查後使用下列命令刪除 Lab 自己建立的 cluster：

```bash
make lab-03-runtime-registry-down
```
