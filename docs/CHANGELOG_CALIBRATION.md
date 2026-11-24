# Kalibrasyon Değişiklik Günlüğü (`CHANGELOG_CALIBRATION.md`)

> `docs/PROTOCOL.md` Bölüm 2.2 (Aşama 0 Kalibrasyon Kuralı) uyarınca, ana 216 koşuluk deney (`main-v1`) dondurulmadan önce yürütülen ön kalibrasyon bulguları ve görev revizyonları bu dosyada kayıt altına alınır.
> Tarihsel `artifacts/calibration-v1/` verisi olduğu gibi korunmuştur ve hiçbir zaman değiştirilmemiştir.

---

## 1. `calibration-v1` Ampirik Bulguları (32 Koşul-A Koşusu)

- **Altyapı & Grader Sağlığı:** 32/32 tamamlandı (`infra_errors = 0`, `grader_error = 0`), toplam API eşdeğeri `\$3.1462`, toplam ajan süresi `56.99 dk`.
- **Genel Ortalama:** Ürün Puanı **`9.15 / 10`**, Geçme **`27/32 (%84.4)`**, Süreç **`9.72 / 10`** (`claude-sonnet-5-5`: `9.38`, `claude-haiku-5-5`: `8.92`).

| Görev | A Ort. (`/10`) | Geçme | Sonnet `5-5` | Haiku `5-5` | Kapı Kararı (`3.5–8.0`, red `≥ 9.0`) | Kök Neden |
|---|---:|---:|---:|---:|---|---|
| `G1-xlsx-financial-model` | 8.75 | 3/4 | 10.00 | 7.50 | `HIGH_WARN` | `prompt.md` içinde `XLOOKUP` yasağı, renk kuralı ve LibreOffice recalc ipuçları verilmişti; grafik XML hijyeni/dolgu denetimi gevşekti. |
| `G2-remotion-display` | 10.00 | 4/4 | 10.00 | 10.00 | `CEILING_REJECT` | `prompt.md` Remotion primitiflerini (`Zod`, `Sequence`, `Audio`, `staticFile`, `useCurrentFrame`) doğrudan söylüyor, sabit `360` kare ezberlenebiliyordu. |
| `G3-systematic-debugging` | 10.00 | 4/4 | 10.00 | 10.00 | `CEILING_REJECT` | Tek aktif kök neden (`cache.py` + `pricing.py`) doğrudan `test_bug_repro.py` üzerinden hemen görülüyordu; çok katmanlı iz sürme gerekmiyordu. |
| `G4-tdd-feature` | 10.00 | 4/4 | 10.00 | 10.00 | `CEILING_REJECT` | `prompt.md` TDD kurallarını veriyordu ve SPEC 7 kurallıydı; gizli sınır mutasyonları orta zorlukta kaldı. |
| `G5-postgres-saas` | 5.00 | 0/4 | 5.00 | 5.00 | `OK` *(ölçüm hatası)* | Ajanlar doğru keyset `if/else` yolu eklediği halde geriye dönük `page` parametresinde `OFFSET` kelimesi kaldığı için `"OFFSET" in queries_src.upper()` yanlış pozitif kapı düşürdü; gerçek SQL planı test edilmiyordu. |
| `G6-frontend-design` | 9.81 | 4/4 | 10.00 | 9.62 | `CEILING_REJECT` | `prompt.md` estetik yönü, kontrast/WCAG ve `textContent` ipuçlarını veriyordu; `frontend-design` skill'inin AI tasarım klişelerinden kaçınma ve aktif-dil ilkeleri ölçülmüyordu. |
| `G7-acme-event-contract` | 9.62 | 4/4 | 10.00 | 9.25 | `CEILING_REJECT` | `docs/` ağacı küçüktü (8 dosya) ve `prompt.md` `acme.v2`, idempotency, Z-UTC ve `audit` kelimelerini açıkça söylüyordu. |
| `G8-acme-release-pipeline` | 10.00 | 4/4 | 10.00 | 10.00 | `CEILING_REJECT` | `prompt.md` `docs/` yapısını, kapı sırasını, geri alma döngüsünü ve manifest sealing sözleşmesini özetliyordu; migration hatası tek açık dosyadan ibaretti. |

### Gözlenen Ek Ölçüm Hataları
1. **Sonnet Bash-Edit Körlüğü (`trace_analyzer.py`):** Sonnet 5.5 sıkça `cat > dosya <<'EOF'`, `tee`, `sed -i` veya satır içi Python ile dosya yazıp aynı komutta `pytest` koştuğu için `self_verified_after_last_edit` yalnızca `%6.2` görünmüş, `DIAGNOSIS.md` gibi rapor dosyası sonradan yazıldığında yanlış düşmüştü.
2. **Jev TLS & Binary Yama Hataları (`judge.py`):** macOS python.org Python 3.13 boş OpenSSL CA deposu için sistem CA geri dönüşü (`_build_ssl_context`) ve `workspace.patch` içindeki base85 `GIT binary patch` bloklarını ayıklayan `_strip_binary_git_patches()` eklendi.

