# Day 16｜kagent、agentgateway 與 Application Team 責任矩陣

這份矩陣不是產品功能比較。每一列只保留一個主要 owner 與一份 source of truth，避免 kagent CR、生成的 runtime config 和 agentgateway route 同時修改同一項行為。

| Responsibility | Primary owner | kagent | agentgateway | Application／Identity team | Source of truth | 驗收方式 |
| --- | --- | --- | --- | --- | --- | --- |
| Agent business logic | Application Team | 提供 declarative runtime 或部署 BYO image | 不執行 Agent 邏輯 | 實作 prompt、loop、memory、workflow、HITL state | Agent source、runtime config、runtime tests | 固定 task fixture 驗證 Tool 選擇、state transition 與 side effect |
| Agent deployment | kagent | 從 `Agent` CR 產生 Deployment、Service、Secret／Config | 不建立 Agent workload | 提供 image、resource 與 runtime contract | `Agent` CR、generated Deployment | `Accepted=True`、`Ready=True`，generated spec 與期望相同 |
| Agent discovery | kagent | 產生 Agent Card，提供 UI／CLI／A2A discovery | 可代理 A2A traffic，不擁有 Agent metadata | 維護描述、skills、版本與 provider metadata | `Agent` status、Agent Card | 從 cluster 與 Gateway 兩條路讀取 Agent Card，欄位一致 |
| LLM traffic policy | agentgateway | `ModelConfig` 只保存 Agent 要打的 base URL 與 model contract | routing、caller policy、backend credential、rate limit、traffic telemetry | 定義 model 需求與 fallback 語意 | Gateway route／policy | Gateway log 命中預期 route；無 credential 與錯 policy case fail closed |
| MCP endpoint discovery | kagent | `RemoteMCPServer` 保存原始 endpoint、protocol 與 tool discovery | 不擁有 kagent resource status | 維護 MCP Service 與 tool contract | `RemoteMCPServer` spec／status | `Accepted=True`，discovered tool name 與 fixture 相符 |
| MCP traffic policy | agentgateway | `proxy.url` 讓 internal URL 進入共同 proxy | route、auth、Tool policy、rate limit、traffic telemetry | 定義哪些 runtime／principal 可以呼叫哪些 Tool | Gateway route／policy | generated runtime URL 指向 Gateway，`x-kagent-host` 保留原始目的地 |
| Credential acquisition／refresh | Identity Platform／Application Team | `headersFrom` 可讀 Secret／ConfigMap；不等於完整 token lifecycle | 驗 credential、交換或注入 backend credential；不創造上游身分生命週期 | 發行、更新、撤銷短效 credential，處理 refresh failure | workload identity、STS／IdP policy、rotation runbook | token 過期、撤銷、refresh failure、restart 與 offboarding 演練 |
| Runtime telemetry | kagent／Application Team | 提供 controller／runtime telemetry 接點 | 不知道 Agent 內部為何選 Tool | 產生 action、workflow、memory 與 HITL event | runtime span／event schema | 同一 task 能重建 model decision、Tool Call、approval 與 effect |
| Traffic telemetry | agentgateway | 提供 Agent／Tool metadata 作為 context | 保存 route、policy、backend、latency、status 與 token usage | 定義 correlation 與 retention requirement | Gateway access log、metric、trace | LLM／MCP／A2A route 可由同一 correlation context 查回 |

## 本次 Lab 的 source-of-truth 對照

| 資料 | 儲存位置 | 誰讀取 | 本次觀察 |
| --- | --- | --- | --- |
| Agent runtime 與 tool reference | `Agent/day16-agent` | kagent controller | 產生 Go runtime Deployment、Service 與 config Secret |
| LLM base URL／reasoning effort | `ModelConfig/day16-model` | kagent controller／Agent runtime | runtime config 保留 Gateway `/v1` 與 `reasoning_effort=low` |
| MCP 原始 endpoint／header reference | `RemoteMCPServer/day16-tools` | kagent controller／Agent runtime | status 發現 14 個 tools；runtime header 值來自 Secret |
| Internal proxy endpoint | kagent Helm `proxy.url` | kagent controller | runtime MCP URL 改寫成 agentgateway，加入 `x-kagent-host` |
| LLM／MCP forwarding | `HTTPRoute` | agentgateway control／data plane | access log 命中 `synthetic-llm` 與 `mcp-everything` route |

`headersFrom` 這一列刻意不標成完整 PASS。它證明 Secret value 能進入 request header，沒有證明 Token 能自動取得、refresh、撤銷或在 runtime restart 後安全復原。
