# Day 8｜JWT 驗證實戰：從 Issuer、Audience、Scope 到 Cognito Token 差異

把 Cognito 接進 Gateway 時，Human SSO 已經能登入，Gateway 也能驗過 JWT signature。我原本以為 Identity 最麻煩的部分到這裡就結束了，剩下只是把 policy 需要的 claim 名稱填進設定檔。

實際拿 ID token 和 access token 對照後，問題才浮出來。授權規則需要的 `team` 出現在 ID token，送往 API 的 access token 卻沒有。登入成功、Token 由正確的 Cognito User Pool 簽發，都無法替 Gateway 補上缺少的 policy input。

改送資料比較完整的 ID token 看起來最省事，我們最後沒有這樣做。MCP resource 的 contract 要求 access token，就應該補齊 access-token claim、scope 或外部 policy data，而不是因為另一枚 Token 剛好有資料，就放寬 API 的驗證規則。

## Lab：JWT 驗證案例

我把這個落差整理成可離線執行的 [Lab 02](https://github.com/MikeHsu0618/2026-ithelp-agent-governance-public/blob/day-08-r1/labs/02-identity-boundary/README.md)。Lab 使用本機 ephemeral issuer 產生合成 Token，不會連到私有 Cognito 設定。正文先看最能影響設計的四組結果：

| Case | 結果 | 停下來的原因 |
| --- | --- | --- |
| `valid_access` | `ALLOW` | access token、resource、scope 與 policy claim 都符合 |
| `wrong_audience` | `DENY` | Token 不是發給這個 resource |
| `access_missing_team` | `DENY` | Token 合法，但缺少 policy 需要的 claim |
| `id_token_has_team` | `DENY` | 資料存在，Token 用途不符合 API contract |

四枚 Token 都由同一個 issuer key 簽出，signature 也都能驗證。差異發生在簽章之後：`wrong_audience` 不屬於目前的 resource，`access_missing_team` 缺少應用政策輸入，帶著 `team=platform` 的 ID token 則因用途錯誤而更早被拒絕。

![Lab 02 的實際 CLI 結果：七組 Token case 只有 valid_access 被放行，其他案例分別在 header、claims 或 policy 階段被拒絕。](https://raw.githubusercontent.com/MikeHsu0618/2026-ithelp-agent-governance-public/day-08-r1/assets/screenshots/day-08/01-jwt-boundary-results.png)

截圖列出完整七組結果，另外包含錯誤 issuer、過期 Token 和缺少 scope。原始 summary、JSONL event 與重現方式都放在 [Day 8 evidence](https://github.com/MikeHsu0618/2026-ithelp-agent-governance-public/blob/day-08-r1/assets/screenshots/day-08/evidence.md)，指令和錯誤碼不需要從圖片抄回來。

## JWT 進入 Policy 前的驗證流程

JWT payload 很容易 decode，開發時也常先把 `sub`、`team` 和 `scope` 印出來確認。Decode 只讓我們看見內容，還沒有證明內容由誰簽發、要交給哪個 resource，或現在是否仍在有效時間內。

Lab 將 Token 進入應用 policy 前的檢查分成四道：

![一枚尚未可信的 JWT 依序通過 Header 與 Key、Signature 與 Registered Claims、OAuth Context、Application Policy Inputs。任何一道失敗都回傳對應拒絕碼，全部通過後 claims 才能進入 policy。](https://raw.githubusercontent.com/MikeHsu0618/2026-ithelp-agent-governance-public/day-08-r1/assets/diagrams/day-08/token-validation-gates.png)

1. **Header 與 Key**：固定可接受的演算法，使用 `kid` 從受信任的 JWKS 找 key。Verifier 不會跟著 Token header 裡的 `jku` 或 `x5u` 到任意位置下載金鑰。
2. **Signature 與 Registered Claims**：驗證 signature、`iss`、`aud`、`exp` 等欄位。Lab 的 `wrong_issuer` 刻意沿用同一把 signing key，證明簽章正確不會順便讓 issuer 變可信。
3. **OAuth Context**：確認 Token 用途、client 與 required scope，避免 ID token 和 access token 共用同一套驗證規則。
4. **Application Policy Inputs**：處理 `team`、role、resource context 與業務限制。Claim 通過驗證，只代表 policy 可以使用它，不保證結果一定是 `ALLOW`。

[RFC 8725](https://www.rfc-editor.org/rfc/rfc8725.html) 建議由應用固定演算法、驗證 audience，並為不同種類的 JWT 使用互斥規則。這些檢查放在同一條 pipeline 裡很合理，但失敗階段必須留下來，否則 on-call 最後只會看到一大片 `401 invalid token`。

## Audience、Scope、Claim 與 Token Type

`wrong_audience` 的 subject、client、scope 和 signature 都沒有問題，只有 `aud` 指向 `mcp://lab/admin/delete`，目前的 observability resource 因此拒絕它。[RFC 7519](https://www.rfc-editor.org/rfc/rfc7519.html#section-4.1.3) 將 `aud` 定義為 Token 預定的接收者。Audience 能隔開 resource，卻不會替每個 Tool 做授權。`query_logs` 和 `delete_index` 是否允許，仍由 Tool policy 根據 principal、action 與 resource 決定。

`missing_scope` 和 `access_missing_team` 會在不同階段停下。`scope=observability.query` 是 Authorization Server 授予 client 的 API 能力，`team=platform` 則是這個 Lab 提供給應用 policy 的合成屬性。缺 scope 要回頭檢查 OAuth client 與授權請求，缺 `team` 則要檢查 IdP mapping、Token customization 或 policy data source。兩者都寫成「權限不足」，值班時很難知道該找誰。

`id_token_has_team` 最容易讓人走捷徑。這枚 Token 有 policy 想要的使用者資料，卻是用來描述登入結果的 ID token。目前 MCP API 明確採用 access-token contract，所以 verifier 在它進入 policy 前就回覆 `TOKEN_TYPE_INVALID`。若另一個產品選擇接受 ID token，它也應有獨立的 validation profile，而不是讓 endpoint 在兩種 Token 之間任選資料比較多的一枚。

每個 claim 可以回答與不能回答的問題，我整理在 [Token Claim Boundary](https://github.com/MikeHsu0618/2026-ithelp-agent-governance-public/blob/day-08-r1/articles/day-08/token-claim-boundary.md)。那張表也刻意把 signature、issuer、audience、scope 與應用屬性分開，避免「payload 看得到」被誤認成「policy 已經可以相信」。

## Cognito Access Token 的驗證條件

公開 Lab 使用 `at+jwt` 和 `id+jwt` 做 explicit typing，方便讀者看出兩套互斥規則。它不是 Cognito emulator。Cognito 主要使用 `token_use` 區分 ID token 與 access token，App client 和 resource audience 的欄位也與通用範例不完全相同。

| 驗證項目 | Cognito 實際要注意的差異 |
| --- | --- |
| Token purpose | API 接受 access token 時，檢查 `token_use=access` |
| App client | ID token 以 `aud` 表示 app client，access token 使用 `client_id` |
| Resource audience | Access token 只有在授權請求使用 resource binding 時才帶對應的 `aud` |
| Signing key | 同一個 session 的 ID token 與 access token 可能使用不同 `kid`，必須各自驗證 |

這些差異可以從 AWS 的 [Cognito access token](https://docs.aws.amazon.com/cognito/latest/developerguide/amazon-cognito-user-pools-using-the-access-token.html) 和 [JWT verification](https://docs.aws.amazon.com/cognito/latest/developerguide/amazon-cognito-user-pools-using-tokens-verifying-a-jwt.html) 文件交叉確認。Generic middleware 如果一律要求 access token 帶 `aud`，卻沒有確認該 flow 是否使用 resource binding，很容易遇到所有 request 都失敗，最後又用關閉 audience validation 的方式硬救。

Cognito 的 [Pre Token Generation trigger](https://docs.aws.amazon.com/cognito/latest/developerguide/user-pool-lambda-pre-token-generation.html) 可以客製 access-token claims。Human access token 需要 V2 或 V3 event，M2M customization 則需要 V3，還會受到 user-pool feature plan 影響。Console 顯示 Lambda 已啟用，不足以證明每一條 OAuth flow 都會得到相同 claim shape，驗收時仍要拿各 flow 實際簽出的 access token 比對。

我們最後為每條 API route 寫下自己的 validation profile：

```text
token type      access
trusted issuer  Cognito User Pool issuer
client          allowed app client IDs
resource        expected audience（該 flow 使用 resource binding 時）
permissions     required scopes
policy inputs   required claims and trusted sources
```

如果 IdP 沒有發出 contract 需要的資料，就修改發行方式或 policy 設計。Verifier 不會為了讓 request 通過，默默少驗一項。JWKS rotation、clock skew、revocation 與錯誤遮罩仍是 production 要處理的工作，但不影響這份 route contract 的基本順序。

## 執行 JWT Boundary Lab

從 repo root 執行以下兩條指令，就能重現七組正負案例：

```bash
make lab-02-up
make lab-02-demo
```

Lab 會輸出每個 case 的 decision code，並將 machine-readable evidence 寫進 artifacts。Compact JWT 和 private key 只留在程序記憶體，不會進入公開證據。

完成這輪驗證後，Gateway 已經能確認目前 Token 由哪個 issuer 發出、預定交給哪個 resource、由哪個 client 取得，也能分開處理 scope 與應用 claim。它仍然只看得到當前 credential 的 subject。

Agent artifact 和實際執行的 Kubernetes Workload 不會自己出現在 access token 裡。Day 9 會沿用同一個 Lab，將 Gateway、Agent runtime 與 Kubernetes 各自看到的證據放進 Delegation Context，並區分「流程本來沒有這個角色」與「證據在途中遺失」。
