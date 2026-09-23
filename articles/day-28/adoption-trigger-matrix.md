# Agent Governance Adoption Trigger Matrix

更新日期：2026-09-18

這份表格用 trigger 決定下一個控制，不用成熟度等級推動平台擴張。`合理停留點` 是可以被正式接受的架構，但仍要保留 owner、evidence 與 reopen trigger。

| Trigger／現況 | 先補的控制 | Current Source／候選 | Owner | 可延後項目 | 合理停留點 | Reopen Trigger／Evidence |
|---|---|---|---|---|---|---|
| 單一團隊、只讀 Agent | Human／M2M identity、bounded credential、Tool outcome、action／trace correlation | Cognito Human／M2M、Git-owned BYO Runtime、Alloy／LGTM | Identity／Platform + Application + SRE | 集中式 Gateway、kagent、Registry、額外的稽核儲存平台 | Git-owned BYO Runtime + LGTM | Tool 出現副作用、共享 traffic 或明確的法遵要求時重開；參考 Lab 01／02／04 |
| Tool 可以寫入、刪除、部署或批准 | Resource-aware allowlist／policy、pre-execution DENY、action ID、policy version、Artifact digest、effect receipt | Runtime callback／Resource Server；共享 boundary 出現後可用 agentgateway | Application + Platform／Security | 集中式 Agent control plane、Catalog UI | 單一 Runtime 的 callback + application authorization + Git review | 新增 Tool／resource／policy 或 failure mode 時重跑 allow／deny／replay；證據來自 Lab 01／03／05 |
| 多個 Runtime 重複處理 LLM／MCP／A2A 的 auth、route、credential、policy 或 telemetry，且設定開始漂移 | JWT／credential validation、route、retry／timeout、shared policy、telemetry | agentgateway | Platform／SRE + Application | kagent、Agent Registry、企業 Identity Center | BYO Runtime + Git + agentgateway + LGTM | Protocol、route、policy schema、consumer 或共同 checkpoint 的需求改變時重驗 Lab 03／04 |
| 跨 team／route 的 showback 或 chargeback 成為正式需求 | Validated caller／team mapping、pricing version、billable usage、Provider billing attribution、invoice reconciliation | agentgateway model catalog + LGTM；Provider billing path 待接 | Platform／FinOps + Model Consumer | 沒有正式分攤時，不建立 invoice-grade pipeline | Gateway per-request cost + 明列 `PARTIAL` gap | Provider、model、pricing、fallback／retry 或分攤規則改變時重驗；失敗 attempt 沒有 usage 時保留 `UNKNOWN` |
| Human／M2M access 已足夠，企業 lifecycle owner 未成立 | 維護 callback、scope、claim、client secret、Gateway policy 與 offboarding | Amazon Cognito User Pools | Identity／IT + Platform | AI 專用 Keycloak Identity Center | Managed identity bridge | 企業 joiner／mover／leaver、SaaS／下游整合範圍與 owner 同時成立時重評；使用實務 E2E + Lab 02 |
| 需要辨識實際 Pod／Runtime instance，或移除長效 secret | Workload attestation、bound credential、issuer／audience、rotation、Gateway mapping | 尚未選定；Kubernetes ServiceAccount／workload-bound Token／SPIFFE 類機制待評估 | 尚未指定；Platform + Security + Application | 在沒有需求與 live evidence 時先不宣稱支援 | `UNKNOWN` | Per-instance attribution、secretless auth 或 workload-bound policy 成為需求後跑 live E2E |
| Artifact 跨環境 promotion，mutable tag 可能改指向 | Immutable digest、build provenance、promotion record、必要的 admission policy | Git + OCI registry + existing delivery pipeline | Application + Platform + Security | Agent Catalog／Registry UI | Git + immutable OCI digest | Build pipeline、base image、promotion 或 admission 改變時重驗；Lab 03 mutable-tag case |
| 多團隊需要 deployment、discovery 或共享 HITL 操作面 | Agent Card／A2A contract、deployment controller、approval actor／receipt | kagent candidate；HITL contract 分開驗收 | Platform + Agent Application + Identity／Security | Registry、進階 workflow、platform-owned memory／sandbox | 沒有 shared demand 時維持 BYO Runtime | 重複維運成本與 owner 同時出現後，以 BYO／A2A／HITL fixture 重驗 |
| 多團隊需要 catalog、desired-state reconciliation 與 lifecycle 查詢 | Source of truth、Git／Registry write path、Authn／Authz、promotion 與 audit | Agent Registry candidate | Platform + Security + Application | Catalog UI 本身不先於 trust control | Git + immutable OCI digest | Catalog self-service、owner 與 trust model 一併成立時，重跑 deploy／mutation／undeploy fixture |
| 法遵明訂保存期限或須偵測紀錄刪改 | 先檢查 Git 變更歷史、Kubernetes Audit Log 與現有 LGTM 的保存方式 | 既有 GitOps 與觀測平台；不足時才補保存機制 | Security／Risk + Platform | 不先建新的儲存平台 | 現有紀錄已符合要求就維持原架構 | 要求改變時再檢查存取權限、保存期限與刪改權限 |

## 使用方式

1. 先選符合目前現況的 trigger，不從產品名稱開始。
2. 填入實際 owner；找不到 owner 時，不把候選 control plane 寫成已採用。
3. 用既有 Lab、production record 或官方文件標示 evidence，三者不要合成同一個 `PASS`。
4. 寫下合理停留點與 reopen trigger。下一次架構 review 只檢查 trigger 是否已改變。
