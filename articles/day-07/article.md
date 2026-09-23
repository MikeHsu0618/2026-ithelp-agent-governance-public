# Day 7｜Agent 的操作該算在誰身上：從使用者一路追到 Kubernetes Workload

值班工程師從 MCP console 請 Agent 調查 latency。Agent 選了 `query_metrics`，最後由 Kubernetes 裡的 Pod 拿著 credential 送出 request。這筆查詢如果越權，Audit 應該記登入的工程師、做決定的 Agent，還是實際送出 request 的 Pod？

我一開始也想替整條路徑找一個統一的 `actor`。把 Cognito、Gateway、Agent runtime 與 Kubernetes audit 串起來後，卻同時拿到四種紀錄：Token 裡有使用者 `sub`，MCP console 有 `client_id`，runtime 知道載入哪一版 Agent，Kubernetes 則留下 ServiceAccount。這些紀錄的來源與證據強度不同，也各自在回答不同問題。

只記使用者，出事時會找不到哪一版 Agent 選了 Tool，也不知道 credential 落在哪個 runtime。只記 ServiceAccount，又會讓整件事看起來像 Pod 自己決定要查資料。這就是 Day 6 把 Human 與 M2M 登入分開後，仍然沒有解完的責任問題。

## 一筆查詢留下四類責任

圖中四張卡片分別對應同一筆 Agent action 的目的、服務驗證、決策邏輯和執行環境。

