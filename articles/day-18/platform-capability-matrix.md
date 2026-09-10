# BYO Agent 平台能力驗收表

測試版本：kagent `0.10.1`、agentgateway `1.5.0`，2026-09-10。

| 能力 | 結果 | 本次證據 | 邊界／Owner |
| --- | --- | --- | --- |
| BYO Deployment／Service／ServiceAccount wiring | `PASS` | `Agent` Ready，產生的 Deployment 與 Service 可用，並採用指定 SA | kagent 接手 workload lifecycle；image 與 SA baseline 仍由 Application Team 維護 |
| Agent Card／Dashboard discovery | `PASS` | Agent Card `200`，kagent UI 顯示 BYO 與 parent | 能找到 Agent，不代表 Runtime semantics 已符合平台規範 |
| 同 namespace Agent-as-Tool | `PASS` | declarative parent 成功呼叫 BYO Agent | 需有通往 BYO A2A endpoint 的 agentgateway route |
| 跨 namespace reference | `NOT_TESTED` | 本次兩個 Agent 都在 `day18-lab` | `allowedNamespaces` 的政策與負向案例留待平台採用測試 |
| HITL approve／reject／resume | `PASS` | 兩條路徑都從 `input-required` 走到 `completed`；Reject 未執行 Tool | BYO 以 `kagent-adk` 實作 approval callback；`requireApproval` 沒有自動注入 BYO Tool |
| Synthetic actor propagation | `PASS` | Tool receipt 保留 `actor=sre-oncaller` | Lab 的 `x-user-id` 是合成 header；正式環境仍須先由 authentication boundary 驗證 |
| Gateway A2A telemetry | `PASS` | route、`message/send`、outcome、task state 與 context 出現在 access log | Gateway 看得到 traffic／task 外層，不知道 Tool 為何批准 |
| Pause／resume task continuity | `PASS` | Probe 逐一核對 approve 與 reject 前後的 task ID、context ID 與狀態 | 只證明本次 HITL continuation，不等於 approver authorization 或一般長期記憶 |
| Declarative `Memory` 能力 | `NOT_APPLICABLE` | BYO spec 沒有 declarative memory 欄位 | BYO Runtime 自己選擇並串接 memory／session store |
| `skills` 內容的執行語意 | `PARTIAL` | Agent Card 公告 skill；本次 Tool 可呼叫 | kagent 可以 materialize／公告 metadata，BYO code 仍要實際消費 |
| Kubernetes container hardening | `PASS` | non-root、drop capabilities、read-only root filesystem、受限 `/tmp`，三個 workload 都停用預設 SA token automount | 兩個 Agent 的 kagent 專用 projected token仍保留；這是 Pod baseline，不是每次 Tool execution 的 sandbox |
| Tool policy／argument authorization | `PARTIAL` | Tool 有 approval callback，Reject 能阻止 receipt | resource／argument 細粒度授權仍由 BYO Runtime 或外部 PEP 實作 |

`NOT_TESTED` 不等於產品不支援；`NOT_APPLICABLE` 代表該 declarative surface 不屬於 BYO spec。讀者在自己的環境驗收時，應把兩者分開。
