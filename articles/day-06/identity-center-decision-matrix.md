# Identity Center 組織選型 Decision Record

版本：2026-08-29

這裡的 Identity Center 是架構角色，不是 AWS IAM Identity Center 這項產品。表格先問「這個中心實際掌握哪些生命週期」，再比較功能。它適合放進 ADR、Architecture Review 或平台提案，不是把所有欄位換成分數後相加。

## 本次已填寫的紀錄

### Context

- AI 平台需要一致的 OIDC issuer，提供 Human federated login 與 machine-to-machine token。
- 下游 Gateway 必須根據 token claim 對 MCP Tool 做授權。
- 真實人員的到職、轉調、離職仍由既有企業 IdP 與其流程掌握。
- IT 團隊與 AI 平台團隊暫時尚未對企業 Identity Center 的範圍、owner 與導入順序取得共識。
- 可投入的整合與維運人力不足，onboarding／offboarding、group／role lifecycle、下游服務與 SaaS 入口的整合負擔也超出當時能承諾的範圍。
- 明確範圍主要是少數 AI 服務，以上限制在 Keycloak PoC 前與進行期間都已存在。
- Keycloak 技術鏈已在 Kubernetes 環境跑通。後續 Cognito User Pools 的 Human／M2M 路徑也完成端到端驗證。

### Decision

以 Amazon Cognito User Pools 承接這個 AI 平台範圍內的 OIDC federation／issuer，不為少數服務先自建全公司的 Identity Center。企業級 Identity Center 等 IT、Security、平台與各服務 owner 對範圍及責任取得共識，並配置足夠的整合與維運人力後再重新評估。組織的人員生命週期仍以上游企業 IdP 為準，Gateway 與 Resource Server 繼續負責 action／resource authorization。

### 比較矩陣

| 決策面 | 必須回答的問題 | Keycloak 路徑 | Cognito 路徑 | 對本次決策的影響 |
| --- | --- | --- | --- | --- |
| 必要技術鏈 | federation、Token、Human、M2M、角色／scope 能否接到 Gateway？ | Human federation、role claim、per-tool RBAC 已 `PASS`，彈性高 | Human PKCE、M2M Client Credentials 與 Gateway policy 已 `PASS` | 兩邊都能做，不用功能多寡決勝 |
| 人員生命週期 | 誰建立、轉調與停用真實員工？ | 仍由上游企業 IdP 掌握 | 仍由上游企業 IdP 掌握 | 兩者都不是本案的 lifecycle source of truth |
| 組織整合範圍 | 是否已取得 IT 共識，並有人力整合 lifecycle、下游服務與 SaaS 入口？ | 能力可支援共用平台，但當時共識、人力與導入條件尚未到位 | 維持少數 AI 服務的 managed identity boundary | 暫不以局部需求承擔企業平台成本 |
| Runtime ownership | 誰維運服務、資料庫、cache、容量、升級與故障復原？ | 平台團隊 | 服務 runtime 在 AWS 邊界，平台仍管設定、整合與復原策略 | AI-only 範圍不值得新增完整自管 IdP runtime |
| 設定 ownership | 誰管 client、callback、scope、claim mapping、keys 與 IaC？ | 平台／Security 共同定義，由平台操作 | 平台／Security 共同定義，由平台操作 | Managed service 沒有消滅 identity engineering |
| 客製需求 | 是否真的需要自訂 login flow、extension、storage 或精細管理能力？ | 能力強，適合明確的客製需求 | 受服務介面限制，換取較小 runtime 面 | 當時沒有足以支付自管成本的必要客製需求 |
| 重用範圍 | 除 AI 平台外，有多少系統會共同使用？ | 當時主要服務 AI 平台 | 當時主要服務 AI 平台 | 使用面窄，使自建中心的固定成本較難攤提 |
| 可攜性與退出 | 若離開目前平台，設定與身分資料怎麼移？ | 開放原始碼、部署選項較多，但 migration 仍需設計 | AWS 耦合較深，pool、client、Lambda hook 與資料移轉要另做出口 | Cognito 的代價必須明列，不能寫成單向獲利 |
| 稽核與授權責任 | IdP claim、Gateway policy、Resource authorization 由誰負責？ | 三層責任都要定義 | 三層責任都要定義 | 換 IdP 不會自動完成 Agent Governance |

### Consequences

得到的：

- 不再由平台團隊維運 Keycloak Pod、資料庫、cache 與版本升級。
- Human 與 M2M 都能使用同一個受管 OIDC 服務邊界。
- 平台可以把時間集中在 claim contract、Gateway policy 與 Resource authorization。

付出的：

- 接受 AWS 服務耦合、quota、費用與產品限制。
- Human public client 與 M2M confidential client 必須分開設計。
- callback、scope、attribute／claim mapping、token validation、IaC 與復原／退出方案仍要有人負責。

### Revisit triggers

出現下列任一條件時，重新評估 Keycloak 或其他組織級 Identity Center：

- 多個非 AI 系統開始需要共用的 federation、realm／tenant 或管理模型。
- IT、Security 與平台團隊對 Identity Center 的範圍與 owner 取得共識，並配置足夠的整合及維運人力。
- 多個下游服務或 SaaS 入口承諾接進共用的 SSO 與存取治理。
- 需要 Cognito 無法合理表達的 authentication flow、extension 或 portability。
- AWS coupling、費用、quota 或復原目標不再能接受。
- 已有專責 Identity Platform 團隊願意擁有 runtime、資料與 on-call。

## 可複製的空白模板

### Context

- 服務範圍：
- Human flow：
- Machine flow：
- 上游 authoritative identity source：
- 下游 enforcement points：
- 現有實測 evidence：

| 決策面 | 要查的 Evidence | 方案 A | 方案 B | Owner／備註 |
| --- | --- | --- | --- | --- |
| 必要技術鏈 | 成功與失敗 request、token、policy decision |  |  |  |
| 人員生命週期 | joiner／mover／leaver 流程與停用延遲 |  |  |  |
| 組織整合範圍 | IT／Security 共識、owner、可投入人力、下游服務與 SaaS 接入承諾 |  |  |  |
| Runtime ownership | HA、DB、cache、patch、upgrade、on-call |  |  |  |
| 設定 ownership | client、callback、scope、claim、keys、IaC |  |  |  |
| 客製需求 | 已確認的必要 extension，不列願望清單 |  |  |  |
| 重用範圍 | 真正承諾接入的系統與 owner |  |  |  |
| 可攜性與退出 | export、migration、lock-in、復原演練 |  |  |  |
| 稽核與授權責任 | IdP、Gateway、Resource Server 分工 |  |  |  |

### Decision

- 選擇：
- 沒選另一案的原因：
- 得到什麼：
- 付出什麼：
- 重新評估的觸發條件：
- 決策 owner／review date：

## Evidence 等級

- `PASS`：實際 request、token 與下游 decision 符合預期。
- `PARTIAL`：能力存在，但條件、欄位或 ownership 未完整。
- `DOCS ONLY`：官方文件宣告，尚未親自驗證。
- `UNKNOWN`：沒有證據，不以推測補滿。

產品功能表可以當索引，不能取代這四種證據。
