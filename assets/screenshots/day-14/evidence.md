# Day 14 Screenshot Evidence

Status：complete。

## Environment

```text
Tested:       2026-09-05 Asia/Taipei
Python:       3.14.5
PyJWT:        2.13.0
agentgateway: v1.5.0 pinned image digest
Docker:       29.4.0
```

## Commands executed

```bash
make lab-03-runtime-check
make lab-03-runtime-run
```

Final result：26 tests passed，branch coverage 85.49%，Ruff lint／format clean。Pinned agentgateway image 對公開 YAML 回傳 `Configuration is valid!`，live container 的 9/9 case 符合預期。

## Actual result

- Human key 在值班工程師 active 時得到 `200`。
- 同一把 key 在 directory state 改成 disabled、Gateway mapping 未同步時仍得到 `200`，結果標為 `RISK_EXPOSED / STALE_MAPPING_ALLOWED`。
- Workload consumer key 得到 `200`，retired key 得到 `401`。
- 合法 Human JWT 得到 `200`；wrong issuer、wrong audience、missing issuer 與 missing audience 都得到 `401`。
- 四條成功路徑抵達同一個 synthetic backend，provider 收到 Gateway 注入的 provider key，沒有收到 caller key 或 JWT。
- Human key、workload key、retired key、JWT、private signing key 與 provider key 都沒有落入 evidence artifact。

## 發稿 review 發現的版本差異

第一版 Lab 鎖在 agentgateway `1.4.1`，只測 valid JWT 與 wrong audience。2026-09-05 補測 missing issuer／audience 時，兩個 request 都得到 `200`。官方 release notes 說明，`1.4.x` 及更早版本只有在 Token 帶著 `iss`／`aud` 時才會比較設定值。

公開版因此升到 pinned `1.5.0`，並把 wrong／missing issuer、wrong／missing audience 都列為固定回歸案例。這份 evidence 保存的是升版後的九組結果；`1.4.1` 的兩個 `ALLOW` 只作發稿校正紀錄，不混入目前的 PASS report。

## Validation boundary

| Evidence | 能證明 | 不能證明 |
| --- | --- | --- |
| Live standalone Lab | pinned `1.5.0` 的 API key metadata、configured JWT issuer／audience 必填與比對、backend key injection，以及九個 HTTP 結果 | Kubernetes controller／CRD、production HA、真實 LLM provider 或 kagent compatibility |
| Synthetic directory state | static Human key mapping 未同步時會形成 offboarding gap | 所有 virtual-key 產品都沒有 IdP／SCIM integration |
| Workload key case | per-runtime key 可隔離、輪替，舊 key 可拒絕 | Pod instance attestation、federated workload identity 或 secret manager delivery |
| JWT cases | signature、issuer、audience 與 policy claim boundary | 停用帳號後，已發出的 Token 一定即時撤銷 |

## Presentation method

`01-credential-boundary-results.png` 由本次 `gateway-runtime run` 的 `terminal.txt` 重新排成 terminal card，再輸出為 1600 × 1080 PNG。畫面與 raw runner 都依 Human key、workload key、JWT 分組，原始文字完整保留在 `evidence/terminal.txt`。正文另保留可複製 command、公開 YAML、decision table 與 machine-readable JSON。

畫面沒有 raw credential。`user/sre-oncaller`、`workload/runtime-a`、issuer、audience 與 backend 都是合成資料。

## Image

| Image | SHA-256 | Run | Redactions | Status |
| --- | --- | --- | --- | --- |
| `01-credential-boundary-results.png` | `4cfab3d677df8467539e5a3b427de1b2f42833b5db8b067319ed4973ffa336b6` | `20260905T123118Z` | none；runtime config 由 Runner 先 redacted | PASS |

## Machine evidence hashes

| File | SHA-256 |
| --- | --- |
| `evidence/agentgateway-config.redacted.json` | `0e487459d9076d7be49c360fd512789bf0a3da8eb77f9bc4c210f0d44a5fcaee` |
| `evidence/config-validation.json` | `d7e5848d08f9a7f53cdc94295a5d87c5898664608599e3c9eea9f773ab47fc7b` |
| `evidence/decision-table.md` | `70c1f809c9b75926068393c8c85177bdfa31af8fed829b152fd5d517a732be21` |
| `evidence/jwks.public.json` | `34e33645f8923d32defa3710bb57608fb45df2147714eb8b330b1766499994d0` |
| `evidence/manifest.json` | `c1b67d720ba2e92c089cf8dfdd06d86ad6714a16c30bcd4eefd88379d2f6e84e` |
| `evidence/report.json` | `cdb71fb1a681ed1dbab758c3ca43655db8613d874ccaaa4d0abb537ace79062d` |
| `evidence/terminal.txt` | `bc98ad20a6f409b4ca3dd7ed683350d747e0deb42dcb1a15e23dba2339d35098` |

## Config and diagram

- `labs/03-gateway-runtime/configs/agentgateway.example.yaml`：`bea2ee2e44b832b67357206b6ab1f8a7fdc22ffe227cd9c93b0cc0046c81ebec`
- `diagrams/svg/day-14/credential-boundary.svg`：`a5a55edca524bf5a073536b0240ca2671ca617165688143bf414b86a89c0ce9e`
- `assets/diagrams/day-14/credential-boundary.png`：`00bf873972eb86288372db223db806ad4ed53fe7b4cea9b873cf907f36306628`

SVG 已通過 `xmllint`，文章用 PNG 為 1386 × 858。三條 credential path 改成上下排列，箭頭不穿過節點，縮到 iT 邦幫忙文章寬度後仍能讀到 stale Human mapping、workload rotation、JWT claim validation 與 provider-key boundary。

## Cleanup

```bash
make lab-03-runtime-down
```

這個 command 只刪除 Lab root 下、帶正確 `.lab-03-artifacts` marker 且不是 symlink 的 `artifacts/`。
