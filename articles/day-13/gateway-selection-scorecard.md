# AI Gateway 平台選型 Scorecard

版本：2026-08-23

這份表不是產品排行榜。先固定 workload、部署模式與治理責任，再填產品能力；換一個前提，答案就可能不同。

## 本次 Context

- 執行環境：Kubernetes。
- 流量：LLM、MCP，後續包含 A2A。
- 交付方式：declarative config、IaC、Git review、GitOps reconciliation。
- 身分：Human 與 M2M 分流；企業 IdP／Cognito 負責發 Token，Gateway 驗證已簽發 Token 並執行 policy。
- 平台責任：routing、policy、telemetry、upgrade、rollback、on-call 與供應鏈審查。
- LiteLLM 評估基準：作者當時的 `1.80.x` Kubernetes snapshot。
- agentgateway 評估基準：作者實際採用前後的 `1.3.x` Kubernetes snapshot。
- 現況校對：LiteLLM `v1.98.0`、agentgateway `v1.4.1` 官方文件；只用來提醒能力已漂移，不重寫原始決策。

## Evidence 標籤

| 標籤 | 意義 |
| --- | --- |
| `PRIVATE PASS` | 作者有去識別化的 Kubernetes 操作紀錄，原始環境不公開 |
| `SNAPSHOT` | 從當時實際 chart／config 盤點所得，未冒充現行版本 |
| `DOCS ONLY` | 官方文件宣告，本文沒有親自重跑 |
| `AUTHOR JUDGMENT` | 根據需求與責任做出的架構判斷，不冒充產品事實 |
| `UNKNOWN` | 沒有足夠證據，不用推測補格 |

## 當時的選型表

| 決策面 | 平台要回答的問題 | LiteLLM `1.80.x` snapshot | agentgateway `1.3.x` snapshot | 仍在產品外的責任 | Evidence |
| --- | --- | --- | --- | --- | --- |
| LLM provider routing | 能否統一模型介面、做 routing、fallback、retry 與 provider translation？ | 強項，也是進候選的主要理由 | 能代理 LLM，但當時不是靠豐富管理 UI 取勝 | Provider quota、model lifecycle、fallback policy owner | `SNAPSHOT` + `PRIVATE PASS` |
| 使用量與 budget | 能否按 consumer／team 追 usage、budget 與 rate limit？ | Virtual key、team、budget 與 spend 是完整主線 | 可在 Gateway policy／telemetry 邊界處理 consumer traffic；當時管理體驗不同 | FinOps 歸屬、價格表、chargeback 與例外流程 | `SNAPSHOT` + `PRIVATE PASS` |
| Human identity | Key 的 owner 是否等於企業 Human？離職與轉調從哪裡撤權？ | Virtual key 仍需維護 Human → key／team mapping | 可驗企業 IdP JWT 並依 claim 做 policy；不負責人員 lifecycle | IdP、joiner／mover／leaver、claim contract | `AUTHOR JUDGMENT` + `PRIVATE PASS` |
| MCP／A2A traffic | 是否能辨識 protocol semantic，並在共同入口套 policy／telemetry？ | 當時 snapshot 已可配置 MCP，但不是本次選型最成熟的治理路徑 | LLM、MCP、A2A 是同一 data-plane 邊界的核心方向 | Tool／Agent owner、runtime、approval 與 downstream auth | `SNAPSHOT` + `PRIVATE PASS` |
| Discovery／registration | MCP client 怎麼找到 authorization metadata，又怎麼註冊？ | 不能因 Gateway 有 auth 就假設完成 | Resource Server Only 同樣不會自動完成 Cognito discovery／registration | Pre-registration、CIMD／legacy DCR、IdP adapter | `AUTHOR JUDGMENT` |
| Declarative delivery | Team、user、route、policy 能否由 Git 宣告、review、diff、reconcile？ | 模型設定可宣告；team／user 管理在當時另以 API + Terraform 膠水補齊 | Kubernetes Gateway API／CRD 與 controller 更貼近既有 GitOps 路徑 | CRD lifecycle、schema upgrade、drift 與 rollback | `SNAPSHOT` + `PRIVATE PASS` |
| Runtime dependencies | 高可用部署需要哪些 state、cache、migration 與 recovery？ | 當時方案包含 Proxy、PostgreSQL、Redis、migration 與 UI state | controller + data plane；仍須處理 CRD、xDS、rollout 與 data-plane capacity | Backup、SLO、capacity、upgrade、disaster recovery | `SNAPSHOT` + `DOCS ONLY` |
| Policy enforcement | Policy 能否緊貼已驗證 principal、protocol action 與 target resource？ | 有 auth hook、key/team limit 與多種 guardrail surface | JWT、MCP tool、LLM／A2A traffic policy 更符合本次 enforcement boundary | Policy authoring、exception、review、evidence retention | `PRIVATE PASS` + `DOCS ONLY` |
| Audit 與 telemetry | 能否回答誰、代表誰、透過哪個 workload、呼叫哪個 target？ | Spend／request log 很實用；完整 delegation 仍要額外 context | Gateway 是穩定 observation point；完整 actor chain 仍須 runtime 傳遞 | Delegation Context、PII、retention、LGTM／SIEM | `AUTHOR JUDGMENT` + `PRIVATE PASS` |
| Supply-chain trust | Artifact 如何驗證、依賴怎麼盤、事故後如何重建信任？ | 當時尚未發生 2026-03 事件；不能列作原始淘汰理由 | 同樣必須 pin image、驗 signature、追 advisory | SBOM、signature policy、dependency audit、patch SLA | 原始決策 `NOT APPLICABLE`；現況 `DOCS ONLY` |

