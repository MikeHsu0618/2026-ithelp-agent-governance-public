# Agent Registry 採用盤點表

這份盤點表來自 Day 19 對 Agent Registry `0.4.0` 的 live Lab，以及作者在 `0.3.3` 時期的實際選型經驗。它不是通用產品評分，也不以功能存在取代組織 ownership。

| 面向 | 要回答的問題 | `0.4.0` 本次證據 | 採納前仍要完成 | 結果 |
| --- | --- | --- | --- | --- |
| Catalog | 使用者能否用 name、namespace 與 tag 找到 Agent | UI／API 可讀 `day19byo@approved` | 定義 metadata schema、owner、deprecation 與搜尋品質 | `PASS` |
| Reconciliation | Deployment 能否建立並更新 kagent Agent | Registry status 為 `RuntimeConfigured=True`，kagent image reference 跟著 target 變更 | 加入 production failure recovery、controller SLO 與告警 | `PASS` |
| Teardown | Desired state 能否移除 runtime resource | `desiredState: undeployed` 後，帶 deployment label 的 kagent Agent 消失 | 定義 data retention、依賴檢查與復原流程 | `PASS` |
| Artifact identity | `approved` 是否綁定不可變內容 | 相同 name／tag 可由 `1.0.0` 改成 `1.0.1` | 使用 digest、signature、attestation，限制 tag mutation | `RISK_EXPOSED` |
| Promotion | 誰能把 Artifact 從 candidate 推到 approved | 本次 Lab 沒有 promotion workflow | 建立 reviewer、separation of duties、環境 promotion 與 rollback | `NOT_PROVEN` |
| Authentication | API caller 是否已驗證 | 預設 OSS chart 接受未帶 credential 的 apply | 配置 AuthnProvider、credential lifecycle 與入口保護 | `RISK_EXPOSED` |
| Authorization | Caller 是否能對特定資源執行特定操作 | Public provider 預設允許所有操作 | 配置 AuthzProvider、role mapping、namespace／resource rule 與 audit | `RISK_EXPOSED` |
| Source of truth | Git、Registry database 與 cluster 以誰為準 | Registry 以 PostgreSQL 保存 spec／status，controller materialize runtime resource | 只保留一條合法 write path，定義 drift、break-glass 與 ownership | `ORGANIZATIONAL` |
| Runtime enforcement | Artifact 進入 Runtime 後，traffic 是否受到 policy 控制 | 本次只驗 kagent resource lifecycle | 由 Gateway／Runtime enforcement point 驗 identity、Tool、argument 與 resource | `OUT_OF_SCOPE` |
| Supply chain | Image 是否完成來源與完整性驗證 | 兩個本機 tag 指向同一份測試 image，未驗簽章 | 驗 digest、SBOM、provenance、signature 與 admission policy | `NOT_PROVEN` |
| Operations | Registry 自己的資料庫、升級與可用性誰負責 | Lab 使用 chart 內建 dev／eval PostgreSQL | 使用外部 HA PostgreSQL，定義 backup、restore、upgrade、SLO 與 on-call | `NOT_PROVEN` |

判讀原則：`PASS` 只代表本次版本與 Lab 範圍內已重現。`RISK_EXPOSED` 代表實驗成功觀察到風險，不是 runner 壞掉。`NOT_PROVEN` 與 `OUT_OF_SCOPE` 都不能在架構簡報裡改寫成功能已完成。
