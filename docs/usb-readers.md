# USB kart okuyucu algılama

Uygulama SD/MMC kartlarını ve USB depolama aygıtlarını kabul eder. 2026-10-14
tarihinde kullanıcı onayıyla Raspberry Pi Imager yaklaşımına geçildi:
Windows'un BusType bilgisi kullanılır; aygıt adında kart okuyucu yazması
gerekmez. Vendor, model, VID/PID veya seri numarası izin listesi yoktur.
USB flash bellekler de uygun hedef olabilir. Sürücü harfi gerekmez.

Tanılama görünümü: 2026-10-14 kullanıcı isteğiyle ana pencerede tüm
Windows boot/sistem diski olmayan diskler listelenir. USB bellekler ve genel
adlı okuyucular da bu listede görünür; bu görünüm yazma izni vermez. Her satır
disk numarası, Windows adı, bağlantı, kapasite, durum ve yazmaya uygun olmama
nedenini gösterir. Kart okuyucu açıklaması yazma için filtre değildir.
Canlı Get-Disk çıktısında takılı kart Disk 1, USB, 15931539456 byte,
çevrimiçi/salt okunur değil olarak görülmüş; adı hâlâ `Mass Storage Device`.

Kart yokken sıfır kapasiteli/offline disk yazma hedefi olamaz. Kart takıldıktan
sonra **Aygıtları Tara** düğmesiyle yeniden taranır. Kullanıcı listeden hedefi
açıkça seçer; başlangıçta otomatik hedef seçilmez. İmaj seçimi sonrası taramada
aynı aygıt hâlâ uygunsa kullanıcının hedef seçimi korunur.
Boot/system, salt okunur, offline ve 2 GiB altı diskler dışlanır. Birden fazla
uygun aygıt varsa kullanıcı bunlardan birini seçer. Yazmadan önce disk numarası, UniqueId,
PnP kimliği, kapasite ve bağlantı türü tekrar karşılaştırılır. Bu karşılaştırma
seçilen aygıtın işlem sırasında değişmediğini denetler; izin listesi değildir.

Doğrulama: `python -m unittest test_device_detection.py`.
Mevcut testler yeni kabul ve hedef seçimi davranışına uyarlandı; kullanıcı
isteğiyle ek test paketi çalıştırılmadı. Python sözdizimi kontrol edildi.
Gerçek disk yazımı yapılmadı; canlı GUI davranışı kullanıcı tarafından doğrulanacak.
