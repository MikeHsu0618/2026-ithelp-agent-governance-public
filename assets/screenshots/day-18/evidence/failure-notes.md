# Day 18 失敗重現摘要

## 唯讀 Root Filesystem 缺少可寫的暫存目錄

第一版 BYO Deployment 已設定 `readOnlyRootFilesystem: true`，但沒有掛載可寫的 `/tmp`。`kagent-adk` 啟動時建立暫存檔，Pod 因而在啟動階段退出：

```text
FileNotFoundError: No usable temporary directory found in ['/tmp', '/var/tmp', '/usr/tmp', '/app']
```

修正方式是保留唯讀 root filesystem，另外掛載受限為 `64Mi` 的 `emptyDir` 到 `/tmp`，並設定 `TMPDIR=/tmp`。修正後 BYO Agent Ready，五項驗收全部通過。

## Agent-as-Tool 找得到 proxy，找不到 BYO Agent

Declarative parent 產生的 remote Agent 設定把 URL 指向 agentgateway proxy，並附上：

```text
x-kagent-host: day18-byo.day18-lab
```

第一版沒有建立對應的 `HTTPRoute`，所以 parent 讀取 proxy 根目錄的 Agent Card 時得到 `404`。加入以 `x-kagent-host` 與 `/` 為 match 的 route，再導向 `AgentgatewayBackend.spec.a2a` 後，Agent Card、`input-required` 與 completed task 都出現在同一條 Gateway route。

此檔只保存合成 namespace、service 與錯誤摘要。Pod IP、時間戳、task／context UUID 與 request duration 沒有公開。
