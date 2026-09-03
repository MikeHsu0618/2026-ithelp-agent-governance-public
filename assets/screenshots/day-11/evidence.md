# Day 11 Screenshot Evidence

Status：complete。

## Environment

```text
Tested:    2026-09-03 Asia/Taipei
Python:    3.14.5
PyJWT:     2.13.0
pytest:    9.1.1
MCP spec:  2026-07-28 (document reference only)
Git tag:   day-11（發稿流程建立後即為固定版本）
```

## Commands executed

```bash
make lab-02-up
make lab-02-oauth
make lab-02-check
uv export --directory labs/02-identity-boundary --frozen --no-dev \
  --no-emit-project --format requirements-txt | uvx pip-audit -r /dev/stdin
uvx bandit -q -r labs/02-identity-boundary/src -ll
uv build --directory labs/02-identity-boundary
```

Final result 為 9/9 OAuth case matched，完整 Lab 73 tests passed，branch coverage 90.81%，Ruff lint／format clean。Dependency audit 沒有找到已知漏洞，Bandit 沒有 medium／high issue，wheel 與 source distribution build 成功。

## Actual result

- Authorization Code + PKCE 成功時，access token 為 `sub=user/sre-oncaller`、`aud=Agent entry`；authorization code 只能兌換一次。
- Callback 從 `127.0.0.1` 換成 `localhost`、要求 client allowlist 外 scope，以及使用未註冊 client，都在 code 發出前被拒絕。
- Client Credentials 成功 Token 為 `sub=client/sre-scheduler`；public client 嘗試使用該 grant 時回 `UNAUTHORIZED_CLIENT`。
- RFC 8693 Token Exchange 先驗 Human `subject_token`、Runtime `actor_token`、authenticated client 與 `may_act` 綁定，成功 Token 為 `sub=user/sre-oncaller`、`act.sub=client/sre-investigator-runtime`、`aud=Observability MCP`。
- 未授權 target 與錯 subject-token audience 分別回 `INVALID_TARGET`、`SUBJECT_TOKEN_INVALID`；actor 未獲 Human `may_act` 授權的 unit test 回 `ACTOR_NOT_AUTHORIZED`。
- Authorization code、PKCE verifier、client credential、compact JWT 與 private key 均未落盤。

## Presentation method

`01-oauth-flow-results.png` 把本次 `make lab-02-oauth` 的實際結果重新排成 1600 × 900 terminal card。九組 case 的 decision、code 與 principal 均取自 `day11-20260903T030015Z-ac212b5d`；圖片省略本機絕對 artifact path，正文另保留可複製 command、完整表格與 machine-readable JSON。

所有 Human、Service、Agent、issuer、resource、client 與 scope 都是合成值。Credential fingerprint 只用於確認各條成功 flow 產生不同 Token，不含 raw bearer credential。

## Images

| Image | SHA-256 | Run | Redactions | Status |
| --- | --- | --- | --- | --- |
| `01-oauth-flow-results.png` | `02b9b2029cea62f6605e2288ceef9488c1468744a36434bb41458676e98e622d` | `day11-20260903T030015Z-ac212b5d` | 省略本機 artifact path；結果未改寫 | PASS |
| `assets/diagrams/day-11/three-oauth-flows.png` | `0faf649a37a3b3ea8ebe0e16afd30eafe121798c544191f1b636dc874662c5e2` | 同一 fixture contract | 無 | PASS |

## Machine evidence hashes

| File | SHA-256 |
| --- | --- |
| `evidence/demo-manifest.json` | `5c4ab99247e03989dd740597023458b37b91dfea7dd70690bd71a305149e1cf5` |
| `evidence/demo-summary.json` | `1e0182f1152dae8e245fc73744f9b8764783c7763ad7c5f1d271a853f5fe215a` |
| `evidence/demo-events.jsonl` | `6025044bcbf758e500e244522efa1023827c92449e3214ae3747491fed05e450` |
| `evidence/demo-registrations.json` | `94caf664576e05437c918ff2f6189cdb1c86e4590070bbf9312c44be1637f049` |
| `evidence/demo-credential-fingerprints.json` | `b26b5faec17aa2d5b366e8a58436fe7edb0bec541e33ba89f869bed3f970c4e6` |
| `evidence/demo-human-entry-claims.json` | `952d1f040bb9f37ac4cb47957eadd497c32fa50884afa0a9bbfc53bb3a316128` |
| `evidence/demo-runtime-actor-claims.json` | `cb3a035aba011c21f7ab5390f632997af6b9aa6566d4d24cbf6ff6a38d89d179` |
| `evidence/demo-token-exchange-claims.json` | `ff66f4949ccfc30af9f036e66d884f71d35c6ad9f234e4124a739379cd330548` |

## Diagram

`three-oauth-flows.png` 使用三列 flow 取代原本過長的 sequence，僅保留 client／Token 輸入、Authorization Server 與最終 principal。Reader-facing PNG 為 1600 × 1000；authoring SVG 已通過 `xmllint`，SHA-256 為 `4f4071107967417d33b37c6c004c4540ecc0c078322d734d35638ee70a2398e2`。以原尺寸檢查後，沒有文字、箭頭或節點超出畫布。

## Cleanup

```bash
make lab-02-down
```

這個 command 只刪除帶正確 `.lab-02-artifacts` marker、位於 Lab 02 root 下且不是 symlink 的 `artifacts/`。