![同一條 Agent action path 需要保存 Human、Service、Agent 與 Workload 四類責任。Human 說明誰提出或核准目的，Service 說明哪個服務在目前 credential hop 完成驗證，Agent 記錄選擇動作的 artifact，Workload 記錄實際持有 credential 的 runtime。](https://raw.githubusercontent.com/MikeHsu0618/2026-ithelp-agent-governance-public/day-21-r3/assets/diagrams/day-07/four-identity-slots.png)

Human 說明目的從哪裡來。這筆 latency 調查是值班工程師提出的，能驗證的識別應該來自 issuer 指派的 `sub`。Email、display name 或 `sre-oncaller` 方便人閱讀，卻可能被修改，也不能取代原始 subject。[OpenID Connect Core 1.0](https://openid.net/specs/openid-connect-core-1_0.html#IDToken) 對 `sub` 的定義，就是 issuer 對 End-User 指派的識別值。

Service 說明某一個 credential hop 由哪個服務完成身分驗證。MCP console 的 public `client_id` 可以告訴我們哪個應用程式參與登入，但 client ID 不是秘密，不能單獨證明「這個服務已通過驗證」。若 Agent runtime 另外使用 confidential client 取得下游 Token，那一跳才有經 client authentication 的 Service principal。

Agent 指向做決策的程式與設定，例如 `sre-investigator@v1`。同一個模型可能被多個 Agent 使用，只留下 model name 無法重建當時有哪些 instruction、Tool 與 policy。Agent artifact 和版本才比較接近「哪一版邏輯選了這個 action 與 arguments」。

Workload 則是實際持有 credential、送出 request 的執行位置。Agent artifact 可以同時跑在多個 replicas，同一個 Kubernetes ServiceAccount 也可能被多個 Pods 使用。ServiceAccount 能提供 non-human identity，若事件需要定位單次執行，還要再關聯 Pod UID、bound token 或其他 workload evidence。[Kubernetes Service Accounts](https://kubernetes.io/docs/concepts/security/service-accounts/) 也將 ServiceAccount 與使用它的 Pod 分開處理。

同一個元件可能同時落在兩類。例如 Agent runtime 既是 OAuth confidential client，也跑在使用特定 ServiceAccount 的 Pod 裡。這不代表 Service 和 Workload 可以合併。前者說明服務用什麼身分取得存取權，後者把那次 request 帶回實際執行環境。

## Human 請求跨過兩個 Credential Hop

值班工程師登入 MCP console 時，第一跳能留下 Human 與 application context：

```text
Human principal       issuer + sub
Application context   public client_id
```

這裡刻意沒有把 public `client_id` 寫成 Service principal。OAuth client identifier 本來就會暴露給使用者，不能靠它單獨完成 client authentication。若 console 是 public client，Audit 應誠實記成「哪個應用程式參與」，而不是把欄位填滿後假裝多驗證了一個服務。

Agent runtime 接手後，第二跳可能換成另一枚 credential：

```text
Service principal     authenticated runtime client
Agent artifact        sre-investigator@v1
Workload              ServiceAccount lab/sre-agent + Pod evidence
```

有些架構會把 Human Token 一路帶到下游，有些會由 runtime 另取 Token。兩種作法的風險和權限語意不同，Day 10 再實際比較。Day 7 先抓住一條比較基本的規則：credential 或執行主體只要換了，Audit 就應留下新的 hop，不能把入口的 `sub` 複製到所有元件，假裝每一跳都是使用者本人直接呼叫。

Agent 與 Workload 也不能互相代替。`sre-investigator@v1` 可以解釋為什麼選了 `query_metrics`，卻不能指出是哪個 Pod 持有下游 credential。ServiceAccount 與 Pod evidence 能定位執行環境，也不會告訴我們那個 runtime 當時載入哪一版 Agent。

## 排程任務本來就沒有 Human Caller

背景排程不經過瀏覽器，也沒有人在 Token endpoint 前登入。Runtime 使用 confidential client 取得 access token，再讓 Agent 選擇 Tool：

```text
authenticated Service
  → Agent artifact
  → Runtime Workload
  → Tool / Resource
```

[RFC 6749 的 Client Credentials](https://www.rfc-editor.org/rfc/rfc6749.html#section-4.4) 用於 confidential client 代表自己，或依事先安排的授權存取 resource。Cognito 的 M2M flow 也要求帶有 secret 的 app client，並以 resource server custom scopes 限定 API 能力。[Amazon Cognito M2M authorization](https://docs.aws.amazon.com/cognito/latest/developerguide/cognito-user-pools-define-resource-servers.html)

這條路徑沒有互動式 Human。系統 owner、排程建立者和 on-call team 仍然要對服務負責，但他們不是每一次排程執行的 caller。若為了讓欄位看起來完整，固定塞入某位工程師帳號，離職、輪班或 owner 變更後，Audit 反而會留下錯誤的責任鏈。

Human 委派與排程任務放在一起，才能看出四類責任不是一張每格必填的表：

| Flow | Human | Service | Agent | Workload |
| --- | --- | --- | --- | --- |
| 值班工程師委派 Agent | 提出目的的 requester，必要時另記 approver | 只在完成服務驗證的 hop 出現 | artifact + version | 實際執行 runtime |
| Scheduled Agent | 沒有互動式 Human caller | authenticated confidential client | artifact + version | 實際執行 runtime |

## 先把責任角色找齊

拿 [Identity Flow Matrix](https://github.com/MikeHsu0618/2026-ithelp-agent-governance-public/blob/day-21-r3/articles/day-07/identity-flow-matrix.md) 檢查自己的 Agent 時，可以從兩種任務開始：有人登入後交辦，以及無人值守的排程。沿著 credential hop 找出誰提出目的、哪個服務取得權限、哪版 Agent 選了 Tool、哪個 Workload 送出 request。現有 JWT 剛好帶了哪些 claims，不應反過來決定要記哪些角色。

Policy 不必在每一站讀取全部角色。M2M rate limit 關心目前取得權限的 Service。高風險 Tool 才可能需要 Human、Agent 和目標資源一起做判斷。Day 7 先找出這些角色，不急著規定整份事件該長什麼樣子。

四類責任找齊後，不能只因 JWT 裡出現 `sub` 或 `client_id`，就認定欄位已經可信。下一篇會拿實際 Token 看 Signature、Issuer、Audience、期限與 Scope：Gateway 到底能接受哪一枚，哪一枚雖然能解碼，卻不該交給眼前的 Resource。
