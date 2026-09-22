# Day 29｜Agent 做錯事，責任算誰的：平台控制、業務決策與 HITL 核准

Day 1 那筆 `delete_demo_database` 沒有遇到系統錯誤。Gemini 從不可信 Log 讀到操作指令，Open Policy 按設定回 `ALLOW`，Google ADK 也把參數交給 Tool。公開 Lab 的 Tool 只寫下一筆 `CANARY_TRIGGERED`，不會碰資料庫。換成真實 Resource Server，同樣的判斷就可能改到 Production 資料。

當時存在的控制都照規則運作，規則本身卻沒有回答「不可信 Log 能不能要求這個動作」。這才是責任缺口。維護控制的人、決定規則的人，以及有權接受執行後影響的人，不能全部塞進同一個 Platform Owner。

Day 26 回放這筆 Action 時，Tool、Resource、Policy Decision 與 Canary Result 找得回來，Principal、Delegation、Agent Artifact、Approval 和原始紀錄完整性仍是 `UNKNOWN`。即使把所有欄位補齊，Identity 也只證明誰來了，Gateway 只證明哪版共同規則放行，Runtime 只證明送了哪些參數。目標服務仍要判斷這張工單、這個帳戶或這次 Deployment 此刻能不能修改。

這篇沿同一筆 Action 建立 [Production Responsibility Contract](https://github.com/MikeHsu0618/2026-ithelp-agent-governance-public/blob/day-09-r1/articles/day-29/production-responsibility-contract.md)，把 Control Owner、Decision Owner、Handoff Evidence、Escalation 與 Residual Risk 放回執行順序裡。

![一筆有副作用的 Agent action 依序經過 Identity admission、Gateway shared guardrail、Application Tool authorization、Business approval，以及 effect 與 evidence handling。每一站分開標示 control owner、decision owner 和 handoff evidence。現有技術控制通過，仍不等於業務意圖已獲證明。](https://raw.githubusercontent.com/MikeHsu0618/2026-ithelp-agent-governance-public/day-09-r1/assets/diagrams/day-29/responsibility-handoff.png)

## 三種通過代表不同判斷

Action 進入 Tool 前，至少有三種不同的綠燈：

1. **Credential Evidence**：Issuer、Audience、Expiry 與 Signature 是否正確。
2. **Technical Enforcement**：Route、Shared Policy、Resource Allowlist 與 Argument Constraint 是否允許。
3. **Business Intent**：工單、時段、目標 Resource 與影響範圍是否符合當下需求。

前兩種可以由程式穩定執行，第三種要先由目標服務 Owner 定義規則。高風險 Action 還需要具名的人在完整 Context 下核准。若把三者壓成 `authorized=true`，事故發生時只會看到所有檢查都通過，卻不知道哪個角色原本應該拒絕。

Day 1 的 Policy Engine 沒有故障，它忠實執行缺少 Resource 與 Argument Constraints 的 Open Policy。Platform Team 可以維護 Gateway 和 Policy Engine，不能自動取得 `delete_demo_database` 業務規則的決定權。

## 一筆 Action 的責任交接

Business Owner 在這裡不是抽象的高階主管，而是有權替目標 Resource 或流程批准變更、判讀影響並接受剩餘風險的人。修改服務時可能是 Service Owner，資料操作可能是 Data Owner，Deployment 則交給指定的 Change Owner。

| Action Stage | Control Owner | Decision Owner | 交給下一站的 Evidence |
| --- | --- | --- | --- |
| Human／Service Admission | IT／Identity | IT／Identity 決定 Principal／Client Lifecycle | Issuer、Audience、Subject／Client、Assurance、Expiry |
| Gateway Shared Guardrail | Platform／SRE | Security／Risk 核准最低共用 Guardrail | Route、Policy ID／Version／Decision、Reason、Request ID |
| Tool／Resource Authorization | Agent Application | Resource／Business Owner 定義可接受範圍 | Tool、Normalized Arguments、Resource、Artifact Digest、Application Decision |
| High-impact Approval | Platform 傳遞 Pause／Resume，Application 綁 Action Context | Business Owner 決定這次 Action 是否符合意圖 | Approver Principal／Authorization、Action Digest、Expiry、Decision、Resume ID |
| Effect／Incident Evidence | Application／Resource Server 產生 Receipt，Platform 維護 Correlation | Security／Risk 決定保存要求，Business Owner 判讀 Impact | Effect Receipt、Resource Revision、Trace ID、Governance Event、Retention Class |

Identity 確認 `user/sre-oncaller` 的 Credential，不代表這個 Principal 可以修改某個 Production Resource。Gateway 知道 JWT、Route 和共同 Policy，不知道工單批准的是 Staging 還是 Production。Application 負責把 Resource 規則落成 Authorization，規則的可接受範圍仍由 Resource Owner 決定。

完整 Contract 會固定 Request Origin、Business Intent、Tool、Resource、Arguments Digest、Artifact、Policy 與有效期，再填 Owner、Handoff Evidence、Escalation 和 Residual Risk。RACI 留在附錄，因為單看 `R`、`A`、`C`、`I`，看不出 Token、Policy Decision、Approval 和 Receipt 是否屬於同一筆 Action。

## Control Owner 與 Decision Owner

這兩種 Owner 的差別，在前面的選型已經出現過。Keycloak 技術鏈跑通，不代表 PoC Owner 有權決定整個企業的 Onboarding、Offboarding、下游服務與 SaaS Lifecycle。最後選 Cognito，是因為當時能長期承擔的範圍只有 Human／M2M Path。

agentgateway 也一樣。Platform／SRE 負責 JWT Validation、Route、Shared Policy、Telemetry 與升級重驗。`delete_demo_database` 可以接受哪些 Database、Ticket 與 Arguments，則由 Resource Owner 決定，再交給 Agent Application 實作。若 Action 需要人工批准，Business Owner 還要確認目標、時段與最大影響範圍。

Control Owner 和 Decision Owner 有時落在同一團隊，Contract 仍應分欄。升級時找操作控制的人，修改規則時找有權改變接受範圍的人，不再用一句「平台已處理」跳過中間責任。

## HITL Approval 必須綁定原始 Action

Day 18 的 BYO Agent 已跑過 Pause／Resume。Approve 與 Reject 沿用相同 Task ID 和 Context ID，Reject 不會執行 Tool。這證明 Workflow Contract 能互通，沒有驗證 Approver Authentication 與 Authorization，因此不能把那次 `PASS` 寫成 Production Approval 已完成。

一份可用的 Approval Evidence 至少要綁住：

- Approver Principal 及其批准權限。
- Tool、Resource 與 Normalized Arguments。
- Agent Artifact 與 Policy Version。
- Action Digest、Expiry 與一次性 Resume ID。

批准後只要其中一項改變，原 Decision 就不應繼續沿用。Platform 可以提供 Pause／Resume、UI 與 Receipt Transport，Application 要保證 Action Context 沒被替換，Business Owner 才負責決定「這一次可以做」。Approve 按鈕只證明有人能點，不能證明誰點、憑什麼能點，以及執行的仍是剛才看過的 Action。

## Operational Telemetry 與 Audit Responsibility

既有 LGTM 可以沿同一個 Action 查 Gateway、Runtime 與 MCP 的 Trace、Log 和 Metrics，適合 On-call、效能問題與事故回放。Responsibility Contract 因此把 Operational Telemetry 交給 Platform／SRE 維護，Application 與 Resource Server 則產生正確的 Tool Result 和 Effect Receipt。

Security／Risk 要決定哪些 Events 必須保存、保存多久、誰能讀或刪，以及是否需要 Event-time Signature、Append-only／WORM、Legal Hold 或 Privileged Deletion Detection。把 Loki Retention 拉長，不會自動把 Operational Log 升格成不可否認的 Audit Record。

兩條路徑可以共用 Action ID、Trace ID 與 Governance Event Schema，保存目的和證據等級仍然分開。SRE 不必替法遵目的作決定，Security／Risk 也不需要把每一筆高基數 Telemetry 永久保存。

## Residual Risk 只收有證據的缺口

責任審查若只列「模型幻覺、資安、法規、擴充性」，很難決定是否上線。本文的 [Residual Risk Register](https://github.com/MikeHsu0618/2026-ithelp-agent-governance-public/blob/day-09-r1/articles/day-29/residual-risk-register.md) 只收前文已經出現的六項缺口：

| Residual Risk | Evidence | 目前處理 |
| --- | --- | --- |
| 不可信內容誘導高風險 Tool | Day 1／3 | Tool／Resource Authorization，不能只靠 Keyword Inspection |
| Workload Instance Attribution 不足 | Day 7／27 | 維持 `UNKNOWN`，出現 Per-instance Policy 時重驗 |
| Agent Artifact 無法證明 | Day 19／26 | Immutable Digest、Promotion Evidence、Admission |
| Approver Authn／Authz 未驗 | Day 18／26 | 集中式 Production HITL 維持 `DEFER` |
| Telemetry 沒有 Tamper Evidence | Day 26／27 | Governance Event 先 `ADOPT`，Audit Storage 保持 `UNKNOWN` |
| Shared Policy 不懂業務意圖 | Day 1／28 | Resource Owner 定義範圍，Application 實作 Authorization |

Risk Owner 負責追蹤和降低風險，Acceptance Authority 才有權決定剩餘風險能否進 Production。接受者要知道現有控制能證明什麼、缺少什麼，以及哪些改變會讓決策失效。

[NIST AI RMF 1.0](https://airc.nist.gov/airmf-resources/airmf/5-sec-core/) 的 Govern Function 也要求組織記錄角色、責任與溝通路徑，並由領導層承擔 AI System 的風險決策。這是組織與 Lifecycle 層的工作，本文 Contract 只處理一筆 Action 的責任交接。Framework 不能替我們補出缺失的 Principal、Approval 或 Artifact Evidence，Action Contract 也不能取代完整法遵與企業治理。

## 帶進設計審查的方式

這份 Contract 不是另一套 Control Plane。設計審查時先填 Control Owner 與 Decision Owner，上線前用同一筆 Fixture 驗證 Handoff Evidence，並演練 Policy Missing、Approval Mismatch 與 Effect Receipt Missing。事故發生後再拿 Contract 對照 Timeline，缺少的欄位保持 `UNKNOWN`，不靠事後口述補成已驗證紀錄。

最後一天會把責任放回 Reference Architecture。Day 30 不再重貼 Capability Ledger 或 RACI，而是沿 Day 1 的同一筆 Action，將 Request Path、Identity／Policy Context、Artifact Source，以及 Telemetry／Audit Path 放進同一張設計審查圖。Principal、Approval 或 Audit Integrity 若仍缺 Evidence，架構圖上就直接標 `UNKNOWN`。
