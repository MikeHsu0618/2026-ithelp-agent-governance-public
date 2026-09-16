# Official agentgateway Grafana Dashboard

`agentgateway-dashboard-v1.5.0.json` 是 agentgateway 專案隨 `v1.5.0` 發佈的原始 Grafana Dashboard，沒有改寫 panel 或 PromQL。

- Source: <https://github.com/agentgateway/agentgateway/blob/v1.5.0/controller/install/helm/agentgateway/files/agentgateway-dashboard.json>
- Commit: `fe6732474a96a0363dfb9822859af4e9bab360fa`
- SHA-256: `1380d6720d4eb1814546264fe1ce22a38ea6a33dfa0ef2c7a4fa9283baab253f`
- Upstream license: <https://github.com/agentgateway/agentgateway/blob/v1.5.0/LICENSE>

官方 Dashboard 以 Kubernetes Helm 部署的 labels、control-plane metrics 與 container metrics 為基礎。Day 24 的公開 Lab 是 standalone Compose，因此不把官方 JSON 改到「勉強有畫面」；Kubernetes 環境應直接使用 Helm chart 的 `monitoring.grafanaDashboard`。

同目錄的 `../grafana-dashboard.json` 是本系列的問題導向 extension，只補官方 Dashboard 沒有的內容：用同一個 `action_id` 對回 primary 503 與 backup 200、說明零值 cost 的證據限制，以及區分 Gateway estimate 與 Provider invoice。它不取代官方維運 Dashboard。

agentgateway 還有另一個官方介面：啟用 `config.database` 與 `modelCatalog` 後，內建 LLM Analytics 會直接從 request log 顯示 cost、tokens、calls 與 provider breakdown。Day 24 的 `client-retry` config 已啟用這條路徑，Compose 只在 loopback 暴露 `28095`。這個 UI 不使用本目錄的 Grafana JSON。