---

## 2. `calibration-v2` Revizyonları (Hedef Band: `4.0 – 7.5 / 10`)

- **Harness (`trace_analyzer.py` & `specs/study.yaml`):** Bash heredoc/`sed -i`/`tee`/Python dosya yazma izleme, bileşik yaz-ve-doğrula tespiti, salt doküman `.md` yazımlarını son kod doğrulamasından ayırma, ek doğrulama komut desenleri; `specs/study.yaml` içine `calibration-v2` eklendi (`seed: 20261202`).
- **`G1-xlsx-financial-model`:** `prompt.md` ve `starter/README.md` skill ipuçlarından arındırıldı; `skills/xlsx/SKILL.md` ile uyumlu grafik XML hijyeni (`roundedCorners=False`, `legend.overlay=False`, `title.overlay=False`, `x_axis/y_axis.delete=False`), Wall Street renk/sarı dolgu (`FFFF00`) + zero-as-dash muhasebe formatı ve bare post-2007 fonksiyon (`_xlfn.` eksikliği) kontrolleri eklendi.
- **`G2-remotion-display`:** `prompt.md`/`README.md` primitif sızıntılarından arındırıldı; `sceneDurationsSec` (`[3,3,3,3]` → gizli `dataset_b` `[2,4,4,4]` = `14s`) ile dinamik `calculateMetadata` süre zorunluluğu, alt yazı bandı piksel değişimi ve `clamp` animasyon kuralı eklendi.
- **`G3-systematic-debugging`:** Nötr vaka raporuna çevrildi; `billing_svc/` içine çok katmanlı 3 etkileşimli gerçek hata (1: `cache.py`+`pricing.py` sığ kopya/mutasyon, 2: `tax_engine.py` eksik önbellek anahtarı & sızan sözlük, 3: `ledger.py`+`batch_runner.py` başarısız fatura sonrası rollback eksikliği) ve 2 sahte belirti (`currency.py`, `reconciler.py`) kuruldu.
- **`G4-tdd-feature`:** TDD ipucu kaldırıldı; `SPEC.md` 10 kurala (`SeatSegment` dönem içi proration, `target_sku`/`min_subtotal` indirim kapsamı, negatif `Adjustment` kredi notu) çıkarıldı ve gizli mutasyon paketi 12 sınır mutantına yükseltildi (`>= 10/12` öldürme şartı).
- **`G5-postgres-saas`:** Kaynak string taraması yerine adayın gerçek çalıştırdığı SQL yakalanıp `EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON)` ile doğrulanıyor; `prompt.md` çözüm ipuçlarından temizlendi ve `Index Only Scan (Heap Fetches == 0)` + toplu insert/unindexed FK olmak üzere 2 yeni Supabase darboğazı eklendi (toplam 6 darboğaz, indeks bütçesi `<= 6`).
- **`G6-frontend-design`:** Prompt tamamen nötr ürün brifine dönüştürüldü, **Field Guide Comparison Drawer** etkileşimli akışı eklendi ve `skills/frontend-design/SKILL.md` ilkeleri (AI klişe krem `#F4F1EA` / ALL-CAPS eyebrow / `·` ayraç kaçınımı, kasıtlı tipografi ölçeği, aktif CTA dili, odak geri dönüşü) Playwright `design_audit.json` + Jev rubriğine taşındı.
- **`G7-acme-event-contract` & `G8-acme-release-pipeline`:** `prompt.md` ve `docs/README.md` tamamen nötr hale getirildi; her iki `starter/docs/` ağacı ~24 dosyalık gerçekçi kurumsal doküman yapısına (`Status: Active` vs `Status: Deprecated / Superseded` eski v1 dokümanları) genişletildi (`Docs vs Skill` adil kıyası korunarak). `G8` içine ayrıca yalnızca gerçek `up → down → up` geri alma döngüsünde patlayan gizli bir migration (`003_add_settlement_batches`) eklendi.

---

## 3. `calibration-v2` Ampirik Bulguları (32 Koşul-A Koşusu)

