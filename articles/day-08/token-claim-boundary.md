# Token Claim Boundary：每個欄位到底證明什麼

這張表服務 Day 8 的設計審查，不能拿來「看見 claim 就信任」。所有 payload claim 都要在 signature、issuer、audience 與 time validation 通過後，才有資格進入 policy。

| 欄位 | 能回答的問題 | 不能回答的問題 | Lab 02 檢查 |
| --- | --- | --- | --- |
| `alg` | Token 宣告使用哪個簽章演算法 | 宣告的演算法是否被應用接受 | 固定 allowlist `RS256`，不由 Token 自選 |
| `kid` | 應在受信任 JWKS 裡找哪把 public key | 哪個遠端 URL 值得信任，`kid` 也不是檔案路徑 | 限制字元與長度，且必須唯一匹配 trusted JWKS |
| signature | Header／payload 是否與該 private key 的簽章相符 | issuer、audience、Token 用途或授權是否正確 | 使用選定 public key 驗證 |
| `iss` | 哪個 authorization／identity authority 發出 assertions | 這枚 Token 是否給目前 resource | 與預先設定的 trusted issuer 完全匹配 |
| `aud` | 目前 resource 是否是預期接收者之一 | 呼叫者可執行哪個 Tool | 與 `mcp://lab/observability/query` 匹配 |
| `exp`／`iat` | Token 的有效時間窗 | Token 是否已被提前撤銷 | 過期拒絕，production 另決定 clock skew／revocation |
| `typ`／`token_use` | 這是哪一類 Token，預定用在哪個 protocol context | 使用者對 resource 的權限 | Lab 用 `at+jwt`，Cognito 整合另驗 `token_use=access` |
| `sub` | issuer namespace 裡的 subject identifier | Agent 版本、執行 Pod，或完整 delegation chain | 保存 verified subject，不複製成四種 actor |
| `client_id` | 哪個 OAuth app client 參與並取得 access token | public client 是否持有 secret，或哪個 workload 實際送出 request | 必須匹配預期 client |
| `scope` | authorization server 授予哪些 OAuth permission strings | business policy 是否有足夠屬性，或某個 Tool 一定能執行 | 必須包含 `observability.query` |
| `team`（示例） | issuer 提供給應用 policy 的合成屬性 | claim 是否仍符合即時組織狀態，單靠存在也不等於 ALLOW | 缺少時回 `CLAIM_MISSING` |

## Review 時依序問

1. Key 從哪個已設定的 issuer／JWKS 取得？程式是否會跟隨外來 `jku`？
2. Access token 的 expected audience／resource 是什麼？若 IdP 不發 resource-bound `aud`，架構怎麼補這條邊界？
3. Resource 要求的是 ID token 還是 access token？Verifier 是否用 mutually exclusive rules 分開驗？
4. Scope 由哪個 app client／flow 取得？它授權到 API、route 還是 Tool？
5. Policy 還需要哪些 claim？這些 claim 是否真的存在於送到 resource 的 Token，而不只存在另一枚 Token？
6. Log 只記 stable decision code，還是把整枚 Token／所有 claims 都寫進去了？

## Cognito 對照提醒

- ID token 的 `aud` 對應 app client，access token 使用 `client_id` 表示 app client。
- 現行 AWS 文件說 access-token `aud` 只有在 request 使用 resource binding 時才出現，值是預定授權的 API URL。沒有 resource binding 時，不要為了讓 generic validator 過關而關掉所有 audience／resource boundary。
- Access token 與 ID token 使用不同 signing keys。同一 session 的 `kid` 不會相同，兩者要分開驗。
- Access token 若需要額外 policy claims，先核對 Cognito Pre Token Generation event version、feature plan 與 Human／M2M flow。不要假設 ID token 的 custom attributes 會原封不動複製過去。

官方依據：[Cognito access token](https://docs.aws.amazon.com/cognito/latest/developerguide/amazon-cognito-user-pools-using-the-access-token.html)、[Cognito JWT verification](https://docs.aws.amazon.com/cognito/latest/developerguide/amazon-cognito-user-pools-using-tokens-verifying-a-jwt.html)、[Pre Token Generation trigger](https://docs.aws.amazon.com/cognito/latest/developerguide/user-pool-lambda-pre-token-generation.html)、[RFC 8725](https://www.rfc-editor.org/rfc/rfc8725.html)。
