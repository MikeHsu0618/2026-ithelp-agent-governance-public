# Day 10｜Token Passthrough 實測：Request 通了，Audit 卻只剩值班工程師

Day 9 把一次 Agent 任務裡的 Human、Agent 與 Workload 都放回 Delegation Context。欄位補齊之後，下一個麻煩很快就出現了。值班工程師已經拿著一枚有效的 access token 進入 Copilot，Investigator runtime 要呼叫 Observability MCP 時，最省事的做法似乎就是沿用它。

這條路徑不必另外取得下游 Token，也少了一組 OAuth client 與 credential flow。只看功能測試，它很可能一次就通過。可是把 caller 逐跳寫在架構圖上，問題就藏不住了。第一跳確實是值班工程師發起任務，第二跳真正送出 `query_logs` 的卻是 Agent runtime。如果兩跳都拿同一枚 Human Token，下游 Audit 還有辦法分辨是誰動用了查詢權限嗎？

我把這個疑問做成 [Lab 02](https://github.com/MikeHsu0618/2026-ithelp-agent-governance-public/blob/day-10/labs/02-identity-boundary/README.md) 的離線 policy simulation。它沒有啟動兩個 HTTP MCP Server，也沒有假裝接上 Cognito，而是以本機 ephemeral issuer、兩個合成 protected resource 與七組正負向 case，驗證 audience、credential attribution 和 Delegation Context binding。最關鍵的四筆結果如下：

```text
user_to_entry_resource        ALLOW  ALLOW                 TOKEN_SUBJECT_AT_ENTRY
passthrough_to_tool_strict    DENY   AUDIENCE_MISMATCH     NOT_EVALUATED
passthrough_shared_audience   ALLOW  ALLOW                 COLLAPSED_TO_TOKEN_SUBJECT
audience_bound_downstream     ALLOW  ALLOW                 FULL_CHAIN
```

值班工程師的 Token 在入口可以使用，原樣送到第二個 resource 時被 audience validation 擋下。接著我故意讓下游接受入口 audience，Request 果然變成 `ALLOW`，但是 Agent 與 Workload 也一起從 Audit 消失。第四筆改用只發給下游的 runtime Token，再帶上 Day 9 的 Delegation Context，三種身分才重新出現在同一筆事件裡。

![Day 10 Lab 實際 CLI 結果。嚴格的下游驗證拒絕 Human Token passthrough，接受共用 audience 雖然允許 Request，attribution 卻塌縮成 Token subject。下游專用 Token 與綁定過的 Context 才得到 FULL_CHAIN。](https://raw.githubusercontent.com/MikeHsu0618/2026-ithelp-agent-governance-public/day-10/assets/screenshots/day-10/01-passthrough-results.png)

圖片由 `make lab-02-passthrough` 的實際輸出重新排版。可複製指令、完整 JSONL 與 run manifest 都保留在 [Day 10 evidence](https://github.com/MikeHsu0618/2026-ithelp-agent-governance-public/blob/day-10/assets/screenshots/day-10/evidence.md)，讀者不必從圖片抄字。

## 第一版常見的 Token Passthrough 捷徑

把 Agent 接上企業 Identity 時，Token passthrough 很容易成為第一版答案。值班工程師已經登入，Gateway 也驗過 `user/sre-oncaller` 的 access token，Agent 呼叫 MCP 時直接沿用即可。少一段 credential flow、少一組 client，出問題時還能拿同一個 `sub` 搜尋 log，對趕著把路徑打通的團隊確實很有吸引力。

我一開始也覺得這個做法夠簡單，直到重新整理 Cognito、Agent runtime 與 Gateway 的 Identity path，並把 Day 9 的 Human、Agent、Workload 逐跳放回去。第一跳記成值班工程師沒有問題，因為入口 Token 表示 `user/sre-oncaller` 要求 Copilot 開始工作。到了第二跳，送出 `query_logs` Request 的已經是 Investigator runtime，Observability MCP 收到的 credential 卻還在說 `sub=user/sre-oncaller`。

這枚 Token 並沒有突然變成偽造憑證，它只是繼續描述上一跳的身分與授權。麻煩在於執行主體已經改變，credential 的語意卻沒有跟著改變。若平台只保存 Token subject，後續看到的每一個下游動作都會繼續算在值班工程師身上。

## Audience Mismatch 劃出第二個 Resource Boundary

Day 10 的 policy simulation 定義了兩個合成 resource：

```text
Agent entry       https://agent.lab.example/mcp
Observability MCP https://observability.lab.example/mcp
```

值班工程師 Token 的主要 claims 如下：

```json
{
  "aud": "https://agent.lab.example/mcp",
  "sub": "user/sre-oncaller",
  "client_id": "sre-console",
  "scope": "agent.delegate observability.query"
}
```

這枚 Token 進入 Agent entry 時會得到 `ALLOW`。Investigator 隨後把完全相同的 compact Token 送到 Observability MCP，這次 validator 預期的是下游自己的 resource ID，因此在 claims validation 階段回傳：

```text
DENY  AUDIENCE_MISMATCH
```

這項檢查沒有在刁難整合，而是 protected resource 正在守住自己的邊界。[MCP Authorization Security Considerations `2026-07-28`](https://modelcontextprotocol.io/specification/2026-07-28/basic/authorization/security-considerations#token-passthrough) 要求 MCP Server 驗證 access token 是否發給自己。當 Server 還要呼叫 upstream API，它必須取得發給該 upstream service 的另一枚 Token，不能把 MCP Client 送來的 Token 原樣轉傳。

[RFC 8707 Resource Indicators](https://www.rfc-editor.org/rfc/rfc8707.html) 也說明了 audience restriction 的理由。Authorization Server 知道 Token 要送往哪個 protected resource，才能把權限限制在正確接收者。規格鼓勵每次授權請求指向單一 resource，因為多 audience bearer token 會讓其中一個 resource 有機會拿同一枚 Token 呼叫其他 resource，只適合彼此高度信任的環境。

因此，`AUDIENCE_MISMATCH` 提供的是一項很有價值的訊號：第二跳已經跨過新的 resource boundary。若修法只是關掉這項檢查，Request 雖然可能恢復，原本應該存在的隔離也會跟著被抹平。

## 共用 Audience 讓 Request 通過，也讓 Attribution 塌縮

Strict path 被拒絕後，專案真正面對的壓力往往是先讓功能上線。Lab 的 `passthrough_shared_audience` 就模擬這種修法。Observability MCP 接受入口的 audience 與 OAuth client profile，Human Token 也預先帶上 `observability.query` scope，最後確實得到 `ALLOW`：

```json
{
  "case_id": "passthrough_shared_audience",
  "decision": "ALLOW",
  "attribution": "COLLAPSED_TO_TOKEN_SUBJECT",
  "human_principal": "user/sre-oncaller",
  "token_subject": "user/sre-oncaller",
  "executing_agent": "UNKNOWN",
  "workload_principal": "UNKNOWN"
}
```

這份結果表面上已經修好功能，實際上只是把拒絕換成另一種治理缺口。為了讓一枚 Token 到處可用，resource 開始共用 audience，Human Token 也逐漸累積每個下游可能需要的 scope。原本只該處理 `delegate_task` 的入口 credential，現在可以直接用來執行 `query_logs`，但 Token 本身不再回答是哪一個 runtime 動用了這份權限。

有人可能會想到另一個折衷方案，在 passthrough Token 旁邊多傳一份 Workload context。這確實可以增加 Audit 欄位，卻無法把值班工程師的 Token 變成已驗證的 runtime credential。下游驗證通過的 `sub` 仍然是值班工程師，所以 Context 與 credential 必須分開保留，不能用呼叫端自報的欄位假裝 workload authentication 已經完成。

Lab 以 SHA-256 fingerprint 關聯每一跳。前三個 case 的 fingerprint 完全相同，足以證明同一枚合成 Human Token 被重用，而且不必將 raw bearer token 寫進 artifact。被 `AUDIENCE_MISMATCH` 擋下的事件也不會先把未驗證 claims 當成 authenticated principal，只保存 fingerprint、失敗階段與 stable decision code。

這種 SHA-256 fingerprint 只適合示範問題。Production 若真的需要跨系統關聯 bearer credential，我會改用 keyed HMAC，限制查詢權限並設定短 retention。即使沒有保存原始 Token，fingerprint 仍然是可關聯資料，不適合放進 metric label 或無限期留存。

## Downstream Token 與 Delegation Context 各自回答不同問題

修正後的路徑沒有把值班工程師從 Audit 拿掉，而是讓 credential 和 Delegation Context 各自回答不同的問題：

- Downstream credential 表示目前這一跳由誰呼叫，以及它能使用哪一個 resource。
- Delegation Context 保存最初由誰提出要求、經過哪些 Agent，以及目前由哪個 Workload 執行。

![Token Passthrough 在第二跳的兩種結果，以及 resource-bound downstream Token 搭配 Delegation Context 後保留下來的 Human、Agent 與 Workload attribution。](https://raw.githubusercontent.com/MikeHsu0618/2026-ithelp-agent-governance-public/day-10/assets/diagrams/day-10/passthrough-vs-bound-token.png)

Lab 另外簽出一枚下游專用的合成 Token：

```json
{
  "aud": "https://observability.lab.example/mcp",
  "sub": "client/sre-investigator-runtime",
  "client_id": "sre-investigator-runtime",
  "scope": "observability.query"
}
```

它只帶 Observability MCP 所需的 scope，回放到 Agent entry 時會得到另一個 `AUDIENCE_MISMATCH`。這項負向測試用來確認兩個 resource 的 credential 確實分開，沒有把 Human 萬用 Token 換成另一枚 runtime 萬用 Token。

通過下游驗證後，Audit 會同時保存目前 Token subject 與上游 delegation：

```json
{
  "decision": "ALLOW",
  "attribution": "FULL_CHAIN",
  "human_principal": "user/sre-oncaller",
  "token_subject": "client/sre-investigator-runtime",
  "token_client_id": "sre-investigator-runtime",
  "executing_agent": "agent/sre-investigator@v1",
  "workload_principal": "k8s://lab/identity-boundary/sa/sre-agent"
}
```

這幾個欄位不是要在 Human 與 Workload 之間選出唯一答案。值班工程師是委派來源，runtime 是目前 credential subject，Agent 和 Kubernetes Workload 則保存版本與執行位置。它們各自回答不同問題，少掉任何一格都會讓事後調查失去一段重要上下文。

證據強度也需要如實標示。這枚 downstream Token 的 runtime subject 通過本機 validator，Human 來自已驗證的上游 Token。公開 Lab 裡的 Agent metadata 與 Kubernetes ServiceAccount 仍然只是 `ASSERTED`，因為這裡沒有實作 workload attestation。`FULL_CHAIN` 代表欄位與 binding 完整，不代表每個欄位都具有相同的驗證強度。

## Credential Binding 防止 Context 被任意拼接

把 Token 與 Context 分開後，還有一個不能省略的檢查。若 client 能拿值班工程師的一份合法 Context，再任意搭配另一枚合法 runtime Token，`FULL_CHAIN` 反而會變成一筆格式漂亮、內容卻不可信的假證據。

Day 10 因此要求下游檢查 Context 是否真的屬於當次 credential 與 target：

```text
credential fingerprint
issuer / subject / client_id / audiences
target resource / action
```

缺少 Context 時，policy 回傳 `DELEGATION_CONTEXT_REQUIRED`。若把 Context 裡的 fingerprint 換成 Human Token fingerprint，再搭配 runtime Token，則回傳 `DELEGATION_CONTEXT_MISMATCH`。這兩個拒絕路徑確保 client 不能只靠湊齊欄位就取得看似完整的 attribution。

這個 Lab 只完成 credential 與 target binding，還沒有完成 production 等級的 Context integrity。資料一旦跨越 trust boundary，應由受信任的 Gateway 重建，或放進具有完整性保護的 envelope，也可以採用等價的簽章機制。下游不能直接相信呼叫端自報 `human=user/sre-oncaller`。Day 9 定義的是資料形狀，Day 10 加上 credential 與 target binding，兩篇都沒有把這份 Context 包裝成新的 OAuth 標準。

## 七組 Case 對照兩條路徑

完整的 Day 10 slice 除了成功案例，也包含 Token 回放、缺少 Context 與錯誤 binding：

| Case | Decision | Code | Attribution |
| --- | --- | --- | --- |
| `user_to_entry_resource` | ALLOW | `ALLOW` | `TOKEN_SUBJECT_AT_ENTRY` |
| `passthrough_to_tool_strict` | DENY | `AUDIENCE_MISMATCH` | `NOT_EVALUATED` |
| `passthrough_shared_audience` | ALLOW | `ALLOW` | `COLLAPSED_TO_TOKEN_SUBJECT` |
| `audience_bound_downstream` | ALLOW | `ALLOW` | `FULL_CHAIN` |
| `downstream_token_replay_entry` | DENY | `AUDIENCE_MISMATCH` | `NOT_EVALUATED` |
| `missing_delegation_context` | DENY | `DELEGATION_CONTEXT_REQUIRED` | `NOT_EVALUATED` |
| `mismatched_delegation_context` | DENY | `DELEGATION_CONTEXT_MISMATCH` | `NOT_EVALUATED` |

從 repo root 執行：

```bash
make lab-02-up
make lab-02-check
make lab-02-passthrough
```

預期最後看到：

```text
7/7 cases matched
Same Human token reused across passthrough hops: yes (fingerprint only)
Raw credential persisted: no
```

若想直接比較兩條 `ALLOW` path，可以使用 [Token Passthrough Audit Reading Guide](https://github.com/MikeHsu0618/2026-ithelp-agent-governance-public/blob/day-10/articles/day-10/token-passthrough-audit-guide.md) 裡的 `jq` 指令。每次執行都會保存 manifest、summary、JSONL events、合成 issuer-input claims、Context 與 Token fingerprints，圖片只是閱讀輔助，不是唯一證據。

Day 10 slice 完成時，共用 Lab 當時有 46 tests，branch coverage 為 91.33%。因為同一個 Lab 後來又加入 Day 11 與 Day 12 的 OAuth case，發稿前重新執行整包測試的結果已變成 72 tests passed、branch coverage 91.17%。測試母體已經不同，這兩個 coverage 數字不能直接拿來解讀成上升或退步。最新 dependency audit 沒有找到已知漏洞，wheel 與 source distribution 也已實際 build。

## 下游 Token 的取得方式留給 Day 11

`audience_bound_downstream` 使用本機 ephemeral issuer 直接簽出 Token，證明的是修正後應具備的幾項性質：它有不同的 fingerprint，只發給 Observability MCP，scope 比 Human Token 更窄，runtime subject 也能和 Delegation Context 綁定。這個實驗沒有聲稱平台已經完成 Token Exchange，更沒有模擬 Cognito 或任何 IdP 的真實換發流程。

[RFC 8693 OAuth 2.0 Token Exchange](https://www.rfc-editor.org/rfc/rfc8693.html) 定義了 resource server 以收到的 subject token 向 Authorization Server 換取 backend token，也提供 delegation 與 `act` claim。真正落地時，平台仍要確認 IdP 支援範圍、Human 是否在線、目前 actor 應該是 runtime 還是 Service，以及無人工作是否應改走 Client Credentials。

因此，Audience 與 Attribution 的問題在 Day 10 先被拆開，credential flow 的選擇則留到下一篇。Day 11 會把互動式 Human、背景 Agent、Client Credentials 與 Token Exchange／OBO 放在同一張決策表裡，避免它們因為都叫 OAuth 就被塞進同一條 flow。
