# TypeSafe Computer Use — Windows uyarlaması

Bu klasör, **awlevin/typesafe-computer-use** projesinin `cc7b5066ae1a07b5e3182e8f87a9b5b6dfdcffc1` sürümünden türetildi. Özgün MIT lisansı ve README korunmuştur. Bu resmi TypeSafe ürünü değildir. Önceki `jev-computer-use` klasörü ayrı ve dar kapsamlı prototipti; ajan bağlantısında artık bu uyarlama kullanılır.

## Korunan işleyiş

Ekranı oku → OCR ve erişilebilirlik öğelerini birleştir → tek Jev isteğinde işlem/hedef/site seç → uygula → tekrar oku. Özgün karar soruları, tarih işleme, seçenek üretimi, yazı doğrulama, görev geçmişi, durma koşulları ve sonuç değerlendirme korunur. Metinler veya tıklanacak düğmeler görev başında tek tek hazırlanmak zorunda değildir.

## Windows karşılıkları

| Özgün macOS bileşeni | Windows karşılığı |
|---|---|
| Vision OCR | Windows.Media.Ocr, yerel |
| AX erişilebilirlik | UI Automation |
| Quartz giriş | Windows klavye/fare girdisi ve UIA işlemleri |
| Ekran yakalama | Yalnız hedef pencereyi PrintWindow ile yakalama, DPI eşleme |
| AppleScript uygulama yönetimi | Gözlemlenen Windows pencereleri |
| Yardımcı Anthropic modeli | Mevcut ana ajanla MCP üzerinden yazıcı/sonuç isteği; özgün Anthropic seçeneği de korunur |

Ana ajan Grok, Codex veya başka bir model olabilir; MCP araçlarını kullanabilmesi ve istenen şemayla cevap verebilmesi gerekir. Her tıklamada ana modele dönülmez. Serbest metin, katalog dışı URL ve son ekran değerlendirmesi için ana ajana dönülür.

## Kullanım

Ajanına: **“Jev Computer Use Windows uyarlamasını kullanarak [görev] yap.”**

1. `typesafe_windows` ile hedef pencere seçilir.
2. `typesafe_run(goal, windowTitle, act=true)` başlatılır. `act=false` yalnız karar üretir.
3. `typesafe_wait` çalışmayı bekler; `needs_host` varsa ana ajan verilen bağlamı okur.
4. Ana ajan `typesafe_respond` ile tam istenen JSON alanlarını sağlar. Görsel varsa önce inceler.
5. Aynı çalışan döngü devam eder. `typesafe_status` raporu, `typesafe_stop` durdurmayı sağlar.

Codex'te mevcut görev araç listesini yenilemiyorsa yeni görev açmak gerekebilir. Başka MCP istemcileri için `mcp-config.json` kullanılabilir. Doğrudan CLI, `.venv\Scripts\clicker.exe "hedef" --act --window-title "tam pencere başlığı"` biçimindedir. CLI'de bağımsız yazıcı kullanmak istersen Anthropic ortam ayarları özgün projedeki gibi desteklenir; bir ajanla kullanımda ek yardımcı model API anahtarı gerekmez.

## Anahtar ve veri

Mevcut Vercel anahtarı `config/vercel-key.dpapi` içinde bu Windows hesabına bağlı şifrelidir. `config/provider.json` sağlayıcıyı seçer. Doğrudan `TYPESAFE_API_KEY` veya Vercel `AI_GATEWAY_API_KEY` de desteklenir. Anahtar loglanmaz. Seçili pencerenin OCR/kontrol metni Jev sağlayıcısına, yazıcı istekleri ana ajana gider. Özgün projedeki gibi `runs/` klasörü ekran, görev ve eylem kayıtları tutar; özel görev kayıtlarını paylaşmadan önce inceleyin.

## Doğrulanan sonuç

20 Eylül 2026: macOS ve Windows ortak mantığı ile Windows portuna ait toplam
**181 test geçti**. Ruff kontrolleri geçti. Gerçek Windows formunda Jev, alanı
seçti → ana ajandan metin istedi → metni yazdı ve Jev ile doğruladı → kutuyu
işaretledi → Tamamla'ya bastı → `done` dedi. Son ekran ana ajan tarafından ve
uygulamanın bağımsız kaydıyla doğrulandı.

Kanıt: `runs/936403fc-8d69-4eea-9cec-c3daecb10426/run.json`, aynı klasörde adım ekranları/kararları ve `runs/windows-fixture-result-final.json`. Bu koşuda 5 Jev karar çevrimi, 4 uygulanan işlem vardı. Ortalama karar süresi 0,527 saniye; toplam 41,9 saniye ana ajanın yanıt bekleme ve son ekran inceleme sürelerini de içeriyor. Bunlar tek görevin ölçümleri; **100 kat hız iddiası veya genel başarı garantisi değildir**.

## Sınırlar

- Ana monitör desteklenir; hedefi burada tutun. İkinci monitör ve karma DPI kapsamlı test edilmedi.
- PrintWindow bazı GPU/canvas uygulamalarında görüntü vermeyebilir. Böyle bir durumda ayrı görüntü yakalama desteği gerekir; masaüstündeki başka pencereye sessizce geçilmez.
- Windows OCR kelime güveni sağlamaz; OCR'daki 1.0 değeri model güveni değildir. Türkçe/karma dil doğruluğu kurulu OCR diline bağlıdır.
- Chrome/Edge adres çubuğu ve uygulama geçişi Windows'a uyarlanmıştır; gerçek web siteleri üzerinde bu sürümde uçtan uca test edilmedi. Aktif profil kullanılır; belirsiz çoklu pencere seçimi reddedilir.
- Parola alanlarına yazılmaz. Terminal, parola yöneticisi, güvenlik ve kilit ekranı işlemleri ana kullanıcıya bırakılır. UAC aşılmaz.
- Mouse sol üst köşeye götürülerek, `typesafe_stop` veya `0-Durdur.cmd` ile durdurulabilir. Gönderilmiş bir işlem geri alınmaz. Ana ajana dönüşte hedef alan değişmişse yazma durdurulur.

Tam uygulama eşdeğerliği henüz her Windows programında sınanmış değildir. Bu, özgün projenin çalışan Windows portudur; yalnız Not Defteri demosundan ibaret olan önceki kontrolcü değildir.

## Kurulum ve yeniden kurulum

Python 3.12+ ve Node.js 20+ kurduktan sonra `Install-Windows.cmd` dosyasına çift
tıklayın. Kurucu `.venv` ortamını, Python ve Node bağımlılıklarını ve taşınabilir
MCP ayarını hazırlar. Ardından `1-Baslat.cmd` menüsünden API anahtarını girin.
Klasörü taşırsanız menüdeki **MCP bağlantı dosyasını aç** seçeneğini yeniden
çalıştırıp istemcinizdeki yolu güncelleyin. Başka Windows hesabında DPAPI
anahtarını yeniden girmeniz gerekir.
