# Day 10｜Agent 沿用使用者的 OAuth Access Token：身分歸屬與權限邊界實測

值班工程師已經登入 SRE Copilot，Investigator Agent 接著要去 Observability MCP 查 Log。這時最省事的接法，是 runtime 收到使用者的 access token 後，原樣放進下一個 `Authorization` header。功能不用等另一條取 Token 的流程，Agent 也不必先管理自己的 OAuth client。

把 Human Token 原樣轉送看起來很有誘惑力，因為 Human SSO 和 M2M credential 的接法本來就不同，後者還要處理 client 註冊與憑證生命週期。但 Day 9 剛把值班工程師、Agent 和執行的 Workload 分開記下來，若第二跳又只帶著值班工程師的 Token，Observability MCP 根本看不出請求是由哪個 runtime 送來的。公開 [Lab 02](https://github.com/MikeHsu0618/2026-ithelp-agent-governance-public/blob/day-14-r2/labs/02-identity-boundary/README.md) 便故意試了這條路：同一枚合成 Token 先到 Agent entry，再原封不動送往另一個 resource。

## 同一枚 Token 到了第二個 resource

Lab 給值班工程師的 Token 設定了明確的接收對象：

```text
Token subject      user/sre-oncaller
Token audience     https://agent.lab.example/mcp
下一個接收者       https://observability.lab.example/mcp
```

Agent entry 驗過 Token，第一跳得到 `ALLOW`。Investigator runtime 把它送往 Observability MCP 時，下游要求的 audience 已經變成自己的 resource，因此回 `AUDIENCE_MISMATCH`。這枚 Token 並沒有過期，甚至帶著 `observability.query` scope。它只是沒有發給這個接收者。

![值班工程師的入口 Token 到了 Observability MCP。嚴格檢查 audience 時拒絕。改讓下游接受入口 audience 時雖能通過，Audit 卻只剩 Human。另一條路改用下游專用 Token 和 Delegation Context。](https://raw.githubusercontent.com/MikeHsu0618/2026-ithelp-agent-governance-public/day-14-r2/assets/diagrams/day-10/passthrough-vs-bound-token.png)

我現在比較願意把這種錯誤當成架構提示，而不是急著把 verifier 調到能通。`scope` 說的是這枚 Token 被授予哪種能力，`audience` 說的是哪個 resource 應該接收它。兩個欄位不會互相補位。[RFC 8707](https://www.rfc-editor.org/rfc/rfc8707.html) 讓 client 在取 Token 時指出目標 resource，好讓 Authorization Server 限制 Token 的使用位置。[MCP Authorization Security Considerations](https://modelcontextprotocol.io/specification/2026-07-28/basic/authorization/security-considerations#token-passthrough) 也要求 MCP Server 驗證 Token 是否發給自己，並禁止把收到的 client Token 直接轉交下游。

## 下游接受入口 audience

Lab 接著測另一種常見的整合捷徑：不換 Token，而是讓 Observability MCP 也接受 Agent entry 的 audience 和 `sre-console` client profile。這不是關閉所有 Token 驗證。下游仍驗 signature、issuer、scope 等條件，只是放寬了「這枚 Token 是發給誰的」這條邊界。

結果很容易讓功能驗收滿意：`query_logs` 變成 `ALLOW`。但下游從這枚 Token 讀到的仍是 `sub=user/sre-oncaller`，`client_id` 也仍屬於使用者登入時的 `sre-console`。在這條架構路徑上，請求是 Investigator runtime 送出的，它卻沒有因此變成 Token 的 subject。Audit 裡的 Agent 和 Workload 都是 `UNKNOWN`。當天查得出某位工程師發起任務，查不出是哪個 runtime 替他用了權限。

我們已把互動式 Human 與無人 M2M 分成不同的 credential 路徑。如果為了讓 Agent 快速呼叫更多下游，就讓 Human Token 多帶 scope、讓更多 resource 接受同一個 audience，原本分好的兩條路會在執行時重新混在一起。請求成功不代表責任也跟著交代清楚。

## 第二跳的憑證代表誰

另一條路是讓 Investigator runtime 在呼叫 Observability MCP 時，使用只發給該 resource 的 Token。Lab 讓它的 subject 是 `client/sre-investigator-runtime`，audience 是 Observability MCP，scope 只有 `observability.query`。這枚 Token 拿回 Agent entry 會因 audience 不符而遭拒絕。

下游因此能驗證眼前這枚 Token 以 runtime client 為 subject，而且是發給自己的。Day 9 的 Delegation Context 另外保存「這筆查詢最初由值班工程師交辦，經過哪版 Agent，最後由哪個 Workload 執行」。兩者放在同一筆 Audit 裡，可以同時看到：

| 這次查詢要回答的事 | Lab 留下的值 |
| --- | --- |
| 任務從誰而來 | `user/sre-oncaller` |
| 目前 Token 代表誰 | `client/sre-investigator-runtime` |
| 哪版 Agent 送出 Tool Call | `agent/sre-investigator@v1` |
| 程式跑在哪個 Workload | `k8s://lab/identity-boundary/sa/sre-agent` |

Runtime 的 OAuth client 與 Kubernetes ServiceAccount 也不是同一個身分。前者是這一跳 Token 的 subject，後者指出執行位置與 Workload。只憑 ServiceAccount 名稱，不能推論下游已驗過它的工作負載憑證。Lab 的 `FULL_CHAIN` 表示這幾個欄位都能在 Audit 裡對上，不表示每個角色都經過相同強度的驗證。

## Context 與下游 Token 的綁定

下游 Token 與 Delegation Context 各司其職，仍需要確認它們描述的是同一次動作。否則拿一份合法的委派紀錄，配上另一枚合法 Token，就可能把不相干的人與請求拼成一筆看似完整的 Audit。

Lab 先把 Context 的 credential 指紋、issuer、subject、client、audience，連同 target resource 與 action，對上這一跳實際收到的 Token 和請求。只給下游 Token、沒帶 Context 時回 `DELEGATION_CONTEXT_REQUIRED`。把 Context 的指紋換成另一筆，則回 `DELEGATION_CONTEXT_MISMATCH`。這兩組拒絕案例提醒我：資料結構有值，不等於它真是這次請求的資料。

這項比對是離線 Lab 的檢查，還不能防止任意 client 自己改寫 Context，再把欄位填得彼此一致。正式環境要由受信任的元件建立或重建委派資訊，或保護跨元件傳遞時的完整性。下游驗過目前 Token，也不會順便替前面每個 Agent 的版本和 Workload metadata 背書。

## 重現兩種接法

從 repo root 執行：

```bash
make lab-02-up
make lab-02-passthrough
```

Lab 會印出七組結果。對這篇最有用的是下面四筆。其餘包含下游 Token 回放到入口、缺少 Context 與 Context 不匹配，完整輸出在 [Day 10 evidence](https://github.com/MikeHsu0618/2026-ithelp-agent-governance-public/blob/day-14-r2/assets/screenshots/day-10/evidence.md)。

```text
CASE                               DECISION   CODE                           ATTRIBUTION
user_to_entry_resource             ALLOW      ALLOW                          TOKEN_SUBJECT_AT_ENTRY
passthrough_to_tool_strict         DENY       AUDIENCE_MISMATCH              NOT_EVALUATED
passthrough_shared_audience        ALLOW      ALLOW                          COLLAPSED_TO_TOKEN_SUBJECT
audience_bound_downstream          ALLOW      ALLOW                          FULL_CHAIN
```

![Day 10 的七組實際 CLI 結果。入口 Token 在自己的 resource 通過，下游嚴格驗 audience 時拒絕。共用 audience 雖通過但只剩 Human 歸屬，下游專用 Token 加 Context 才保留完整責任鏈。](https://raw.githubusercontent.com/MikeHsu0618/2026-ithelp-agent-governance-public/day-14-r2/assets/screenshots/day-10/01-passthrough-results.png)

想查同一枚 Token 究竟被送過哪些 resource，以及兩條 `ALLOW` 路徑的 Audit 差在哪裡，可以直接使用 [Token Passthrough Audit Reading Guide](https://github.com/MikeHsu0618/2026-ithelp-agent-governance-public/blob/day-14-r2/articles/day-10/token-passthrough-audit-guide.md) 的查詢。這裡用本機 issuer 與兩個離線 protected-resource validator 測授權結果，沒有啟動兩個 HTTP MCP Server，也沒有實作 Cognito 或 Token Exchange。Lab 的下游 Token 由本機 issuer 直接簽出，只用來比較 Token 與 Context 應具有的性質。

到這裡，第二跳該帶什麼已經比較清楚：Observability MCP 要收到發給自己的憑證，也要能把 runtime 的動作和原本的 Human 委派連起來。更難的問題是下游憑證從哪裡來，以及它究竟應代表 runtime 自己，還是明確表達 runtime 正代表某位使用者。Day 11 會把 Client Credentials、Token Exchange／OBO 與互動式 Human 的 PKCE 路徑放在一起比較。
