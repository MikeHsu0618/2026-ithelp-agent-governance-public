# Agent Governance Capability Ledger v1

更新日期：2026-09-18

這份總帳以 capability 為列，不用產品功能數量排名。決策只適用於本系列描述的組織條件與已驗證範圍；若 reopen condition 成立，應回到原始 evidence 重新驗收。

決策狀態：

- `KEEP`：保留目前實作與責任分工，只涵蓋該列寫明的範圍。
- `ADOPT`：缺口已成立，納入下一版正式基線。
- `DEFER`：能力有價值，前置需求或 owner 尚未成立。
- `REJECT`：在限定情境下不採用，保留重新評估條件。
- `UNKNOWN`：證據不足，不推測補滿。

## Capability Ledger

| Capability | Current Source | Evidence | Owner | Upgrade／Fork Surface | Remaining Gap | Decision | Reopen／Revalidate Condition |
|---|---|---|---|---|---|---|---|
| Human identity／app lifecycle | Amazon Cognito User Pools、Human public client、agentgateway JWT policy | 實務 Human SSO E2E（去識別化）；Lab 02 token／flow contract | Identity／IT + Platform | App client、callback、scope、claim mapping、JWKS、Gateway policy | 尚未成為全企業 joiner／mover／leaver 的統一 Identity Center | `KEEP` | Client、claim 或 downstream audience 改變時重跑 Human flow；企業 lifecycle owner 成立時重評統一 IdP |
| M2M／Service access | Cognito confidential client + Client Credentials；Runtime 保存 service credential | 實務 M2M E2E（去識別化）；Lab 02 M2M contract | Identity／Platform + Application | Client secret、custom scope、token lifetime、rotation、Gateway audience／policy | Client secret 仍不是 workload instance attestation；rotation／offboarding 要有 owner | `KEEP` | Credential form、scope 或 Runtime deployment model 改變時重跑 M2M path |
| Workload instance identity | 尚無已驗證的 workload attestation source | Day 7 identity boundary；Kubernetes／SPIFFE 文件，未做 live E2E | 尚未指定；至少需 Platform + Security + Application | ServiceAccount token issuer／audience／rotation、pod binding、Runtime injection、Gateway mapping | Client Credentials 識別的是 app client，不是實際執行的 workload instance | `UNKNOWN` | 需要 per-instance attribution、secretless authentication 或 workload-bound policy 前，先選定機制並跑 live E2E |
| Human → Runtime → Tool delegation | Delegation Context v0.1；尚無統一 Token Exchange／OBO service | Lab 02；RFC 8693／MCP 文件 | Identity + Agent Runtime + Resource Server | Context schema、actor binding、target、subject／actor token、replay protection | Production exchange service、credential binding 與完整 multi-agent propagation 尚未驗證 | `DEFER` | Human-on-behalf-of 或跨 Agent action 成為正式需求時，用真實 issuer／resource server 重跑 |
| LLM／MCP／A2A traffic enforcement | agentgateway data plane + Kubernetes control plane | UAT／Production 經驗的去識別化結論；Lab 03／04 | Platform／SRE | Chart／CRD、Gateway API、route、policy、CEL、xDS、telemetry schema、Dashboard | Resource-specific business authorization 仍由 Application／Resource Server 定義 | `KEEP` | agentgateway、Gateway API 或 policy schema 升級時重跑 JWT、Tool、LLM、MCP、A2A 與 telemetry fixture |
| Agent runtime／business logic | BYO Google ADK + application repository | Lab 01／03／04 | Agent Application Team | Framework dependency、Tool callback、state／memory、filesystem、A2A adapter、evaluation | Runtime portability、sandbox 與 long-term memory 沒有平台統一保證 | `KEEP` | ADK／MCP／A2A SDK 升級或 Tool contract 改變時重跑 action、deny、HITL 與 telemetry |
| Deployment／discovery control plane | kagent candidate | Lab 03：deployment、Agent Card、Agent-as-Tool；部分能力未測 | Platform + Agent Application | CRD／controller／chart、generated runtime config、BYO adapter、A2A contract | Cross-team self-service 需求、advanced workflow、memory／sandbox 責任尚未成立 | `DEFER` | 跨團隊 discovery／統一部署成為需求時，以同一組 BYO fixture 重驗 |
| HITL pause／resume contract | BYO Runtime + kagent-compatible `input-required`／resume adapter | Lab 03：approve／reject、task／context continuity 與 synthetic actor propagation；authentication／authz 未測 | Agent Application + Platform + Identity／Security | A2A task／context、callback、approval UI、actor binding、decision receipt、replay protection | Approver authentication／authorization、production callback 與 audit receipt 尚未驗證 | `DEFER` | 有副作用的 Tool 需要集中式 human approval 前，以真實 IdP、approver policy 與 callback 重驗 |
| Artifact identity／promotion | Git review + immutable OCI digest；promotion evidence 待正式化 | Lab 03 mutable-tag risk；Lab image digest／lock | Application + Platform + Security | Dockerfile／lockfile、image digest、signature、SBOM、admission、promotion record | Signature、attestation、admission policy 與 production promotion receipt 尚未形成一條完整鏈 | `ADOPT` | 任何 image、base image、build pipeline 或 admission policy 改變時重驗 digest／signature／receipt |
| Cross-team catalog／reconciliation | Agent Registry candidate；目前 Git／runtime state 各自維護 | 私有 `0.3.3` deployment／source review；公開 `0.4.0` Lab | Platform；採用前需 Security／Application 共識 | API／schema、controller、database、kagent adapter、AuthnProvider／AuthzProvider、CLI | Catalog owner、Git／Registry write path、immutable artifact、promotion、authz 與 audit 尚未確立 | `DEFER` | Catalog self-service 成為正式需求，且 owner／auth／promotion／source of truth 一併確定時重評 |
| Telemetry／correlation | Alloy + Grafana／Loki／Tempo／Prometheus-compatible backend + agentgateway telemetry | 長期 LGTM 維運經驗；Lab 04 | SRE／Observability Platform | Collector pipeline、semantic conventions、labels／metadata、PII transform、retention、queries、Dashboard | Signal completeness、PII、cardinality 與跨 backend retention 仍需持續治理 | `KEEP` | Collector、backend、schema 或 label strategy 改變時重跑五種 traffic 與 backend verifier |
| Governance Event／incident replay | Governance Event v1 + action／event／trace correlation + replay tool | Lab 05；Day 1／3 locked Artifact + Day 26 live reference | Platform + Security／Risk + Application | Event schema、normalizer、field provenance、correlation query、case lock | Production ingestion、access model、retention 與 incident workflow 尚待接入 | `ADOPT` | Event schema、Tool contract、policy decision 或 evidence backend 改變時重跑 historical／live replay |
| Tamper-evident Audit storage | 尚無已驗證實作 | Day 26 明確保留 `UNKNOWN`；目前只有 repository lock 與 operational telemetry | 尚未指定；至少需 Security／Risk + Platform | Event-time signature、hash chain、append-only／WORM、access audit、retention、legal hold | Completeness、integrity、privileged deletion 與長期保存均未驗證 | `UNKNOWN` | 先指定保存目的與 owner，再以 threat model 驗證儲存與查詢路徑 |
| Cost attribution | agentgateway model-catalog estimate；Provider billing／invoice 尚未接入同一條 evidence chain | Lab 04：成功 usage 可估；失敗 attempt usage 為 `UNKNOWN` | Platform／FinOps + Model Consumer | Model catalog、pricing version、route／team mapping、billable usage、Provider invoice | Missing usage、shared overhead、credit／discount 與 invoice-grade reconciliation 未完成 | `KEEP` | Provider、model、price、fallback／retry 行為改變或進入正式 chargeback 時重驗 |

