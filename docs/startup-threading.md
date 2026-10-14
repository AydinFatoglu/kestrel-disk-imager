# Başlangıç ve arayüz iş parçacıkları

2026-10-14: Açılış taraması ve ayrı Loading penceresi kaldırıldı. Yönetici
yetkisi kontrolünden sonra Main doğrudan gösterilir; açılışta PowerShell veya
aygıt envanteri sorgusu yapılmaz. Başlangıçta liste boş ve yazma kapalıdır;
arayüz imaj seçilmesini ister. İmaj seçimi bir arka plan taraması başlatır.

Aygıtları Tara, imaj seçimi sonrası tarama ve yazma sonrası tarama arka
planda çalışır. Tarama süresince seçim/yazma düğmeleri kilitlenir ve gösterge
hareket eder. wx kontrolleri yalnız ana iş parçacığından güncellenir.
SHA-256, imaj açma, yazma ve doğrulama mevcut yazma iş parçacığında kalır.
Yazma öncesindeki hedef kimliği/uygunluğu kontrolü ayrıca korunur; bu kontrol
envanterin yazmaya kadar değişmediğini doğrular ve açılış taramasından farklıdır.

Tarama hatasında ana pencere hatayı gösterir; yazma kapalıdır ve
kullanıcı yeniden tarayabilir. Tarama sırasında kapatılırsa
gecikmiş sonuç pencereyi yeniden açmaz veya kapalı kontrollere erişmez.
Yazma/doğrulama sırasında kapatma engeli korunur.

İlerleme çubuğu 32 DIP yüksekliğe, ayrı yüzde göstergesi kalın 28 puntoya
çıkarıldı. Çubuk ve yüzde ana iş parçacığında birlikte güncellenir; tarama
sırasında yüzde yerine belirsizlik göstergesi kullanılır.

Sıkıştırılmış imajın bütünlük/boyut kontrolünde de `show_indeterminate`
aynı timer ile Pulse çalıştırır; önceki SHA-256 aşamasının %100 değeri
gösterilmez. Gerçek ilerleme bildirimi başlayınca show_progress timer'ı
durdurur ve sayısal yüzdeye döner. Hata/başarı bildirimi öncesi timer durur.
Canlı wx kontrolünde %100 → belirsiz ilerleme → %25 geçişi ve kapanışta
timer'ın durması doğrulandı.

Python sözdizimi ve canlı wx arayüzü kontrol edildi: pencere oluşturulurken
tarama çağrısı sıfır, imaj seçiminden sonra bir. Yüzde/çubuk eşleşmesi ve
hedef seçilmeden yazmanın kapalı olması doğrulandı. Gerçek disk yazımı yok.
