# Skill-Eval: Agent Skills Deneysel Değerlendirme Çerçevesi

Bu depo, kodlama ajanlarında kullanılan **Agent Skills (`SKILL.md`)** mekanizmasının gerçek etkisini, AERA/APA/NCME ölçme standartları ve ETS eşik belirleme ilkeleri çerçevesinde objektif, tekrarlanabilir ve kör değerlendirmeyle ölçmek için sıfırdan tasarlanmıştır.

- **Türkçe Araştırma Raporu:** [RAPOR.md](RAPOR.md) *(etkileşimli HTML: `reports/rapor.html`)*
- **English Research Report:** [REPORT.md](REPORT.md) *(interactive HTML: `reports/report.html`)*
- **Tasarım ve Mimari Belgesi:** [docs/DESIGN.md](docs/DESIGN.md)
- **Ön Kayıt Protokolü:** [docs/PROTOCOL.md](docs/PROTOCOL.md)

## Araştırma Özeti

- **8 Derin Görev × 4 Skill Arketipi:** Araç & Üretim (`xlsx`, `remotion-best-practices`), Süreç & Disiplin (`systematic-debugging`, `test-driven-development`), Üretim Mühendisliği (`supabase-postgres-best-practices`, `frontend-design`) ve Projeye Özel Kurumsal Bilgi (`acme-event-contract`, `acme-release-pipeline` — kurallar dağınık `docs/` içinde de mevcut, %100 adil kıyas).
- **4 Koşul:** `A` (skillsiz kontrol), `B` (ortogonal çeldiricili 6 skill kurulu — pasif keşif), `C1` (aynı 6 skill kurulu — açık *on-demand* çağrı), `C2` (4 temsili görevde oturum başı sistem bağlamı ön-yükleme / *always-on* ablasyonu).
- **2 Model:** `claude-sonnet-5-5` ve `claude-haiku-5-5` (`effort: medium`).
- **216 Ana Koşu + 32 Ön Kalibrasyon Koşusu:** Ana matriste hücre başına `k = 4` tekrar (`pass@1` ve `pass^4`), öncesinde A koşulunda tavan etkisi eleme kapısı.
- **İzolasyon:** Her koşu sıfır Docker container + Claude abonelik OAuth volume; sıfır host sızıntısı.
- **Ölçüm & Kör Değerlendirme:** Kapılı 0–10 Ürün Kalitesi Puanı + ayrı 0–10 Süreç & Toparlanma Puanı + ayrı Verimlilik/Maliyet Profili + 3 katmanlı Skill İzleme (`Exposure → Adherence → Delta`) + atomik rubrikli çift-geçişli **Jev** (`jev-1.14.0`) + anonimleştirilmiş yerel Kör Görsel & Hakemlik Arayüzü.

## Hızlı Başlangıç

```bash
# 1. Bağımlılıkları kur
uv sync --extra dev

# 2. Ortam değişkenini hazırla (Jev için TYPESAFE_API_KEY)
cp .env.example .env

# 3. Docker sandbox imajını derle ve smoke test et
uv run skilleval docker-build
uv run skilleval docker-login   # Claude abonelik OAuth volume'üne tek seferlik giriş
uv run skilleval validate

# 4. Aşama 0: 32 koşuluk tavan-etkisi ön kalibrasyonu
uv run skilleval run --study calibration-v1 --auto-wait

# 5. Ana deneyi dondur ve çalıştır (kota dolduğunda otomatik bekler veya kaldığı yerden devam eder)
uv run skilleval freeze --study main-v1
uv run skilleval run --study main-v1 --auto-wait

# 6. Değerlendirme, iz analizi, kör Jev, kör görsel/hakemlik UI ve iki dilli raporlar
uv run skilleval grade --study main-v1
uv run skilleval trace --study main-v1
uv run skilleval judge --study main-v1
uv run skilleval review-ui --study main-v1
uv run skilleval report --study main-v1
```
