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

            # === GÖRSELİ YAKALA (Media Content veya Enclosure) ===
            image_url = ""
            # 1. Yöntem: media_content kontrolü
            if hasattr(entry, 'media_content') and entry.media_content:
                image_url = entry.media_content[0].get('url', '')
            # 2. Yöntem: media_thumbnail kontrolü
            elif hasattr(entry, 'media_thumbnail') and entry.media_thumbnail:
                image_url = entry.media_thumbnail[0].get('url', '')
            # 3. Yöntem: enclosure (eklenti) kontrolü
            elif hasattr(entry, 'enclosures') and entry.enclosures:
                for enc in entry.enclosures:
                    if 'image' in enc.get('type', ''):
                        image_url = enc.get('href', '')
                        break

            # Eğer görsel bulunduysa HTML koduna ekle, bulunmadıysa sadece metin kalsın
            if image_url:
                content_html = f"<p><img src='{image_url}' alt='{title}' style='max-width:100%; height:auto; border-radius:8px;' /></p><p>{summary}</p><p><i>Kaynak: {kaynak_adi}</i></p>"
            else:
                content_html = f"<p>{summary}</p><p><i>Kaynak: {kaynak_adi}</i></p>"

            # === KATEGORİLER VE ETİKETLER (En fazla 9 adet) ===
            categories = [kaynak_adi]
            
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
                
            if len(categories) == 1:
                categories.append("Teknoloji")
                
            categories = categories[:9]

            # === Blogger API Verisi ===
            post_data = {
                "kind": "blogger#post",
                "blog": {"id": BLOG_ID},
                "title": title,
                "content": content_html,
                "published": published,
                "labels": categories
            }

            url = f"https://www.googleapis.com/blogger/v3/blogs/{BLOG_ID}/posts/"
            headers = {
                "Authorization": f"Bearer {ACCESS_TOKEN}",
                "Content-Type": "application/json"
            }

            response = requests.post(url, headers=headers, json=post_data)

            if response.status_code == 200:
                print(f"  ✅ Görsel Destekli Yayınlandı [{kaynak_adi}]: {title}")
            else:
                print(f"  ❌ Blogger Hatası [{kaynak_adi}]: {response.status_code} - {response.text}")

        except Exception as e:
            print(f"  ❌ Hata [{kaynak_adi}]: {e}")
