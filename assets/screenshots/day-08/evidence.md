# Day 8 Screenshot Evidence

Status：complete。

## Environment

```text
Tested:       2026-08-19
Python:       3.14.5
PyJWT:        2.13.0
cryptography: 50.0.0
pytest:       9.1.1
```

## Commands executed

```bash
make lab-02-up
make lab-02-check
make lab-02-demo
```

## Actual result

- 7 組正向／負向 case 全部符合預期。
- `valid_access` 是唯一 ALLOW。
- 錯 issuer、錯 audience、過期 Token 分別回 `ISSUER_MISMATCH`、`AUDIENCE_MISMATCH`、`TOKEN_EXPIRED`。
- Token 通過 signature／registered claims 後，仍可能因缺 scope 或 policy claim 被拒絕。
- 帶有 `team` 的 synthetic ID token 不能替代這個 resource contract 要求的 access token。
- 24 tests 通過，branch coverage 87.07%。

## Presentation method

`01-jwt-boundary-results.png` 由本地 HTML terminal template 將 `make lab-02-demo` 的實際 CLI output 重新排版，再以本機 Chrome headless 匯出 1600 × 1050 PNG。圖片沒有模擬額外結果，也沒有把錯誤輸出裁掉。

正文會同時保留可複製 command 與文字輸出。圖片只是讓 ALLOW／DENY 差異更容易掃讀，machine-readable manifest、summary 與 JSONL 也保存在 `evidence/`。

所有 issuer、principal、client、resource、scope 與 claim 都是合成值。Compact JWT 與 private key 沒有進入圖片或 committed evidence。

## Image

| Image | SHA-256 | Run | Redactions | Status |
| --- | --- | --- | --- | --- |
| `01-jwt-boundary-results.png` | `ed4f9d78509244b5148f5a6570bd98a9af34b62a9d6439800426d61ae839a03e` | `20260819T033232Z-af32958a` | none，全為 synthetic | PASS |

## 2026-08-31 發稿前重驗

Public Makefile 已恢復 `lab-02-up`、`lab-02-check`、`lab-02-demo` 與 `lab-02-down`。從 repo root 實際執行 `make lab-02-check && make lab-02-demo` 後，完整共用 Lab 為 72 tests passed、branch coverage 91.17%，Day 8 路徑仍是 7/7 cases matched。Compact JWT 與 private key 都沒有寫入 artifact。

本文沿用 2026-08-19 的 Day 8 terminal 圖，因為圖中輸出與目前七組 case 完全一致。圖上的 24 tests 是當時 Day 8 slice 的歷史結果，不改畫成 72，正文已清楚區分兩個時間點。

## Machine evidence hashes

| File | SHA-256 |
| --- | --- |
| `evidence/demo-manifest.json` | `75002c9ca6f262b54b15a4f2acf613e89e230f3aab9efb16c39ba3b8df510e6c` |
| `evidence/demo-summary.json` | `2e3322fd266fe54102d4613c44e6fc307c4e4bbd377d98e24ccd422937023bf0` |
| `evidence/demo-events.jsonl` | `cfe4b747fe85e2b9a76e6aaf34be4727dba3e495717e42ddfc95c6d819cac500` |

## What to inspect

- `wrong_audience` 與 `access_missing_team` 都是 DENY，但前者停在 `claims`，後者停在 `policy`。
- `id_token_has_team` 明明有 policy 想要的屬性，仍先因 token type 不符被拒絕。
- Manifest 的 `encoded_tokens_persisted` 與 `private_key_persisted` 都是 `false`。
- Fixture hash 為 `sha256:a995bdcab3593ba9914abeb160f8fe6109ed7f1bb005e6bc4fbdfa4c3394cc9c`。
