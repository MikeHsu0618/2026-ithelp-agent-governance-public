# Day 6｜雖然 Keycloak 十分強大，但最終我們選擇 AWS Cognito

我們已經有企業 IdP 管理員工帳號，但 Agent Gateway 要替 MCP Tool 做授權，還需要一個能把登入身分轉成下游可用 Token 的入口。我們先在 Kubernetes 部署 Keycloak，接上企業 IdP，也讓 Gateway 根據 JWT 裡的角色限制 Tool 權限。這條路走得通，最後我們卻選了 AWS Cognito。

選型的分歧不在 Keycloak 能不能做，而在我們打算讓這套身分服務承擔多少工作。當時 IT 團隊與我們尚未對全公司 Identity Center 的範圍、owner 和整合順序取得共識，能投入的人力也有限。眼前排進時程的是少數 AI 服務。如果為它們先自管一套身分平台，後續的維運責任仍得有人接。

## Keycloak 的登入與 Tool 權限

我們使用的路徑是員工透過企業 IdP 登入，由 Keycloak 接住 federated identity、發出 Token，再由 Agent Gateway 檢查角色，決定 MCP client 看得見哪些 Tool。Keycloak 在這裡是身分橋接層，員工帳號的到職、轉組與停用仍由上游系統掌握。

串接時有個容易忽略的細節：Keycloak 的 realm role 不在扁平的 `role` 欄位，而是在 `realm_access.roles` 陣列裡。例如：

```json
{
  "realm_access": {
    "roles": ["mcp-observer", "default-roles-platform"]
  }
}
```

Gateway policy 若寫成 `jwt.role == "mcp-observer"`，有角色的使用者也會被拒絕。我們改成檢查陣列 membership，並評估用 protocol mapper 統一下游看到的 claim。修正後，沒有 Token 的請求拿到 `401`。有 Token 但缺少授權角色時，Gateway 仍拒絕。角色不同，能使用的 Tool 也不同。這段經驗讓我知道，產品都支援 OIDC 不等於下游已經約好同一份 claim contract。Keycloak 的 federation、role 與 mapper 能力可參考[官方管理文件](https://www.keycloak.org/docs/latest/server_admin/)。

## 全公司 Identity Center 的前提

Keycloak 很適合由一個團隊長期經營，讓多個內部服務共用 federation、角色模型和登入入口。但我們那時仍無法把 IT 的員工生命週期流程、Security 的權限規範、各系統的角色，以及 SaaS 接入排成同一個計畫。平台團隊若先為幾個 AI 服務架起 Keycloak，並不會因此取得維護全公司帳號和權限的權責。

這裡說的「Identity Center」是組織裡的統一身分平台角色，不特指 AWS IAM Identity Center。它需要有人維護共用的登入與 Token 約定，也需要各服務 owner 願意接入。少了這些條件，Keycloak 對我們而言會是一套功能完整、但主要只由 AI 平台使用的服務。

維運工作也很具體。自管 Keycloak 時，平台得照顧 Pod／Operator、資料庫、session 與 cache，安排備份、升級、復原和 on-call。realm、client、scope、mapper、signing key 也會牽動每一個下游應用。即使先從單一叢集開始，資料庫復原與版本升級也不會消失。至於員工何時到職或離職，還是在原本的企業 IdP 和組織流程裡處理。Keycloak 的 [HA](https://www.keycloak.org/high-availability/introduction) 與 [cache](https://www.keycloak.org/server/caching) 文件能幫忙規劃服務本身，但跨團隊的 owner 需要我們自己談妥。

## AWS Cognito 的登入路徑

換成 AWS Cognito User Pool 後，員工仍在既有企業 IdP 登入。它透過 federation 接收身分，再向 MCP console 發出供 Agent Gateway 驗證的 Token。下面這張圖只畫有人值班、從瀏覽器發起調查的路徑。下游看到的是 AWS Cognito 核發的 access token，不是企業 IdP 原封不動傳來的 Token。

![值班工程師透過 MCP console 啟動登入。AWS Cognito 將瀏覽器轉往企業 IdP。員工完成登入後，AWS Cognito 把授權碼帶回 console，console 以 PKCE 換取 access token，再攜帶 Token 呼叫 Agent Gateway，由 Gateway 驗證並套用 MCP Tool policy。](https://raw.githubusercontent.com/MikeHsu0618/2026-ithelp-agent-governance-public/day-06-r5/assets/diagrams/day-06/cognito-oauth-login.png)

互動式登入使用 public client 的 Authorization Code + PKCE。MCP console 導向 AWS Cognito 的授權入口，之後由它把使用者帶到企業 IdP。登入完成後，console 用授權碼和 PKCE verifier 換回 Token。AWS Cognito 的 [federation](https://docs.aws.amazon.com/cognito/latest/developerguide/cognito-user-pools-identity-federation.html)、[授權入口](https://docs.aws.amazon.com/cognito/latest/developerguide/authorization-endpoint.html)和 [Token endpoint](https://docs.aws.amazon.com/cognito/latest/developerguide/token-endpoint.html)文件分別說明了這幾段。Gateway 接到 access token 後，還是要按 issuer、Token 內容與 Tool policy 做自己的判斷。

沒有使用者互動的排程任務則走另一條路：confidential client 使用 Client Credentials 取得代表服務自己的 Token。Human 與 M2M 分開 app client，callback、scope、Token lifetime 和 secret 輪替才不會混在一起。Day 11、12 會再處理這兩條 OAuth flow 的 Token 與設定細節。

## 受管服務與平台責任

|  | Keycloak | AWS Cognito User Pool |
| --- | --- | --- |
| 產品識別 | ![Keycloak 官方專案圖示](https://raw.githubusercontent.com/MikeHsu0618/2026-ithelp-agent-governance-public/day-06-r5/assets/third-party/keycloak/keycloak-icon-color.png) | ![AWS Cognito 官方 AWS Architecture Icon](https://raw.githubusercontent.com/MikeHsu0618/2026-ithelp-agent-governance-public/day-06-r5/assets/third-party/aws/amazon-cognito-architecture-icon.png) |
| 平台自己維運的部分 | Keycloak runtime、資料庫、備份、升級，以及 Identity 設定 | Identity 設定與下游整合。OIDC runtime 由 AWS 維運 |
| 這次最在意的取捨 | 有較多控制空間，也要接下完整服務的 on-call | 少維運一套 runtime，接受 AWS coupling、quota 與產品限制 |

我們最後選 AWS Cognito，是因為它讓少數 AI 服務先有共同的 OIDC 入口，不必同時成立一個全公司的身分平台。平台團隊仍要維護上游 IdP mapping、app client、scope、Gateway policy、IaC、監控與復原方案。AWS Cognito 的費用、配額和可客製範圍也會持續影響這個選擇。

如果以後 IT、Security 和平台團隊一起承接統一的 Identity Center，或更多非 AI 系統需要共用登入與角色模型，Keycloak 就值得重新評估。[這次的選型 Decision Record](https://github.com/MikeHsu0618/2026-ithelp-agent-governance-public/blob/day-06-r5/articles/day-06/identity-center-decision-matrix.md) 留著當時的責任分工與代價，讀者也可以拿它檢查自己的組織條件。

身分入口選定後，還有一個問題沒有跟著解決：Token 能辨認登入的使用者或取得憑證的服務，卻不能單憑一個 `user_id` 說清楚哪一版 Agent 做了決定、哪個 Kubernetes Workload 真正送出請求。Day 7 會沿著同一筆調查，把這些角色拆開。
