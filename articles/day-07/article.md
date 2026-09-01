# Day 7｜Agent Audit 不能只留一個 actor：Human、Service、Agent 與 Workload

Day 6 把登入路徑收斂成兩條：互動式使用者走 Authorization Code + PKCE，無人服務走 Client Credentials。Token 終於有了清楚的入口，但我把一筆 Tool Call 往後追到 Agent runtime 與 Kubernetes audit 時，又碰到另一個麻煩。

假設值班工程師從 MCP console 發出調查請求，Agent 收到任務後選擇 Tool，最後由 Kubernetes 裡的 Pod 執行。沿途看到的紀錄可能長成這樣：

```text
hop=1  gateway.auth      sub=user/sre-oncaller
                         client_id=client/mcp-console

hop=2  agent.runtime     client_id=client/sre-agent-runtime
       agent.event       agent=agent/sre-investigator@v1
       kubernetes.audit  user.username=system:serviceaccount:lab:sre-agent
```

這四筆資料來自同一條 action path 上的不同 credential hop。Human `sub` 回答誰登入，`client_id` 記錄哪個 client 參與，Agent artifact 指向做決定的邏輯版本，ServiceAccount 則把 request 帶回實際執行的 runtime。

如果 audit 最後只留 `actor=user/sre-oncaller`，看起來歸責很完整，實際上卻把中間三段都壓平了。遇到誤刪資料、越權查詢或 Tool 參數異常時，我仍然無法知道是哪一版 Agent 做了選擇、哪個 service 接手任務，也不能確認 credential 當時落在哪個 workload。

> 上面是依 Day 6 架構整理的合成紀錄，不是原始 production log。實戰能證明的是 Human 與 M2M 兩條 Cognito 路徑都曾端到端跑通。本文的四類責任模型，則是我在整理 Gateway、Agent runtime 與 audit 邊界後做出的架構歸納。

## 四類責任先放回同一條 action path

一開始我也把 Human、Service、Agent、Workload 畫成四個格子，彷彿每格只要塞進一個 ID 就完成了。真的把請求拆成多個 hop 後，才發現這種畫法很容易再製造一個新的 `actor` 欄位，只是換了名字。

實際需要保存的是四類責任，而且每一類都可能出現不只一次。Human 可以分成 requester 與 approver，Service 會隨 credential hop 改變，多 Agent 協作時也要保留呼叫順序。

| 責任類別 | 它要回答的問題 | 常見證據 |
| --- | --- | --- |
| Human | 誰提出、委派或核准這個目的？ | federated user `sub`、approval event |
| Service | 每個 hop 由哪個 application／service client 參與？ | OAuth client context、client authentication |
| Agent | 哪一版決策邏輯選擇 action 與 arguments？ | Agent artifact ID、版本、受控設定 |
| Workload | 哪個程序持有 credential 並送出 request？ | Kubernetes ServiceAccount、Pod 關聯、workload attestation |

下圖把這四類資訊排成 2×2，共同對應同一條 action path。圖上刻意不畫串聯箭頭，避免讀者把它理解成「Human 依序變成 Service、Agent、Workload」的流水線。

