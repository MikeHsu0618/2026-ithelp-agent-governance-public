# Day 14｜Virtual Key 不能代替企業身分，但能隔離 Agent Workload

評估 LiteLLM 時，我們最後沒有採用，其中一個顧慮就是 virtual key 帶來的身分管理。幾個月後接 kagent 的 LLM path，我卻又在 agentgateway 前面替每個 runtime 放了一把 static consumer key。兩邊都是 bearer secret，表面上看起來像是前後矛盾。

差別出在 key 代表的對象。把一把 key 標成值班工程師，平台便要接手登入、MFA、team 異動、停權、離職、遺失與重發。若它只代表 `workload/runtime-a`，責任會縮到 secret delivery、rotation、爆炸半徑與 provider credential isolation。前者牽涉 Human identity lifecycle，後者處理 machine consumer boundary。

這也是我後來評估 credential 的方式。碰到 API key、virtual key 或 JWT 時，我會先找出它代表的 actor，以及誰能撤銷它，再判斷它適不適合放在這條路徑。

## Human virtual key 多出一套 lifecycle

Virtual key 對 LLM Gateway 很實用。它可以替 consumer 分開 budget、rate limit、usage 與 provider access，也能把實際的 provider credential 留在 Gateway 後面。這些功能正是 LiteLLM 當時進入候選名單的原因，不過一旦拿它映射 Human，Gateway 就得多維護下面這條 lifecycle：

```text
企業 IdP 的值班工程師
    ↓ 另做 mapping
Gateway user / team
    ↓ 發 virtual key
LLM usage / budget / provider access
```

企業 IdP 原本已經知道值班工程師是否在職、屬於哪個 team、能否登入，以及有沒有通過 MFA。Gateway database 再保存一份 `值班工程師 → user → team → virtual key` 後，offboarding 便多了一條同步路徑。Team change、key 撤銷、UI 或 API 造成的 drift 都需要 owner，兩邊資料不一致時還得決定相信哪一邊。

一把 key 上的 `user=sre-oncaller`，只能說明 Gateway 找到了這筆 metadata。它無法證明值班工程師剛剛完成登入，也無法證明帳號目前有效。若產品另外整合 IdP 或 SCIM，當然可以補上 lifecycle，但單靠 key mapping 不會自然得到這項能力。

因此，我們沒有讓 virtual key 承擔企業 Human identity。它仍可管理用量與 provider access，只是 Human lifecycle 繼續以企業 IdP 為準。

## Static-only runtime 的 credential boundary

後來串 kagent 的 LLM path 時，限制完全不同。我當時使用的 runtime path 接受 API key，卻不會替平台完成 OAuth login、取得短效 Token，再處理 cache、expiry 與 refresh。硬把 Human OAuth 塞進去，只會把 credential lifecycle 搬進原本不負責這件事的 runtime，因此我們留下的是一條很單純的兩段式 credential 路徑：

```text
kagent runtime
    │ agentgateway consumer key
    ▼
agentgateway
    │ provider key
    ▼
LLM provider
```

Consumer key 從頭到尾只代表 runtime。Audit 記錄的是 `workload/runtime-a`，Human 欄位明確寫成 `NOT_APPLICABLE`。如果上游還需要知道是哪一位使用者發起請求，就要另外傳遞可驗證的 Human 與 delegation context，不能把 runtime key 改名成某位值班工程師。

Static bearer key 仍然有明顯限制。它可能被複製，無法證明是哪一個 Pod instance，也沒有 workload attestation。不過在 runtime 只接受 API key 的條件下，它至少能隔離不同 consumer，避免 provider key 散進每個 Agent deployment。

## Lab 03：同一個 Gateway 比較三種 credential