## 目前的產品決策與限制範圍

| Candidate | Decision | 適用範圍 | Reopen Condition |
|---|---|---|---|
| Amazon Cognito | `KEEP` | 目前已驗證的 Human／M2M access path | 企業 Identity Center owner 或 lifecycle scope 改變 |
| AI 專用 Keycloak Identity Center | `REJECT` | 只服務少數 AI 元件、無法掌握企業 joiner／mover／leaver 的情境 | IT／Identity owner、人力與下游整合範圍一併成立 |
| agentgateway | `KEEP` | LLM／MCP／A2A traffic policy、routing 與 telemetry boundary | Control plane、policy 或 data-plane contract 改變時重驗 |
| LiteLLM evaluation profile | `REJECT` | 當時 `1.80.x` Kubernetes operating model、identity mapping 與額外 GitOps glue | Operating model、identity ownership、declarative delivery 與 supply-chain posture 有實質改變 |
| BYO Google ADK runtime | `KEEP` | Application Team 仍需掌握 workflow、Tool 與 runtime semantics | 框架或平台需求改變 |
| kagent control plane | `DEFER` | 尚未出現足以負擔新 control plane 的跨團隊 self-service 需求 | Deployment／discovery／HITL 的共享需求與 owner 同時成立 |
| Agent Registry | `DEFER` | Catalog／reconciliation 已可用，trust／ownership 前置條件未齊 | Catalog owner、authz、promotion 與 source-of-truth 決策完成 |
| Alloy／LGTM | `KEEP` | Operational telemetry、correlation 與 investigation | Backend、pipeline、schema 或 retention 改變時重驗 |
