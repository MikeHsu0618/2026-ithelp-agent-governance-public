# Day 5｜Agent Governance 四問：用一條 Action Path 盤點治理缺口

Day 3 的 Tool allowlist 已經把 `delete_demo_database` 擋在 Function Tool 前。相同的外部惡意 Log、相同的 Gemini Tool Call，open policy 會讓 safe canary 增加一筆，allowlist 則回傳 `DENY`，canary 維持零。這個危險 Tool 在 Lab 裡只會追加測試事件，不會碰真實資料庫。

如果只驗收這個控制點，Enforcement 當然可以寫 `PASS`。但我把 Day 1–4 的同一條 action path 攤開後，沒有一項能直接寫成完整的 `PASS`：

```text
Identity       PARTIAL
Provenance     UNKNOWN
Enforcement    PARTIAL
Traceability   PARTIAL
```

那次 policy 只看 `tool_name`，沒有值班工程師、executing workload 與 `payments-demo` target。Agent 和 Tool 的版本也沒有進入事件，ordered events 雖然能重播，仍不足以還原完整責任鏈。這些缺口讓四個狀態都停在 `PARTIAL` 或 `UNKNOWN`，也說明一次成功的 `DENY` 只能證明我們找到有效控制點，不能直接推論整條 action path 已受治理。

Identity、Provenance、Enforcement、Traceability 是我根據前四天的 Lab，以及後續研究 Identity Center、Gateway、Agent Registry 與 LGTM 的過程整理出的 review lens。這篇會用它們分開盤點「一個控制點」與「一條責任鏈」，但它們不是外部標準，尚未驗證的能力也不會因為畫進架構圖就變成 `PASS`。

## 產品分類與 Action Path

我最初也照產品分工整理架構。身分中心（Identity Center）負責登入與 token，Gateway 負責 routing、auth 與 policy，Agent Registry 管 catalog 和 metadata，Grafana LGTM 收 metrics、logs、traces。方框都有名字，看起來也各有 owner。

當 `delete_demo_database` 被提出時，request 不會照產品分類跳格子，只會沿著下面這條 path 往下走：

```text
值班工程師
  → SRE Agent
  → Runtime Workload
  → Policy Checkpoint
  → Tool／Target Resource
```

沿著這條路檢查，產品之間的接縫才會出現：

- Identity Center 認得某個 Human principal，下游 decision event 不一定保留它。
- Registry 找得到 Agent 或 Tool，不代表執行中的版本已經過核准。
- Gateway 回傳 `ALLOW`，resource server 仍可能有自己的 authorization。
- Trace 收得齊，不代表事件裡有 policy version、delegation 與 artifact digest。

看到同一條 action path 在產品接縫間一路掉資料後，我就不再繼續增加產品欄位，而是固定追四個不會跟著產品名稱改變的治理問題。後面即使替換 IdP、Gateway 或 Agent runtime，盤點欄位也不需要跟著重畫。

## 治理四問

### Identity：Actor 與 Delegation

Day 4 已經把一個模糊的 `agent_id` 拆成 Human principal、delegating Agent 與 executing workload。這一問不只檢查 request 裡有沒有 JWT，還要辨認每一個 hop 驗證了誰、credential 發給哪個 audience，以及 workload 是替 Human 執行工作，還是執行自己的排程。

Day 1–4 目前只有兩個可見值：ADK session 裡的 `synthetic-user-sre-oncaller`，以及 Agent 名稱 `sre_investigation_agent`。前者未經 IdP 驗證，後者也不是 workload credential。這些值對除錯有用，還不能構成完整的 actor chain，因此 Identity 是 `PARTIAL`。

### Provenance：Artifact 與版本

Repo 裡找得到 Agent 定義與三個 Function Tools，但 `policy.decision` 沒有 Agent version、Tool digest、signer、approval 或 Registry source。事後即使知道 `delete_demo_database` 被拒絕，也無法單靠事件確認當時載入哪一版 Agent、Tool definition 是否更換過，以及該 artifact 由誰核准。

Source tree 只能證明程式碼存在，不能證明執行中的 action 已經綁定到可信 artifact，因此 Provenance 只能保留 `UNKNOWN`。後面談 Agent Registry 時，也會繼續分開兩件事：catalog 讓人找得到 artifact，provenance 才負責交代版本與信任來源。

### Enforcement：Decision Point 與拒絕位置

Day 3 已實測改寫後的 Prompt Injection 能通過 keyword guard，open policy 會觸發 canary，Tool allowlist 則在 function 執行前拒絕相同 Tool Call，這是四項裡最完整的一份 evidence。

不過現有 policy input 只有 Tool name，尚未判斷 principal、resource、environment、delegation 或 approval。Safe canary 後面也沒有真正的 resource server 執行第二次授權。目前能確認的是「已有獨立拒絕點」，還不是完整 authorization model，所以 Enforcement 仍是 `PARTIAL`。

### Traceability：Event 與重建能力

Day 1 留下 trace ID、ordered events、summary 與 replay command，並且真的抓到兩次 summary bug。第一次是危險 Tool 執行後被後續 `SUCCESS` 蓋掉，另一次則是 policy `DENY` 被允許的 read-only Tool 蓋過。

