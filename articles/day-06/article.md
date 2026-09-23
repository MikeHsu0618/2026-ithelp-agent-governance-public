# Day 6｜雖然 Keycloak 十分強大，但最終我們選擇 AWS Cognito

要讓 Agent Gateway 根據「誰在呼叫」決定 MCP Tool 權限，我們需要一個能接上既有企業 IdP、再向 AI 服務發出穩定 Token 的入口。我們先把 Keycloak 部署到 Kubernetes，Federated Login、JWT Role、Gateway 到 MCP 的 Tool RBAC 都跑通了，最後卻選擇改用 Cognito。

這不是一次「PoC 失敗所以換產品」的故事。技術鏈通了，選型問題才看得更清楚：團隊現在準備經營一座企業級 Identity Center，還是只需要先替少數 AI 服務補上一層 OIDC bridge？

這項組織限制從評估開始就存在。我們和 IT 團隊還沒有對企業 Identity Center 的範圍、owner 與導入順序取得共識，可投入的整合和維運人力也有限。人員到職、轉組與離職仍由既有流程和企業 IdP 掌握，近期明確排進時程的只有幾個 AI 服務。兩個方案因此都能發出合格的 Token，背後代表的工作量卻完全不同。

## Keycloak 實際跑通了什麼

我們測試的不是一個只會顯示登入頁的 Keycloak。完整路徑從企業 IdP 開始，經過 Keycloak 轉換身分，再由 Gateway 根據 JWT 中的角色決定使用者能看見哪些 MCP Tools：

```text
Human
  → 上游企業 IdP
  → Keycloak
  → Agent Gateway
  → MCP Server
```

實作時遇過一個很小、卻會讓授權結果完全不同的細節。Keycloak 預設不是把 realm role 放在扁平的 `role` 欄位，而是放在 `realm_access.roles` 陣列裡：

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

Gateway policy 如果直接判斷 `jwt.role == "mcp-observer"`，自然永遠對不到。我們後來改成檢查 `realm_access.roles` 的 membership，也評估過透過 protocol mapper 把 claim 轉成下游共同約定的形狀。

調整後，沒有 Token 的 request 會收到 `401`，缺少角色時維持 deny by default，不同角色也只能看見自己被允許的 Tool 子集。Keycloak 可以接企業 IdP，也能把角色一路帶到 Gateway 與 MCP。後來影響選型的，是誰來長期維護這條路。

