# Agent Governance 四問 Checklist

這份表以「一個 action」為單位。不要一開始就評整個 AI 平台，先選一條真的會發生的路徑，例如：

```text
值班工程師 → SRE Agent → Runtime Workload → query_metrics → payments-demo
```

狀態沿用 repo 的證據規則：

- `PASS`：實際 request 與輸出符合這一列的明確 claim。
- `PARTIAL`：已有一部分 evidence，仍缺欄位、驗證或邊界。
- `DOCS ONLY`：目前只有官方文件或設計說明，尚未用實際 request 驗證。
- `UNKNOWN`：目前沒有足夠 evidence，不猜。
- `N/A`：經 review 確認此 action 不需要，並且已寫下原因。

## Day 1–4 快照

| 治理問題 | 現有 evidence | 狀態 | 還缺什麼 |
| --- | --- | --- | --- |
| Identity：誰在行動，又代表誰？ | ADK session 有 `synthetic-user-sre-oncaller`，Agent 名稱已知 | `PARTIAL` | Human 未驗證，executing workload、credential subject／audience 為 `UNKNOWN` |
| Provenance：這次用了哪個 Agent／Tool artifact，可信嗎？ | Source tree 能找到 Agent 與三個 Tool | `UNKNOWN` | decision event 沒有 version、digest、signer、approval 或 registry source |
| Enforcement：這次 action 可以執行嗎，誰拒絕？ | `before_tool_callback` 的 allowlist 實測 DENY，canary delta 0 | `PARTIAL` | policy 只看 Tool name，缺 principal、resource、environment 與 resource-side authorization |
| Traceability：實際發生什麼，能重建嗎？ | trace ID、ordered events、summary、replay command | `PARTIAL` | 缺 delegation、workload、artifact 與下游 decision，也尚未定義 audit retention／integrity |

## 空白 review 表

### 1. Identity

| 檢查 | Evidence／值 | 狀態 |
| --- | --- | --- |
| Human 或 service principal 經什麼機制驗證？ |  |  |
| Delegating Agent 如何被識別，名稱是否綁定版本？ |  |  |
| Executing workload 有沒有可驗證的 machine identity？ |  |  |
| Credential 的 issuer、subject、audience、expiry 是什麼？ |  |  |
| 代表誰行動的 delegation context 在哪裡保存？ |  |  |

### 2. Provenance

| 檢查 | Evidence／值 | 狀態 |
| --- | --- | --- |
| Agent 定義、model config、prompt 或 image 的確切版本是什麼？ |  |  |
| Tool／MCP Server 的 owner、版本與 digest 能否回查？ |  |  |
| Artifact 由誰建立、review、簽章或核准？ |  |  |
| Discovery／Registry 回傳的 metadata 是否被 policy 驗證？ |  |  |
| Artifact 變更後，既有 approval 是否仍有效？ |  |  |

### 3. Enforcement

| 檢查 | Evidence／值 | 狀態 |
| --- | --- | --- |
| Policy input 是否同時含 principal、action、resource 與 environment？ |  |  |
| 最早能獨立拒絕危險 action 的 enforcement point 在哪裡？ |  |  |
| Gateway `ALLOW` 後，resource server 是否仍做自己的 authorization？ |  |  |
| 高風險 action 需要 approval 嗎？缺席時預設是 DENY 嗎？ |  |  |
| Policy reason、version 與 decision input 是否一起保存？ |  |  |

### 4. Traceability

| 檢查 | Evidence／值 | 狀態 |
| --- | --- | --- |
| Model proposal、policy decision、Tool execution、outcome 能否按順序重建？ |  |  |
| 同一個 trace／request key 能否跨 Agent、Gateway、Tool 與 resource？ |  |  |
| Summary 是否可能被後續 `SUCCESS` 覆寫高嚴重度事件？ |  |  |
| Telemetry 與 Audit 各保存哪些欄位，誰能修改？ |  |  |
| Retention、redaction、查詢權限與事件完整性由誰負責？ |  |  |

## Review 結果

| Action | Identity | Provenance | Enforcement | Traceability | 下一個要補的最小缺口 | Owner |
| --- | --- | --- | --- | --- | --- | --- |
|  |  |  |  |  |  |  |

最後一欄只填一個最小缺口。四問的用途是找出下一個設計工作，第一次 review 不需要把整個平台畫成全綠。
