# Skill-Eval Mimari ve Tasarım Belgesi (`DESIGN.md`)

> **Bu belge `/grill-me` tasarım oturumunda kilitlenen tüm kararların tek doğruluk kaynağıdır.**
> Yeni bir sohbette bu projeden devam ederken doğrudan bu dosyayı referans gösterebilirsiniz.

## 1. Araştırma Amacı ve Temel Sorular

Bu araştırma, milyonlarca kez indirilen ve ekipler tarafından yaygın kullanılan **Agent Skills (`SKILL.md`)** yapısının kodlama ajanları üzerindeki gerçek etkisini nicel ve nitel olarak ölçmeyi hedefler:

1. **Hangi tür skill ne zaman işe yarıyor?** (Araç zanaati vs Süreç disiplini vs Üretim mühendisliği vs Kurumsal/projeye özel bilgi)
2. **Skill "bodozlama dalmayı" azaltıyor mu?** (Keşif-önce oranı, yeniden yazma/churn, kök neden vs semptom yaması, öz-doğrulama disiplini)
3. **Otomatik keşif (B) çalışıyor mu?** 6 skill’lik gerçekçi ama çapraz sızıntısız (ortogonal) kütüphanede model doğru skill’i kendiliğinden bulup seçebiliyor mu?
4. **On-Demand Skill (C1) vs Always-On Sistem Bağlamı (C2):** Görev anında `Skill` aracıyla çağrılan skill ile oturum başında sistem bağlamına (`CLAUDE.md` benzeri) gömülen skill arasında kalite, uygulama ve token farkı nedir?
5. **Küçük model + Skill, büyük modelin skillsiz halini yakalıyor mu?** (`Haiku + Skill` vs `Sonnet Skillsiz`)
6. **Zaten `docs/` varken kurumsal Skill yazmak ne katıyor?** (G7–G8 görevleri; tüm kurallar repodaki dağınık `docs/` içinde de mevcuttur.)

---

## 2. Kilitlenmiş Deney Tasarımı

### 2.1. Modeller ve Çalıştırma Ortamı
- **Modeller:** `claude-sonnet-5-5` ve `claude-haiku-5-5` (`effort: medium`, sabit Claude Code CLI sürümü).
- **İzolasyon:** Her koşu sıfır **Docker container** (`skilleval-sandbox:latest`) içinde çalışır.
  - Tüm araçlar (Python 3.13, Node 22, Chromium, LibreOffice headless, PostgreSQL 16, ffmpeg, Claude Code CLI) container imajında sabit sürümdedir.
  - Host makineden `~/.gitconfig`, `~/.claude`, proje testleri veya önceki koşular fiziksel olarak erişilemez (`GIT_CONFIG_GLOBAL=/dev/null`, izole `/workspace` ve `/tmp`).
  - Claude abonelik kimliği ayrı bir Docker volume (`skilleval-claude-auth`) üzerinden salt-okunur kopyayla geçici belleğe alınır; koşu bitince container imha edilir.
- **Kota Yönetimi:** Python çalıştırıcısı (`skilleval run`) tamamen idempotenttir; rate-limit / abonelik kotası reddinde temiz durur veya `--auto-wait` ile reset saatini bekleyip kaldığı koşudan otomatik devam eder.

### 2.2. 8 Görev × 4 Skill Arketipi

| Görev | Kategori | Hedef Skill | Senaryo Özeti |
|---|---|---|---|
| **G1** | Araç & Üretim | `xlsx` *(Anthropic)* | Çok sekmeli finansal/bütçe modeli (Girdi + Varsayımlar + 12 Aylık Nakit Akışı + Özet); formül canlılığı, LibreOffice recalc, görsel taşma (`###`) kontrolü. |
| **G2** | Araç & Üretim | `remotion-best-practices` *(Remotion)* | Çok sahneli, veri odaklı animasyon + ses + altyazı senkronlu 1080p/720p Remotion videosu; ikinci gizli veriyle yeniden render + kare/ses doğrulaması. |
| **G3** | Süreç & Disiplin | `systematic-debugging` *(Superpowers)* | 4–5 modüllü gerçekçi servis + 2 yanıltıcı belirti (red herring); semptom yaması gizli testlerde patlar, gerçek kök neden izolasyonu ve minimal düzeltme gerekir. |
| **G4** | Süreç & Disiplin | `test-driven-development` *(Superpowers)* | Çok katmanlı yeni özellik + kenar durum sözleşmesi; üretim kodu öncesinde fail eden kırmızı test -> minimal geçiş -> refactor disiplini ve mutasyon/hata yakalama gücü. |
| **G5** | Mühendislik & Mimari | `supabase-postgres-best-practices` *(Supabase)* | 5 tablolu SaaS Postgres şemasında 4 darboğaz (OFFSET pagination, eksik partial/composite index, N+1/correlate subquery, eşzamanlı kilit/RLS); `EXPLAIN (ANALYZE, BUFFERS)` + yazma bütçesi. |
| **G6** | Mühendislik & Mimari | `frontend-design` *(Anthropic)* | Gerçekçi ürün arayüzü; Playwright + axe-core (1440px/375px layout, WCAG kontrast, a11y, font yükleme) + Jev kod/CSS mimarisi + anonim Kör Görsel Galeri. |
| **G7** | Projeye Özel (Custom) | `acme-event-contract` | Dağınık `docs/` içinde yer alan kurumsal olay zarfı, idempotency header, audit-log ve hata kodu sözleşmesi (%100 adil "Docs vs Skill" kıyası). |
| **G8** | Projeye Özel (Custom) | `acme-release-pipeline` | Dağınık `docs/` rehberlerinde tanımlı çok adımlı yerel sürüm/migrasyon/manifest doğrulama ve geri alma iş akışı (SOP uyumu). |

