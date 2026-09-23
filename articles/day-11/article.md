# Day 11｜Agent OAuth Flow 實測：PKCE、Client Credentials 與 Token Exchange

Day 10 已經讓 Gateway 驗過入口 JWT，Agent 接著呼叫下游 MCP 時，卻不能把同一枚 Token 繼續往後送。值班工程師從 CLI 發起查詢時，人還在線上。凌晨固定產生報表時，只有 Scheduler 在工作。Agent Runtime 代表值班工程師查詢 Observability MCP 時，則同時存在「要求這件事的人」與「目前執行這件事的程式」。三種工作都需要 Token，Token 代表的對象卻完全不同。

我以前串接不同 MCP Client 時，經常把問題概括成「OAuth 沒設好」。真正拆開後才發現，失敗點可能是 Client Registration、使用者授權，也可能是 Token 發給了錯誤的 Resource。更麻煩的情況是 API 回了 `200`，Token 卻代表錯的人，直到追查 Audit 才發現整條責任鏈早已斷掉。

這篇用三條常見路徑把問題拆開：互動式 Human 使用 Authorization Code + PKCE，無人排程使用 Client Credentials，Runtime 代表 Human 呼叫下游時則示範 RFC 8693 Token Exchange。實務上最磨人的 Client Registration、Callback 與 Scope 問題，也會跟著各自的路徑出現。公開 Lab 用離線 Token 呈現三種不同身分語意。文章最後再回到 Cognito，確認哪些 Flow 能直接落地。

## 三種工作對應三種身分語意

選 OAuth Flow 以前，我會先把三件事寫清楚：Client 怎麼被 Authorization Server 認得、這次工作由誰授權，以及 Token 要送給哪個 Resource。這三個問題沒有對齊，換一種 Grant Type 通常只是把錯誤延後發生。

| 工作 | Token 最後代表誰 | 使用的 Flow |
| --- | --- | --- |
| 值班工程師從 CLI 啟動 Agent | `user/sre-oncaller` | Authorization Code + PKCE |
| Scheduler 定時查詢 | `client/sre-scheduler` | Client Credentials |
| Runtime 代表值班工程師呼叫下游 | Human 是 subject，Runtime 是 current actor | RFC 8693 Token Exchange |

