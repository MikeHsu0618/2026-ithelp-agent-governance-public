# Day 29｜Agent 做錯事，責任算誰的：平台控制、業務決策與 HITL 核准

Day 1 那筆 `delete_demo_database` 沒有遇到系統錯誤。Gemini 從不可信 Log 讀到操作指令，Open Policy 按設定回 `ALLOW`，Google ADK 也把參數交給 Tool。公開 Lab 的 Tool 只寫下一筆 `CANARY_TRIGGERED`，不會碰資料庫。換成真實 Resource Server，同樣的判斷就可能改到 Production 資料。

當時存在的控制都照規則運作，規則本身卻沒有回答「不可信 Log 能不能要求這個動作」。這才是責任缺口。維護控制的人、決定規則的人，以及有權接受執行後影響的人，不能全部塞進同一個 Platform Owner。

假設下一版 `delete_demo_database` 真的能連到資料庫：值班工單只允許處理測試環境，Agent 卻提出指向正式環境的參數。誰該在執行前發現不對？如果請求先通過 Gateway，誰又有權說「這次仍然可以做」？這是上線前的設計審查情境，不是公司事故。我用它走讀 [Production Responsibility Contract](https://github.com/MikeHsu0618/2026-ithelp-agent-governance-public/blob/day-23-r2/articles/day-29/production-responsibility-contract.md)，把控制維護者、規則決定者和每站要交接的資料分開。

![一筆有副作用的 Agent action 依序經過 Identity admission、Gateway shared guardrail、Application Tool authorization、Business approval，以及 effect 與 evidence handling。每一站分開標示 control owner、decision owner 和 handoff evidence。現有技術控制通過，仍不等於業務意圖已獲證明。](https://raw.githubusercontent.com/MikeHsu0618/2026-ithelp-agent-governance-public/day-23-r2/assets/diagrams/day-29/responsibility-handoff.png)

## 三種通過代表不同判斷

Action 進入 Tool 前，至少有三種不同的綠燈：

1. **Credential Evidence**：Issuer、Audience、Expiry 與 Signature 是否正確。
2. **Technical Enforcement**：Route、Shared Policy、Resource Allowlist 與 Argument Constraint 是否允許。
3. **Business Intent**：工單、時段、目標 Resource 與影響範圍是否符合當下需求。

前兩種可以由程式穩定執行，第三種要先由目標服務 Owner 定義規則。高風險 Action 還需要具名的人在完整 Context 下核准。若把三者壓成 `authorized=true`，事故發生時只會看到所有檢查都通過，卻不知道哪個角色原本應該拒絕。

Day 1 的 Policy Engine 沒有故障，它忠實執行缺少 Resource 與 Argument Constraints 的 Open Policy。Platform Team 可以維護 Gateway 和 Policy Engine，不能自動取得 `delete_demo_database` 業務規則的決定權。

## 讓這筆請求走過五個決策點

Business Owner 在這裡不是抽象的高階主管，而是有權替目標 Resource 或流程批准變更、判讀影響並接受剩餘風險的人。修改服務時可能是 Service Owner，資料操作可能是 Data Owner，Deployment 則交給指定的 Change Owner。

| 這一站要回答 | 維護控制的人 | 決定規則或單次批准的人 | 交給下一站的資料 |
| --- | --- | --- | --- |
| 請求者是誰？ | IT／Identity 維護登入與 Client | IT／Identity 定義身分生命週期 | 已驗證的 Caller、Token 用途與有效期 |
| 可以走這條入口嗎？ | Platform／SRE 維護 Gateway | Security／Risk 定義共同底線 | Route、Policy 版本、放行或拒絕原因 |
| 工單允許改哪個資料庫？ | Agent Application 實作檢查 | 資料或服務 Owner 定義目標、時段與參數範圍 | 目標 Resource、正規化參數、應用授權結果 |
| 這次真的需要人工批准嗎？ | Platform 傳遞暫停／繼續，Application 固定 Action | 有權的業務 Owner 批准這一次 | 批准者、Action 摘要、有效期與 Decision |
| 實際改了什麼？ | Resource Server 產生 Receipt，Platform 串起紀錄 | 業務 Owner 判讀影響，Security／Risk 定保存規則 | 修改結果、Resource Revision、Trace ID 與事件 |

在這個情境，Identity 可以正確辨認值班工程師，Gateway 也可能正確放行這條 Tool Route。真正該擋下 `production` 參數的，是知道工單只批准測試環境的 Application／Resource Server。若這一站缺席，不能事後說「Gateway 已經驗過 Token」來補理由。

完整 Contract 會固定 Request Origin、Business Intent、Tool、Resource、Arguments Digest、Artifact、Policy 與有效期，再填 Owner、Handoff Evidence、Escalation 和 Residual Risk。RACI 留在附錄，因為單看 `R`、`A`、`C`、`I`，看不出 Token、Policy Decision、Approval 和 Receipt 是否屬於同一筆 Action。

## 控制正常運作，不代表決策已有人負責

Platform／SRE 可以把 Gateway 的 Token 驗證、Route、共同 Policy 與 Telemetry 維護好，卻無法替某個資料庫 Owner 定義工單准許的影響範圍。反過來，業務 Owner 可以決定哪些修改可接受，也不能只說「交給平台」就假設授權檢查會自己出現在 Tool 裡。規則由誰決定、由誰落成可執行控制，兩邊都要寫清楚。

Control Owner 和 Decision Owner 有時落在同一團隊，Contract 仍應分欄。升級時找操作控制的人，修改規則時找有權改變接受範圍的人，不再用一句「平台已處理」跳過中間責任。

## HITL Approval 必須綁定原始 Action

Day 18 的 BYO Agent 已跑過 Pause／Resume：Approve 與 Reject 沿用相同 Task ID 和 Context ID，Reject 不執行 Tool。當時還沒處理誰有資格按下 Approve；正式讓人核准高風險動作，必須把批准者與原始 Action 綁在一起。

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

## 風險清單只留下會影響上線決定的缺口

責任審查若只列「模型幻覺、資安、法規、擴充性」，很難決定是否上線。這筆假設中的資料庫修改至少要把三件事擺上桌：不可信 Log 可能誘導 Tool、公開 Lab 尚未驗證正式的批准者身分、執行映像與事件保存也還沒有形成完整來源鏈。前文各自有測試或缺口紀錄，不需要在這篇重新把每個產品列一遍。

[Residual Risk Register](https://github.com/MikeHsu0618/2026-ithelp-agent-governance-public/blob/day-23-r2/articles/day-29/residual-risk-register.md) 留下完整來源、Owner、重驗條件與接受者。這裡的判斷是：若 Resource Authorization 還不能比對工單與目標環境，高風險 Tool 就不應對正式資料庫開放。補上檢查後，剩下哪些風險能接受，仍要由有權承擔業務影響的人決定，不能讓維護 Gateway 的團隊代簽。

[NIST AI RMF 1.0](https://airc.nist.gov/airmf-resources/airmf/5-sec-core/) 的 Govern Function 同樣把角色、責任與溝通路徑放在組織層級。本文把範圍收在一筆 Action：誰定規則、誰執行檢查、誰接受結果。組織風險決策仍要有自己的負責人。

## 帶進設計審查的方式

這份 Contract 不是另一套 Control Plane。設計審查時，先拿一筆會改動資料的請求，故意把工單目標與 Tool 參數設成不同環境，看 Resource Server 是否真的拒絕。接著檢查批准後換參數是否失效，以及執行結果能否對回同一筆請求。測試結果、控制維護者和決策者，都要跟著 Action 留下來。

最後一天會把這場審查放回整體架構，看三十天前那筆危險 Tool Call，若今天重新設計，它會在哪一站停下，事後又能查到什麼。
