# Ön Kayıt Protokolü (`PROTOCOL.md`)

> Durum: **Taslak — Aşama 0 Ön Kalibrasyon henüz başlamadı.**
> Ana koşular başlamadan önce bu protokol, tüm `specs/`, `skills/`, `tasks/` ve Docker imaj SHA-256 hash’leri `artifacts/<study-id>/freeze.lock.json` içine kilitlenecektir.

## 1. Ön Kayıtlı Hipotezler

- **H1 (Keşif ve Seçim):** B koşulunda (1 hedef + 5 ortogonal çeldirici kurulu) modeller hedef skill’i her görevde kendiliğinden çağırmayabilir; keşif oranı skill türüne ve model büyüklüğüne göre değişir.
- **H2 (Arketip Farkı):** Skill’in Ürün Kalitesi üzerindeki katkısı (`Δ_product`) skill arketipine göre anlamlı biçimde farklılaşır: özellikle araç zanaati (G1–G2), tuzaklı disiplin (G3–G4) ve dağınık dokümanlı kurumsal protokollerde (G7–G8) pozitif fark beklenir.
- **H3 (Süreç Disiplini / "Bodozlama Dalma"):** Skill uygulaması, yalnızca son test sonucunu değil; ilk düzenleme öncesi keşif oranını, yeniden yazma (rework) döngüsünü ve öz-doğrulama disiplinini iyileştirir.
- **H4 (On-Demand C1 vs Always-On C2):** Görev anında `Skill` aracıyla çağrılan içerik (C1) ile oturum başında sistem bağlamına enjekte edilen içerik (C2) arasında uygulama oranı ve token/süre maliyeti farkı oluşur.
- **H5 (Model Kaldıracı):** Zayıf/hızlı model (`Haiku`) + Skill kombinasyonunun, büyük modelin (`Sonnet`) skillsiz performansına ne ölçüde yaklaştığı betimsel olarak karşılaştırılır.

## 2. Dondurma ve Değişmezlik Kuralları

1. **Tek Veri Sözleşmesi:** Tüm koşular aynı `RunManifest`, `GradeResult`, `TraceSummary` ve `JudgeResult` Pydantic şemalarına uyar.
2. **Aşama 0 Kalibrasyon Kuralı:** 32 A-koşulu kalibrasyon koşusu ana 216 koşuya **dahil edilmez**. A ortalaması `≥ 9.0/10` olan görevler dondurma öncesi revize edilir; revizyon gerekçesi değişiklik günlüğünde saklanır.
3. **Ana Deney Değişmezliği:** `skilleval freeze --study main-v1` sonrası hiçbir görev, prompt, skill, test, rubrik ağırlığı veya Docker imajı değiştirilemez.
4. **Kayıp Veri & Kota Politikası:** Abonelik kotası reddi geçersiz teknik kesinti sayılır ve aynı slot temiz yeni denemeyle tamamlanır (önceki yarım deneme silinmez, `attempts/` altında saklanır). Modelin kendi zaman aşımı veya tur sınırına ulaşması ise **geçerli bir başarısızlık/bütçe-tükenmesi gözlemi** olarak rapora girer; seçilerek yeniden başlatılmaz.
5. **Körlük Koruması:** Jev’e ve kör insan inceleme arayüzüne koşul (`A/B/C1/C2`), model adı, skill metni, maliyet ve oturum logu **verilmez**; yalnızca rastgele anonim ID, görev sözleşmesi ve teslim artefaktları verilir. Eşleme anahtarı (`blind-key.json`) SHA-256 ile mühürlenir.
6. **Ölçüm Standartları:** Puanlama kuralları ve `7.0/10` geçme eşiği deneyden önce `specs/rubric-global.yaml` içinde sabitlenir (AERA/APA/NCME ve ETS eşik belirleme ilkeleri).
