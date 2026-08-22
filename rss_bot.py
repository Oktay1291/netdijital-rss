import feedparser
import os

# 17 adet global kaynağımız
RSS_FEEDS = [
    "https://techcrunch.com/feed/",
    "https://thenextweb.com/feed/",
    "https://www.wired.com/feed/rss",
    "https://gizmodo.com/rss",
    "https://mashable.com/feed/",
    "https://www.theverge.com/rss/index.xml",
    "https://www.digitaltrends.com/feed/",
    "https://www.techradar.com/rss",
    "https://www.businessinsider.com/rss",
    "https://feeds.macrumors.com/MacRumors-All",
    "https://venturebeat.com/feed/",
    "https://blog.playstation.com/feed/",
    "https://www.engadget.com/rss.xml",
    "https://www.slashgear.com/feed/",
    "https://www.ubergizmo.com/feed/",
    "https://www.droid-life.com/feed/",
    "https://www.eurogamer.net/feed"
]

MEMORY_FILE = "yayinlanan_haberler.txt"

# 1. Eski haberleri hafızadan oku
yayinlananlar = set()
if os.path.exists(MEMORY_FILE):
    with open(MEMORY_FILE, "r", encoding="utf-8") as f:
        yayinlananlar = set(f.read().splitlines())

islenen_haber_sayisi = 0
yeni_yayinlanacak_linkler = []

# 2. Kaynakları tara ve sadece 2 YENİ haber bul
for feed in RSS_FEEDS:
    if islenen_haber_sayisi >= 2:
        break # 2 habere ulaştıysak taramayı durdur
    
    parsed_feed = feedparser.parse(feed)
    for entry in parsed_feed.entries:
        if islenen_haber_sayisi >= 2:
            break
            
        haber_linki = entry.link
        
        # Eğer haber daha önce YAYINLANMADIYSA
        if haber_linki not in yayinlananlar:
            print(f"Yeni Haber Bulundu: {entry.title}")
            
            # ---> BURAYA GEMINI ÇEVİRİ VE SMTP (E-POSTA) GÖNDERİM KODLARIN GELECEK <---
            
            # İşlem başarılı olursa linki listeye ekle
            yeni_yayinlanacak_linkler.append(haber_linki)
            yayinlananlar.add(haber_linki)
            islenen_haber_sayisi += 1

# 3. Yeni yayınlanan haberleri hafıza dosyasına kaydet
with open(MEMORY_FILE, "a", encoding="utf-8") as f:
    for link in yeni_yayinlanacak_linkler:
        f.write(link + "\n")