- **Altyapı & Grader Sağlığı:** `32/32` (`31 completed`, `1 budget_exhausted` `CAL-014` Haiku `G5`, `infra_errors = 0`, `grader_error = 0`), toplam API eşdeğeri `\$3.6790`, toplam ajan süresi `68.76 dk`, ortanca `112.9 sn`.
- **Kör İnceleme & Otomatik Olasılık Çözümü:** `G1`/`G2`/`G6` üzerindeki 24 görsel madde kullanıcı tarafından kör arayüzde puanlandı (`blind-review.html`); Jev belirsiz kod maddeleri (`0.50–0.80`) sıra ortalamalı sürekli olasılık (`source="jev_prob"`) ile çözüldü.
- **Genel Ortalama:** Ürün Puanı **`8.82 / 10`**, Geçme **`26/32 (%81.2)`**, `pass^k` **`12/16`**, Süreç **`9.69 / 10`** (`claude-sonnet-5-5`: `9.14`, `claude-haiku-5-5`: `8.50`).

| Görev | A Ort. (`/10`) | Geçme | Kapı Kararı (`3.5–8.0`, red `≥ 9.0`) | Bulgular |
|---|---:|---:|---|---|
| `G1-xlsx-financial-model` | **5.00** | 0/4 | **KALİBRE (KORUNDU)** | LibreOffice cached değer eksikliği, OOXML grafik `overlay=False` ve `#FFFF00` dolgu eksikliği net ayrışma üretti. |
| `G2-remotion-display` | **9.95** | 4/4 | `CEILING_REJECT` → **v3 revizyon** | Temel sahne/süre/audio gereksinimleri karşılandı ancak `@remotion/media` audio fade, `zColor()`, bireysel CSS `translate`/`scale`, `Easing.*` ve üst-bileşen frame izolasyonu ölçülmüyordu. |
| `G3-systematic-debugging` | **9.47** | 4/4 | `CEILING_REJECT` → **v3 revizyon** | İstem kök neden ipuçlarını sayıyordu; fazla ledger kredi iadesi, webhook idempotency ve katmanlar arası defense-in-depth doğrulama yoktu. |
| `G4-tdd-feature` | **9.91** | 4/4 | `CEILING_REJECT` → **v3 revizyon** | Koşul-A tek seferde kodu yazıp sonradan 12 mutantı öldüren testler üretiyordu; `included_units`/`VOLUME`, `max_discount_amount`, `credit_cap_pct`, negatif vergili düzeltme ve 20-mutantlı suite gerekli. |
| `G5-postgres-saas` | **8.56** | 3/4 | **KORUNDU (`HIGH_WARN`)** | Sonnet `9.73`, Haiku `7.39`; `Index Only Scan` ve `bulk_insert_events` anlamlı fark üretti. |
| `G6-frontend-design` | **7.67** | 3/4 | **KALİBRE (KORUNDU)** | 4/4 A koşusu sıcak krem AI klişesi ve görsel tasarım ayrımından puan kaybetti. |
| `G7-acme-event-contract` | **10.00** | 4/4 | **KORUNDU (Docs vs Skill)** | 24 dokümanlı adil kıyas doğrulukta değil keşif/verimlilikte fark ölçer. |
| `G8-acme-release-pipeline` | **10.00** | 4/4 | **KORUNDU (Docs vs Skill)** | 24 dokümanlı SOP + gizli migration döngüsü korundu. |

---

## 4. `calibration-v3` Hedefli Revizyonu (Yalnızca `G2`, `G3`, `G4` — 12 Koşu)

- **`specs/study.yaml` & `config.py`:** Çalışma bazlı opsiyonel `tasks:` alt küme filtresi eklendi; `calibration-v3` yalnızca revize edilen 3 görevi (`G2`, `G3`, `G4` × 2 model × 2 tekrar = **12 Koşul-A koşusu**, `seed: 20261203`) çalıştıracak şekilde tanımlandı.
- **`G2-remotion-display`:** `skills/remotion-best-practices` ilkelerine dayalı `@remotion/media` `Audio` + ses fade-in/out akustiği (başlangıç ve bitişte gövdeye kıyasla `≥ 2.5 dB` düşüş), `@remotion/zod-types` `zColor()`, bireysel CSS `translate`/`scale`/`rotate` + `Easing.bezier`/`Easing.spring` ve üst kompozisyonda `useCurrentFrame()` izolasyonu eklendi; `prompt.md`/`README.md` çözüm ipuçlarından arındırıldı.
- **`G3-systematic-debugging`:** `prompt.md` dosya/hata ipuçlarından tamamen arındırıldı; `incidents/incident_4812.log` ve `billing_svc/webhook.py` eklendi. 4. kök neden zinciri (fazla `ledger_credit` iadesi, yinelenen fatura idempotency ve `webhook → cache → ledger → pricing` çok katmanlı boş `tenant_id` defense-in-depth doğrulaması) grader, gold ve Jev rubriğine işlendi.
- **`G4-tdd-feature`:** `SPEC.md` domain düzyazısına dönüştürüldü; `included_units` + `VOLUME` tier modu, `max_discount_amount` indirim tavanı, `credit_cap_pct` kredi tavanı, aynı tarihli kredi `credit_id` eşitlik bozumu ve negatif vergilendirilebilir düzeltme etkileşimleri eklendi. Gizli mutasyon paketi 20 sınır mutantına (`>= 18/20`), test dürüstlüğü denetimi `>= 12` davranış testine çıkarıldı.

