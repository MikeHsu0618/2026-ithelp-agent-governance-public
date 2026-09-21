# Day 29 Residual Risk Register

這份清單只保留 Day 1–28 已經出現的 evidence gap。它不列泛稱的「模型不準」、「法規風險」或「未來擴充性」，也不把尚未跑過的控制寫成既有能力。

| ID | Evidence-backed risk | 目前證據／控制 | Risk owner | Acceptance authority／目前決定 | Revalidation／close condition |
|---|---|---|---|---|---|
| RR-01 | 不可信內容可誘導高風險 Tool Call；只做 keyword inspection 仍可能漏過改寫 | Day 1 open policy 為 `CANARY_TRIGGERED`；Day 3 keyword guard 對改寫 fixture 漏判，Tool allowlist 最終 `DENY` | Agent Application | Business Owner；有副作用 Tool 不接受只靠 prompt filter 或 open policy 上線 | 新增寫入、刪除、部署或批准 Tool 時，對相同 fixture 重跑 allow／deny，並確認 resource policy 與 effect receipt |
| RR-02 | Human、Service 與實際 Workload instance 可能只共用 client identity，無法做 instance attribution | Day 7／27：Workload identity 為 `UNKNOWN`；現有控制為 Cognito Human／M2M、Token validation 與 Runtime context | IT／Identity + Platform／SRE | 受影響服務的 Business Owner；需要 per-instance policy 時不得繼續沿用 shared client attribution | 出現長效 client secret、跨 namespace 共用 credential 或 per-instance policy 時，以 workload-bound Token 或同等機制完成 live E2E |
| RR-03 | 事件無法證明實際執行哪一份 Agent Artifact | Day 26 `agent.artifact_digest=UNKNOWN`；Day 19 同一 mutable tag 可換 image；immutable digest／promotion evidence 列為 `ADOPT` | Agent Application + Platform／SRE | Business Owner + Security／Risk；Artifact provenance 是 release gate 時不得例外放行 | Mutable tag 進入 shared environment 或 replay 找不到 digest 時，驗 immutable deployment、build provenance、promotion record 與 Runtime 實際 digest |
| RR-04 | HITL 能 pause／resume，卻未證明 approver 有權批准該 action | Day 18 approve／reject contract `PASS`，approver authn／authz 未測；Day 26 approval 為 `UNKNOWN` | Agent Application + IT／Identity | Business Owner + Security／Risk；集中式 production HITL 維持 `DEFER` | Tool 要依人工批准執行 production 副作用前，以真實 IdP 驗 actor binding、action digest、expiry、single-use resume 與 decision receipt |
| RR-05 | Operational telemetry 可查詢，不代表紀錄完整、未被竄改或符合長期保存義務 | Day 26／27：Tamper-evident Audit 為 `UNKNOWN`；現有控制為 Alloy／LGTM correlation、Governance Event schema 與 replay | Security／Risk | Security／Risk；目前不接受把 LGTM 紀錄宣稱為不可否認 Audit | 出現 legal hold、不可否認或長期稽核要求時，驗 event-time signature／hash chain、append-only／WORM、access audit 與 deletion workflow |
| RR-06 | Gateway 能執行共同 policy，卻不能判斷特定帳戶、工單或 deployment 是否符合業務意圖 | Day 1 open policy 正常 `ALLOW` 不可信 Log 提出的 action；Day 28 將業務決策留給 resource owner | Agent Application + Business Owner | Business Owner | 高風險 action 缺 business intent、ticket／change window 不符，或 resource／arguments 在 approval 後改變時，重做 action-bound approval 與例外演練 |

## 使用規則

1. `Control implemented` 不等於風險關閉；close condition 要有可重跑的證據。
2. Risk owner 負責追蹤與降低風險，acceptance authority 才能決定剩餘風險是否可以進 production。Platform／SRE 不能代替所有角色簽收。
3. 新增項目時要附對應的 incident、Lab、test、decision record 或文件義務；沒有證據的擔憂留在研究清單，不進這張表。
4. 版本、Tool contract、Identity flow、policy schema、Artifact promotion 或 evidence backend 改變後，依該列的 revalidation 重驗。
