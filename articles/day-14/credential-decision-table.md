# Human Virtual Key、Workload Key、JWT 決策表

這張表不是產品排名。它用 actor、lifecycle、rotation、delegation、audit 與 provider-key exposure，判斷一種 credential 適不適合目前這條路徑。

| Credential | 它直接證明什麼 | Human lifecycle | Rotation／offboarding | Delegation 與 audit | Provider key | 比較適合 |
| --- | --- | --- | --- | --- | --- | --- |
| Human virtual key | 持有人知道這把 bearer key；Gateway 可把 key 對到 metadata | 只有在 mapping 與 authoritative IdP lifecycle 同步時才成立 | 需另建同步、撤銷、遺失與重發流程；Lab 中值班工程師停用後舊 mapping 仍 ALLOW | 可記 usage owner，但 metadata 不等於當下登入、MFA、session 或代表關係 | 可留在 Gateway 後面 | 個人 developer key、短期相容路徑；前提是清楚標示 lifecycle owner |
| Workload consumer key | 持有人知道某個 runtime 的 bearer key | `NOT_APPLICABLE`，不冒充 Human | 可按 workload 個別輪替；retired key 應立即拒絕 | 可辨認 consumer／workload，不能證明 pod instance 或 Human delegation | 可留在 Gateway 後面 | 只接受 static API key 的 runtime、provider key isolation、有限爆炸半徑 |
| Human JWT principal | Issuer 對 claims 簽章；Resource 可驗 `iss`、`aud`、`exp`、`sub`、`client_id` | Token issuance 可接企業 IdP；既有 Token 是否立即撤銷仍取決於 TTL／revocation／session 設計 | 短效 Token 到期後重取；wrong／missing issuer、wrong／missing audience、signature 與 expiry 都應在 Gateway 拒絕 | 可攜帶可驗 principal 與 client context；完整 Agent delegation 仍需 Day 9 類 contract | 可由 backend auth 換成另一把 credential | Human session、resource-bound access、需要 issuer／audience／client attribution 的路徑 |

## Lab 03 的實際結果

| Case | HTTP | Control result | 穩定代碼 | 判讀 |
| --- | ---: | --- | --- | --- |
| Human key，值班工程師 active | 200 | `CONTROL_OK` | `KEY_MAPPING_ACTIVE` | key 與 mapping 一致 |
| 同一把 Human key，值班工程師 disabled | 200 | `RISK_EXPOSED` | `STALE_MAPPING_ALLOWED` | Gateway 不知道企業目錄已停用值班工程師 |
| Workload 新 key | 200 | `CONTROL_OK` | `WORKLOAD_KEY_ISOLATED` | key 只代表 `workload/runtime-a` |
| Workload retired key | 401 | `CONTROL_OK` | `OLD_KEY_REJECTED` | 輪替後舊 key 不在 allowlist |
| Human JWT | 200 | `CONTROL_OK` | `JWT_PRINCIPAL_VERIFIED` | 驗簽章、issuer、audience 與 policy claims |
| Wrong-issuer JWT | 401 | `CONTROL_OK` | `JWT_ISSUER_REJECTED` | Token 由未允許的 issuer 簽發 |
| Wrong-audience JWT | 401 | `CONTROL_OK` | `JWT_AUDIENCE_REJECTED` | Resource boundary 在 Gateway 擋下 |
| Missing-issuer JWT | 401 | `CONTROL_OK` | `JWT_ISSUER_REQUIRED` | Token 缺少 configured issuer 對應的 `iss` |
| Missing-audience JWT | 401 | `CONTROL_OK` | `JWT_AUDIENCE_REQUIRED` | Token 缺少 configured audiences 對應的 `aud` |

JWT 四個負向案例鎖在 agentgateway `1.5.0`。`1.4.x` 及更早版本只在 Token 含有 `iss`／`aud` 時比對設定值，缺少 claim 的 Token 可能通過；版本差異請參考官方 [release notes](https://agentgateway.dev/docs/standalone/latest/release-notes/release-notes/)。

## 使用前再補的四個欄位

1. `authoritative source`：人員／workload 狀態的權威來源在哪裡？
2. `lifecycle owner`：誰負責建立、輪替、撤銷、遺失與離職處理？
3. `evidence level`：只能看到 consumer，還是能看到 Human、client、Agent chain 與 executing workload？
4. `fallback behavior`：IdP、key store 或 policy service 故障時，是 fail closed、沿用 cache，還是直接放行？

若這四格填不出來，「支援 API key／JWT」仍只是一張功能表。