![同一條 Agent action path 需要保存 Human、Service、Agent 與 Workload 四類責任。Human 可分 requester 與 approver，Service 與 Agent 可依 hop 或呼叫順序保留多筆，Workload 記錄實際送出 request 的 runtime。四類資訊一起進入 audit，缺少證據時寫 UNKNOWN，本來不存在時才寫 NOT_APPLICABLE。](https://raw.githubusercontent.com/MikeHsu0618/2026-ithelp-agent-governance-public/day-09/assets/diagrams/day-07/four-identity-slots.png)

Human 與完成 client authentication 的 confidential Service，可能在各自的 network hop 成為 authenticated principal。Public client 的 `client_id` 只能說明哪個應用參與登入流程，不能證明它持有 secret。Agent 比較接近邏輯上的決策者，Workload 則是讓那套邏輯實際運作的 process、Pod 或 deployment instance。

有些平台會替 Agent 發獨立 credential，Agent、Service 與 Workload 的邊界因而部分重疊。也有不少系統只有 OAuth client 與共用 secret，Agent 名稱只是 deployment 裡的一個設定值。Design review 要把每個值的來源與驗證強度寫清楚，光填產品名稱看不出這些差異。

## Human 委派 Agent：一個請求跨過兩個 credential hop

值班工程師登入 MCP console 時，這一段可驗證的 Human identifier 應來自 issuer 指派的 `sub`，不是 email、display name，也不是看帳號格式猜出來的名字。

[OpenID Connect Core 1.0](https://openid.net/specs/openid-connect-core-1_0.html#IDToken) 用 `sub` 表示 issuer 對 End-User 指派的識別值。Cognito 的 access token 文件也把 `sub` 定義為已驗證使用者的唯一識別，並提醒 username 不一定唯一。[Amazon Cognito access token](https://docs.aws.amazon.com/cognito/latest/developerguide/amazon-cognito-user-pools-using-the-access-token.html)

公開範例裡的 `user/sre-oncaller` 是為了閱讀與去識別化使用的 normalized label，不代表 Cognito `sub` 原本就長這樣。真正的 audit 應保存 issuer 與原始 subject 的對應關係，不能把 email 或值班角色反向當成 `sub`。

高風險 Tool 如果需要另一個人核准，Human 類別就會同時出現 requester 與 approver。兩人的責任與發生時間不同，就算剛好由同一人擔任，也不能把 Agent 後續選擇的 Tool 與 arguments 全部算在他身上。

值班工程師使用的 MCP console 是 public client，沒有安全保存 client secret 的能力。因此 `client_id=client/mcp-console` 只能當 application context，不能證明這個 Service 已用自己的 credential 完成驗證。

當 Agent runtime 接手任務，下一個 hop 可能改由 confidential client `client/sre-agent-runtime` 取得 access token。這次 client 能用自己的 credential 完成 authentication，證據強度與前一個 public client 已經不同。兩筆資料都屬於 Service 類別，audit 不該為了方便只保留最後一個 `client_id`。

真正把目的轉成 action 的是 `agent/sre-investigator@v1`。這裡至少要留受控的 artifact ID 與版本，因為 Prompt、Tool set、模型設定或 workflow 只要有一項改變，行為就可能不同。同一個 runtime 可以承載多個 Agent，同一個 Agent 也可以由多個 workloads 水平擴展，Agent 名稱不能直接拿來替代 Service 或 Workload。

Agent runtime 進入 Kubernetes 執行後，Service identity 仍只回答哪個 client 通過驗證，Workload identity 才回答 credential 當時由哪個程序持有。兩個 Pods 如果共用同一組 client secret，Gateway 看見的 Service 完全相同，實際執行位置卻可能不一樣。

Kubernetes 官方把 ServiceAccount 定義為 cluster 內的 non-human identity，Pod 可以使用短效、會自動輪替的 Token 向 API server 或外部服務表明身分。[Kubernetes Service Accounts](https://kubernetes.io/docs/concepts/security/service-accounts/)

ServiceAccount name 只能把範圍縮到一組 Kubernetes workloads，還不能定位單次執行。同一個 ServiceAccount 可以被多個 Pods 使用，如果要繼續追到特定 instance，還得保留 Pod UID、bound token 關聯或其他 attestation。若所有 Agent 都使用 namespace 裡的 `default` ServiceAccount，欄位雖然有值，實際區分能力仍然很低。

這條 Human 委派路徑走完後，audit 至少看到了 requester、參與兩個 hop 的 services、做決策的 Agent，以及實際送出 request 的 Workload。它們來自不同證據，不能靠複製同一個 `sub` 或 `client_id` 補滿。

## 排程 Agent：Human 本來就不存在

另一條路徑沒有瀏覽器，也沒有人在 Token endpoint 前面完成登入。排程 runtime 直接用 confidential client 取得 Token，再由 Agent 選 Tool：

```text
client/sre-agent-runtime
  → Client Credentials
  → Agent Gateway
  → agent/sre-investigator@v1
  → system:serviceaccount:lab:sre-agent
```

[RFC 6749 的 Client Credentials](https://www.rfc-editor.org/rfc/rfc6749.html#section-4.4) 讓 client 代表自己，或依事先安排好的授權存取 resource。Cognito 也把這條 flow 定位為 M2M，只發 access token，不發用來描述 Human 的 ID token，而且只允許 resource server 的 custom scopes。[Amazon Cognito App Clients](https://docs.aws.amazon.com/cognito/latest/developerguide/user-pool-settings-client-apps.html)

這條 flow 的 Human 本來就不存在，應標成 `NOT_APPLICABLE`。如果為了讓 audit 看起來完整，硬塞一位「系統管理員」或服務 owner 進去，紀錄反而開始說謊。Service principal 在這裡是完成 client authentication 的 confidential client，Agent 與 Workload 則沿用各自的 artifact 與 runtime evidence。

多個 Pods 共用同一組 client credential 時，`client/sre-agent-runtime` 只能證明 request 知道那組 credential，無法單獨證明是哪個 Pod 使用它。反過來說，只有 ServiceAccount name 也不能回答這個 workload 被允許使用哪些 OAuth scopes，Service 與 Workload 因此不能合併。

Day 6 選定的 Cognito 雙路徑，實際處理的是 Human 與 Service 的 credential lifecycle：

```text
Human request
  user → public client + Authorization Code + PKCE

Scheduled request
  confidential client + Client Credentials
```

AWS 建議 public-client app 使用 Authorization Code 並加上 PKCE，Client Credentials 則只能用在具有 client secret 的 app client。[Amazon Cognito App Client Types](https://docs.aws.amazon.com/cognito/latest/developerguide/user-pool-settings-client-apps.html#user-pool-settings-client-apps-terms)

Cognito 的兩條 client flow 只處理 Human 與 Service credential，不會替 Agent artifact 或 Kubernetes Workload 自動發出身分。Human 委派 Agent 時還會跨過不只一個 credential hop，audit 必須靠 correlation 與後續的 delegation context 串起它們，不能把第一枚 Human Token 一路轉傳到所有下游。

## Identity Flow Matrix：空白也要留下原因

Human 委派與排程 Agent 使用相同的四類責任，Human 與 Service 欄位卻會得到不同結果：

| Flow | Human | Service | Agent | Workload |
| --- | --- | --- | --- | --- |
| Human 委派 Agent | requester／approver | interactive client + runtime service | 依順序保存 Agent chain | Agent runtime workload |
| Service 排程 Agent | `NOT_APPLICABLE` | authenticated confidential client | Agent artifact + version | runtime ServiceAccount／attestation |

我把這兩條路徑，加上 Human 直接使用 MCP client 與 Agent 呼叫另一個 A2A Agent，整理成可直接拿去做 design review 的 [Identity Flow Matrix](https://github.com/MikeHsu0618/2026-ithelp-agent-governance-public/blob/day-09/articles/day-07/identity-flow-matrix.md)。完整版會逐欄記錄主要 credential、credential 能證明什麼、decision point 與最低 audit evidence。

Matrix 的 A2A row 依實際順序保存 caller Agent、remote Agent 與中間 coordinator。Agent Card 提供 discovery 資訊，transport credential 才能證明這次連線由誰發出。兩種證據解的是不同問題。[A2A Protocol Specification v1.0.0](https://github.com/a2aproject/A2A/blob/v1.0.0/docs/specification.md)

排程工作本來就沒有人類在場，所以 Human 是 `NOT_APPLICABLE`。Human 委派 Agent 時，事件理應知道執行 workload，卻沒有留下任何可驗證線索，這才叫 `UNKNOWN`。Matrix 必須分開這兩種狀態。

兩者若都存成 `null`，incident review 就無法判斷「這個角色本來不存在」還是「證據在途中弄丟了」。這個差別最後會影響 policy 要 fail open、fail closed，還是把 request 送去人工核准。

Matrix 不只檢查 identifier 有沒有值，還要求每筆資料附上四項證據：

- 來源：Token claim、Gateway authentication、Agent artifact、Kubernetes audit 或 approval event。
- 驗證方式：signature、client authentication、bound token、attestation 或 asserted metadata。
- 適用 hop：它在哪一段 request path 生效。
- 角色或順序：requester／approver、calling／remote、Agent chain sequence。

這些資料能阻止 design review 把 public `client_id` 當 authenticated Service，或把 deployment label 當成 workload attestation。拿不到證據時保留 `UNKNOWN`，比複製既有欄位誠實得多。

## Audit 保存責任鏈，Policy 再挑欄位

Audit 先保存完整的四類責任，各 decision point 再挑自己需要的欄位。M2M rate limit 可能只看 authenticated Service，高風險 Tool approval 會同時看 Human、Agent 與 Workload，resource server 則驗自己的 audience、scope、resource 與 action。

設計順序不該從「現在 JWT 有哪些 claims」開始，而是先把 action path 上應負責的人與程序列完整，再讓每個 decision point 選擇必要欄位。反過來做，很容易把目前拿得到的 `sub` 或 `client_id` 當成完整真相。

Audit 裡的責任鏈要能查出目的由誰提出或核准、每個 credential hop 經過哪些 services、哪一版 Agent 做出 action 決策，以及 credential 最後落在哪個 runtime。這四類資料各有自己的證據來源，不能再壓回單一 `actor`。

下一步要回到入口那枚 JWT，逐項確認 `iss`、`aud`、`sub`、`client_id`、`scope` 與有效期限到底證明了什麼。Day 8 會用可執行的 validator，把「Token 能解開」與「Token 真的是發給這個 resource」分成兩件事。
