# Identity field placement matrix

這份表是 Lab 04 的讀者交付物，用來區分 raw claims、驗證後的 principal context，以及送往不同後端的 telemetry projection。它不是通用法規清單；實際欄位仍要依資料分類、查詢需求、保留期限與組織政策調整。

| 欄位 | Raw claims | Verified context | Metric labels | Trace attributes | Loki resource labels | Loki structured metadata | Audit | 原因 |
|---|---:|---:|---:|---:|---:|---:|---:|---|
| raw token | 有 | 不保留 | 禁止 | 禁止 | 禁止 | 禁止 | 原則上禁止 | credential 不應成為觀測資料；必要時另留一次性 token fingerprint |
| email／full name | 可能有 | 驗證後可供產品邏輯使用 | 禁止 | 預設禁止 | 禁止 | 預設禁止 | 依政策決定 | 直接識別資訊會擴大存取面，也容易被複製到多個 backend |
| `principal.ref` | 無 | HMAC pseudonym | 禁止 | 建議 | 禁止 | 建議 | 建議 | 可關聯單筆 action，不適合成為 Prometheus／Loki index 維度 |
| team | claim | 經 mapping 驗證 | 適合，需受控字典 | 適合 | 視租戶與基數決定 | 適合 | 適合 | bounded dimension，可支援責任歸屬與聚合查詢 |
| role | claim | 經 mapping 驗證 | 通常不放 | 可放 primary role | 通常不放 | 視查詢需求 | 完整角色集合 | 角色集合與組合可能變多，Audit 又需要保留決策當下的證據 |
| tenant | claim | 經 mapping 驗證 | 只有 bounded tenant 才考慮 | 適合 | 多租戶隔離時依平台設計 | 適合 | 適合 | 先確認 tenant 是安全邊界還是單純標籤 |
| issuer／audience | token | 驗證證據 | 禁止 | 可用低基數 normalized value | 禁止 | 視除錯需求 | 建議 | Audit 要回答哪個 IdP 與哪個 workload 接受了 credential |
| assurance | 無 | 驗證流程產生 | 禁止 | 建議 | 禁止 | 建議 | 建議 | 讓查詢者分辨 verified、delegated 與 observed identity |
| `action_id` | 無 | action context | 禁止 | 建議 | 禁止 | 建議 | 必要 | 單筆 correlation 屬於高基數，不應成為 metric／stream label |
| session／conversation ID | 可能有 | application context | 禁止 | 依需要 | 禁止 | 依需要 | 依事件要求 | 長生命週期識別碼要另外評估資料保留與跨事件串接風險 |

## 三條實作規則

1. Raw claim 只留在驗證邊界內。驗證成功後建立一個結構明確的 `VerifiedPrincipalContext`，不要把 claims map 原封不動往下傳。
2. 每個 destination 使用獨立 allowlist。Metrics、Traces、Logs 與 Audit 不共用一個 `to_attributes()`。
3. Collector 做第二道清理。Lab 的 Alloy transform 會刪除已知禁止欄位，但不能取代 producer minimization、backend RBAC、retention 與資料盤點。

`principal.ref` 在 Lab 內以 HMAC-SHA256 產生。公開 fixture 的 key 只是為了讓輸出可重現，不能直接搬到 production；真實環境應由 Secret 管理、規劃 rotation，並理解 pseudonym 仍可能被重新關聯，因此不等於匿名化。
