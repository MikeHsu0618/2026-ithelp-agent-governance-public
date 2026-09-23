# Day 14｜認識 AI Gateway Virtual Key：企業身分與 Agent Workload 的使用邊界

評估 LiteLLM 時，我們沒有採用的其中一個顧慮，是 Virtual Key 帶來的 Human Identity 管理。幾個月後接 kagent 的 LLM Path，我卻又在 agentgateway 前替每個 Runtime 放了一把 Static Consumer Key。兩邊都是 Bearer Secret，表面上看起來像是前後矛盾。

差別不在 Key 的形式，而在它代表的對象。把一把 Key 標成值班工程師，平台便要接手登入、MFA、Team 異動、停權、離職、遺失與重發。若它只代表 `workload/runtime-a`，責任會縮到 Secret Delivery、Rotation、爆炸半徑與 Provider Credential Isolation。前者牽涉 Human Identity Lifecycle，後者處理 Machine Consumer Boundary。

從那次選型以後，我看到 API Key、Virtual Key 或 JWT 時，會先找出它代表哪一種 Actor，以及誰能撤銷它，再判斷是否適合這條路徑。Credential 的外形相似，不代表能承擔相同的身分責任。

## Human Virtual Key 會多出一套 Lifecycle

Virtual Key 對 LLM Gateway 很實用。它可以替不同 Consumer 分開 Budget、Rate Limit、Usage 與 Provider Access，也能把真正的 Provider Credential 留在 Gateway 後面。這些功能正是 LiteLLM 當時進入候選名單的原因。

問題出現在我們把它映射成 Human：

```text
企業 IdP 的值班工程師
    ↓ 另做 mapping
Gateway user / team
    ↓ 發 virtual key
LLM usage / budget / provider access
```

企業 IdP 原本已經知道值班工程師是否在職、屬於哪個 Team、能否登入，以及有沒有通過 MFA。Gateway Database 再保存一份 `Human → User → Team → Virtual Key` 後，Offboarding 便多出另一條同步路徑。Team Change、Key 撤銷、UI 或 API 造成的 Drift 都需要 Owner，兩邊資料不一致時還得決定相信哪一份。

Key 上的 `user=sre-oncaller` 只能證明 Gateway 找到了這筆 Metadata，不能證明值班工程師剛完成登入，也不能證明帳號目前仍有效。產品若另外整合 IdP 或 SCIM，可以補上 Lifecycle。單靠一份 Key Mapping 不會自然得到這項能力。

因此，我們沒有讓 Virtual Key 承擔企業 Human Identity。它仍然能管理用量與 Provider Access，只是 Human Lifecycle 繼續以企業 IdP 為準。

## Workload Key 只代表 Agent Runtime

後來串 kagent 的 LLM Path 時，條件完全不同。當時使用的 Runtime Path 接受 API Key，卻不會替平台完成 OAuth Login、取得短效 Token，再處理 Cache、Expiry 與 Refresh。硬把 Human OAuth 塞進去，只會把 Credential Lifecycle 搬進原本不負責這件事的 Runtime。

我們最後留下的是一條單純的兩段式 Credential Path：

```text
kagent runtime
    │ agentgateway consumer key
    ▼
agentgateway
    │ provider key
    ▼
LLM provider
```

Consumer Key 從頭到尾只代表 Runtime。Audit 記錄 `workload/runtime-a`，Human 欄位則明確標成 `NOT_APPLICABLE`。上游若還要知道是哪一位使用者發起請求，就必須另外傳遞可驗證的 Human 與 Delegation Context，不能把 Runtime Key 改名成某位值班工程師。

Static Bearer Key 當然有侷限。它可能被複製，無法辨認特定 Pod Instance，也沒有 Workload Attestation。不過在 Runtime 只接受 API Key 的條件下，它至少能隔離不同 Consumer，避免 Provider Key 散進每個 Agent Deployment。Runtime A 的 Key 外洩時，也不必連 Runtime B 一起撤銷。

若風險模型要求辨認 Pod Instance，下一步應該是 Kubernetes ServiceAccount Federation、SPIFFE 或其他同等的 Attestation，而不是把 Metadata 裡的 Workload 名稱當成密碼學證據。

