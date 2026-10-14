# Raspberry Pi Imager Windows kaynak incelemesi

## Doğrulama sırasında Windows'un karta yazması (2026-10-14)

20:48:01 başarısız denemesinde ilk uyuşmayan blok offset 411041792 idi.
Salt-okunur incelemede kaynakla farklı 228 bayt, FAT32 boş veri alanındaki
cluster 196610–196612'ye eşlendi (ilk farklı bayt 413147136). Kaynak FAT
kayıtlarında bu üç cluster boştu; içerikleri sıfırdı. Diskte bunlar
`System Volume Information` dizini, `WPSettings.dat` (12 bayt) ve
`IndexerVolumeGuid` (76 bayt) içeriyordu. Diskteki root cluster 527'ye
eklenen System Volume Information girdisi kaynakta yoktu.

Dizin oluşturulma zamanı 20:47:28; dosyalar 20:47:32'ye kadar değiştirilmiş.
Logda bölüm tablosu 20:47:17'de yazılmış ve ardından doğrulamaya geçilmişti.
Dolayısıyla Windows dosyaları doğrulama sürerken oluşturuldu. İki direct ve
bir buffered okuma aynı 228 farkı verdi. Hangi Windows işleminin yazdığı
izlenmedi; bu bulgu tüm kartta başka fark olmadığını kanıtlamaz.

Raspberry Pi Imager `DownloadThread::_writeComplete` önce `_verify()` çağırır,
sonra saklanan `_firstBlock`'u yazar. Bizdeki önce ilk blok, sonra doğrulama
sırası bu davranışla aynı değildi. Bu fark düzeltildi: veri gövdesi imajla
karşılaştırılırken MBR görünür yapılmaz; kontrol başarılıysa ilk blok yazılıp
flush edilir ve aynı buffered/direct reader ile geri okunarak karşılaştırılır.
Kaynak ilk bloğun değişmediği de ikinci açma sırasında kontrol edilir.
Ancak tüm baytlar doğrulandıktan sonra Windows disk görünümü yenilenir.

32 test geçti. Regresyon testleri ilk bloğun gövde doğrulamasından önce
yazılmadığını, gövde hatasında hiç yayımlanmadığını ve ilk bloğun son geri
okuması başarısızsa başarı bildirilmediğini kontrol eder. Gerçek Windows API'si
ile geçici normal dosyada gövde doğrulama → ilk blok commit → direct readback
testi geçti. İnceleme sırasında SD karta yazılmadı; düzeltilmiş sürümle tam
kart yazma/doğrulama testi henüz yapılmadı.

## Ek imaj dosyası gerektirmeyen iyileştirmeler (2026-10-14)

Uyumluluk profili: blok boyutu 4 MiB olarak kalır; aynı anda yalnızca bir
senkron disk isteği gönderilir. Yazmada WRITE_THROUGH ve son flush korunur.
İlk blok veri flush edilip doğrulandıktan sonra yazılır; doğrulama tüm baytları kapsar.

1. Yazma ve doğrulamada ayrı bir decoder imajı RAM'e açar. En fazla iki blok
   kuyrukta bekler (8 MiB). Disk istekleri tüketici tarafından sırayla yapılır.
   Kaynak dosyası sadece decoder tarafından `rb` modunda açılır. Hatalar ana
   writer iş parçacığına aktarılır; erken çıkışta decoder durdurulur. Decoder
   belleği, eldeki bloklar ve doğrudan okuma tamponu ayrıca RAM kullanır.
2. Blok boyutunu büyütmek yerine kısmi yazmalarda `memoryview` ile gereksiz
   kopyalama azaltılır. Arayüz saniyede en fazla beş kez güncellenir; aşama
   değişimleri ve tamamlanma hemen gösterilir. Log ilerleme kayıtları korunur.
3. Doğrulama ayrı, yalnızca okumaya açık `FILE_FLAG_NO_BUFFERING` handle'ı ve
   VirtualAlloc tamponuyla yapılır. Mantıksal/fiziksel sektör bilgisi ve imaj
   boyutunun hizalaması uygun değilse eski buffered yöntem kullanılır.
   Desteklenmeyen açma veya ilk okuma için hata kodları 1/50/87 geri dönüşe
   izin verir. Sonraki okuma hatası, kısa okuma ve veri uyuşmazlığı işi durdurur;
   fallback ile gizlenmez. Kullanılan yöntem ve fallback nedeni loga yazılır.
   Buffered geri dönüş önceki yöntemin önbellek sınırlamalarını taşır.

Geçici açılmış `.img` dosyası oluşturulmaz; ek 4,8 GB depolama gerekmez.
Önbelleksiz doğrulama güvenilirlik amaçlıdır; hızlanma garantisi değildir.
İlk kapasite/bütünlük taraması korunur; imaj hâlâ üç geçişte açılır, ancak yazma
ve doğrulama sırasında açma ile disk I/O beklemeleri örtüşür.

