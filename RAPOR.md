# Agent Skills Gerçekten İşe Yarıyor mu? — Araştırma Raporu

> **Durum:** Çalışma kurulum aşamasında. Ana koşular (`main-v1`, 216 koşu) tamamlandığında bu dosya `uv run skilleval report --study main-v1` komutuyla otomatik olarak güncellenecektir.
>
> - **İngilizce Rapor:** [REPORT.md](REPORT.md)
> - **Tasarım & Metodoloji:** [docs/DESIGN.md](docs/DESIGN.md) · [docs/PROTOCOL.md](docs/PROTOCOL.md)
> - **Etkileşimli HTML Rapor:** `reports/rapor.html` *(rapor üretildiğinde oluşur)*

## Planlanan Deney Özeti

| Bileşen | Değer |
|---|---|
| Görev sayısı | 8 görev (4 skill arketipi × 2) |
| Modeller | `claude-sonnet-5-5`, `claude-haiku-5-5` (`effort: medium`) |
| Koşullar | `A` (skillsiz), `B` (6 ortogonal skill — keşif), `C1` (açık on-demand çağrı), `C2` (4 görevde sistem bağlamı ön-yükleme) |
| Ön Kalibrasyon | 32 koşu (A koşulu tavan-etkisi elemesi + Jev çapa doğrulaması) |
| Ana Matris | 192 (`A/B/C1`, k=4) + 24 (`C2` ablasyonu, k=3) = **216 koşu** |
| Ölçüm Sistemi | Kapılı 0–10 Ürün Puanı (eşik 7.0) + ayrı 0–10 Süreç Puanı + Verimlilik Profili + 3 Katmanlı Skill İzleme |
| Kör Değerlendirme | Atomik rubrikli çift-geçişli Jev (`jev-1.14.0`, `≥0.80`) + Anonim Kör Görsel & Hakemlik Arayüzü |
