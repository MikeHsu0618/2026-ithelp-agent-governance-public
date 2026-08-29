# Day 6｜雖然 Keycloak 十分強大，但最終我們選擇 AWS Cognito

Day 5 盤點完 Identity 缺口後，下一步看起來很直覺：替 Gateway 接上一個可信的 OIDC issuer，讓 `synthetic-user-sre-oncaller` 這種 Lab label 換成可驗證的人員身分。這題我們不是從白紙開始。當時已經有一套 Keycloak 跑在 Kubernetes，上游企業 IdP、JWT role、Gateway 與 MCP Tool RBAC 也真的串了起來。把那次驗收重新排在一起，最後一列反而最醒目：

```text
Federated login         PASS
JWT role claim          PASS
Gateway per-tool RBAC   PASS
MCP request             PASS
架構決策                 REPLACE
```

四個技術項目都通過，Keycloak 最後仍被 Cognito 取代。把實際服務範圍和 owner 清單並排後，問題很清楚：平台只拿它來替 AI 系統轉接身分，卻同時接下了一套完整 IdP 的 production responsibility。

> `實戰` Keycloak 的結果來自 Kubernetes 環境的操作紀錄，Cognito Human／M2M 結果來自後續端到端驗證。內部 realm、client、role 與 endpoint 不公開，本文只保留足以說明架構取捨的部分。官方文件用來核對產品能力，沒有拿來代替實測。

## AI 平台缺的是 OIDC Contract

本文把「Identity Center」當成架構角色，指的是統一 federation、token 與 identity policy 的中心，不是 AWS IAM Identity Center 這項產品。實際環境早已有企業 IdP，新同事到職、成員轉組、帳號停用與登入驗證，都有既有系統和流程處理。AI 平台當時缺的不是另一份人員主檔，而是一份穩定的 OIDC contract，讓 MCP clients、Gateway 與後端服務對 issuer、client、role／scope 有一致理解。

我們一開始把需求想得更大：既然要統一 issuer 與 claim，乾脆順便建立 AI 平台的 Identity Center。Keycloak 因此成為第一個方案，它不是為了寫這篇文章才臨時找來比較的候選。

## Keycloak 與 Cognito User Pools

| Keycloak | Amazon Cognito User Pools |
| --- | --- |
| <img src="https://raw.githubusercontent.com/MikeHsu0618/2026-ithelp-agent-governance-public/day-06/assets/third-party/keycloak/keycloak-icon-color.png" alt="Keycloak 官方專案圖示" width="120"> | <img src="https://raw.githubusercontent.com/MikeHsu0618/2026-ithelp-agent-governance-public/day-06/assets/third-party/aws/amazon-cognito-architecture-icon.png" alt="Amazon Cognito 官方 AWS Architecture Icon" width="120"> |
| 開源的 Identity and Access Management server，可作 OIDC／SAML identity broker，管理 realm、client、role、session 與 token mapping。服務與資料層由採用者部署和維運。 | AWS 的受管 user directory 與 OIDC provider，可接外部 OIDC／SAML IdP，也能用 app clients 分別處理 Human 與 M2M flow。平台仍須管理 client、scope、claim 與下游 policy。 |