27 test geçti. Gerçek Windows API testleri silinen geçici normal dosyalarda
çalıştı. Takılı Disk 1 üzerinde sadece okuma yapılarak ilk 4 MiB ve imajın son
512 baytı buffered/unbuffered yöntemlerle eşleşti. Yeni sürümle tam fiziksel
yazma ve doğrulama performans testi henüz yapılmadı.

Windows hizalama kuralları:
https://learn.microsoft.com/en-us/windows/win32/fileio/file-buffering

## Yazma öncesi disk hazırlığı (2026-10-14)

Resmî Windows hazırlama kodu:
https://github.com/raspberrypi/rpi-imager/blob/main/src/windows/diskpart_util.cpp

`cleanDiskFast`, `IOCTL_DISK_DELETE_DRIVE_LAYOUT` ile eski bölüm tablosunu
kaldırır; bu işlem `diskpart clean` eşdeğeridir. RAW medyada bölüm tablosu
bulunmaması kabul edilir. Kaynak ayrıca bazı hatalarda MBR sıfırlama ve
DiskPart alternatifleri içerir. Bizde diğer temizleme hataları yazmayı durdurur.

Yeni bir geçici partition oluşturulmaz veya format atılmaz. İmaj kendi bölüm
tablosunu içerir. İlk blok, veri yazılıp flush edilip doğrulandıktan sonra yazılır:
https://github.com/raspberrypi/rpi-imager/blob/main/src/downloadthread.cpp

Uygulanan sıra: SHA-256 ve açılmış imaj kapasitesi kontrolü → hedef kimliği ve
uygunluğu kontrolü → volume kilitleme/dismount → fiziksel diski açma → eski
bölüm tablosunu temizleme → ilk bloğu sona bırakarak imaj yazma → flush →
gövdeyi birebir okuyup doğrulama → ilk bloğu yazma ve flush → ilk bloğu geri
okuyup doğrulama → kilitleri
bırakma → `IOCTL_DISK_UPDATE_PROPERTIES` ile Windows disk görünümünü yenileme.
Temizleme ile yazma arasında disk görünümü yenilenmez.

`clean` güvenli veri silme veya tüm diski sıfırlama değildir. Yazma işlemi
yalnızca uygulamadaki hedef seçimi ve son silme onayından sonra başlar.
13 otomatik test geçti; hazırlama testleri bellek üzerinde sahte Windows
API'leriyle çalıştı. Fiziksel disk temizleme/yazma testi yapılmadı.

2026-10-14 tarihinde resmi `raspberrypi/rpi-imager` deposunun
`8e7e0b6f67ba9b659b612c82b566f1a6260c59d9` commit'i incelendi.

Kaynaklar:
- https://github.com/raspberrypi/rpi-imager/blob/8e7e0b6f67ba9b659b612c82b566f1a6260c59d9/src/drivelist/drivelist_windows.cpp
- https://github.com/raspberrypi/rpi-imager/blob/8e7e0b6f67ba9b659b612c82b566f1a6260c59d9/src/drivelistmodel.cpp
- https://github.com/raspberrypi/rpi-imager/blob/8e7e0b6f67ba9b659b612c82b566f1a6260c59d9/src/wizard/StorageSelectionStep.qml

Windows diskleri SetupDi disk arayüzleri üzerinden listelenir. DeviceIoControl
ile fiziksel disk numarası, geometri/kapasite, bağlantı türü, sektör boyutu
ve yazılabilirlik sorgulanır. Açıklamada "card reader" yazması aranmaz.

USBSTOR/UASPSTOR gibi depolama sürücüleri USB olarak sınıflandırılır; SCSI
enumerator + USB bus birleşimi de USB sayılır. isCard yalnız SD/MMC/UFS bus
için ayarlanır; USB hedef seçimi isCard koşuluna bağlanmaz. Belirli okuyucu
vendor/model/VID/PID/seri numarası izin listesiyle seçilmez.

Sistem diski tespiti Windows ve kritik sistem klasörlerinin bulunduğu
volume'lerin fiziksel disk numaralarıyla yapılır. GUI'de sistem diskleri
varsayılan filtreyle gizlenir. Salt okunur cihaz seçilemez; normal sıfır
kapasiteli cihaz model listesine alınmaz. Kullanıcı hedef depolamayı seçer.

Bu yaklaşım USB flash bellekleri de dışlamaz. Kaynakta USB kart okuyucusunu
USB bellekten evrensel şekilde ayıran bir kontrol yoktur. Bizim uygulamadaki
açıklama filtresi, gerçek kart okuyucuyu `Mass Storage Device` adı nedeniyle
reddetmektedir. Raspberry Pi Imager uyumluluğu için genel USB depolamayı
kabul etmek gerekir; bu, USB bellekleri kesin gizleme isteğiyle aynı değildir.

Araştırma turunda imager uygulama kodu değiştirilmedi. Ardından kullanıcı
onayıyla uygulama USB/SD/MMC bus temelli kabul ve açık hedef seçimine geçirildi.
Uygulama artık birden fazla uygun cihaz bağlıyken seçilen diske yazabilir;
yazma öncesi yalnız seçilen diskin kimliği ve uygunluğu yeniden denetlenir.
