import feedparser
import html
from datetime import datetime
import requests
from deep_translator import GoogleTranslator

# === AYARLAR ===
BLOG_ID = "BURAYA_BLOG_ID_YAZ"  # Blogger blog ID
ACCESS_TOKEN = "BURAYA_ACCESS_TOKEN_YAZ"  # OAuth 2.0 erişim tokenı

# === ÇOKLU RSS KAYNAKLARI LİSTESİ ===
RSS_SOURCES = [
    {"url": "https://techcrunch.com/feed/", "kaynak": "TechCrunch"},
    {"url": "https://www.theverge.com/rss/index.xml", "kaynak": "The Verge"},
    {"url": "https://www.engadget.com/rss.xml", "kaynak": "Engadget"},
    {"url": "https://feeds.arstechnica.com/arstechnica/index", "kaynak": "Ars Technica"},
    {"url": "https://www.wired.com/feed/rss", "kaynak": "Wired"},
    {"url": "https://thenextweb.com/feed", "kaynak": "The Next Web"},
    {"url": "https://www.digitaltrends.com/feed/", "kaynak": "Digital Trends"},
    {"url": "https://gizmodo.com/feed", "kaynak": "Gizmodo"},
    {"url": "https://electrek.co/feed/", "kaynak": "Electrek"},
    {"url": "https://www.androidpolice.com/feed/", "kaynak": "Android Police"},
    {"url": "https://bgr.com/feed/", "kaynak": "BGR"},
    {"url": "https://www.tomshardware.com/rss.xml", "kaynak": "Tom's Hardware"},
    {"url": "https://www.anandtech.com/rss/", "kaynak": "AnandTech"},
    {"url": "https://readwrite.com/feed/", "kaynak": "ReadWrite"}
]

translator = GoogleTranslator(source='auto', target='tr')

for source in RSS_SOURCES:
    rss_url = source["url"]
    kaynak_adi = source["kaynak"]
    
    print(f"🔄 Taranıyor: {kaynak_adi}...")
    feed = feedparser.parse(rss_url)

    for entry in feed.entries[:2]:
        try:
            original_title = entry.title
            original_summary = getattr(entry, 'summary', 'Açıklama bulunamadı.')

            title = html.escape(translator.translate(original_title))
            summary = html.escape(translator.translate(original_summary))

            published = datetime.now().isoformat()

            # === KATEGORİLER VE ETİKETLER (En fazla 9 adet olacak şekilde sınırlandırıldı) ===
            categories = [kaynak_adi]  # 1. Etiket: Kaynağın adı
            
            original_lower = original_title.lower()
            if "ai" in original_lower or "artificial intelligence" in original_lower or "yapay zeka" in original_lower:
                categories.append("Yapay Zeka")
            if "phone" in original_lower or "mobile" in original_lower or "android" in original_lower or "iphone" in original_lower:
                categories.append("Telefon")
            if "computer" in original_lower or "pc" in original_lower or "hardware" in original_lower:
                categories.append("Bilgisayar")
            if "game" in original_lower or "gaming" in original_lower:
                categories.append("Oyun")
            if "tesla" in original_lower or "ev" in original_lower or "car" in original_lower:
                categories.append("Elektrikli Araçlar")
                
            # Varsayılan kategori ekleme
            if len(categories) == 1:
                categories.append("Teknoloji")
                
            # Blogger en fazla etiket/kategori sınırına (veya senin belirttiğin 9 sınırına) uyması için kesme işlemi
            categories = categories[:9]

            # === Blogger API Verisi ===
            post_data = {
                "kind": "blogger#post",
                "blog": {"id": BLOG_ID},
                "title": title,
                "content": f"<p>{summary}</p><p><i>Kaynak: {kaynak_adi}</i></p>",
                "published": published,
                "labels": categories   # Etiketler buraya işleniyor
            }

            url = f"https://www.googleapis.com/blogger/v3/blogs/{BLOG_ID}/posts/"
            headers = {
                "Authorization": f"Bearer {ACCESS_TOKEN}",
                "Content-Type": "application/json"
            }

            response = requests.post(url, headers=headers, json=post_data)

            if response.status_code == 200:
                print(f"  ✅ Yayınlandı [{kaynak_adi}] ({', '.join(categories)}): {title}")
            else:
                print(f"  ❌ Blogger Hatası [{kaynak_adi}]: {response.status_code} - {response.text}")

        except Exception as e:
            print(f"  ❌ Hata [{kaynak_adi}]: {e}")