Keycloak 的吸引力很直接。它的 identity brokering、role、client 與 mapper 都有完整控制面，也能放進既有的 Kubernetes 與 IaC 流程。[Keycloak Server Administration Guide](https://www.keycloak.org/docs/latest/server_admin/) 把外部 OIDC／SAML brokering 與 token mapper 列為正式能力。

Cognito 不是因為 Keycloak 接不起來才進場。等需求縮成「替 AI 平台提供 federation 與 token」後，受管 OIDC service 才成為合理的比較對象。Cognito User Pools 對應用扮演 OIDC IdP，也能接外部 OIDC／SAML IdP。[Amazon Cognito User Pools](https://docs.aws.amazon.com/cognito/latest/developerguide/cognito-user-pools.html)、[Third-party identity federation](https://docs.aws.amazon.com/cognito/latest/developerguide/cognito-user-pools-identity-federation.html)。本文只把兩個產品放進同一個決策情境：誰來承接 AI 平台需要的 OIDC bridge，以及平台團隊要長期擁有哪些責任。

## Keycloak 技術鏈的驗收結果

當時跑通的路徑可以縮成這樣：

```text
Human
  → 上游企業 IdP
  → Keycloak
  → Agent Gateway
  → MCP Server
```

Keycloak 在中間扮演 identity broker 與 OIDC issuer。實作時有一個很小、但很能分辨「讀過文件」和「真的接過」的地方：realm role 不是一個扁平字串，而是在 JWT 的陣列裡。

```json
{
  "realm_access": {
    "roles": [
      "mcp-observer",
      "default-roles-platform"
    ]
  }
}
```

Gateway policy 如果假設 claim 長成 `jwt.role == "mcp-observer"`，授權就不會照預期工作。修法可以是讀取 `realm_access.roles` 再做 membership 判斷，也可以在 Keycloak 加 mapper，把下游 contract 轉成雙方約定的形狀。

調整完成後，沒有 Token 的 request 回 `401`，沒有對應角色時採 deny-by-default，不同角色看到的 Tool 子集也不同。這段驗收很重要，因為它先排除了最容易寫的淘汰理由：Keycloak 的 federation、claim 與 Tool RBAC 都接得起來。

## 人員生命週期沒有移到 Keycloak

技術鏈跑通後，我們重新把人員生命週期攤開：

```text
新同事到職，是誰建立身分？          上游企業 IdP
同事轉組，哪裡先改 group／role？     上游流程與企業 IdP
同事離職，哪裡負責立即停用？         上游企業 IdP
Keycloak 在這裡新增了什麼？          AI 平台使用的 federation、claim 與 token
```

四個答案擺在一起後，「Identity Center」這個名字開始變得尷尬。我們建立的是技術中心，卻沒有把組織人員生命週期的 source of truth 移進來。Keycloak 的主要工作，是把上游已經知道的人員狀態轉成 AI 平台看得懂的 token 與 role。

服務範圍窄本來不構成問題，前提是固定成本也一起縮小。Keycloak 的 runtime、資料層、升級與故障處理並不會因為只有 AI 平台使用就自動變少，選型於是從功能比較轉成 ownership 盤點。

## Keycloak 的 Production 責任清單

我不太喜歡在選型文件裡只寫「Keycloak 維運太重」。這句話沒有 owner，也沒有辦法拿去做決策。一旦 IdP 進入 production path，至少要把下列責任放到人名或團隊上：

| 維運面 | 不是安裝完就結束的問題 |
| --- | --- |
| Runtime／Operator | 誰管 image、CR、資源、probe、rollout 與相容性？ |
| Database／session | 誰做容量、連線、備份、復原與資料保護？ |
| Cache／cluster | 多節點如何 discovery、invalidation，降級時怎麼處理？ |
| Realm／client／mapper | 誰 review callback、scope、role 與 claim contract？ |
| Keys／JWKS | 誰輪替 signing key，如何讓 verifier 平順接住？ |
| Upgrade／rollback | 版本、schema 與 extension 如何測試，失敗退到哪裡？ |
| Audit／on-call | 登入異常、管理事件與 IdP outage 由誰回應？ |

這份清單不表示每個 Keycloak deployment 都得從跨區多叢集起步。單一叢集也能成立，但 database、cache、backup、upgrade 與 on-call 的責任仍在。可用性要求提高後，load balancer、跨叢集故障模式與更多資料層考量才會跟著展開。Keycloak 官方文件也分開說明 [HA 架構取捨](https://www.keycloak.org/high-availability/introduction)、[distributed cache](https://www.keycloak.org/server/caching) 與 [multi-cluster upgrade](https://www.keycloak.org/high-availability/multi-cluster/upgrades)。

如果 Keycloak 同時服務多個內外部系統，或組織真的要把 federation、user lifecycle、custom flow 與跨應用角色收進同一個平台，這份 operating surface 可能值得。當時我們的收益主要落在 AI Gateway 這一段，平台團隊卻為一個較窄的 identity bridge 接下接近完整 IdP 的 runtime responsibility。

## 改用 Cognito 後的責任邊界

下面這張圖不是在比較誰的功能比較多。兩條技術路徑都已經通過，閱讀重點是 JML 的 owner 有沒有移動，以及平台團隊少了哪些 runtime 工作。

![Keycloak 與 Cognito 兩條技術鏈都通過，差別是平台擁有的 runtime 維運面，兩者的人員生命週期仍在上游企業 IdP。](https://raw.githubusercontent.com/MikeHsu0618/2026-ithelp-agent-governance-public/day-06/assets/diagrams/day-06/identity-center-before-after.png)

換成 Amazon Cognito User Pools 後，request path 仍然要經過 issuer、Gateway 與 MCP Server：

```text
Human／Service
  → 上游企業 IdP 或 client credential
  → Cognito User Pool
  → Agent Gateway
  → MCP Server
```

改採 Cognito 後，平台不再操作 Keycloak Pod、Operator、database 與 cache。OIDC service runtime 進入 AWS 的服務邊界，正好對準當時想縮小的維運面。

設定責任沒有一起消失。平台仍然要維護 upstream IdP 與 attribute／claim mapping、app client、callback URL、scope、token lifetime、Gateway policy、IaC、quota、監控與退出方案。員工是否存在、屬於哪個群組、何時失效，也依舊以上游企業 IdP 和組織流程為準。

Human 與 M2M 也不能偷懶塞進同一個 client。我們把 Human 做成 public client，走 Authorization Code + PKCE。M2M 使用有 secret 的 confidential client，走 Client Credentials。AWS 的 [app client 文件](https://docs.aws.amazon.com/cognito/latest/developerguide/user-pool-settings-client-apps.html) 也要求 client-credentials client 必須有 secret，而且不能同時支援 authorization-code 或 implicit grant。

把這些責任放回 request path 後，owner 分成四層：

| 問題 | 本次 owner |
| --- | --- |
| 這個人還是不是有效員工？ | 上游企業 IdP／組織 lifecycle |
| 這個 client 能拿哪些 scope？ | Cognito client／resource server 設定 |
| 這個角色能不能呼叫某個 MCP Tool？ | Agent Gateway policy |
| Tool 對目標資源能做什麼？ | MCP／Resource Server 最終授權 |

IdP 能發出 role，不表示所有 action／resource policy 都該塞進 IdP。Cognito 幫我們縮小的是 runtime ownership，沒有收走 claim contract、Gateway policy 與 Resource Server authorization。

## Decision Record：不做功能加權總分

完整的 [Identity Center 組織選型 Decision Record](https://github.com/MikeHsu0618/2026-ithelp-agent-governance-public/blob/day-06/articles/day-06/identity-center-decision-matrix.md) 放在 repo。文章裡保留最影響這次決策的五列：

| 決策面 | Keycloak | Cognito | 本次判斷 |
| --- | --- | --- | --- |
| 技術鏈 | 已實測 `PASS` | Human／M2M 已實測 `PASS` | 不靠功能表決勝 |
| JML 覆蓋 | 仍在上游 IdP | 仍在上游 IdP | 都不是本案的人員主檔 |
| Runtime | 平台維運 | AWS 服務邊界 | 縮小 AI-only operating surface |
| 設定與 Policy | 平台仍要負責 | 平台仍要負責 | Managed 不等於 zero-ops |
| 客製與可攜性 | 彈性與部署選項較多 | 服務限制與 AWS coupling | 接受限制，換取較少 runtime ownership |

我沒有把這些欄位做成 `82 分 vs. 76 分`。Runtime ownership 在不同組織裡不是固定權重：若企業真的需要高度客製的 authentication flow，也有 Identity Platform 團隊願意擁有資料、升級與 on-call，Keycloak 的成本可能是一筆合理投資。放在 AI-only bridge 的前提下，同一筆成本就不划算。

這次選 Cognito 也不是單向獲利。我們接受 AWS coupling、quota、費用與產品限制，換掉自己維運 IdP runtime。只要發生以下任何變化，Decision Record 就應該重開：

- 多個非 AI 系統開始共用同一套 federation 與管理模型。
- 組織準備把 joiner／mover／leaver 收進新的身分中心。
- 必要的 authentication flow 或 extension 超出 Cognito 能合理承接的範圍。
- AWS coupling、費用、quota 或復原目標不再能接受。

## 選型結果與下一個 Identity 缺口

Keycloak 的技術鏈成功後，我們才看清楚原本把需求叫作 Identity Center 有多大。實際需要的是 AI 平台的 identity bridge，於是 Cognito 接走 OIDC runtime，企業 IdP 繼續掌握人員生命週期，Gateway 與 Resource Server 也保留各自的授權責任。

產品換完，identity contract 反而需要寫得更精確。Human 的 `sub`、Service 的 client identity、真正執行的 workload、token audience、role／scope，以及「Agent 正代表誰」的 delegation，不能再全部塞進一個 `user_id`。Day 7 會把 Human、Service、Agent 與 Workload 拆成四個責任位置，再確認每一格究竟靠什麼 evidence 成立。
