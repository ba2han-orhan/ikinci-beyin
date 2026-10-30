---
name: hata-defteri
description: Tekrar eden hataları (asistanın davranış hataları, başarısız araç/komut çağrıları, hook istisnaları) gözden geçirir, kullanıcının onayıyla kalıcı çözümü (kural, hook, skill, kod düzeltmesi) uygular ve defterde kapatır. "hata defteri", "hata defterine bak", "hataları gözden geçir", "aynı hata yine oldu", "bu bir daha olmasın" dendiğinde ya da açılıştaki [Hata Defteri] satırı onay bekleyen çözüm gösterdiğinde kullan.
---

# Hata Defteri

Hatalar otomatik kaydedilir, çözüm otomatik uygulanmaz: sistem tekrar
edeni bulur ve önerir, kullanıcı onaylar, sen uygularsın. Onaysız kural yazma; yanlış bir ders
kural dosyasını şişirir ve bütün oturumları etkiler.

Kayıt zinciri (değiştirmen gerekmez, arızada bilmen için):
- `.beyin/hooks/hata-yakalayici.py`: `PostToolUseFailure` ve
  `UserPromptSubmit` (düzeltme cümlesi sinyali).
- `.beyin/scripts/flush.py`: oturum özetinin sonundaki `DUZELTMELER:` bloğu davranış olayı
  olur, ardından analiz koşar.
- `.beyin/scripts/hata_sayaci.py`: yutulan hook istisnaları `hook:` imzasıyla düşer.
- Kayıt `.beyin/scripts/.state/hata-olaylari.jsonl`, kararlar `.state/hata-kararlari.json`,
  insan notu `850-hafiza/hata-defteri.md` (makine yazar, elle düzenleme).

## Nasıl çalışırsın

1. Güncel durumu üret ve oku (vault kökünde):

   ```bash
   python3 .beyin/scripts/hata_defteri.py analiz
   ```

   Sonra `850-hafiza/hata-defteri.md` notunun "Tekrarladı" ve "Onay bekleyen" bölümlerini
   oku. "Tekrarladı" önce gelir: uygulanmış bir çözüm tutmamış demektir.

2. Her madde için kök nedeni kısa doğrula. Öneri metni deterministik bir tablodan gelir, kör
   uygulama. Araç hatasında olayın `ozet` alanına ve ilgili dosyaya bak; davranış hatasında
   ilgili günlük log oturumunu (`800-gunluk-oturum-kayitlari/`) kaynak olarak kullan.

3. Kullanıcıya madde başına tek satır sun: ne tekrarladı, kaç kez, önerdiğin kalıcı çözüm ve
   hangi dosya. Çözüm türünü seç:
   - **kural**: tekrar eden davranış ya da ortam gerçeği (ör. "pytest yok, `python3 -m
     unittest discover -s tests` kullan"). `850-hafiza/davranis-kurallari.md`,
     "Nasıl büyür" biçiminde: kural + **neden:** + tarih.
   - **hook**: kural yetmiyor ve hata mekanik olarak önlenebiliyor. PreToolUse ile uyar ya
     da engelle; kayıt `.claude/settings.json`.
   - **skill**: hata bir iş akışının adımında oluyor. İlgili `SKILL.md`'ye ön kontrol adımı.
   - **kod**: `hook:` imzaları ve script hataları. `debugging` skill'iyle kök neden, düzeltme
     ve regresyon testi.

4. Kullanıcı onayladıktan sonra uygula ve uygun testle doğrula (script değiştiyse
   script'i küçük bir girdiyle çalıştırıp çıktısına bak). Sonra kapat:

   ```bash
   python3 .beyin/scripts/hata_defteri.py onayla 'IMZA' --cozum "ne yapıldı; dosya yolu"
   ```

   İstemediği madde için `reddet 'IMZA' --neden "..."`; o imza bir daha önerilmez.
   Sonra `analiz` komutunu tekrar çalıştır, defter ve açılış satırı güncellensin.

5. Kayıtta olmayan bir hatayı elle eklemek için (ör. kullanıcı "bunu yine yaptın" dedi):

   ```bash
   python3 .beyin/scripts/hata_defteri.py kaydet --tur davranis --kategori baglam \
     --imza davranis:baglam:kisa-anahtar --ozet "tek cümlelik ders"
   ```

## Sınırlar

- Kayda istem, komut çıktısı ya da sır yazma; `ozet` tek satır ve maskelidir.
- Bir imza "Tekrarladı"ya düştüyse aynı çözümü yeniden önerme; neden tutmadığını söyle,
  daha güçlü bir çözüm türüne çık (kural → hook, hook → kod).
- `rapor` komutu salt okunur hızlı bakış verir: `python3 .beyin/scripts/hata_defteri.py rapor`.
