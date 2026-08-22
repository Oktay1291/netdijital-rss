import feedparser
import os
import json
import urllib.request
import base64

BLOG_ID = os.environ.get("BLOGGER_BLOG_ID")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")

RSS_FEEDS = [
    "https://techcrunch.com/feed/"
]

MEMORY_FILE = "yayinlanan_haberler.txt"

yayinlananlar = set()
if os.path.exists(MEMORY_FILE):
    with open(MEMORY_FILE, "r", encoding="utf-8") as f:
        yayinlananlar = set(f.read().splitlines())

islenen_haber_sayisi = 0
yeni_yayinlanacak_linkler = []

# E-posta yerine doğrudan Google API üzerinden Blogger'a taslak/yayın olarak ekleme fonksiyonu
def post_to_blogger_api(title, content):
    # Google API Anahtarı ile Blogger API v3 uç noktası
    url = f"https://www.googleapis.com/blogger/v3/blogs/{BLOG_ID}/posts/?key={GEMINI_API_KEY}"
    
    body = {
        "title": title,
        "content": content
    }
    
    req = urllib.request.Request(
        url, 
        data=json.dumps(body).encode('utf-8'), 
        headers={'Content-Type': 'application/json'}
    )
    
    try:
        with urllib.request.urlopen(req) as response:
            res_data = json.loads(response.read().decode('utf-8'))
            print("Blogger API ile yazı başarıyla oluşturuldu!")
            return True
    except Exception as e:
        print(f"Blogger API Gönderim Hatası: {e}")
        return False

for feed in RSS_FEEDS:
    if islenen_haber_sayisi >= 1:
        break
        
    parsed_feed = feedparser.parse(feed)
    for entry in parsed_feed.entries:
        if islenen_haber_sayisi >= 1:
            break
            
        haber_linki = entry.link
        
        if haber_linki not in yayinlananlar:
            print(f"İşleniyor: {entry.title}")
            
            try:
                gorsel_url = ""
                if hasattr(entry, 'media_content') and entry.media_content:
                    gorsel_url = entry.media_content[0].get('url', '')
                elif hasattr(entry, 'enclosures') and entry.enclosures:
                    gorsel_url = entry.enclosures[0].get('href', '')

                haber_icerigi = entry.summary if hasattr(entry, 'summary') else entry.title
                
                gorsel_html = f"<img src='{gorsel_url}' style='width:100%; border-radius:8px; margin-bottom:15px;' /><br>" if gorsel_url else ""
                html_icerik = f"{gorsel_html}<p>{haber_icerigi}</p><br><p><strong>Kaynak:</strong> <a href='{haber_linki}'>{entry.title}</a></p>"
                
                basarili = post_to_blogger_api(entry.title, html_icerik)
                
                if basarili:
                    yeni_yayinlanacak_linkler.append(haber_linki)
                    yayinlananlar.add(haber_linki)
                    islenen_haber_sayisi += 1
                
            except Exception as e:
                print(f"Hata oluştu: {e}")

with open(MEMORY_FILE, "a", encoding="utf-8") as f:
    for link in yeni_yayinlanacak_linkler:
        f.write(link + "\n")
