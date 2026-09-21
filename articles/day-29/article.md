# Day 29｜Agent 做錯事，責任算誰的：平台控制、業務決策與 HITL 核准

Day 1 那筆 `delete_demo_database` 沒有遇到系統錯誤。Gemini 從不可信 Log 讀到操作指令後提出 Tool Call，open policy 按照設定回了 `ALLOW`，Google ADK 也正常把參數交給 Tool。公開 Lab 的 Tool 不會碰資料庫，只留下一筆 `CANARY_TRIGGERED` receipt。換成真的 Resource Server，同樣的判斷就可能改到 production 資料。

當時存在的控制都照規則運作，規則本身卻沒有回答「不可信 Log 能不能要求這個動作」。這才是這篇要處理的責任缺口。控制由誰維護、規則由誰決定，以及誰有權接受執行後的影響，不能全部塞給同一個 Platform owner。

[Day 26](https://ithelp.ithome.com.tw/articles/10412919) 回放這筆 action 時，Tool、resource、policy decision 與 canary result 都找得回來。Principal、delegation、Agent Artifact、approval，以及原始紀錄是否完整，則只能寫 `UNKNOWN`。即使把這些欄位全部補齊，Identity 仍只證明誰來了，Gateway 只證明哪版規則放行，Runtime 只證明送了哪些參數。它們無法替目標服務確認這張工單、這個帳戶或這次 deployment 此刻是否應該被修改。

Day 27 的 [Capability Ledger](https://ithelp.ithome.com.tw/articles/10413859) 把每項能力的來源、證據和維運 owner 分開，[Day 28](https://github.com/MikeHsu0618/2026-ithelp-agent-governance-public/blob/day-29/articles/day-28/article.md) 再依既有 LGTM、Identity 與 Gateway 排出導入順序。共同控制交給平台之後，單次 action 的業務決策並沒有跟著移過去。這一篇會沿同一筆 action 製作 Production Responsibility Contract，記下誰維護控制、誰能做決定、下一站要收到什麼證據，以及哪種差異必須升級處理。

![一筆有副作用的 Agent action 依序經過 Identity admission、Gateway shared guardrail、Application Tool authorization、Business approval，以及 effect 與 evidence handling。每一站分開標示 control owner、decision owner 和 handoff evidence。現有技術控制通過，仍不等於業務意圖已獲證明。](https://raw.githubusercontent.com/MikeHsu0618/2026-ithelp-agent-governance-public/day-29/assets/diagrams/day-29/responsibility-handoff.png)

## 三種「通過」不能混成一個綠燈

一筆 action 進入 Tool 以前，至少會遇到三種性質不同的判斷。第一種是 credential evidence：Token 是否由可信 issuer 簽發、audience 是否正確、是否過期，這些問題由 Identity 與驗證端回答。第二種是 technical enforcement：route、shared policy、resource allowlist、argument constraint 是否允許，控制可能落在 Gateway、Runtime callback 或 Resource Server。第三種才是 business intent：這次變更是否有正確工單、是否落在允許時段、目標資源和影響範圍是否符合當下需求。

前兩種判斷可以由程式穩定執行。第三種必須先由目標服務的 owner 把規則說清楚，某些高風險動作還需要具名的人在完整 context 下批准。把三者壓成一個 `authorized=true`，事故發生後只會看到所有現有檢查都通過，卻找不到哪個角色原本應該拒絕這次變更。

Day 1 的 policy engine 沒有故障，它只是執行了一條沒有 resource 與 argument constraint 的 open policy。Tool／resource 層少了 authorization，規則也沒有 decision owner。若這兩個 owner 沒有分開，事後很容易把 policy 內容也算在維護 Gateway 的 Platform Team 頭上。

## 沿著同一筆 action 交接責任

前面系列用過的角色可以整理成五組。Business Owner 在這裡指有權替目標 resource 或業務流程批准變更、判讀影響並接受剩餘風險的角色。修改服務或資料時可能是 service owner 或 data owner，deployment 則可能交給指定的 change owner。

| Action stage | Control owner | Decision owner | 必須交給下一站的 evidence |
|---|---|---|---|
| Human／Service admission | IT／Identity | IT／Identity 決定 principal／client lifecycle | issuer、audience、subject／client、assurance、expiry、token fingerprint |
| Gateway／shared guardrail | Platform／SRE | Security／Risk 核准最低共用 guardrail | route、policy ID／version／decision、reason、request ID |
| Tool／Resource authorization | Agent Application | Resource／Business Owner 定義可接受範圍，Application owner 將規則落成 policy | Tool、normalized arguments、resource、Artifact digest、application decision |
| High-impact approval | Platform 傳遞 pause／resume，Application 綁定 action context | Business Owner 決定這次 action 是否符合業務意圖 | approver principal／authorization、action digest、expiry、decision、resume ID |
| Effect／incident evidence | Application／Resource Server 產生 receipt，Platform 維護 correlation | Security／Risk 決定事件與保存要求，Business Owner 判讀 impact | effect receipt、resource revision、trace ID、Governance Event、retention class |

Identity 能確認 `user/sre-oncaller` 的 credential，不代表這個人可以刪除某個 production resource。Gateway 可以檢查 JWT、route 與共同 policy，不知道工單裡批准的是 staging 還是 production。Application 負責把 resource 規則落成可執行的 authorization，規則的可接受範圍仍要由目標 resource 的 owner 決定。這些判斷需要接力，不能靠同一個 `owner=platform` 欄位一次帶過。

完整的 [Production Responsibility Contract](https://github.com/MikeHsu0618/2026-ithelp-agent-governance-public/blob/day-29/articles/day-29/production-responsibility-contract.md) 會先固定 request origin、business intent、Tool、resource、arguments digest、Artifact、policy 與有效期，再填 control owner、decision owner、handoff evidence、escalation 和 residual risk。正文按 action 發生的順序走，RACI 只放在附錄，因為單看 `R`、`A`、`C`、`I` 看不出 Token、policy decision、approval 和 receipt 是否真的屬於同一筆 action。

## Control Owner 與 Decision Owner

Keycloak 的技術鏈跑通後，企業 Identity Center 仍沒有進入我們的正式方案。IT 團隊當時缺少共同承擔 onboarding、offboarding、下游服務與 SaaS 入口的人力和整合共識。PoC owner 可以安裝 Operator、設定 realm 與 client，卻不能代替 IT 決定整個組織的 identity lifecycle。最後選 Cognito，是因為當時能長期承擔的範圍只有 Human／M2M path。

相同的差異也出現在 agentgateway。Platform／SRE 要讓 JWT validation、route、共同 policy、telemetry 和升級後重驗都能工作，這是 control ownership。`delete_demo_database` 可以接受哪些 database、ticket 與 arguments，則由目標 resource 的 owner 決定，再交給 Agent Application 落成 policy。若 action 還需要人工批准，Business Owner 也要確認目標、時段與最大影響範圍。

Control owner 和 decision owner 有時會落在同一團隊，契約仍要分欄。分開以後，升級時找操作控制的人，修改規則時找有權改變可接受範圍的人，不會再用一句「平台已經處理」跳過中間的責任。

## HITL 的 Approve 必須綁住原本那筆 action

[Day 18](https://ithelp.ithome.com.tw/articles/10409155) 的 BYO Agent 已跑過 pause／resume。Approve 與 Reject 都沿用同一組 task ID 和 context ID，Reject 不會執行 Tool。這證明 workflow contract 可以互通，但該次 Lab 沒有驗 approver authentication 與 authorization，因此不能把 `PASS` 延伸成 production approval 已完成。

一份可用的批准證據，至少要綁住 approver principal、這個人是否有權批准、Tool、resource、normalized arguments、Agent Artifact、policy version、到期時間與一次性的 resume ID。任何一項在批准後改變，原 decision 都不該繼續沿用。Platform 可以提供 pause／resume、UI 和 receipt transport，Application 必須保證 action context 沒被替換，Business Owner 才是那個決定「這一次可以做」的人。

所以我沒有把 HITL 收斂成 Agent Platform 的一個功能勾選。畫面上出現 Approve 按鈕，只能證明有人可以點。責任契約還得證明誰點、憑什麼能點，以及按下去後執行的仍是剛才看過的 action。

## LGTM 保存操作證據，Audit 另有完整性責任

既有 LGTM 是這個系列最穩定的核心。Gateway、Runtime 與 MCP 的 trace、log、metric 都能沿同一個 action 查詢，對 on-call、效能問題與事故重建很實用。Production Responsibility Contract 因此把 operational telemetry 交給 Platform／SRE 維護，Application 與 Resource Server 負責產生正確的 Tool result 和 effect receipt。

Security／Risk 要回答的是另一組問題：哪些事件必須保存、保存多久、誰能讀或刪、是否需要 event-time signature、append-only／WORM、legal hold 或 privileged deletion detection。Day 26 沒有驗證這些機制，Day 27 也把 Tamper-evident Audit 留在 `UNKNOWN`。把 Loki retention 拉長，仍不能直接把 operational log 升格成不可否認的 Audit record。

兩條路徑可以共用 action ID、trace ID 和 Governance Event schema，保存目的與證據等級仍要分開。這樣事故發生時，SRE 不需要替法遵目的作決定，Security／Risk 也不會把每一筆高基數 telemetry 都要求成永久 Audit。

## Risk Register 只收已經看見的缺口

整理責任時很容易順手列出「模型幻覺、法規、資安、擴充性」等泛稱風險。這種清單沒有 evidence、owner 或關閉條件，很難拿來決定是否上線。目前的 [Residual Risk Register](https://github.com/MikeHsu0618/2026-ithelp-agent-governance-public/blob/day-29/articles/day-29/residual-risk-register.md) 有六項，每一項都能回到前面的 Lab 或決策紀錄：

| Residual risk | 證據來源 | 目前處理 |
|---|---|---|
| 不可信內容誘導高風險 Tool Call | Day 1／3 | Tool／resource authorization，不能只靠 keyword inspection |
| Workload instance attribution 不足 | Day 7／27 | 維持 `UNKNOWN`，出現 per-instance policy 時重驗 |
| 實際 Agent Artifact 無法證明 | Day 19／26 | 採 immutable digest、promotion evidence 與 admission |
| HITL approver authn／authz 未驗 | Day 18／26 | 集中式 production HITL 維持 `DEFER` |
| Operational telemetry 沒有 tamper evidence | Day 26／27 | Governance Event 先 `ADOPT`，Audit storage 保持 `UNKNOWN` |
| 共同 policy 不懂業務意圖 | Day 1／28 | Resource／Business Owner 定義範圍，Application 落成 authorization |

Risk owner 負責追蹤與降低風險，risk acceptance authority 則有權決定剩餘風險能否進 production。兩個角色不能再塞進同一欄。接受者要知道現有控制能證明什麼、缺少什麼，以及什麼事件會讓決策失效。Tool contract、Identity flow、policy schema、Artifact promotion 或 evidence backend 改變後，都要依對應條件重驗。

## NIST AI RMF 放在組織層

[NIST AI RMF 1.0 Core](https://airc.nist.gov/airmf-resources/airmf/5-sec-core/) 的 Govern function 要求組織記錄清楚的角色、責任與溝通路徑，也把領導層對 AI system 風險決策的責任列進治理工作。[Govern Playbook](https://airc.nist.gov/airmf-resources/playbook/govern/) 還涵蓋持續監控、人機配置、事件與下架。這些是組織與 lifecycle 層的治理工作，不是一張 action contract 能取代的範圍。

Production Responsibility Contract 只處理一筆 action 如何跨過控制與組織邊界。NIST 文件不能替我們補出 Day 26 缺失的 principal、approval 和 Artifact evidence，這份契約也不處理完整的法遵、模型風險或企業治理。兩者尺度不同，交集只有角色、決策責任與持續追蹤。

## 把責任契約帶進設計審查

我不打算把這份契約再做成一套 control plane。設計審查時填好 control owner 和 decision owner。上線前用同一筆 fixture 檢查 evidence 能否綁回 action，並演練 policy missing、approval mismatch 與 effect receipt missing。事故發生後再拿它對照 timeline，缺欄位就保留 `UNKNOWN`，不靠事後口述補成已驗證紀錄。

最後一天會把這些責任放回 Reference Architecture。Day 30 不會再貼一次 Capability Ledger 或 RACI，而是沿 Day 1 的同一筆 action，把 request path、identity／policy context、Artifact source，以及 telemetry／audit path 畫在同一張可供設計審查的圖上。Principal、approval 或 Audit integrity 若仍缺證據，圖上就直接標 `UNKNOWN`。
