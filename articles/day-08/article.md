# Day 8｜JWT 驗證實戰：從 Issuer、Audience、Scope 到 AWS Cognito Token 差異

把 AWS Cognito 接進 Gateway 時，員工已經能登入，Gateway 也能驗過 JWT 簽章。我原本以為最麻煩的身分問題已經過去，接下來只要把 policy 需要的 claim 名稱填進設定檔。實際攤開 ID token 和 access token，才發現授權規則要用的 `team` 出現在前者，送往 API 的後者卻沒有。

一種看似方便的做法，是改送資料比較完整的 ID token。我們最後保留了 MCP API 的 access-token contract，回頭處理 access token 要帶哪些資訊，以及哪些資訊該由其他 policy data 提供。要看懂這個取捨，先不用跑 Lab，從一枚 JWT 裡有什麼開始。

## 先看一枚 JWT 裡裝了什麼

JWT 在傳輸時是一段以句點分隔的 `header.payload.signature`。Header 會指出簽章演算法與找金鑰用的 `kid`。Payload 放 claims，Signature 讓接收者檢查內容是否被竄改。下面是**合成、解碼後的 access-token payload**，只挑與本文有關的欄位，並非可使用的憑證：

```json
{
  "iss": "https://cognito-idp.ap-northeast-1.amazonaws.com/ap-northeast-1_EXAMPLE",
  "sub": "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
  "client_id": "demo-console",
  "token_use": "access",
  "scope": "observability-mcp/query",
  "exp": 1893456000
}
```

`iss` 指出誰簽發、`sub` 指向使用者、`client_id` 指出取得 Token 的 app client，`scope` 是授予的 API 能力，`exp` 是到期時間。這份 access token 沒有 `team`，也沒有 `aud`。後者在 AWS Cognito 的 access token 裡，與授權流程是否使用 resource binding 有關，不能只因為一般 JWT 範例都有，就假設它一定存在。

同一次登入的 ID token 可能另外帶著這段使用者資料。這裡的 `team` 是我們應用需要的自訂屬性，不是 AWS Cognito 預設會發出的 claim：

```json
{
  "token_use": "id",
  "aud": "demo-console",
  "team": "platform"
}
```

兩段 JSON 解釋了當時為什麼會卡住：policy 想讀 `team`，而 API 接受的那枚 Token 沒有。把 ID token 拿來呼叫 API，等於因為資料剛好在另一張證件上，就改了接收規則。更重要的是，**能把 Payload 解碼出來，不代表它已通過驗證**。上面任何欄位都不該在驗簽與檢查用途之前交給 policy。

## Gateway 收到 Token 後要查什麼

我會按接收端的問題來看，而不是把 claims 當成一張名詞表。先確認使用的是預期的演算法與受信任 JWKS 中的 key，再驗簽、檢查 issuer 與期限。接著確認 Token 是給眼前的 API 使用，以及它的用途、client 和 scope 是否符合這條 route，最後才讓 `team` 這類應用屬性進入 policy。

