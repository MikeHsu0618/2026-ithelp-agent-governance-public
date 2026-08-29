# Day 6｜雖然 Keycloak 十分強大，但最終我們選擇 AWS Cognito

Day 5 盤點完 Identity 缺口後，下一步看起來很直覺：替 Gateway 接上一個可信的 OIDC issuer，讓 `synthetic-user-sre-oncaller` 這種 Lab label 換成可驗證的人員身分。這題我們不是從白紙開始。當時已經有一套 Keycloak 跑在 Kubernetes，上游企業 IdP、JWT role、Gateway 與 MCP Tool RBAC 也真的串了起來。把那次驗收重新排在一起，最後一列反而最醒目：

```text
Federated login         PASS
JWT role claim          PASS
Gateway per-tool RBAC   PASS
MCP request             PASS
架構決策                 REPLACE
```

四個技術項目都通過，Keycloak 最後仍被 Cognito 取代。真正左右選型的是我們有沒有準備把它做成企業平台級的 Identity Center。如果答案是肯定的，就不能只部署一套 Keycloak：IT 團隊的 onboarding／offboarding、group／role lifecycle、各下游服務的接入規範，以及共用的 SaaS 登入入口都要一起納入，還得有人承諾這個平台的 SLA 與 on-call。

當時這些組織條件還沒成立。AI 平台尚未和 IT 團隊整合完整的人員生命週期，也沒有一份要把各下游服務與 SaaS 入口都收進來的共同計畫。真正承諾接入的只有少數 AI 服務。此時保留 Keycloak，等於為局部需求接下一套完整 IdP 的 production responsibility。改用 Cognito，則是先把需求收斂成較小的 managed identity bridge。

> `實戰` Keycloak 的結果來自 Kubernetes 環境的操作紀錄，Cognito Human／M2M 結果來自後續端到端驗證。內部 realm、client、role 與 endpoint 不公開，本文只保留足以說明架構取捨的部分。官方文件用來核對產品能力，沒有拿來代替實測。

## AI 平台缺的是 OIDC Contract

本文把「Identity Center」當成架構角色，指的是統一 federation、token 與 identity policy 的中心，不是 AWS IAM Identity Center 這項產品。實際環境早已有企業 IdP，新同事到職、成員轉組、帳號停用與登入驗證，都有既有系統和流程處理。AI 平台當時缺的不是另一份人員主檔，而是一份穩定的 OIDC contract，讓 MCP clients、Gateway 與後端服務對 issuer、client、role／scope 有一致理解。

我們一開始把需求想得更大：既然要統一 issuer 與 claim，乾脆順便建立 Identity Center。Keycloak 因此成為第一個方案，它不是為了寫這篇文章才臨時找來比較的候選。但把「企業平台」四個字寫進提案很容易，真正要做時至少得回答下面幾件事：

| 企業平台要接住的事情 | 當時的實際狀態 |
| --- | --- |
| IT onboarding／offboarding | 流程仍在既有企業 IdP，AI 平台尚未接到完整的 lifecycle integration |
| Group／role lifecycle | 上游已有資料，但還沒有跨平台共用的 claim 與 ownership contract |
| 下游服務接入 | 當時明確要接的主要是少數 AI 服務，沒有全公司的導入排程 |
| SaaS 登入入口 | 尚未決定把各 SaaS 與內部系統收進同一套 SSO／存取治理 |
| 平台責任 | Keycloak 的 runtime、資料與 on-call 會先落到平台團隊 |

這份盤點讓需求回到原本的大小。當時要解的是 AI 平台的 OIDC bridge，不是由 AI 團隊先替整間公司建立新的 Identity Center。

## Keycloak 與 Cognito User Pools

|  | Keycloak | Amazon Cognito User Pools |
| --- | --- | --- |
| 產品識別 | <img src="https://raw.githubusercontent.com/MikeHsu0618/2026-ithelp-agent-governance-public/day-06/assets/third-party/keycloak/keycloak-icon-color.png" alt="Keycloak 官方專案圖示" width="120"> | <img src="https://raw.githubusercontent.com/MikeHsu0618/2026-ithelp-agent-governance-public/day-06/assets/third-party/aws/amazon-cognito-architecture-icon.png" alt="Amazon Cognito 官方 AWS Architecture Icon" width="120"> |
| 定位 | 開源的 Identity and Access Management server，由採用者部署與操作 | AWS 受管的 user directory 與 OIDC provider |
| 控制面 | realm、client、role、group、session、identity brokering、user federation、protocol mapper 與 authentication flow | user pool、app client、federation、attribute mapping、resource server 與 OAuth scope |
| Runtime 責任 | 團隊管理服務、資料庫、cache、HA、升級與復原 | AWS 管理服務 runtime，團隊仍管設定、整合、監控與退出方案 |
| 比較適合 | 多個系統共用、需要較深客製，而且有團隊願意長期經營 Identity Platform | 需求範圍較明確，希望用受管 OIDC boundary 支援特定應用與 workload |

