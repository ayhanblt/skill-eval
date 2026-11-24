# Agent Skills Gerçekten İşe Yarıyor mu? (`main-v1`)

[English Report](REPORT.md) · [Etkileşimli HTML](reports/rapor.html) · [Tasarım](docs/DESIGN.md)

## Koşullara Göre Özet

| Koşul | Geçme (ETS ≥7.0 & Kapılar) | `pass^k` | Ürün Puanı (/10) | Süreç Puanı (/10) | Yönerge Uygulama | Ortanca Süre | API Eşdeğeri | Başarı Başı Maliyet |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| **A** | 54/64 (84.4%) | 12/16 | 8.60 | 9.66 | 86.6% | 98.7s | $7.743 | $0.143 |
| **B** | 61/64 (95.3%) | 14/16 | 9.31 | 9.69 | 87.1% | 96.0s | $8.208 | $0.135 |
| **C1** | 58/64 (90.6%) | 13/16 | 9.18 | 9.69 | 86.3% | 103.5s | $10.141 | $0.175 |
| **C2** | 22/24 (91.7%) | 7/8 | 9.02 | 9.50 | 84.4% | 114.7s | $3.148 | $0.143 |

## Görev Bazında Ürün & Süreç Puanları

| Görev | Arketip | A | B | C1 | C2 | B Hedef Skill Erişimi |
|---|---|---|---|---|---|---|
| `G1-xlsx-financial-model` | `tool_craft` | 5.00 (0/8) | 9.43 (8/8) | 9.28 (8/8) | — | 8/8 |
| `G2-remotion-display` | `tool_craft` | 8.11 (8/8) | 9.35 (8/8) | 9.57 (8/8) | 8.62 (6/6) | 8/8 |
| `G3-systematic-debugging` | `workflow_discipline` | 8.61 (8/8) | 8.70 (8/8) | 9.01 (8/8) | 8.64 (6/6) | 0/8 |
| `G4-tdd-feature` | `workflow_discipline` | 9.96 (8/8) | 9.99 (8/8) | 9.99 (8/8) | — | 0/8 |
| `G5-postgres-saas` | `production_engineering` | 9.15 (7/8) | 9.75 (8/8) | 9.75 (8/8) | 8.76 (4/6) | 6/8 |
| `G6-frontend-design` | `production_engineering` | 8.22 (7/8) | 7.90 (6/8) | 6.48 (3/8) | — | 4/8 |
| `G7-acme-event-contract` | `proprietary_custom` | 9.81 (8/8) | 9.38 (7/8) | 10.00 (8/8) | 10.00 (6/6) | 8/8 |
| `G8-acme-release-pipeline` | `proprietary_custom` | 9.95 (8/8) | 10.00 (8/8) | 9.36 (7/8) | — | 7/8 |

## Model × Koşul Karşılaştırması

| Model | Koşul | Ürün (/10) | Süreç (/10) | Geçme | Keşif-Önce Adım | Öz-Doğrulama |
|---|---|---:|---:|---:|---:|---:|
| `claude-haiku-5-5` | **A** | 8.48 | 9.52 | 27/32 | 5.3 | 87.5% |
| `claude-haiku-5-5` | **B** | 9.34 | 9.67 | 31/32 | 6.1 | 90.6% |
| `claude-haiku-5-5` | **C1** | 9.01 | 9.61 | 28/32 | 5.8 | 90.6% |
| `claude-haiku-5-5` | **C2** | 8.56 | 9.42 | 10/12 | 6.5 | 100.0% |
| `claude-sonnet-5-5` | **A** | 8.72 | 9.80 | 27/32 | 2.5 | 75.0% |
| `claude-sonnet-5-5` | **B** | 9.28 | 9.70 | 30/32 | 3.4 | 84.4% |
| `claude-sonnet-5-5` | **C1** | 9.35 | 9.77 | 30/32 | 3.9 | 78.1% |
| `claude-sonnet-5-5` | **C2** | 9.43 | 9.58 | 12/12 | 2.4 | 83.3% |