![JWT 從 Header 與 Key、Signature 與標準 Claims、OAuth Context，到 Application Policy Inputs 的驗證順序。任一階段失敗都不把 claims 交給後面的 policy。](https://raw.githubusercontent.com/MikeHsu0618/2026-ithelp-agent-governance-public/day-08-r2/assets/diagrams/day-08/token-validation-gates.png)

Audience、scope 和 `team` 回答的不是同一題。Audience 指向 Token 預定的接收者，scope 表示授權伺服器給了 client 哪類 API 能力，`team` 則可能是我們自己的政策輸入。即使 Token 的簽章正確、scope 也包含查詢權限，仍不表示任意團隊都能查任意資源。反過來說，缺少 `team` 也不是要把 audience 或簽章檢查關掉。RFC 的 [JWT Audience 定義](https://www.rfc-editor.org/rfc/rfc7519.html#section-4.1.3) 與 [JWT 安全建議](https://www.rfc-editor.org/rfc/rfc8725.html) 分別說明了接收者限制，以及不同用途 Token 應使用清楚分開的驗證規則。

## AWS Cognito 有自己的 Token 形狀

這裡有個通用 JWT middleware 很容易踩到的差異：AWS Cognito 的 ID token 用 `aud` 指向 app client，access token 則有 `client_id`。Access token 只有在相應的 resource binding 流程中才會帶 resource `aud`。接收 API 時還要檢查 `token_use=access`，不能只看兩枚 Token 都來自同一個 User Pool。同一次登入的 ID token 與 access token 也可能有不同的 `kid`，必須各自用 JWKS 驗證。這些欄位可對照 AWS 的 [access token](https://docs.aws.amazon.com/cognito/latest/developerguide/amazon-cognito-user-pools-using-the-access-token.html) 與 [JWT 驗證](https://docs.aws.amazon.com/cognito/latest/developerguide/amazon-cognito-user-pools-using-tokens-verifying-a-jwt.html) 文件。

我們遇到的 `team` 落差，不能靠 Gateway 猜出來。若 API 真要依它做 policy，就得選擇讓 access token 帶所需 claim，或從可信的外部資料來源補足。AWS Cognito 的 [Pre Token Generation trigger](https://docs.aws.amazon.com/cognito/latest/developerguide/user-pool-lambda-pre-token-generation.html) 能客製 claims，但 Human access token 與 M2M token 所需的 event version 不同，也受 User Pool 功能方案影響。這是設定時要查的產品條件，不是把 ID token 改名成 access token 就能繞過的問題。

每條 API route 因此需要自己的接受條件。例如觀測查詢 API 要接受 AWS Cognito 發出的 access token、限定 app client、要求查詢 scope，並決定這條 Human flow 是否使用 resource-bound audience。`team` 若是必要的 policy input，還要明確約定它從哪裡來。對 M2M 不能直接照抄 Human 的 `sub` 與 audience 要求，Day 12 會再拆開這兩條路。常用 claim 能提供什麼、不能提供什麼，可用 [Token Claim Boundary](https://github.com/MikeHsu0618/2026-ithelp-agent-governance-public/blob/day-08-r2/articles/day-08/token-claim-boundary.md) 對照。

## 用 Lab 看錯誤會停在哪裡

理解上述差異後，再跑 [Lab 02](https://github.com/MikeHsu0618/2026-ithelp-agent-governance-public/blob/day-08-r2/labs/02-identity-boundary/README.md) 比較有意思。它用本機暫時建立的 issuer 簽出**合成 Token**，不是 AWS Cognito 模擬器，也不會連到我們的私有設定。Lab 特意讓幾枚 Token 都能驗簽，觀察「簽章正確」之後還會在哪一關停下：

| 合成案例 | 結果 | 對應的實務問題 |
| --- | --- | --- |
| `valid_access` | `ALLOW` | 接收者、用途、scope 與 policy input 都符合 |
| `wrong_audience` | `DENY` | Token 不是給眼前的 resource |
| `access_missing_team` | `DENY` | Token 合法，卻缺少應用政策需要的資料 |
| `id_token_has_team` | `DENY` | `team` 有值，但 ID token 不是這條 API 接受的憑證 |

![Lab 02 的 CLI 結果：同一組 JWT 驗證案例中，只有符合 API contract 的 access token 被放行，其餘案例在不同階段被拒絕。](https://raw.githubusercontent.com/MikeHsu0618/2026-ithelp-agent-governance-public/day-08-r2/assets/screenshots/day-08/01-jwt-boundary-results.png)

截圖另列出 issuer 錯誤、過期和 scope 不足等案例。這份 Lab 使用 `at+jwt`／`id+jwt` 明確區分合成 Token。接 AWS Cognito 時，應改依它實際發出的 `token_use` 等欄位設定規則，不能把 Lab 的 header 原樣抄到正式環境。要自己重現，從 repo root 執行：

```bash
make lab-02-up
make lab-02-demo
```

詳細結果與機器可讀紀錄放在 [Day 8 Lab 結果](https://github.com/MikeHsu0618/2026-ithelp-agent-governance-public/blob/day-08-r2/assets/screenshots/day-08/evidence.md)，不需要從圖片抄指令。這篇想帶走的是判斷順序：先決定 API 接受哪種 Token，再檢查它是不是由可信 issuer 簽給眼前的資源、是否具備必要 scope，最後才讀取政策屬性。Gateway 做完這些，知道的仍只是**眼前這枚憑證**。當請求繼續交給 Agent 和下游服務，原本的交辦者要怎麼跟著留下來，就是 Day 9 要處理的事。