兩次 summary bug 都是 ordered events 保住了真實執行順序，才沒有讓 final status 把前面的危險動作或 policy `DENY` 蓋掉。不過目前事件仍缺 verified Human、executing workload、artifact version 與下游 authorization，也尚未定義 retention、integrity、redaction 與查詢權限。現在的 Traceability 足以重播 Lab，還不是完整 Audit，所以也是 `PARTIAL`。

## Reference Architecture v0.1

![Agent action path 由 Caller 經 Agent Runtime 與 Policy Checkpoint 到 Tool／Resource。四個治理問題分別補上 principal 與 delegation、artifact 版本與信任、policy decision，以及可重建的執行證據。](https://raw.githubusercontent.com/MikeHsu0618/2026-ithelp-agent-governance-public/day-08/assets/diagrams/day-05/reference-architecture-v0.1.png)

這張圖沒有放 Cognito、Keycloak、agentgateway、kagent、Registry 或 Grafana Logo。v0.1 先固定責任與 evidence，等實作時再決定哪個元件承接：

| 治理問題 | 必須跟著 action 的資料 | 可能負責的元件，但不是唯一答案 |
| --- | --- | --- |
| Identity | human／service principal、delegation、workload、credential audience | IdP、STS、workload identity、Agent runtime |
| Provenance | Agent／Tool version、digest、owner、approval | Git、Registry、OCI、admission／deployment control |
| Enforcement | principal、action、resource、environment、policy version、decision | Agent callback、Gateway、Tool server、resource server |
| Traceability | proposal、decision、execution、outcome、trace／request key | OTel pipeline、structured log、Audit store |

同一個元件可能回答兩題，卻很少單獨回答四題。Gateway 可以驗 token、做 policy、輸出 trace，但它通常不知道 Agent artifact 是誰核准的。Registry 能提供 metadata，也不該因此被當成 runtime authorization 的最後防線。

## NIST AI RMF 與四問的尺度

[NIST AI RMF 1.0 Core](https://airc.nist.gov/airmf-resources/airmf/5-sec-core/) 以 Govern、Map、Measure、Manage 組織 AI risk management，涵蓋組織治理與 AI system lifecycle。官方的 [AI RMF Playbook](https://airc.nist.gov/airmf-resources/playbook/) 也明確說明，它提供的是 voluntary suggestions，不是一份必須全部照順序執行的 checklist。

本系列的四問窄得多，只拿來 review 一條具體的 Agent action：誰在行動、使用哪個 artifact、哪裡能拒絕，以及事後能否重建。它不是 NIST crosswalk，也無法取代法遵、模型品質、公平性、風險容忍度與組織責任。兩者處理的尺度不同，不能因為剛好都是四個項目就畫成一對一對照。

## Day 1–4 盤點結果

我把目前的 evidence 填進 [Agent Governance 四問 Checklist](https://github.com/MikeHsu0618/2026-ithelp-agent-governance-public/blob/day-08/articles/day-05/governance-four-question-checklist.md)：

| 治理問題 | 現有 evidence | 狀態 | 下一個最小缺口 |
| --- | --- | --- | --- |
| Identity | session user、Agent name | `PARTIAL` | verified principal 與 workload identity |
| Provenance | source tree 中有 Agent／Tool | `UNKNOWN` | 執行事件綁定 version／digest／approval |
| Enforcement | Tool allowlist 在執行前 `DENY` | `PARTIAL` | principal + resource-aware policy |
| Traceability | trace ID、ordered events、replay | `PARTIAL` | delegation、artifact 與下游 decision |

這張表不計算總分，因為四項風險並非等權重。唯讀 Metrics Agent 缺少 provenance，和能修改 Kubernetes workload 的 Agent 面臨的處理順序不會相同。Review 最後只要求選出一個「下一個最小缺口」並指定 owner，避免列出二十項改善後，整張表變成沒人維護的安全願望清單。

## Checklist 的使用順序

1. **先選 action。** 不要直接填「我們的 AI 平台」。同一個 Agent 查 Metrics 與修改 Deployment，應該拆成兩列。
2. **只填拿得出 evidence 的狀態。** 文件寫「支援」只能先算 `DOCS ONLY`，看得到 user email 也不等於 principal 已驗證。沒有資料就保留 `UNKNOWN`。
3. **找出最早能獨立拒絕的位置。** Agent callback、Gateway、MCP Server 與 Kubernetes API 都可能是 enforcement point，差別在各自看得到哪些 decision input。
4. **最後才選產品。** 缺口若是 workload identity，換 Dashboard 沒有幫助。問題若是 Tool artifact 沒版本，繼續增加 JWT claim 也補不了 provenance。

## 下一個缺口：可驗證的 Principal

Day 5 沒有再加一層防護，而是把前四天的結果放回同一張責任圖。盤點後排在最前面的缺口很清楚：值班工程師目前只是 session label，沒有 IdP 驗證、issuer、audience，也沒有 Gateway 可以採信的 role claim。

實際做平台時，人員身分通常早已存在企業 IdP，AI 平台缺的是一份穩定的 OIDC contract，把既有登入轉成 Gateway 與 MCP 能使用的 token 和 claim。當時我們先選了 Keycloak，而且 federation、role claim、Gateway 到 MCP Tool RBAC 都真的跑通。

技術鏈跑通後，我們還是得回答一個組織問題：如果員工的到職、轉調與離職仍由上游系統管理，這一層究竟是組織的 Identity Center，還是只服務 AI 平台的 identity bridge？Day 6 會從 Keycloak 的成功驗收開始，再說明 Cognito 為什麼後來才進入選項。
