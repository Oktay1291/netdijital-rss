import os
import feedparser
import html
from datetime import datetime
import requests
from deep_translator import GoogleTranslator

# === GİT-HUB SECRETS'DAN BİLGİLERİ ALMA ===
BLOG_ID = os.getenv("BLOGGER_BLOG_ID")
CLIENT_ID = os.getenv("BLOGGER_CLIENT_ID")
CLIENT_SECRET = os.getenv("BLOGGER_CLIENT_SECRET")
REFRESH_TOKEN = os.getenv("BLOGGER_REFRESH_TOKEN")

# === OTOMATİK ACCESS TOKEN ÜRETME FONKSİYONU ===
def get_access_token(client_id, client_secret, refresh_token):
    url = "https://oauth2.googleapis.com/token"
    data = {
        "client_id": client_id,
        "client_secret": client_secret,
        "refresh_token": refresh_token,
        "grant_type": "refresh_token"
    }
    response = requests.post(url, data=data)
    if response.status_code == 200:
        token_info = response.json()
        return token_info.get("access_token")
    else:
        print(f"❌ Token yenileme hatası: {response.status_code} - {response.text}")
        return None

print("🔄 Kimlik doğrulaması yapılıyor ve token yenileniyor...")
ACCESS_TOKEN = get_access_token(CLIENT_ID, CLIENT_SECRET, REFRESH_TOKEN)

if not ACCESS_TOKEN:
    print("❌ Kritik Hata: Token alınamadığı için bot durduruldu.")
    exit(1)

print("✅ Taze Access Token başarıyla alındı!")

# === HANGİ BLOGLARA YETKİN VAR KONTROL EDELİM ===
print("🔍 Bu token ile erişilebilen bloglar listeleniyor...")
blogs_url = "https://www.googleapis.com/blogger/v3/users/self/blogs"
headers = {
    "Authorization": f"Bearer {ACCESS_TOKEN}",
    "Content-Type": "application/json"
}
blogs_response = requests.get(blogs_url, headers=headers)

if blogs_response.status_code == 200:
    blogs_data = blogs_response.json()
    if "items" in blogs_data:
        print("📌 Erişilebilen Blog Listesi:")
        for blog in blogs_data["items"]:
            print(f"   👉 Blog Adı: {blog['name']} | Gerçek Blog ID: {blog['id']} | URL: {blog['url']}")
    else:
        print("⚠️ Bu hesapta yönetici olduğun hiçbir Blogger blogu bulunamadı!")
else:
    print(f"❌ Bloglar listelenemedi: {blogs_response.status_code} - {blogs_response.text}")

# === ÇOKLU RSS KAYNAKLARI LİSTESİ (14 Kaynak) ===
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

# === TÜM KAYNAKLARI DÖNGÜYE SOK ===
for source in RSS_SOURCES:
    rss_url = source["url"]
    kaynak_adi = source["kaynak"]
    
    print(f"🔄 Taranıyor: {kaynak_adi}...")
    feed = feedparser.parse(rss_url)

    # Her kaynaktan en son 2 haber çekilir
    for entry in feed.entries[:2]:
        try:
            original_title = entry.title
            original_summary = getattr(entry, 'summary', 'Açıklama bulunamadı.')

            title = html.escape(translator.translate(original_title))
            summary = html.escape(translator.translate(original_summary))

            published = datetime.now().isoformat()

            # === GÖRSELİ YAKALA ===
            image_url = None
            if hasattr(entry, 'media_content') and entry.media_content:
                image_url = entry.media_content[0].get('url')
            elif hasattr(entry, 'media_thumbnail') and entry.media_thumbnail:
                image_url = entry.media_thumbnail[0].get('url')

            # === İÇERİK HTML YAPISI ===
            if image_url:
                content_html = f"<p><img src='{image_url}' alt='Haber Görseli' style='max-width:100%; height:auto; border-radius:8px;'/></p><p>{summary}</p><p><i>Kaynak: {kaynak_adi}</i></p>"
            else:
                content_html = f"<p>{summary}</p><p><i>Kaynak: {kaynak_adi}</i></p>"

            # === KATEGORİLER VE ETİKETLER (Maksimum 9 adet) ===
            categories = [kaynak_adi]  # İlk etiket her zaman kaynağın kendi adıdır
            
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
                
            categories = categories[:9]  # En fazla 9 etiket sınırı

            # === Blogger API Gönderi Paketi ===
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
                print(f"  ✅ Yayınlandı [{kaynak_adi}] ({', '.join(categories)}): {title}")
            else:
                print(f"  ❌ Blogger Hatası [{kaynak_adi}]: {response.status_code} - {response.text}")

        except Exception as e:
            print(f"  ❌ İşlem Hatası [{kaynak_adi}]: {e}")
