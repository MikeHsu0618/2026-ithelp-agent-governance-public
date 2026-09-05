# Day 11｜Agent OAuth Flow 實測：Authorization Code + PKCE、Client Credentials 與 Token Exchange

Day 10 把值班工程師的入口 Token 原樣送到第二個 MCP Server，結果不是撞上 audience 驗證，就是讓 Audit 誤以為整條鏈都由同一個人操作。這個洞不能靠「再發一枚 Token」帶過，因為 Agent 平台上至少有三種性質不同的工作。

值班工程師從 CLI 發起查詢時，人還在線上。凌晨執行固定報表時，只剩 Scheduler 自己工作。Investigator runtime 代表值班工程師呼叫 Observability MCP 時，Human 與目前執行者又得同時留下來。如果三種情境共用同一份 client credential，API 也許都能回 `200`，Token 卻會開始代表錯的人。

這次 [Day 11 Lab](https://github.com/MikeHsu0618/2026-ithelp-agent-governance-public/blob/day-13/labs/02-identity-boundary/README.md#day-11-oauth-flow-執行結果) 分別跑 Authorization Code + PKCE、Client Credentials 與 RFC 8693 Token Exchange，再故意放入 callback、scope、registration、client type、target 與 audience 錯誤。九組結果都符合預期，三枚成功 Token 則留下三種不同的 principal：

| 工作 | 成功 Token 代表誰 | OAuth flow |
| --- | --- | --- |
| 值班工程師從 CLI 啟動 Agent | `user/sre-oncaller` | Authorization Code + PKCE |
| Scheduler 定時查詢 | `client/sre-scheduler` | Client Credentials |
| Runtime 代表值班工程師呼叫下游 | `user/sre-oncaller` via `client/sre-investigator-runtime` | RFC 8693 Token Exchange |

![Day 11 OAuth Flow Lab 的九組實際結果。Authorization Code 加 PKCE、Client Credentials 與 RFC 8693 Token Exchange 各有一組成功案例，六組錯誤在發出 Token 前被拒絕。](https://raw.githubusercontent.com/MikeHsu0618/2026-ithelp-agent-governance-public/day-13/assets/screenshots/day-11/01-oauth-flow-results.png)

圖片是 `make lab-02-oauth` 的實際結果重新排版，指令與完整表格都留在正文。Manifest、decision event 與合成 Token claims 收在 [Day 11 evidence](https://github.com/MikeHsu0618/2026-ithelp-agent-governance-public/blob/day-13/assets/screenshots/day-11/evidence.md)，不需要從圖片抄字。

## 三份工作先分清楚，再選 Flow

我早期在接不同 MCP client 時，很容易把所有錯誤都收斂成一句「OAuth 沒設好」。實際追下去，問題通常散在三個位置：Authorization Server 認不認得這個 client、這次工作由誰授權，以及拿到的 Token 到底要送給哪個 resource。

```text
client 怎麼被認得？          registration
這次工作由誰授權？           grant / flow
Token 要交給哪個服務？       resource / audience
```

這三項有任何一項沒對齊，換 grant type 通常只會把錯誤往後推。更麻煩的是，即使 Token 成功發出，principal 也可能已經選錯。下面這張圖把 protocol round trip 收掉，只保留每條路徑最關鍵的輸入與最後的 Token 語意。

![三種 Agent 工作對應三種 OAuth Token 語意。互動式 Human 使用 Authorization Code 加 PKCE，Scheduler 使用 Client Credentials，Human delegation 則同時驗證 subject token、actor token 與兩者的授權綁定。](https://raw.githubusercontent.com/MikeHsu0618/2026-ithelp-agent-governance-public/day-13/assets/diagrams/day-11/three-oauth-flows.png)

## Human CLI：Authorization Code + PKCE

互動式 CLI 適合走 Authorization Code + PKCE。Public client 無法可靠保存長期 client secret，所以每次登入先建立一次性的 `code_verifier`，把 S256 `code_challenge` 放進 authorization request，最後再用原本的 verifier 兌換 authorization code。

[RFC 7636](https://www.rfc-editor.org/rfc/rfc7636.html) 規定 verifier 長度必須在 43 到 128 個 unreserved characters 之間，能使用 S256 的 client 就必須使用 S256。Lab 每次產生 32-byte random verifier，Authorization Server 只保存 challenge。Code 成功兌換後會立刻標成 consumed，同一個 code 再送一次就回 `INVALID_GRANT`。

```text
public client: sre-console
redirect URI: http://127.0.0.1:8765/callback
resource:     https://agent.lab.example/mcp
scope:        agent.delegate
result:       sub=user/sre-oncaller, aud=Agent entry
```

這條 flow 的成功 Token 表示值班工程師正在操作，`client_id=sre-console` 則保留他是從哪個 public client 進來。兩個欄位不能互相取代，否則 Audit 只看得到人，卻分不出是 Web、CLI 還是其他入口。

### Callback、Registration 與 Scope 是同一條登入路徑的三個關卡

我實際串接不同 MCP client 時，最花時間的往往不是 PKCE 本身，而是 client 對 registration 與 callback 的假設不同。有的 client 使用 `localhost`，有的固定送 `127.0.0.1`。我也遇過 client 預期能自動註冊，Authorization Server 卻只接受事先建立的 client。Discovery 顯示某個 scope，也不表示這個 app client 的 allowlist 已經放行。

Lab 把已註冊的 callback：

```text
http://127.0.0.1:8765/callback
```

換成同 port、同 path 的 `http://localhost:8765/callback`，結果仍是 `REDIRECT_URI_MISMATCH`。修這類問題時，我現在會先記錄 client 實際送出的 scheme、host、port 與 path，再回頭調整 registration，不會先猜「這兩個網址應該差不多」。

Registration 的現況也和我最初踩坑時不同。現行 [MCP Client Registration `2026-07-28`](https://modelcontextprotocol.io/specification/2026-07-28/basic/authorization/client-registration) 依序考慮 pre-registration、Client ID Metadata Documents（CIMD）、已 deprecated 的 DCR fallback，最後才是手動輸入 client information。這個版本的 MCP 規格引用的是當時的 CIMD draft-00，IETF 後來已更新到 [draft-02](https://datatracker.ietf.org/doc/html/draft-ietf-oauth-client-id-metadata-document-02)。CIMD 讓 `client_id` 本身成為 HTTPS metadata URL，但它仍是 Internet-Draft，也沒有消除 metadata fetch、redirect URI 驗證、SSRF 與 phishing 等風險。這份 offline Lab 沒有假裝架出 CIMD 或 DCR endpoint，只保留一個基本 contract：Authorization Server 不認得 client，就不能繼續簽 code。

Scope 則有兩份清單要對。MCP client 會先看 `WWW-Authenticate` challenge，沒有時才參考 protected resource metadata 的 `scopes_supported`，Authorization Server 還是要檢查該 client 自己的 allowlist。Lab 讓 client 要求 `admin.everything`，registration 卻只允許 `agent.delegate` 與 `observability.query`，因此在 authorization request 階段回 `INVALID_SCOPE`。Discovery 告訴 client「這次操作需要什麼」，不等於替它完成授權。

真正上線的 browser flow 還要處理 `state`、consent 與 authorization response 的 issuer 驗證。現行 [MCP Authorization 規格](https://modelcontextprotocol.io/specification/2026-07-28/basic/authorization) 要求 client 把 expected issuer 與同一筆 PKCE／state request record 綁定，收到 callback 後先驗 `iss`，再拿 code 去 token endpoint。Offline Lab 沒有跑瀏覽器，所以這些項目沒有被算進 PASS。

## Scheduler：Client Credentials

Scheduler 凌晨自己跑任務，不需要替它虛構一名值班工程師。它是 confidential client，向 Authorization Server 證明自己的身分後，以 Client Credentials 取得 app-only token。這枚 Token 的 Audit principal 就是 Scheduler：

```json
{
  "sub": "client/sre-scheduler",
  "client_id": "sre-scheduler",
  "aud": "https://observability.lab.example/mcp",
  "scope": "observability.query"
}
```

[RFC 6749 section 4.4](https://www.rfc-editor.org/rfc/rfc6749.html#section-4.4) 把 Client Credentials 限定給 confidential clients。Lab 另外讓 public CLI 嘗試相同 grant，Authorization Server 在 client authentication 階段就回 `UNAUTHORIZED_CLIENT`，不需要再判斷那串 secret 對不對。

把固定 secret 打包進 CLI、desktop app 或 container image，不會讓 public client 變成 confidential client。那只會讓每個能讀到 binary、image layer 或環境變數的人，共用一把難以追責的 credential。無人工作若真的需要 Client Credentials，secret 的保存與輪替責任也必須一起進入平台設計。

## Runtime Delegation：RFC 8693 Token Exchange

第三種工作不能直接套 Scheduler 的答案。值班工程師已經用入口 Token 請 Agent 查 log，Investigator runtime 現在要呼叫 Observability MCP。若 Runtime 改拿 app-only token，下游只會看到 `client/sre-investigator-runtime`。沿用 Human 的入口 Token，則會重演 Day 10 的 passthrough 問題。

這份 Lab 因此採用 [RFC 8693 OAuth 2.0 Token Exchange](https://www.rfc-editor.org/rfc/rfc8693.html)，而且明確使用 delegation profile：

```text
runtime client authentication
+ subject_token      = 值班工程師的 Agent entry Token
+ actor_token        = Investigator runtime 的 Token
+ resource           = Observability MCP
+ scope              = observability.query
```

RFC 8693 的 `actor_token` 在通用 request grammar 裡是 optional。不過同一份 RFC 的 delegation 範例也說得很清楚，只有 `subject_token` 而沒有 actor 時，表達的是 impersonation，不足以建立 delegation。這次 Lab 要驗證的是後者，因此把 `actor_token` 設成必要條件。

Authorization Server 先驗 Runtime 的 client authentication 與兩種 Token type，也把 resource、scope 限制在這個 client 的 allowlist 內。接著才分別驗證 Human `subject_token` 與 Runtime `actor_token`。Actor Token 的 subject 必須和已驗證的 confidential client 一致，Human Token 裡的 `may_act.sub` 也必須允許這個 actor。全部通過後，才會發出一分鐘有效、只給 Observability MCP 的 Token：

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

`sub` 保留被代表的值班工程師，`act` 則指出目前執行者。把 target 換成未授權的 Billing MCP 會得到 `INVALID_TARGET`。拿原本發給其他 resource 的 Human Token 來換，會在 `subject_token` stage 因 `AUDIENCE_MISMATCH` 被拒絕。Unit test 還多跑了一次 actor 綁定錯誤，確認 `may_act` 沒有授權目前 Runtime 時回 `ACTOR_NOT_AUTHORIZED`。

Microsoft Entra 的 On-Behalf-Of（OBO）處理相近的 middle-tier delegation 問題，request profile 卻不同。[Entra OBO 文件](https://learn.microsoft.com/en-us/entra/identity-platform/v2-oauth2-on-behalf-of-flow) 使用 JWT bearer grant、`assertion` 與 `requested_token_use=on_behalf_of`，不能直接拿 RFC 8693 的 request body 套上去。平台選哪一條要看 IdP 的公開合約。產品兩邊都不支援時，也不能默默退回 Token passthrough。

## Lab 結果：三次 ISSUE、六次 DENY

| Case | Flow | Decision | Code | Principal |
| --- | --- | --- | --- | --- |
| `pkce_human_success` | Authorization Code + PKCE | ISSUE | `TOKEN_ISSUED` | `user/sre-oncaller` |
| `pkce_callback_mismatch` | Authorization Code + PKCE | DENY | `REDIRECT_URI_MISMATCH` | `NOT_ISSUED` |
| `pkce_invalid_scope` | Authorization Code + PKCE | DENY | `INVALID_SCOPE` | `NOT_ISSUED` |
| `pkce_unregistered_client` | Authorization Code + PKCE | DENY | `CLIENT_NOT_REGISTERED` | `NOT_ISSUED` |
| `client_credentials_success` | Client Credentials | ISSUE | `TOKEN_ISSUED` | `client/sre-scheduler` |
| `client_credentials_public_client` | Client Credentials | DENY | `UNAUTHORIZED_CLIENT` | `NOT_ISSUED` |
| `token_exchange_success` | Token Exchange | ISSUE | `TOKEN_ISSUED` | `user/sre-oncaller via client/sre-investigator-runtime` |
| `token_exchange_invalid_target` | Token Exchange | DENY | `INVALID_TARGET` | `NOT_ISSUED` |
| `token_exchange_wrong_subject_audience` | Token Exchange | DENY | `SUBJECT_TOKEN_INVALID` | `NOT_ISSUED` |

從 repo root 執行：

```bash
make lab-02-up
make lab-02-check
make lab-02-oauth
```

最後會看到：

```text
9/9 cases matched
Authorization code persisted: no
PKCE verifier persisted: no
Client secret persisted: no
Raw credential persisted: no
```

目前完整 Lab 02 共 73 個 tests，branch coverage 90.81%，Ruff lint／format 也已通過。Day 11 的九組 fixture 只保存 safe registration snapshot、合成 claims、SHA-256 fingerprint、expected result 與 JSONL decision events。Authorization code、PKCE verifier、client credential、compact JWT 與 RSA private key 都不落盤。

如果要快速查是哪一層拒絕，或只比較三條成功 flow 的 principal，可以直接用 [OAuth Flow 選擇與故障判讀表](https://github.com/MikeHsu0618/2026-ithelp-agent-governance-public/blob/day-13/articles/day-11/oauth-flow-selection-guide.md) 裡的 `jq` 指令。這份 Lab 是 offline policy simulation，不是 Authorization Server 相容性測試。Browser、consent、TLS、CIMD fetch、DCR、refresh token 與 production client authentication 都不在 PASS 範圍。

## 兩條 Flow 能落到 Cognito，第三條仍是平台缺口

把三條 flow 放回我們選定的 Cognito，下一步就不只是照表抄設定。[Cognito token endpoint 文件](https://docs.aws.amazon.com/cognito/latest/developerguide/token-endpoint.html) 列出的 `grant_type` 是 `authorization_code`、`refresh_token` 與 `client_credentials`，其中沒有 RFC 8693 Token Exchange。依目前公開合約判斷，Human CLI 與 Scheduler 兩條路可以直接落到 Cognito。Runtime delegation 不能假設把相同 request 丟給 Cognito 就會成功。

這不表示第三條路只能放棄。平台可以另外評估支援 RFC 8693／OBO 的 Token Broker 或 STS，也可以使用 app-only downstream credential，再把 Human delegation 放進具完整性保護的 Context。只是後者必須坦白：credential 代表 Runtime，Human attribution 來自另一份可驗證資料，兩者不能混寫成同一件事。

下一篇先處理 Cognito 能直接接住的兩條路：public Human client 與 confidential M2M client 如何共用 issuer，卻分開 callback、scope、audience rule、secret lifecycle 與 Gateway policy。Token Exchange 留下的缺口也會繼續掛在架構上，不會因為 IdP 選型完成就當作已解決。