![三種 Agent 工作對應三種 OAuth Token 語意。互動式 Human 使用 Authorization Code 加 PKCE，Scheduler 使用 Client Credentials，Human delegation 則同時驗證 subject token、actor token 與兩者的授權綁定。](https://raw.githubusercontent.com/MikeHsu0618/2026-ithelp-agent-governance-public/day-18-r2/assets/diagrams/day-11/three-oauth-flows.png)

這張圖刻意省略協定往返，只保留最後進入下游服務的身分。Human 路徑必須留下操作者，Scheduler 不該虛構一個使用者，而 Delegation 路徑不能讓 Runtime 冒充 Human。接下來三段都沿著這個判斷往下走。

## 互動式 CLI 使用 Authorization Code + PKCE

值班工程師從 CLI 登入時，適合走 Authorization Code + PKCE。CLI 屬於 Public Client，無法可靠保存長期 Client Secret，因此每次登入都產生一次性的 `code_verifier`，把它轉成 S256 `code_challenge` 放進授權請求，兌換 Authorization Code 時再交回原本的 Verifier。

[RFC 7636](https://www.rfc-editor.org/rfc/rfc7636.html) 規定 Verifier 必須是 43 到 128 個 unreserved characters，能使用 S256 的 Client 也應使用 S256。Lab 另外限制 Authorization Code 只能兌換一次，避免同一個 Code 被重播。成功後取得的 Token 大致保留以下語意：

```text
sub:       user/sre-oncaller
client_id: sre-console
aud:       https://agent.lab.example/mcp
scope:     agent.delegate
```

`sub` 是正在操作的值班工程師，`client_id` 則指出他從哪個入口進來。只記住其中一個都不夠。Audit 若只有 Human，看不出請求來自 Web、CLI 或其他入口。若只有 Client，也不知道是誰完成登入。

PKCE 本身反而不是我實務上最常卡住的地方。不同 MCP Client 對 Callback、Registration 與 Scope 的假設不一致，才是整合時反覆磨人的部分。有的 Client 使用 `localhost`，有的固定送 `127.0.0.1`。兩者即使 Port 和 Path 相同，也不是同一個 Redirect URI。Lab 把已註冊的：

```text
http://127.0.0.1:8765/callback
```

換成 `http://localhost:8765/callback`，Authorization Server 便以 `REDIRECT_URI_MISMATCH` 拒絕。我現在遇到 Callback 錯誤時，會先記錄 Client 實際送出的 Scheme、Host、Port 與 Path，再回頭比對 Registration，不再憑印象認定兩個網址「應該一樣」。

Registration 也可能有落差。有些 Client 預期能自動註冊，Authorization Server 卻只接受事先建立的 Client。現行 [MCP Client Registration 規格](https://modelcontextprotocol.io/specification/2026-07-28/basic/authorization/client-registration) 已把 Pre-registration、Client ID Metadata Documents 與其他註冊方式列出，但產品支援程度仍不一致。這篇不展開規格沿革，只保留實務上的底線：Authorization Server 不認得這個 Client，就不該繼續簽發 Code。

Scope 也不是 Discovery 顯示了就能取得。Protected Resource 可以告訴 Client 這次操作需要 `observability.query`，Authorization Server 還是要確認該 App Client 的 Allowlist 是否允許。需求與授權是兩份不同的清單，不能把前者當成後者。

## 無人排程使用 Client Credentials

凌晨執行固定報表時，Scheduler 自己就是工作主體。這類 Confidential Client 可以保存與輪替 Credential，向 Authorization Server 證明身分後，以 Client Credentials 取得 App-only Token：

```json
{
  "sub": "client/sre-scheduler",
  "client_id": "sre-scheduler",
  "aud": "https://observability.lab.example/mcp",
  "scope": "observability.query"
}
```

這枚 Token 不需要捏造值班工程師。Audit 看到 `client/sre-scheduler`，就知道動作來自排程服務，後續輪替、停用與權限收斂也都能指向同一個 Workload。

[RFC 6749 section 4.4](https://www.rfc-editor.org/rfc/rfc6749.html#section-4.4) 將 Client Credentials 限定給 Confidential Client。Lab 讓 Public CLI 嘗試相同 Flow，Authorization Server 在 Client Authentication 階段便拒絕，不會因為程式裡剛好塞了一段 Secret，就把 Public Client 當成 Confidential Client。

把固定 Secret 打包進 CLI、Desktop App 或公開可讀的 Container Image，只會讓所有能讀到 Binary、Image Layer 或環境變數的人共用一把 Credential。Client Credentials 解決的是無人 Workload 的身分，不是替 Public Client 補上一段看似方便的密碼。

## Runtime Delegation 同時保留 Human 與 Agent

第三種情境最容易被前兩種答案誤導。值班工程師已經請 Agent 查 Log，Investigator Runtime 接著要呼叫 Observability MCP。Runtime 若改拿自己的 App-only Token，下游只會看到 `client/sre-investigator-runtime`。若沿用 Human 的入口 Token，又會重演 Day 10 的 Token Passthrough：Audience 不合，Runtime 的參與也從責任鏈上消失。

Lab 因此用 [RFC 8693 OAuth 2.0 Token Exchange](https://www.rfc-editor.org/rfc/rfc8693.html) 示範 Delegation。Runtime 除了用自己的 Client Credential 完成驗證，還要帶入 Human 的 `subject_token` 與自己的 `actor_token`：

```text
subject_token = 值班工程師的 Agent Entry Token
actor_token   = Investigator Runtime 的 Token
resource      = Observability MCP
scope         = observability.query
```

RFC 8693 的通用 Request Grammar 沒有要求每次 Exchange 都必須帶 `actor_token`。本文處理的是 Delegation，不是 Impersonation，因此把 Actor 設成這個 Profile 的必要條件。Authorization Server 會檢查 Human Token 的 `may_act` 是否允許目前這個 Runtime，也會確認 Actor Token 的 Subject 與已驗證的 Client 相符。通過後才簽出只給 Observability MCP 使用的短效 Token：

```json
{
  "sub": "user/sre-oncaller",
  "act": {
    "sub": "client/sre-investigator-runtime"
  },
  "client_id": "sre-investigator-runtime",
  "aud": "https://observability.lab.example/mcp",
  "scope": "observability.query"
}
```

`sub` 保留被代表的 Human，`act` 記錄目前執行者。Target 若換成未授權的 Billing MCP，或 Human Token 原本不是發給 Agent Entry，Exchange 都會在簽發新 Token 前被拒絕。這些負向案例比「成功拿到一枚 JWT」更重要，因為它們證明 Runtime 不能自行改寫代表關係與目的地。

不同 IdP 對 Delegation 的支援方式並不相同。Microsoft Entra 的 On-Behalf-Of Flow 處理相近問題，Request Profile 卻使用 JWT Bearer Grant、`assertion` 與 `requested_token_use=on_behalf_of`，不能把 RFC 8693 的 Request Body 原封不動套上去。架構設計應以 IdP 公開支援的合約為準，沒有支援時也不能默默退回 Token Passthrough。

## 三條 Flow 的關鍵結果

[Day 11 Lab](https://github.com/MikeHsu0618/2026-ithelp-agent-governance-public/blob/day-18-r2/labs/02-identity-boundary/README.md#day-11-oauth-flow-執行結果) 一共跑九個案例。三條 Flow 各有一個成功案例，其餘六個負向案例刻意放入 Callback、Scope、Registration、Client Type、Target 與 Audience 錯誤。正文不再逐列抄完整驗收表，只留下最能區分三條路徑的結果：

| 情境 | 結果 | 說明 |
| --- | --- | --- |
| Human 完成 PKCE | ISSUE | Token 的 `sub` 是值班工程師，並保留入口 `client_id` |
| Public CLI 嘗試 Client Credentials | DENY | Public Client 不能靠內嵌 Secret 變成 Confidential Client |
| Runtime 完成 Delegation | ISSUE | Downstream Token 同時保留 `sub` 與 `act` |
| Runtime 要求未授權 Target | DENY | 代表關係不能自行擴張可存取的 Resource |
| Human Token 的 Audience 錯誤 | DENY | 入口 Token 不能拿來交換任意下游 Token |

![Day 11 OAuth Flow Lab 的九組實際結果。Authorization Code 加 PKCE、Client Credentials 與 RFC 8693 Token Exchange 各有一組成功案例，六組錯誤在發出 Token 前被拒絕。](https://raw.githubusercontent.com/MikeHsu0618/2026-ithelp-agent-governance-public/day-18-r2/assets/screenshots/day-11/01-oauth-flow-results.png)

從 Repo Root 執行以下指令，就能重跑完整案例：

```bash
make lab-02-up
make lab-02-check
make lab-02-oauth
```

完整 Decision Event、合成 Claims 與故障判讀指令放在 [Day 11 Lab 結果](https://github.com/MikeHsu0618/2026-ithelp-agent-governance-public/blob/day-18-r2/assets/screenshots/day-11/evidence.md) 和 [OAuth Flow 選擇與故障判讀表](https://github.com/MikeHsu0618/2026-ithelp-agent-governance-public/blob/day-18-r2/articles/day-11/oauth-flow-selection-guide.md)。這份離線 Lab 用來比較 Token 代表誰、錯誤會在哪一站被拒絕。它沒有啟動真正的瀏覽器登入或 Cognito Token Endpoint。

## Cognito 能接住兩條路，Delegation 仍待補齊

把三條 Flow 放回我們選定的 AWS Cognito 後，差異就很具體。[Cognito Token Endpoint 文件](https://docs.aws.amazon.com/cognito/latest/developerguide/token-endpoint.html) 列出 Authorization Code、Refresh Token 與 Client Credentials，沒有列出 RFC 8693 Token Exchange。依公開合約，Human CLI 與 Scheduler 可以直接落到 Cognito，Runtime Delegation 則不能假設送出相同 Request 就會成立。

平台仍可評估支援 RFC 8693 或 OBO 的 Token Broker／STS，也可以讓 Runtime 使用 App-only Downstream Credential，再把 Human Delegation 放入另一份具完整性保護的 Context。選擇後者時必須把兩件事寫清楚：Credential 代表 Runtime，Human Attribution 來自另一份可驗證資料。它們可以一起送到下游，卻不能混寫成同一個身分。

下一篇會先落地 Cognito 能直接支援的部分。Public Human Client 與 Confidential M2M Client 雖然共用同一個 Issuer，Callback、Scope、Audience Rule、Secret Lifecycle 與 Gateway Policy 都必須拆開。這是 IdP 選定後，第一個真正需要在設定裡做出的分界。