### 2.3. 4 Koşul ve Ortogonal Çeldirici Kuralı

| Koşul | Kurulu Skill | `Skill` Aracı | Sistem Bağlamı Ön Yükleme | Kullanıcı Promptu |
|---|---|---|---|---|
| **A** | Yok (0) | Kapalı | Yok | Temel `prompt.md` |
| **B** | 1 hedef + 5 ortogonal çeldirici (6) | Açık | Yok (yalnız metadata) | Temel `prompt.md` |
| **C1** | 1 hedef + 5 ortogonal çeldirici (6) | Açık | Yok (yalnız metadata) | *"Başlamadan önce `<target-skill>` skill’ini `Skill` aracıyla çağır ve yönergelerini uygula."* + `prompt.md` |
| **C2** *(4 görev ablasyonu)* | Yok (0) | Kapalı | `--append-system-prompt-file <target>/SKILL.md` | Temel `prompt.md` *(A/B ile birebir aynı — `CLAUDE.md` / always-on kıyası)* |

> **Ortogonal Çeldirici Kuralı (Sıfır Çapraz Sızıntı):**
> `systematic-debugging` (G3) ve `test-driven-development` (G4) genel yazılım disiplini olduğu için **asla** başka bir görevin çeldirici havuzuna konmaz. Çeldiriciler yalnızca hedef görevle işlevsel örtüşmesi sıfır olan alan-dışı skill’lerden seçilir (`xlsx`, `remotion-best-practices`, `frontend-design`, `supabase-postgres-best-practices`, `pdf`, `playwright-cli`, `acme-event-contract`, `acme-release-pipeline`).

### 2.4. Koşu Matrisi ve Ön Kalibrasyon Kapısı
- **Aşama 0 — Ön Kalibrasyon Kapısı (32 koşu):** 8 görev × `A` koşulu × 2 model × 2 tekrar + Jev çapa (anchor) kalibrasyonu.
  - **Tavan Etkisi Kuralı:** Bir görevde skillsiz A ortalaması `≥ 9.0/10` (veya iki modelde de 2/2 tam puan) çıkarsa, o görev ana deneye dondurulmadan önce zorlaştırılır ve yeniden kalibre edilir. Hedef A bandı: `4.0 – 7.5 / 10`.
- **Aşama 1 — Ana Deney Matrisi (216 koşu):**
  - Ana blok: 8 görev × 3 koşul (`A, B, C1`) × 2 model × 4 tekrar = **192 koşu** (`pass@1` + `pass^4`).
  - `C2` ablasyonu: 4 temsili görev (`G2`, `G3`, `G5`, `G7`) × 2 model × 3 tekrar = **24 koşu**.
  - **Toplam:** 216 ana koşu (sabit seed ile karıştırılmış, `freeze.lock.json` ile hash-kilitli).

---

## 3. Ölçme ve Puanlama Mimarisi (AERA/APA/NCME + ETS)

Tek bir yüzeysel toplam yerine **4 ayrışık, şeffaf ölçü ekseni**:

### 3.1. Kapılı Ürün Kalitesi Puanı (`0 – 10`)
- **Birleşik Kritik Kapılar (Conjunctive Gates):**
  - `G1_CONTRACT_BUILD`: Teslim üretildi, derleniyor/çalıştırılabiliyor, şema okunabilir.
  - `G2_CRITICAL_CORRECTNESS`: Görevin kritik kabul testlerinin tamamı geçti.
  - `G3_CRITICAL_SAFETY_RULES`: Kritik güvenlik, gizlilik, veri bütünlüğü veya yasaklı dosya/bağımlılık ihlali yok.
- **ETS Eşik Kuralı:**
  - `GEÇTİ (PASS)` ⇔ `(G1 & G2 & G3)` **ve** `product_score >= 7.0`.
  - Herhangi bir kritik kapı düşerse karar kesinlikle `KALDI (FAIL)` olur ve görünür puan **`<= 5.0`** ile tavanlanır.