## 本次 Decision

選 agentgateway 作為 LLM、MCP、A2A runtime traffic 的共同治理執行點。Identity provider、client registration、Agent runtime、Tool ownership、delegation context 與 telemetry backend 仍各有 owner，不塞進 Gateway 產品名稱裡。

這個決策不是「LiteLLM 功能不足」。LiteLLM 對快速統一模型 provider、routing、virtual key、budget 與 UI 的需求很有吸引力；只是本次平台最重的權重落在 Kubernetes reconciliation、identity-aware policy、跨 protocol traffic boundary 與既有 GitOps operating model。

## 2026-08 現況校對

| 項目 | 目前能安全說的話 | 不能延伸成什麼 |
| --- | --- | --- |
| LiteLLM `v1.98.0` | 現行官方架構仍以 virtual key／budget check、PostgreSQL、Redis、Router 與 provider translation 為主，也已有 MCP 等更廣的能力 | 不能拿當年 UI／MCP snapshot 代表現在 |
| agentgateway `v1.4.1` | Kubernetes 模式有 controller／xDS control plane 與代理 LLM、MCP、A2A 的 data plane | 不能宣稱所有 IdP discovery、registration、runtime 或 HITL 都由 Gateway 處理 |
| LiteLLM 2026-03 事件 | 官方 issue 指出 PyPI `1.82.7`、`1.82.8` 遭植入惡意程式；維護團隊移除套件、輪替帳號並重整供應鏈 | 不能說所有版本都受影響，也不能倒寫成當初選型理由 |
| Security WG | Supply-chain hardening 已標 Done，dependency audit 在查證日仍列 TODO | 不能宣布風險已經根治 |
| LiteLLM Rust staging | README 描述 minimal Axum gateway；Realtime hot path 用 Rust，啟動設定與 request log 仍銜接 Python proxy | 不能寫成 LiteLLM 已完成 Rust 重寫或已證明比現行 proxy 更安全／更快 |

## 空白模板

Context：

- Workload／protocol：
- 部署模式：
- Identity source：
- 交付方式：
- Policy owner：
- Telemetry backend：
- Upgrade／on-call owner：
- 比較版本與日期：

| 決策面 | 必要條件 | 方案 A | 方案 B | 產品外 owner | Evidence | Revisit trigger |
| --- | --- | --- | --- | --- | --- | --- |
| Provider routing |  |  |  |  |  |  |
| Consumer／budget |  |  |  |  |  |  |
| Human／workload identity |  |  |  |  |  |  |
| Protocol coverage |  |  |  |  |  |  |
| Discovery／registration |  |  |  |  |  |  |
| Declarative delivery |  |  |  |  |  |  |
| Runtime dependencies |  |  |  |  |  |  |
| Policy enforcement |  |  |  |  |  |  |
| Audit／telemetry |  |  |  |  |  |  |
| Supply-chain trust |  |  |  |  |  |  |

最後再寫 Decision、付出的代價與 revisit triggers。不要先替喜歡的產品加權，再把表格補成答案。