Keycloak 的強項正是控制權。它能 broker 外部 OIDC／SAML IdP，也能透過 user federation 接既有目錄。Realm、client、role、group、mapper 與 authentication flow 都能由平台自行設計。[Keycloak Server Administration Guide](https://www.keycloak.org/docs/latest/server_admin/) 對這些能力有完整說明。如果組織真的要讓多個內部系統、外部服務與 SaaS 共用一套登入及角色模型，並且有 Identity Platform 團隊承接資料層、升級與 on-call，這些能力很有價值。

Cognito User Pools 解的是比較收斂的問題。它可以對應用提供 OIDC token，也能 federation 外部 OIDC／SAML IdP，再用不同 app client 處理 Human 與 M2M flow。[Amazon Cognito User Pools](https://docs.aws.amazon.com/cognito/latest/developerguide/cognito-user-pools.html)、[Third-party identity federation](https://docs.aws.amazon.com/cognito/latest/developerguide/cognito-user-pools-identity-federation.html)。需要 M2M API scope 時，也能建立 [resource server 與 custom scope](https://docs.aws.amazon.com/cognito/latest/developerguide/cognito-user-pools-define-resource-servers.html)。服務 runtime 在 AWS 邊界內，但 client、callback、scope、attribute mapping 與下游 policy 仍由平台設計。

我們沒有把 Cognito 當成全公司 Identity Center 的替代品。它承接的是當下幾個 AI 服務需要的 issuer 與 federation，刻意不處理尚未和 IT 團隊對齊的企業 lifecycle 與統一 SaaS 入口。

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

## 當時還沒有和 IT 流程整合

技術鏈跑通後，我們重新把人員生命週期攤開：

```text
新同事到職，是誰建立身分？          上游企業 IdP
同事轉組，哪裡先改 group／role？     上游流程與企業 IdP
同事離職，哪裡負責立即停用？         上游企業 IdP
Keycloak 在這裡新增了什麼？          AI 平台使用的 federation、claim 與 token
```

四個答案擺在一起後，「Identity Center」這個名字開始變得尷尬。我們建立的是技術中心，卻沒有把組織人員生命週期的 source of truth 移進來，也沒有和 IT 團隊約定下游服務、SaaS 接入與權限回收的共同流程。Keycloak 的主要工作，是把上游已經知道的人員狀態轉成少數 AI 服務看得懂的 token 與 role。

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

如果 Keycloak 同時服務多個內外部系統，IT onboarding／offboarding 已經能驅動帳號與權限回收，各下游服務也承諾接進共用 SSO 與角色模型，這份 operating surface 就有機會攤在整個組織上。當時我們的收益主要落在少數 AI 服務，平台團隊卻要先為它們接下接近完整 IdP 的 runtime responsibility。這才是放棄 Keycloak 的主因。

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

改採 Cognito 後，平台不再操作 Keycloak Pod、Operator、database 與 cache。OIDC service runtime 進入 AWS 的服務邊界，正好對準當時想縮小的維運面。這項選擇也保留了一條界線：企業級 Identity Center 要等 IT、Security 與各服務 owner 都準備參與時再談，不由 AI 平台靠多部署一套服務先行宣布完成。

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
| 組織整合 | 可成為共用平台，但當時尚未整合 IT lifecycle、下游服務與 SaaS 入口 | 維持 AI 服務範圍 | 暫不為少數服務自建企業 Identity Center |
| Runtime | 平台維運 | AWS 服務邊界 | 縮小 AI-only operating surface |
| 設定與 Policy | 平台仍要負責 | 平台仍要負責 | Managed 不等於 zero-ops |
| 客製與可攜性 | 彈性與部署選項較多 | 服務限制與 AWS coupling | 接受限制，換取較少 runtime ownership |

我沒有把這些欄位做成 `82 分 vs. 76 分`。這次決策先問的其實是組織範圍：我們現在是不是正在和 IT 團隊一起建企業共用的 Identity Center？當時答案是否定的。沒有完整 lifecycle integration、下游服務接入承諾與共同 owner，再多功能也很難替 Keycloak 的固定維運成本找到合理歸屬。

如果這些前提成立，Keycloak 的結論完全可能反過來。高度客製的 authentication flow、跨應用 federation、統一角色模型與較高的部署自主性，都是值得投資的理由。放在只有少數 AI 服務使用的 identity bridge，同一筆成本就不划算。

這次選 Cognito 也不是單向獲利。我們接受 AWS coupling、quota、費用與產品限制，換掉自己維運 IdP runtime。只要發生以下任何變化，Decision Record 就應該重開：

- IT、Security 與平台團隊開始共同設計 onboarding／offboarding 與權限回收。
- 多個非 AI 系統或 SaaS 入口承諾接入同一套 federation 與管理模型。
- 必要的 authentication flow 或 extension 超出 Cognito 能合理承接的範圍。
- AWS coupling、費用、quota 或復原目標不再能接受。

## 選型結果與下一個 Identity 缺口

Keycloak 的技術鏈成功後，我們才看清楚原本把需求叫作 Identity Center 有多大。企業平台級的 Identity Center 必須接進 IT lifecycle、各下游服務與共用 SaaS 存取治理，不能只靠 AI 團隊部署一套 Keycloak 就算完成。這些條件尚未成立時，我們先把需求縮回 AI identity bridge，由 Cognito 接走 OIDC runtime。企業 IdP、Gateway 與 Resource Server 仍保留各自的責任。

產品換完，identity contract 反而需要寫得更精確。Human 的 `sub`、Service 的 client identity、真正執行的 workload、token audience、role／scope，以及「Agent 正代表誰」的 delegation，不能再全部塞進一個 `user_id`。Day 7 會把 Human、Service、Agent 與 Workload 拆成四個責任位置，再確認每一格究竟靠什麼 evidence 成立。