## 同一個 Gateway 比較三種 Credential

[Lab 03](https://github.com/MikeHsu0618/2026-ithelp-agent-governance-public/blob/day-07-r2/labs/03-gateway-runtime/README.md) 使用一個 agentgateway 與一個 Synthetic OpenAI-compatible Backend，比較 Human Key、Workload Key 與 Human JWT。三種 Credential 都呼叫 `/v1/chat/completions`，通過入口驗證後，再由 Backend Authentication 換成 Provider Key。

這裡需要先釐清名稱。LiteLLM Virtual Key 是前一篇實務選型的對象，Lab 使用 agentgateway API Key Policy 與 Metadata 重現相同的 Identity Mapping 問題。`Consumer Key` 是本文為了區分用途採用的名稱，不是 agentgateway 另一種正式 Credential Type。

![Human key、Workload key 與 Human JWT 各自經過 agentgateway 的驗證與 backend authentication。Human key 未收到 IdP 停權資訊，因此仍回 200。Workload retired key，以及 issuer 或 audience 錯誤或缺漏的 JWT，都在 Gateway 被拒絕。](https://raw.githubusercontent.com/MikeHsu0618/2026-ithelp-agent-governance-public/day-07-r2/assets/diagrams/day-14/credential-boundary.png)

API Key Route 使用 Strict Mode，兩把 Key 分別映射成 Human 與 Workload Metadata：

```yaml
apiKey:
  mode: strict
  keys:
  - key: <ephemeral-human-key>
    metadata:
      kind: HUMAN_VIRTUAL_KEY
      human: user/sre-oncaller
  - key: <ephemeral-workload-key>
    metadata:
      kind: WORKLOAD_CONSUMER_KEY
      workload: workload/runtime-a
```

完整設定放在 [agentgateway.example.yaml](https://github.com/MikeHsu0618/2026-ithelp-agent-governance-public/blob/day-07-r2/labs/03-gateway-runtime/configs/agentgateway.example.yaml)。讀者重跑時會產生新的測試 Key。下面只看三種入口 Credential 最後讓 Gateway 做出什麼不同決定。

## Offboarding Gap 會被 HTTP 200 藏起來

Human Key 的第一個案例把 Directory State 設為 `ACTIVE`，Gateway 找到 `user/sre-oncaller` 後回傳 `200`。第二個案例使用完全相同的 Key 與 Gateway Mapping，只把外部 Directory State 改成 `DISABLED`，結果仍然是 `200`。

```text
human-key-active             ALLOW  KEY_MAPPING_ACTIVE
human-key-after-offboarding  ALLOW  STALE_MAPPING_ALLOWED
```

Gateway 沒有收到這次停權事件。它只知道 Key 還在 Allowlist、Metadata 存在，而且 Route 可以繼續走。回應仍是 `200`，對值班工程師來說卻已經是錯誤授權：人被停用了，用他的名字建立的 Static Key 仍然有效。這比「Key 可以正常發 Request」更直接地說明，Human Identity 不能只靠 Gateway 裡的一份靜態 Mapping 管理。

Workload Key 的結果比較單純。Current Key 得到 `200`，移出 Allowlist 的 Retired Key 得到 `401`。這正是我們要它負責的範圍：隔離並撤銷 Machine Consumer。輪替期間如何不中斷服務，還要另設交付流程。

## JWT 驗證曾在版本升級時改寫結論

Human JWT 延續 Day 12 的 Contract，包含 `iss`、`aud`、`sub`、`client_id`、Scope、`token_use` 與五分鐘效期。Resource 可以透過 JWKS 驗證簽章與 Issuer，再確認 Token 是否發給自己的 Audience。

第一版 Lab 鎖在 agentgateway `1.4.1`，當時只測 Valid Token 與 Wrong Audience。發稿 Review 時，我重新閱讀 Release Note，補跑 Missing Issuer 與 Missing Audience，兩個 Request 都回了 `200`：

```text
agentgateway 1.4.1 review case

jwt-missing-issuer    ALLOW
jwt-missing-audience  ALLOW
```

這個結果直接改變了文章與 Lab。公開版本升到 Pinned agentgateway `1.5.0`，並把 Wrong／Missing Issuer 與 Wrong／Missing Audience 全部加入 Regression Test。官方 [JWT Authentication](https://agentgateway.dev/docs/standalone/latest/documentation/configuration/security/jwt-authn/) 提供現行設定方式，[Release Notes](https://agentgateway.dev/docs/standalone/latest/release-notes/release-notes/) 則記錄了這項版本差異。

```text
jwt-human             ALLOW  JWT_PRINCIPAL_VERIFIED
jwt-wrong-issuer      DENY   JWT_ISSUER_REJECTED
jwt-wrong-audience    DENY   JWT_AUDIENCE_REJECTED
jwt-missing-issuer    DENY   JWT_ISSUER_REQUIRED
jwt-missing-audience  DENY   JWT_AUDIENCE_REQUIRED
```

升版後，錯誤或缺少 Issuer、Audience 的 Token 都會被拒絕。值班工程師被停用時，已發出的 Access Token 仍可能活到 TTL 結束。Revocation、Session 與 Gateway Cache 需要另行設計。JWT 讓 Gateway 不必自己保存一份 Human Key Mapping，但員工停權仍須由企業 Identity 流程接住。

## 入口 Credential 不應傳到 Provider

Human Key、Workload Key 與 Human JWT 通過後，都由同一個 Backend Authentication Policy 注入 Provider Key。agentgateway 的 [Backend Authentication](https://agentgateway.dev/docs/standalone/latest/documentation/configuration/security/backend-authn/) 說明 Incoming Credential 通過驗證後預設不再轉送，Gateway 可以改掛 Backend 專用 Credential。

Synthetic Provider 會檢查收到的 `Authorization` 是否等於本次產生的 Provider Key，也確認它不等於 Human Key、Workload Key 或 JWT。這個實際 Backend Behavior 才能支持「Provider Key 已被隔離」，不能只從架構圖推論。

![Day 14 實際 Lab terminal card。Human key 在外部目錄停權後仍 ALLOW，標成 RISK_EXPOSED。Workload retired key，以及 issuer 或 audience 錯誤或缺漏的 JWT，都被拒絕。](https://raw.githubusercontent.com/MikeHsu0618/2026-ithelp-agent-governance-public/day-07-r2/assets/screenshots/day-14/01-credential-boundary-results.png)

Human Key、Workload Key 與 JWT 的差異，現在可以沿著停權、撤銷與 Provider 收到的 Credential 一路查下去。不必因為三者都能當 Bearer Secret，就交給同一套 Lifecycle。完整結果放在 [Lab 紀錄](https://github.com/MikeHsu0618/2026-ithelp-agent-governance-public/blob/day-07-r2/assets/screenshots/day-14/evidence.md)，要帶進架構討論也有可複製的 [Credential Decision Table](https://github.com/MikeHsu0618/2026-ithelp-agent-governance-public/blob/day-07-r2/articles/day-14/credential-decision-table.md)。重跑整組案例只需要：

```bash
make lab-03-runtime-up
make lab-03-runtime-run
```

## Production 還要補上 Lifecycle Control

這個 Lab 只比較 Credential Boundary，沒有處理 Static Key 存在 Kubernetes Secret 或外部 Secret Manager、雙 Key Overlap、Hot Reload 與 Rolling Restart。Policy Service 故障時要 Fail Closed 或暫時使用 Cache，也必須由正式環境另外決定。

Agent 代表 Human 行動時，還要把 Human `sub`、Client、Agent Chain 與 Executing Workload 放進同一份 Audit Event。到了這裡，Human Identity、Workload Consumer 與 Provider Credential 已經能分開處理，不需要再靠一把 Key 同時扮演三個角色。

實務架構仍保留既有 Ingress，下一個問題會轉到 Traffic Path。若 Edge 與 Agent Gateway 同時處理 Authentication、Retry、Header 或 Streaming，剛釐清的 Credential Boundary 又會變得模糊。Day 15 會拆開兩層 Gateway 的責任，同時讓公開 Lab 維持單層 agentgateway，避免讀者為了理解邊界先多除錯一層 Proxy。
