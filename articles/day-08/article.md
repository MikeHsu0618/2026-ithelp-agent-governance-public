# Day 8｜JWT 簽章過了，為什麼還是不能放行？Issuer、Audience、Scope 與 Claim 實測

把 Cognito 接進 Gateway 的那一輪，我原本以為最麻煩的部分已經處理完了。Human SSO 可以登入，Gateway 也能驗 JWT signature，MCP policy 則已經寫好需要哪些使用者資訊。照這個進度看，剩下的工作應該只是把 claim 名稱填進設定檔。

真正拿 ID token 和 access token 對照後，情況沒有那麼簡單。授權規則需要的使用者 context 出現在 ID token 裡，送往 API 的 access token 卻沒有同樣的資料。登入沒有失敗，Token 也確實由 Cognito 簽發，但 Gateway 手上的那枚 access token 仍不足以完成原本設計的 policy。

當時最直覺的解法，是把資料比較完整的 ID token 送給後端。我沒有採用這條捷徑，因為這個 resource 的 contract 要求 OAuth access token。為了多拿一個 claim 改送 ID token，會把「使用者完成登入」和「client 取得 resource access」混在一起，後續連 audience 和 audit 都很難解釋。

我把這個落差縮成可離線重現的 [Lab 02](https://github.com/MikeHsu0618/2026-ithelp-agent-governance-public/blob/day-10/labs/02-identity-boundary/README.md)。公開案例用 `team=platform` 取代實際欄位，其中四筆最能說明問題：

```text
valid_access          ALLOW  ALLOW
wrong_audience        DENY   AUDIENCE_MISMATCH
access_missing_team   DENY   CLAIM_MISSING
id_token_has_team     DENY   TOKEN_TYPE_INVALID
```

七枚 Token 都由同一個本機 issuer 產生，也使用同一把 2048-bit RSA private key 簽署。它們的 signature 都能通過，最後卻只有 `valid_access` 被放行。少了 `team` 的 access token 停在 policy，帶著 `team=platform` 的 ID token 則更早就因 Token type 不符而被拒絕。

![Lab 02 的實際 CLI 結果：七組 Token case 只有 valid_access 被放行，其他案例各自在 header、claims 或 policy 階段被拒絕。](https://raw.githubusercontent.com/MikeHsu0618/2026-ithelp-agent-governance-public/day-10/assets/screenshots/day-08/01-jwt-boundary-results.png)

這張圖保留的是 2026-08-19 完成 Day 8 slice 時的實際輸出，當時有 24 個測試。Lab 後來繼續承接 Day 9 到 Day 12，目前從 repo root 執行 `make lab-02-check` 會跑完整的 72 個測試。原始 JSON summary、hash 和圖片製作方式都放在 [Day 8 evidence](https://github.com/MikeHsu0618/2026-ithelp-agent-governance-public/blob/day-10/assets/screenshots/day-08/evidence.md)，指令和結果不需要從圖片上抄。

## 簽章正確，Token 的用途仍可能不對

JWT 是承載 header、claims 和 signature 的格式。把 payload decode 出來很適合除錯，卻不代表裡面的 `sub`、`team` 或 `scope` 已經可信。Verifier 還得用自己設定的 issuer、key、audience 和演算法完成驗證，不能從待驗 Token 抄一份 expected value 回去。

OIDC 和 OAuth 又各自多回答了一層問題。OpenID Connect 的 ID Token 描述 End-User authentication，OAuth access token 則交給 resource 判斷這次存取是否符合授權條件。[OpenID Connect Core 1.0](https://openid.net/specs/openid-connect-core-1_0.html#IDToken) 對 ID Token 的定位很清楚，兩種 Token 即使都長成三段式 JWT，resource 也不能因此共用同一套驗證規則。

這次遇到的問題正好跨過三層。JWT signature 是真的，Cognito 登入也成功，Gateway 還是得依 access-token contract 檢查 resource、client、scope 和 policy input。前面的成功結果無法替後面的授權判斷代簽。

## Lab 02 的四道驗證

Lab 02 把 Token 從「看得懂」走到「可以交給 policy」拆成四道 gate。每一道都留下穩定的拒絕 stage 和 decision code，這樣 on-call 才能分辨問題出在 key、registered claim、OAuth context，還是應用 policy。

![一枚尚未可信的 JWT 依序通過 Header 與 Key、Signature 與 Registered Claims、OAuth Context、Application Policy Inputs。任何一道失敗都回傳對應的拒絕碼，全部通過後 claims 才能進入 policy。](https://raw.githubusercontent.com/MikeHsu0618/2026-ithelp-agent-governance-public/day-10/assets/diagrams/day-08/token-validation-gates.png)

第一道檢查 header 和 key。Server 固定允許 `RS256`，`kid` 只能到預先信任的 JWKS 裡找 key，也不會跟著 Token 內的 `jku` 去抓任意 URL。Lab 使用 `at+jwt` 和 `id+jwt` 做 explicit typing，讓 access token 和 ID token 從入口就走不同規則。

第二道驗 signature、`iss`、`aud`、`exp` 等 registered claims。`iss` 要與預先設定的發行者完全相符，`aud` 要包含目前 resource，時間 claim 也必須落在允許的有效區間。`wrong_issuer` 特別使用同一把 private key 簽署，用來證明 cryptographic verification 成功不會順便替 issuer 的語意背書。

第三道進入 OAuth context，檢查 `token_use`、`client_id` 和 required scope。第四道才處理 `team`、role 或 resource context 等應用 policy input。到這裡即使每個 claim 都存在，policy 仍可能依 action、resource 和環境條件回覆 `DENY`。

[RFC 8725](https://www.rfc-editor.org/rfc/rfc8725.html#name-best-practices) 建議 verifier 固定允許的演算法，也討論 cross-JWT confusion、explicit typing 和外來 `jku`／`x5u` 的風險。同一個平台開始同時處理 ID token、access token 和多個 issuer 後，這些規則很快就會從安全硬化變成日常整合需求。

## Audience 限制 Token 可以送到哪裡

Lab 正向 Token 的 audience 是：

```text
mcp://lab/observability/query
```

`wrong_audience` 只把它換成另一個 resource：

```text
mcp://lab/admin/delete
```

兩枚 Token 的 signature、subject、client 和 scope 都相同，差別只有 `aud`。如果 observability resource 關掉 audience validation，原本簽給 admin resource 的 Token 也可能被接受。當平台上有多個 MCP Server，或 Agent 開始互相呼叫時，這類 Token replay 很難只靠 URL path 看出來。

[RFC 7519](https://www.rfc-editor.org/rfc/rfc7519.html#section-4.1.3) 要求不在 `aud` 裡的 processor 拒絕 Token。[RFC 8725](https://www.rfc-editor.org/rfc/rfc8725.html#section-3.9) 也把 audience validation 列為避免 Token 被換到另一個 context 的手段。對這次的架構來說，`aud` 是 resource boundary，不只是 JWT payload 裡一個有值就好的欄位。

Audience 能證明目前 resource 是預期接收者之一，卻不會直接授權每一個 Tool。`query_logs` 和 `delete_index` 是否允許執行，仍需要 Tool-level policy 依 principal、action、resource 和其他 context 判斷。

## Scope 和 Claim 不在同一層

`scope=observability.query` 是 authorization server 授予的 permission string，適合表達 API 或能力的粗粒度邊界。`team=platform` 則是這個 Lab 用來代表應用 policy context 的合成 claim，應用可以拿它做 ABAC，也可以完全不採用。

兩者的來源和生命週期不同。即使 `team` 存在，平台仍要知道誰能發這個欄位、允許哪些值，以及人員轉組或離職後多久更新。反過來說，只有 scope 也不一定能回答某個高風險 Tool 在目前環境能否執行。

Lab 因此保留兩種錯誤，而不是全部壓成 `invalid_token`：

```text
missing_scope          → SCOPE_MISSING  (OAuth context)
access_missing_team    → CLAIM_MISSING  (Application policy)
```

對外 response 可以維持模糊，不必透露內部政策。內部 audit event 至少要留下拒絕 stage 和 stable code，否則 on-call 很難判斷該找 IdP claim mapping、OAuth client、JWKS rotation，還是應用 policy 的 owner。

我另外整理了一份 [Token Claim Boundary](https://github.com/MikeHsu0618/2026-ithelp-agent-governance-public/blob/day-10/articles/day-08/token-claim-boundary.md)，逐欄記錄每個 claim 能證明什麼，又不能拿來代替什麼。像 `sub` 可以識別 issuer namespace 裡的 subject，卻不能直接複製成 Day 7 的 Human、Service、Agent 和 Workload 四種責任。

## ID Token 有資料，不代表適合拿來打 API

Lab 的 `id_token_has_team` 帶著以下資料：

```json
{
  "sub": "user/sre-oncaller",
  "aud": "sre-console",
  "token_use": "id",
  "team": "platform"
}
```

這枚 Token 在第一道 gate 就得到 `TOKEN_TYPE_INVALID`。`team` 並沒有因為放在 ID token 裡就變成假資料，問題是目前 resource 明確要求 access-token profile，所以 verifier 根本不該讓它走進同一套 policy。

這不是所有 API 都必須遵守的全球禁令。有些產品會明確接受 ID token 作為自己的 authentication credential，Amazon Cognito 文件也描述過這類用法。若產品真的選擇這種 contract，就應該建立獨立 verifier，驗 ID token 的 issuer、client audience、signature、expiry 和 `token_use=id`，而不是讓 endpoint 在兩種 Token 之間任選一枚。

Agent Gateway 和 MCP resource 在這個設計裡採用 OAuth access-token contract。Policy 若需要 `team`，我會回頭調整 access-token claims、scope 或外部 policy data source，不靠另一枚 Token 把資料偷渡進來。

## Cognito 的 Access Token 不能照抄通用範例

公開 Lab 使用 resource-bound `aud`，但它不是 Cognito emulator。Lab 裡的 `at+jwt`／`id+jwt` 是為了示範 mutually exclusive validation rules，Cognito 本身主要使用 `token_use` 區分 Token 類型。

AWS 現行文件還有幾個容易在 generic JWT middleware 裡配錯的差異：

- Cognito ID token 的 `aud` 是 app client ID，access token 則用 `client_id` 表示 app client。
- Access-token `aud` 只有在 authorization request 使用 resource binding 時才會出現，值是預定授權的 API URL。
- Access token 和 ID token 使用不同 signing keys。同一個 session 的兩枚 Token 會有不同 `kid`，兩種 Token 必須獨立驗證。
- Access token 仍要檢查 `token_use=access`、issuer、expiry、client 和 scope。

這些行為可在 [Cognito access token](https://docs.aws.amazon.com/cognito/latest/developerguide/amazon-cognito-user-pools-using-the-access-token.html) 和 [Cognito JWT verification](https://docs.aws.amazon.com/cognito/latest/developerguide/amazon-cognito-user-pools-using-tokens-verifying-a-jwt.html) 交叉確認。Generic library 若一律要求 access token 具備 `aud`，又沒有先確認 Cognito flow 是否用了 resource binding，很容易在「關掉 audience validation」和「所有 request 都失敗」之間做錯選擇。

如果 Gateway policy 需要額外 claim，也要先確認那個 claim 是否真的會出現在 access token。Cognito 的 Pre Token Generation trigger 可以客製 access-token claims，但 Human 和 M2M 適用的 event version、feature plan 及觸發條件並不完全相同。[Pre Token Generation trigger](https://docs.aws.amazon.com/cognito/latest/developerguide/user-pool-lambda-pre-token-generation.html) 應該和實際 app client flow 一起核對，不能只看 Lambda 設定畫面已經啟用就當作完成。

我最後把每條 route 的 Token validation profile 寫成 contract，明確列出接受哪種 Token、信任哪個 issuer、對應哪個 client 和 resource，以及需要哪些 scope 與 claim。IdP 沒有發出 contract 需要的內容時，就修改發行方式或 policy 設計，不在 verifier 裡悄悄少驗一項。

## 完全離線重現

從 repo root 執行以下三個 target：

```bash
make lab-02-up
make lab-02-check
make lab-02-demo
```

`lab-02-check` 目前會跑完整共用 Lab 的 72 個測試，`lab-02-demo` 只執行 Day 8 的七組 JWT case。最後應該看到：

```text
7/7 cases matched
Encoded JWT persisted: no
Private key persisted: no
```

需要讓 CI 或其他工具讀取時，可以改成 JSON output：

```bash
uv run --directory labs/02-identity-boundary \
  identity-boundary run --output json
```

每次 run 都會建立 `manifest.json`、`summary.json`、`events.jsonl`、public `jwks.json`、預期結果和合成 claims。Compact JWT 與 private key 只留在程序記憶體，測試也會掃描 artifact，確認兩者沒有落盤。

清理使用明確的 Lab root 和 ownership marker：

```bash
make lab-02-down
```

Cleanup 只會處理位於 Lab root、不是 symlink，而且帶正確 marker 的 `artifacts/`。它不依賴寬鬆 glob，也不會碰同層的其他目錄。

## 上線前還有四筆驗證責任

這個離線 Lab 固定了 validation boundary，沒有把 JWKS 和 Token lifecycle 的 production 問題一起藏進 demo。真的接 IdP 時，下面四項仍需要平台 owner 做決策：

1. **JWKS rotation 與 outage**：key 要 cache 多久，遇到新 `kid` 何時 refresh，issuer 暫時不可用時接受哪一版既有 cache。
2. **Clock skew 與 token lifetime**：`exp`／`nbf` 可以容忍多少 leeway，應依風險和基礎設施時間同步狀況決定。
3. **Revocation**：JWT 尚未過期，不代表 session、user 或 client 沒被撤銷。短效 Token、revocation state 和高風險操作需要另外設計。
4. **Claim 與錯誤最小化**：Log 不應保存完整 bearer token、email 或所有 groups。對外錯誤可以遮住 policy 細節，內部 evidence 則保留 stage、code、issuer、resource 和 credential fingerprint。

目前的 72 個測試會保護共用 Lab，Day 8 的七組 case 則固定本文討論的 JWT boundary。它們不會替 production 完成 key rotation、即時離職停權或完整 ABAC，這幾筆責任仍要回到實際平台設計裡處理。

## Token 驗過後，責任鏈仍然是空的

經過這一輪調整，Gateway 已經可以確認 Token 由哪個 issuer 發出、交給哪個 resource、由哪個 client 取得，也能分開檢查 scope 和 policy claim。這比單純驗 signature 多了完整的 resource contract，但 audit 目前仍只看得到 Token 內的 subject。

假設 `user/sre-oncaller` 要求 `sre-investigator@v1` 執行查詢，真正送出 request 的又是 Kubernetes 裡另一個 runtime，單靠 access token 無法把三者的責任串回來。把 Agent 或 Pod 名稱繼續塞進 claims，只會讓 Token 越來越胖，仍然沒有一份可查詢的委派關係。

Day 9 會沿用同一個 Lab，替 Human、Agent、Workload 和 credential context 定義 Delegation Context。下一個要解的問題，是如何在不偽造身分的前提下，讓每次 Tool Call 留下一條完整的責任鏈。
