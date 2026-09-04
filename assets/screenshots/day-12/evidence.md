# Day 12 Screenshot Evidence

Status：complete。

## Environment

```text
Tested:                 2026-09-04
Python:                 3.14.5
PyJWT:                  2.13.0
Terraform:              1.8.2
Terraform AWS provider: 6.61.0
agentgateway:            1.4.1
```

## Commands executed

```bash
make lab-02-up
make lab-02-check
make lab-02-cognito
make lab-02-cognito-config-check
```

Lab result：75 tests passed，branch coverage 90.81%，Ruff lint／format clean。Terraform HCL 通過 provider-schema validation，pinned agentgateway image 載入 committed JWKS、YAML 與 CEL 後回傳 `Configuration is valid!`。兩條 authorization rule 都要求 `token_use=access`，避免 Human 或 M2M 路徑誤收 ID Token。

## Actual result

- Human public client + Authorization Code + PKCE + resource-bound audience 通過。
- M2M confidential client + Client Credentials + custom scope 通過。Machine actor 取 verified `client_id`，Human subject 記為 `NOT_APPLICABLE`。
- Callback mismatch、Human scope、缺 policy claim、public client 誤走 M2M、錯 secret、M2M `openid` scope 與 M2M resource binding 都在預期階段拒絕。
- 9/9 case 符合預期。Compact JWT、PKCE verifier、client secret 與 private key 均未落盤。

## Validation boundary

| Evidence | 能證明 | 不能證明 |
| --- | --- | --- |
| Offline Lab | Cognito-shaped Human／M2M contract、decision 與 audit attribution | 真實 Cognito endpoint 或 client interoperability |
| `terraform validate` | HCL syntax 與 AWS provider schema | AWS 權限、domain 唯一、federation、callback 或 managed login |
| agentgateway `--validate-only` | Committed JWKS、YAML 與 CEL 可由 v1.4.1 解析 | Live Cognito token、discovery、client registration 或 MCP target call |
| Private operational record | 特定 Human SSO、M2M、Gateway JWT 與 MCP policy 路徑已跑通 | 所有 MCP client、OAuth flow 或 provider 組合都相容 |

AWS apply 與 live Cognito token call 都沒有在公開 Lab 執行，不標成 integration PASS。

## Presentation method

`01-cognito-dual-path-results.png` 由本次 `identity-boundary cognito` 的實際 CLI output 重新排成 Carbon 類型 terminal card，再輸出為 1600 × 850 PNG。正文另保留可複製 command、result table 與 machine-readable JSON。

所有 issuer、principal、client、callback、resource 與 scope 都是合成值。Credential fingerprint 只用來證明兩條成功路徑拿到不同 Token，不含 raw bearer credential。

## Image

| Image | SHA-256 | Run | Redactions | Status |
| --- | --- | --- | --- | --- |
| `01-cognito-dual-path-results.png` | `000fbe13555bf034290a84b3c4a49410641dbaccf9da415ffce3ce842826f648` | `day12-20260903T080349Z-99455893` | none，畫面不含 artifact 絕對路徑 | PASS |

## Machine evidence hashes

| File | SHA-256 |
| --- | --- |
| `evidence/config-validation.json` | `fc629d3735b8b276a8f537d2fb2474c8e974fa76c8f60a070b4f426d103dddb2` |
| `evidence/demo-manifest.json` | `09292d50f6bc57aa9a987b643dae12e42d295df7d0147543a3e8ae59e133960c` |
| `evidence/demo-summary.json` | `732d12e7c241f89fab0a32e1635249bfdc0ff25d9b34d594cdf6b716fc318727` |
| `evidence/demo-registrations.json` | `02623e47f8ff4ce7d884da2f4493b87b55b573bfe1fa9ea299172db68cfee05c` |
| `evidence/demo-credential-fingerprints.json` | `0636e634a143850104783c74a96481aa7a7afaa318c89a9440e4c9d480a8f354` |
| `evidence/demo-human-claims.json` | `29c892f8fb82049f068e0e39dacca06cd43510ac416a2c91aecd7d150a8e3467` |
| `evidence/demo-m2m-claims.json` | `b31b385ee72ec0e80bc1aecafa36c06c7dc82d09ec35655c8a09ce8a1d7a946e` |

## Diagram

公開圖 `assets/diagrams/day-12/cognito-dual-path.png` 由私有工作區的 Mermaid／SVG authoring source 渲染，SHA-256 為 `6d0ef706822ba7c55401938d209c1b4f49b55427d98e07dba54310dcc32023a2`。PNG 已以 1600 × 900 畫面視覺檢查，兩條 flow、Token contract、Gateway 分流與 audit principal 都在畫布內，public export 不包含 SVG source。

## Cleanup

```bash
make lab-02-down
```

這個 command 只刪除帶正確 `.lab-02-artifacts` marker、位於 Lab 02 root 下且不是 symlink 的 `artifacts/`。
