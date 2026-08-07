# Pineal Gland

`Pineal Gland`, gürültülü ve klişe dolu çevrim içi iletişim yerine, daha dikkatli, daha kişisel ve daha anlamlı ilk temas kurmaya yardımcı olan bir `human-in-the-loop` iletişim asistanıdır.

Bu proje bir otomasyon botu değildir. İnsanların yerine gizlice hareket eden, hesap ele geçiren, veri çeken, platform kurallarını aşmaya çalışan veya insanlar üzerinde manipülatif profil çıkarımı yapan bir sistem olmayı hedeflemez. Sistemin rolü, kullanıcının zaten bakmakta olduğu kamusal ve kullanıcı tarafından açıkça paylaşılmış bağlamı daha düzenli okuyup, daha özenli bir ilk mesaj taslağı hazırlamasına yardımcı olmaktır. Son karar, son düzenleme ve son gönderim her zaman insandadır.

## Neden var

Sosyal platformlarda ilk mesajların büyük kısmı birbirinin aynısıdır. `Selam`, `naber`, `nasılsın` gibi yüzlerce benzer açılış cümlesi, karşı tarafta ilgi değil yorgunluk yaratır. Oysa iyi bir ilk temas, hazır kalıplardan değil, kişinin açıkça paylaştığı ton, mizah, ilgi alanı ve kendini ifade ediş biçiminden doğar.

`Pineal Gland` bu yüzden var: yüzeyselliği azaltmak, klişeyi kırmak ve daha dikkatli bir iletişim başlangıcı hazırlamak için.

## Proje ne yapar

- Kamusal ve kullanıcı tarafından paylaşılmış içerikteki tekrar eden temaları toplar
- Kişinin dili, mizahı ve ilgi alanları üzerinden iletişim tonu önerir
- Tek tip mesaj yerine bağlama uygun birkaç ilk mesaj taslağı üretir
- Mesajı otomatik göndermez; sadece öneri sunar
- Kullanıcının kendi üslubuna göre metni düzenlemesine alan bırakır

## Proje ne yapmaz

- Hesap kırma, oturum çalma, gizli veri toplama
- Kişisel bilgi hırsızlığı veya izinsiz veri çıkarımı
- Platform tespit sistemlerini atlatmaya dönük davranış
- İnsanları kandırmak, baskılamak veya zayıf noktalarını sömürmek
- Tam otonom mesaj gönderme ve insan yerine ilişki yürütme

## Temel ilke

Bu projenin temel yaklaşımı şudur: teknoloji, insanın yerine geçmemeli; insanın daha dikkatli ve daha özenli davranmasına yardım etmelidir.

Bu nedenle `Pineal Gland` bir `send bot` değil, bir `drafting and context assistant` olarak konumlanır. Sistem önerir, kullanıcı seçer. Sistem bağlam çıkarır, kullanıcı yorumlar. Sistem taslak hazırlar, kullanıcı gönderir ya da vazgeçer.

## Neden “Üçüncü Göz”

Bu isim gösteriş için seçilmedi. Buradaki fikir, daha fazla veri toplamak değil; zaten ortada olan gürültünün içinden daha temiz bir sinyal görebilmektir.

İnsanlar çoğu zaman yalnızca fotoğrafa, takipçi sayısına veya yüzeyde duran birkaç işarete bakar. Oysa biri kendini çoğu zaman kullandığı dilde, tekrar ettiği küçük ayrıntılarda, mizahında ve ilgi alanlarında belli eder. `Pineal Gland`, bu bağlamı daha dikkatli okuyup kullanıcıya şu türden bir yardım sunmayı amaçlar:

`Bu kişiye standart bir selam yazmak yerine, açıkça sevdiğini paylaştığı şu tema üzerinden doğal bir giriş yapmak daha anlamlı olabilir. İşte üç farklı mesaj taslağı.`

## Kullanım felsefesi

İyi bir ilk mesaj, karşı tarafı avlamak için değil, gerçekten duyulduğunu hissettirmek için yazılmalıdır. Proje bu yüzden manipülatif değil, özenli iletişim tarafında durur.

Hedefimiz, kullanıcıya “haksız avantaj” vermek değil; onu daha az klişe, daha az rastgele ve daha fazla dikkat sahibi hale getirmektir.

## Mimari yön

Bu depo, farklı servisleri bir araya getirerek şu akışı desteklemeyi amaçlar:

1. Bağlam toplama
2. Tema ve ton çıkarımı
3. Mesaj taslağı üretimi
4. İnsan onayı
5. İsteğe bağlı düzenleme ve gönderim

Buradaki en önemli sınır, `approval boundary` çizgisidir. Sistem, insan onayı olmadan dış dünyaya aksiyon alan bir yapıya dönüşmemelidir.

## Güvenli ürün ilkeleri

- `human-in-the-loop` zorunludur
- yalnızca kamusal ve kullanıcı tarafından paylaşılmış bağlam kullanılmalıdır
- hassas kişisel veri toplanmamalıdır
- otomatik gönderim varsayılan olarak kapalı olmalıdır
- tüm öneriler düzenlenebilir ve reddedilebilir olmalıdır
- sistem, iletişim koçu gibi davranmalı; gizli gözetim aracı gibi değil

## Kime hitap eder

- İlk mesaj yazmakta zorlanan ama klişe olmak istemeyen kişiler
- Soğuk ve kopya metinler yerine daha dikkatli giriş yapmak isteyenler
- Bağlamı okuyup daha insani, daha doğal bir ton bulmak isteyenler

## Kısa ürün tanımı

`Pineal Gland`, kamusal bağlamı daha dikkatli okuyarak kullanıcıya daha doğal, daha kişisel ve daha anlamlı ilk mesaj taslakları hazırlayan bir iletişim asistanıdır. Otomatik ilişki botu değil, insan kararını merkeze alan bir taslak ve bağlam yardımcısıdır.