---

## 5. `calibration-v3` Ampirik Bulguları (12 Hedefli Koşul-A Koşusu)

- **Altyapı & Grader Sağlığı:** `12/12 completed` (`infra_errors = 0`, `grader_error = 0`), toplam API eşdeğeri `\$1.5733`, toplam ajan süresi `29.95 dk`, ortanca `122.1 sn`.
- **Kör Görsel İnceleme & Otomatik Çözüm:** `G2` üzerindeki `8/8` kör görsel madde kullanıcı tarafından `blind-review.html` üzerinden puanlandı (`Pending blind human items: 0`); kod maddeleri `jev` / `jev_prob` ile çözüldü.
- **Genel (`calibration-v3`, `G2/G3/G4`):** Ürün **`8.55 / 10`**, Geçme **`11/12 (%91.7)`**, `pass^k` **`5/6`**, Süreç **`9.83 / 10`** (`claude-sonnet-5-5`: `9.09`, `claude-haiku-5-5`: `8.01`).

| Görev | `v2` A Ort. | `v3` A Ort. | Geçme | Sonnet `5-5` | Haiku `5-5` | Kapı Kararı (`< 9.0`) | Ayırt Edici Bulgular |
|---|---:|---:|---:|---:|---:|---|---|
| `G2-remotion-display` | 9.95 | **8.17** | 4/4 | 8.16 | 8.17 | **KALİBRE (`< 9.0`)** | `4/4` A koşusu `@remotion/media` `Audio` yerine legacy import kullandı ve CSS `transform:` dizesiyle çalıştı (`g2_remotion_media_audio_and_fade` & `g2_studio_editable_transforms_and_easing` = `0`); `3/4` koşuda görsel hiyerarşi `partial`. |
| `G3-systematic-debugging` | 9.47 | **8.73** | 4/4 | 9.11 | 8.36 | **KALİBRE (`< 9.0`)** | `4/4` A koşusu `g3_defense_in_depth_validation` adımında takıldı (iç katman `cache` boş `tenant_id` kabul etti); `CAL-004` Haiku `g3_regression_tests_catch_unfixed_starter` testini geçemedi (`7.58`). |
| `G4-tdd-feature` | 9.91 | **8.75** | 3/4 | 10.00 | 7.50 | **KALİBRE (`< 9.0`)** | `CAL-006` Haiku `g4_decimal_only_and_performance` (`uses_float=True`) nedeniyle kapıdan `5.00` tavanına düştü; ayrıca `4/4` A koşusunda `tdd_red_before_green` uygulanmadı (`False`/`None`), `test-driven-development` skill'i için net ayrım alanı oluştu. |

### Birleşik 8 Görev Kalibrasyon Özeti (`main-v1` Hazır)
- `calibration-v2`'den korunan görevler: `G1` (`5.00`), `G5` (`8.56`), `G6` (`7.67`) ve `Docs vs Skill` görevleri `G7` (`10.00`), `G8` (`10.00`).
- `calibration-v3`'ten kalibre edilen görevler: `G2` (`8.17`), `G3` (`8.73`), `G4` (`8.75`).
- Tüm `Docs vs Skill` dışı 6 görevde Koşul-A ortalaması tavan eşiğinin (`9.0`) altında kalarak `main-v1` (216 koşu) dondurma kriterini sağladı.

### Uzun Koşular İçin OAuth Yenileme Koruması (`src/skilleval/sandbox.py`)
- `calibration-v3` sırasında `CAL-009` koşusunda 8 saatlik OAuth oturum süresi dolunca `:ro` bağlı auth volume yüzünden dönen yenileme tokenı kalıcılaşamamıştı (`OAuth session expired and could not be refreshed`).
- `docker/entrypoint.sh` ve `skilleval-sandbox:latest` imaj SHA'sı (`sha256:6064de4d5b69d9c6720b103ac49d1dc210e52ed2b7641b0a29bb0373cd9cfbee`) değiştirilmeden, `src/skilleval/sandbox.py` içine `/control/run-wrapper.sh` eklendi: her container izole `/tmp/claude-ephemeral-$$` ile çalışır ve yalnızca `.credentials.json` hash'i değişip geçerli JSON olarak doğrulandığında atomik `chmod 600 + mv -f` ile `/claude-auth-sync/.credentials.json` geri yazılır; `.claude.json` veya oturum/geçmiş dosyaları asla geri kopyalanmaz.