- **5 Sabit Alt Boyut (Toplam 10.0 puan):**
  1. Doğruluk & Eksiksiz Tamamlama (`3.5`)
  2. Sağlamlık & Sınır Durumları (`2.0`)
  3. Test & TDD Kalitesi (`1.5`) *(uygulanmayan görsel/belge görevlerinde ağırlık `task.yaml`'de dondurularak diğer boyutlara dağıtılır)*
  4. Kod / Çıktı Kalitesi & Bakım (`1.5`) — Jev atomik rubrik (+ G6’da Kör Görsel Galeri)
  5. Çözüm Performansı & Güvenlik/Kural Uyumu (`1.5`) — çözümün kendi çalışma performansı (**ajan süresi değil!**)

### 3.2. Süreç & Toparlanma Puanı (`0 – 10`, Ürün Puanından Ayrı)
- **4 Sınıflı Hata Taksonomisi:**
  - `infra_sandbox`: Altyapı/sandbox hatası → **Ceza = 0** (ayrı ortam sağlığı metriği).
  - `expected_negative`: Beklenen kırmızı test (TDD) veya keşif yoklaması → **Ceza = 0**.
  - `recoverable_agent_error`: Yanlış araç/argüman/derleme hatası yapıp 1–2 adımda düzelttiği olay (ardışık zincir tek olay) → **−0.5**.
  - `repeated_or_unverified_error`: Aynı hatayı tekrarlama, hatayı çözmeden ilerleme veya bütçe/tur sınırına çarpma → **−2.0**.
- **Bodozlama Dalma / Planlama Metrikleri:**
  - `explore_before_edit_ratio` (ilk düzenleme öncesi okuma/keşif adımı)
  - `rework_churn_ratio` (aynı dosyaya geri dönüp tekrar yazma)
  - `self_verified_after_last_edit` (son değişiklikten sonra gerçek test/doğrulama çalıştırma)
  - `tdd_red_before_green` (ilk üretim kodundan önce beklenen assertion hatası alma)

### 3.3. Verimlilik & Maliyet Profili (Puanlanmaz — A’ya Oranla Gösterilir)
- `agent_seconds` (yalnız ajan süresi; grader süresi ayrı), token kırılımı (`input`, `cache_write`, `cache_read`, `output`), `api_equivalent_usd` (abonelik faturası değildir), `cost_per_passed_run`.

### 3.4. 3 Katmanlı Skill İzleme (`Exposure → Adherence → Delta`)
- **Katman 1 — Erişim:** `none | metadata_only | invoked_target | invoked_wrong_distractor | references_read | preloaded`.
- **Katman 2 — Uygulama (`skills/<id>/probes.yaml`):** Her skill’in 3–5 somut davranışsal göstergesi **tüm koşullarda (A dahil!)** `applied | not_applied | violated` olarak ölçülür.
- **Katman 3 — Net Katkı:** $\Delta_{\text{adherence}} = P(\text{uygulandı} \mid C) - P(\text{uygulandı} \mid A)$ ve $\Delta_{\text{score}} = \text{Score}(C) - \text{Score}(A)$.

---

## 4. Kör Değerlendirme (Jev + Kör Görsel/Hakemlik UI)

- **Jev (`jev-1.14.0`, `https://api.typesafe.ai/v1/systemone`):** Geniş soyut sorular yerine her görev için 5–7 **atomik, gözlenebilir kanıtlı kontrol listesi maddesi**; çift geçiş (2. geçişte seçenek ve dosya sırası ters), `min(prob) >= 0.80` ve tam uyum kuralı.
- **Ön Kalibrasyon:** Her görevde 2 altın (good) + 2 kasıtlı kusurlu (bad) çapa örneğinde Jev doğrulaması yapılmadan ana deney dondurulmaz.
- **Sıfır Eksik Karar (`review-ui`):** Jev’in kararsız kaldığı (`<%10`) maddeler ve **G6 (`frontend-design`) + G2 (`remotion`)** anonim ekran görüntüleri yerel **Kör İnceleme HTML Arayüzü**’nde rastgele kodlarla (`#7f3a`) sunulur; A/B/C/model ve Jev seçimi tamamen gizlenir.

---

## 5. Tam Şeffaflık, Capture ve İki Dilli Raporlama

- Her koşu `artifacts/<study-id>/runs/<run-id>/capture/` altında eksiksiz kayıt tutar:
  - `session.jsonl` (ham stream-json)
  - `hook-events.jsonl` (PreToolUse / PostToolUse / Skill olayları)
  - `transcript.md` (insan-okunur tam sohbet: her tur, düşünce/yanıt, araç çağrısı, araç çıktısı/hatası, token özeti)
  - `workspace.patch` (tüm dosya değişiklikleri)
  - `deliverables/` (üretilen PDF, XLSX, MP4, ekran görüntüleri vb.)
- Kök dizinde GitHub’da doğrudan okunabilir **iki dilli raporlar** üretilir:
  - [RAPOR.md](../RAPOR.md) + etkileşimli `reports/rapor.html`
  - [REPORT.md](../REPORT.md) + etkileşimli `reports/report.html`