[Lab 03](https://github.com/MikeHsu0618/2026-ithelp-agent-governance-public/blob/day-14/labs/03-gateway-runtime/README.md) 只有一個 agentgateway 與一個 synthetic OpenAI-compatible backend。Human key、workload key 與 Human JWT 都呼叫 `/v1/chat/completions`，成功的 request 再由 backend authentication 換成 provider key。

這裡要先釐清產品名稱。LiteLLM 的 virtual key 是前面那段實務選型的對象，Lab 使用的是 agentgateway API key policy 加上 metadata，用來重現相同的 identity mapping 問題。`consumer key` 是本文為了區分用途採用的名稱，並不是 agentgateway 另一種正式 credential type。

![Human key、Workload key 與 Human JWT 各自經過 agentgateway 的驗證與 backend authentication。Human key 未收到 IdP 停權資訊，因此仍回 200。Workload retired key，以及 issuer 或 audience 錯誤或缺漏的 JWT，都在 Gateway 被拒絕。](https://raw.githubusercontent.com/MikeHsu0618/2026-ithelp-agent-governance-public/day-14/assets/diagrams/day-14/credential-boundary.png)

API key route 採用 strict mode，把兩把有效 key 對到不同 metadata。官方 [API Key authentication](https://agentgateway.dev/docs/standalone/latest/documentation/configuration/security/apikey-authn/) 文件對這項能力的描述，也是先驗 key，再讓後續 policy 使用 associated metadata。Metadata 可以做 attribution，但它仍是 Gateway 內的 mapping，不是企業目錄的即時狀態。

```yaml
apiKey:
  mode: strict
  keys:
  - key: <ephemeral-human-key>
    metadata:
      kind: HUMAN_VIRTUAL_KEY
      human: user/sre-oncaller
      workload: NOT_APPLICABLE
  - key: <ephemeral-workload-key>
    metadata:
      kind: WORKLOAD_CONSUMER_KEY
      human: NOT_APPLICABLE
      workload: workload/runtime-a
```

JWT route 會用 JWKS 驗 RSA signature，並檢查 issuer、audience、`token_use` 與 scope。完整設定放在 [agentgateway.example.yaml](https://github.com/MikeHsu0618/2026-ithelp-agent-governance-public/blob/day-14/labs/03-gateway-runtime/configs/agentgateway.example.yaml)，讀者可以直接複製，不必從文章片段拼回去。

```bash
make lab-03-runtime-up
make lab-03-runtime-run
```

Runner 每次建立新的 Human key、workload key、provider key 與 RSA signing key，raw credential 只存在 temporary directory 與 process memory。公開 artifact 只保存短指紋、redacted config、public JWKS 與 decision event。本文的實務取捨來自去識別化的 LiteLLM、kagent 與 agentgateway 操作紀錄，HTTP 結果則由這個 standalone Lab 重現，不拿它冒充 Kubernetes production topology。

## Human key mapping 沒收到停權事件

第一個 case 把 directory state 設成 `ACTIVE`，Gateway 收到 key 後找到 `user/sre-oncaller`，request 得到 HTTP `200`。第二個 case 使用完全相同的 key 與 Gateway mapping，只把外部 directory state 改成 `DISABLED`，結果仍然是 `200`。

```text
human-key-active             ALLOW  KEY_MAPPING_ACTIVE
human-key-after-offboarding  ALLOW  STALE_MAPPING_ALLOWED
```

Gateway 沒有查詢這份 synthetic directory state，所以它並不是看見停權資料後仍決定放行。它只知道 key 有效、metadata 存在，而且 route 可以走。Lab 的評估器會把 HTTP decision 與治理結果分開，避免把成功重現的風險算成安全控制通過。

```text
gateway_decision = ALLOW
control_result   = RISK_EXPOSED
code             = STALE_MAPPING_ALLOWED
```

這組輸出也說明了為什麼測試報告不能只寫 `matched 9/9`。九個觀察都符合預期，其中一個預期就是 offboarding gap 確實存在，必須連同 `control_result` 與穩定代碼一起閱讀。

## Workload key 只管 runtime

Workload path 使用另一把 key，metadata 只有 `workload/runtime-a` 與 `consumer=key/runtime-a`。目前的 key 得到 `200`，輪替掉的舊 key 已從 allowlist 移除，因此得到 `401`。

```text
workload-key          ALLOW  WORKLOAD_KEY_ISOLATED
retired-workload-key  DENY   OLD_KEY_REJECTED
```

這個控制讓 runtime-A 的 key 外洩時不必同時撤銷 runtime-B，也讓 Agent deployment 不需要直接持有 provider key。Usage 與 rate limit 暫時可以歸到一個 machine consumer，Human attribution 則由另一條 context 處理。

輪替仍有維運成本。Runtime 必須 reload 或重新部署，secret delivery 出錯也會直接中斷服務。若風險模型要求辨認特定 Pod instance，就要再接 Kubernetes ServiceAccount federation、SPIFFE 類機制或同等的 attestation，不能把 metadata 裡的 workload 名稱當成密碼學證據。

## JWT 的 issuer 與 audience 必須存在

Human JWT 延續 Day 12 的 claim contract，包含 `iss`、`aud`、`sub`、`client_id`、scope、`token_use` 與五分鐘效期。與 caller 自己填一組 header 相比，Resource 可以用 JWKS 驗證簽章與發行者，再決定這個 Token 是否屬於自己的 audience。

第一版 Lab 鎖在 agentgateway `1.4.1`，當時只測 valid token 與 wrong audience。我在這次發稿 review 重新讀 release note，才發現 `1.4.x` 及更早版本只有在 Token 帶著 `iss` 或 `aud` 時才會比較設定值。拿掉 claim 再跑一次，兩個 request 都回了 `200`。

```text
agentgateway 1.4.1 review case

jwt-missing-issuer    ALLOW
jwt-missing-audience  ALLOW
```

這個結果改變了文章與 Lab。公開版本升到 pinned agentgateway `1.5.0`，並把 wrong issuer、wrong audience、missing issuer 與 missing audience 全部加入測試。官方 [JWT authentication](https://agentgateway.dev/docs/standalone/latest/documentation/configuration/security/jwt-authn/) 文件提供現行設定方式，[release notes](https://agentgateway.dev/docs/standalone/latest/release-notes/release-notes/) 則明確記錄了這項版本差異。

```text
jwt-human             ALLOW  JWT_PRINCIPAL_VERIFIED
jwt-wrong-issuer      DENY   JWT_ISSUER_REJECTED
jwt-wrong-audience    DENY   JWT_AUDIENCE_REJECTED
jwt-missing-issuer    DENY   JWT_ISSUER_REQUIRED
jwt-missing-audience  DENY   JWT_AUDIENCE_REQUIRED
```

升版後的結果能證明 signature、issuer 與 audience boundary，仍然不能保證 instant offboarding。值班工程師被停用時，已發出的 access token 何時失效，取決於 TTL、revocation、session 與 Gateway cache 設計。這也是 JWT 與企業 lifecycle 之間仍要保留的一條責任線。

## Caller credential 到 Gateway 為止

四條成功路徑進入 backend 前，都由同一個 backend-auth policy 注入 provider key。agentgateway 的 [backend authentication](https://agentgateway.dev/docs/standalone/latest/documentation/configuration/security/backend-authn/) 文件說明，incoming authentication 驗證過的 credential 預設會從 request 移除，Gateway 可以再掛上 backend 專用 credential。

Synthetic provider 會檢查收到的 `Authorization` 必須等於本次 ephemeral provider key，且不得等於 Human key、workload key 或 JWT。它只把 SHA-256 短指紋寫進 evidence。Artifact 完成後，Runner 還會掃描整個 run directory，任何 raw credential 落盤都會讓 command 失敗。

這次檢查的是實際 backend behavior，不是從架構圖推論 provider key 已被隔離。Backend authentication 只決定 Gateway 如何向上游證明自己，caller 能不能通過仍由入口的 authentication 與 authorization policy 負責。

## 九組結果與 credential 決策表

![Day 14 實際 Lab terminal card。Human key 在外部目錄停權後仍 ALLOW，標成 RISK_EXPOSED。Workload retired key，以及 issuer 或 audience 錯誤或缺漏的 JWT，都被拒絕。](https://raw.githubusercontent.com/MikeHsu0618/2026-ithelp-agent-governance-public/day-14/assets/screenshots/day-14/01-credential-boundary-results.png)

圖片來自本次 `make lab-03-runtime-run` 的真實輸出。可複製指令、machine-readable report 與 hash 保存在 [Screenshot Evidence](https://github.com/MikeHsu0618/2026-ithelp-agent-governance-public/blob/day-14/assets/screenshots/day-14/evidence.md)，因此讀者不必從圖片手動抄字。

| Case | Gateway | Control | Human | Workload | Upstream |
| --- | --- | --- | --- | --- | --- |
| Human key，值班工程師 active | ALLOW | `CONTROL_OK` | `user/sre-oncaller` | `NOT_APPLICABLE` | provider key matched |
| 同一把 key，值班工程師 disabled | ALLOW | `RISK_EXPOSED` | stale `user/sre-oncaller` | `NOT_APPLICABLE` | provider key matched |
| Workload 新 key | ALLOW | `CONTROL_OK` | `NOT_APPLICABLE` | `workload/runtime-a` | provider key matched |
| Workload retired key | DENY | `CONTROL_OK` | `NOT_OBSERVED` | `NOT_OBSERVED` | backend 未抵達 |
| Human JWT | ALLOW | `CONTROL_OK` | `user/sre-oncaller` | `NOT_APPLICABLE` | provider key matched |
| Wrong-issuer JWT | DENY | `CONTROL_OK` | `NOT_OBSERVED` | `NOT_OBSERVED` | backend 未抵達 |
| Wrong-audience JWT | DENY | `CONTROL_OK` | `NOT_OBSERVED` | `NOT_OBSERVED` | backend 未抵達 |
| Missing-issuer JWT | DENY | `CONTROL_OK` | `NOT_OBSERVED` | `NOT_OBSERVED` | backend 未抵達 |
| Missing-audience JWT | DENY | `CONTROL_OK` | `NOT_OBSERVED` | `NOT_OBSERVED` | backend 未抵達 |

若要帶進自己的架構 review，可以直接複製完整的 [Credential Decision Table](https://github.com/MikeHsu0618/2026-ithelp-agent-governance-public/blob/day-14/articles/day-14/credential-decision-table.md)。除了產品支援哪種 credential，表裡還要填 authoritative source、lifecycle owner、rotation、delegation evidence 與 fallback behavior。

## Production 還需要補的控制

這個 Lab 把變因縮到 credential boundary，沒有處理 static key 應放在 Kubernetes Secret 或外部 secret manager，也沒有實作雙 key overlap、hot reload 與 rolling restart。IdP 停用帳號後的 Token 壽命，以及 policy service 故障時要 fail closed 或使用 cache，同樣要由 production 設計回答。

Agent 代表 Human 行動時，還得把 `sub`、client、Agent chain 與 executing workload 放進同一份 audit event。Day 9 已先定義 Delegation Context，Day 20 之後會把這些欄位接進 LGTM。到了這裡，Human identity、workload consumer 與 provider credential 已經能分開處理，不需要再靠一把 key 同時扮演三個角色。

實務架構還留著既有 Ingress，這會把問題帶到 traffic path。若 edge 與 Agent Gateway 同時處理 auth、retry、header 或 streaming，剛釐清的 credential boundary 又會變得模糊。Day 15 會拆解 production 裡的責任分工，同時保留公開 Lab 的單層 agentgateway，讓讀者不用多除錯一層 proxy。