[Keycloak Server Administration Guide](https://www.keycloak.org/docs/latest/server_admin/) 對 identity brokering、user federation、role 與 protocol mapper 都有完整說明。實際導入時，文件能告訴我們功能在哪裡，claim contract 要長什麼樣子，仍得由平台和下游服務共同決定。

## 我們缺的是橋接層，不是另一份員工主檔

這裡說的 Identity Center 是一個架構角色，不是 AWS IAM Identity Center 這項產品。如果要把 Keycloak 建成全組織的 Identity Center，工作範圍會包括共用 federation、group／role model、Token contract、下游系統與 SaaS 接入，以及相應的 SLA 和 on-call。

當時的組織條件還接不住這個範圍：

- 員工身分的 source of truth 已經在上游企業 IdP，Keycloak 不會取代既有的 onboarding、轉組和 offboarding 流程。
- IT、Security、平台和各服務 owner 尚未承諾一套全公司的 group、role 與 claim contract。
- 已排進時程的需求集中在少數 AI 服務，其他系統沒有一起遷移共用 SSO 的計畫。
- 平台團隊可以完成 PoC，卻沒有足夠人力同時承諾企業級 rollout、migration 與長期 on-call。

這些都不是 Keycloak 的產品缺陷。問題在於，若只有 AI 平台使用它，完整 runtime 的固定成本只能由少數服務吸收。等到多個內部系統願意共用 federation 和角色模型，這筆成本才有機會攤在整個組織上。

## 「維運很重」必須說清楚重在哪裡

只在選型文件寫一句「Keycloak 維運很重」沒有太大用處，因為沒有人能對這句話負責。需要排進 backlog 和 on-call 的工作，大致落在三層。

第一層是服務本身。Keycloak Pod、Operator、database、session、cache、backup、restore、upgrade 和 rollback 都要有 owner。它不需要第一天就做跨區多叢集，但單一叢集也躲不開資料庫、備份與版本升級。等 SLA 提高之後，load balancer、cache topology 和跨叢集故障模式才會繼續加上去。Keycloak 官方的 [HA 架構說明](https://www.keycloak.org/high-availability/introduction) 和 [distributed cache 文件](https://www.keycloak.org/server/caching) 也清楚列出了這些取捨。

第二層是 Identity 設定。Realm、client、callback URL、scope、role、protocol mapper、signing key 和 JWKS 輪替都會影響下游。任何 claim 變更都不能只在管理介面按下儲存，還要確認 Gateway policy、MCP Server 與既有 client 能否一起接住。

第三層才是人員生命週期。誰是有效員工、何時轉組、帳號何時停用，仍以上游企業 IdP 和組織流程為準。Keycloak 在我們的架構裡負責 federation 與 Token，不會自動補齊跨團隊尚未談妥的 joiner、mover、leaver 流程。

把這三層拆開後，決策就清楚多了。Keycloak 帶來的控制力很有價值，但當時我們只需要第二層的一部分，卻得先接下第一層的完整責任。第三層則依舊留在原本的組織流程。

## 換成 Cognito，移走的是 Runtime

![Keycloak 與 Cognito 兩條技術鏈都通過，差別是平台擁有的 runtime 維運面，兩者的人員生命週期仍在上游企業 IdP。](https://raw.githubusercontent.com/MikeHsu0618/2026-ithelp-agent-governance-public/day-09-r2/assets/diagrams/day-06/identity-center-before-after.png)

改用 Cognito User Pools 後，請求仍然經過相同的責任位置：

```text
Human／Service
  → 上游企業 IdP 或 client credential
  → Cognito User Pool
  → Agent Gateway
  → MCP Server
```

Cognito 可以 federation 外部 OIDC／SAML IdP，也能透過 resource server 和 custom scope 處理 M2M 授權需求。Human 使用 public client 走 Authorization Code + PKCE，M2M 則使用帶有 secret 的 confidential client。兩條 flow 分開後，callback、scope、Token lifetime 和 credential rotation 才不會混在同一個 client 裡。相關能力可參考 AWS 的 [third-party identity federation](https://docs.aws.amazon.com/cognito/latest/developerguide/cognito-user-pools-identity-federation.html)、[app client](https://docs.aws.amazon.com/cognito/latest/developerguide/user-pool-settings-client-apps.html) 與 [M2M resource server](https://docs.aws.amazon.com/cognito/latest/developerguide/cognito-user-pools-define-resource-servers.html) 文件。

平台不再操作 Keycloak Pod、Operator、database 和 cache，OIDC runtime 進入 AWS 的服務邊界。不過 managed service 只縮小了 operating surface，沒有替我們設計 Identity。上游 IdP mapping、app client、scope、Token lifetime、Gateway policy、IaC、quota、監控與退出方案，仍然是平台的工作。

兩個產品在本次決策裡扮演的角色，可以濃縮成這張表：

|  | Keycloak | Amazon Cognito User Pools |
| --- | --- | --- |
| 產品識別 | ![Keycloak 官方專案圖示](https://raw.githubusercontent.com/MikeHsu0618/2026-ithelp-agent-governance-public/day-09-r2/assets/third-party/keycloak/keycloak-icon-color.png) | ![Amazon Cognito 官方 AWS Architecture Icon](https://raw.githubusercontent.com/MikeHsu0618/2026-ithelp-agent-governance-public/day-09-r2/assets/third-party/aws/amazon-cognito-architecture-icon.png) |
| 技術驗收 | Federation、role claim、Gateway 與 MCP RBAC 已跑通 | Human 與 M2M 路徑已跑通 |
| 平台要承擔的範圍 | Identity 設定加上完整服務 runtime | Identity 設定與整合，runtime 在 AWS 服務邊界 |
| 當時的適配性 | 適合有人長期經營、服務多個系統的 Identity Platform | 適合先替少數 AI 服務提供清楚的 OIDC boundary |
| 接受的代價 | 固定維運成本較高 | AWS coupling、quota、費用與可客製範圍受產品限制 |

我們最後選 Cognito，換來的不是更多 IAM 功能，而是不用為少數服務先維運一整套 IdP runtime。相對地，Cognito 的限制也被寫進決策紀錄，不能因為它是 managed service 就把 portability 和成本問題略過。

## 什麼條件會讓我們重選

完整的 [Identity Center 組織選型 Decision Record](https://github.com/MikeHsu0618/2026-ithelp-agent-governance-public/blob/day-09-r2/articles/day-06/identity-center-decision-matrix.md) 放在 repo。這次沒有替功能逐項打分，因為兩條技術鏈都已經跑通，先決條件在於組織準備承接哪一種 operating model。

出現以下情況時，我們會重開這份決策：

- IT、Security 和平台團隊對企業 Identity Center 的 owner、範圍與資源取得共識。
- 多個非 AI 系統或 SaaS 願意接入共同的 federation、角色模型與生命週期流程。
- Cognito 的 authentication flow、AWS coupling、quota、費用或復原目標開始限制平台。

Keycloak PoC 排除了技術不可行這個理由。最後選 Cognito，是因為當時只承諾 AI identity bridge，還沒有準備經營全公司的 Identity Center。

產品選完後，Token 裡的身分仍然不能含糊帶過。Human 的 `sub`、Service 的 client identity、真正執行請求的 Workload，以及 Agent 正代表誰，都不能塞進同一個 `user_id`。Day 7 會把這些角色拆開，確認每一個責任位置應該留下什麼證據。
