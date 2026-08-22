import feedparser
import os
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from google import genai

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
SENDER_EMAIL = os.environ.get("SENDER_EMAIL") 
SENDER_PASSWORD = os.environ.get("SENDER_PASSWORD") 
BLOGGER_EMAIL = "ktysarikaya.netdijital1291@blogger.com"

# Yeni ve kararlı genai kütüphanesi istemcisi
client = genai.Client(api_key=GEMINI_API_KEY)

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

def send_email_to_blogger(title, content):
    msg = MIMEMultipart()
    msg['From'] = SENDER_EMAIL
    msg['To'] = BLOGGER_EMAIL
    msg['Subject'] = title # Artık Türkçe başlık gidecek
    msg.attach(MIMEText(content, 'html', 'utf-8'))
    
    try:
        with smtplib.SMTP_SSL('smtp.gmail.com', 465) as server:
            server.login(SENDER_EMAIL, SENDER_PASSWORD)
            server.sendmail(SENDER_EMAIL, BLOGGER_EMAIL, msg.as_string())
        print("E-posta Blogger'a başarıyla iletildi!")
    except Exception as e:
        print(f"E-posta gönderim hatası: {e}")
        raise e

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
                # RSS'ten görsel URL'sini yakalama (varsa)
                gorsel_url = ""
                if hasattr(entry, 'media_content') and entry.media_content:
                    gorsel_url = entry.media_content[0].get('url', '')
                elif hasattr(entry, 'enclosures') and entry.enclosures:
                    gorsel_url = entry.enclosures[0].get('href', '')

                # Yapay zekadan hem Türkçe başlık hem içerik hem de etiketleri istiyoruz
                prompt = f"""
                Aşağıdaki İngilizce haberi teknoloji blogum NetDijital için profesyonelce işle.
                Şu formatta tam olarak JSON benzeri veya etiketli metin ver:
                [TURKCE_BASLIK]: (Buraya ilgi çekici Türkçe başlık yaz)
                [ETIKETLER]: (Virgülle ayrılmış 3-4 adet teknoloji etiketi yaz, örn: yapay zeka, teknoloji, donanım)
                [ICERIK]: (Sadece <h2>, <p>, <strong> etiketleri kullanarak SEO uyumlu HTML makale içeriği yaz. Haberin sonuna 'Kaynak: Orijinal Başlık' şeklinde link ekle.)

                Haber: {entry.title} - {entry.summary}
                """

                response = client.models.generate_content(
                    model='gemini-2.5-flash',
                    contents=prompt,
                )
                
                yanit_metni = response.text

                # Yapay zekadan gelen yanıtı parçalarına ayıralım
                tr_baslik = entry.title # Yedek olarak orijinal başlık
                etiketler = "teknoloji, gündem"
                html_govde = yanit_metni

                if "[TURKCE_BASLIK]:" in yanit_metni and "[ICERIK]:" in yanit_metni:
                    parts = yanit_metni.split("[ICERIK]:")
                    baslik_bolumu = parts[0]
                    html_govde = parts[1].replace("```html", "").replace("```", "").strip()
                    
                    if "[TURKCE_BASLIK]:" in baslik_bolumu:
                        tr_baslik = baslik_bolumu.split("[TURKCE_BASLIK]:")[1].split("[ETIKETLER]:")[0].replace("\n", "").strip()

                # Eğer görsel varsa içeriğin en başına ekleyelim ki Blogger kapak olarak alsın
                gorsel_html = f"<img src='{gorsel_url}' style='width:100%; border-radius:8px; margin-bottom:15px;' /><br>" if gorsel_url else ""
                
                final_icerik = gorsel_html + html_govde

                # Blogger'a Türkçe başlık ve içerikle gönder
                send_email_to_blogger(tr_baslik, final_icerik)
                
                yeni_yayinlanacak_linkler.append(haber_linki)
                yayinlananlar.add(haber_linki)
                islenen_haber_sayisi += 1
                print("Başarıyla Türkçe başlık, görsel ve içerik Blogger'a gönderildi!")
                
            except Exception as e:
                print(f"Hata oluştu: {e}")

with open(MEMORY_FILE, "a", encoding="utf-8") as f:
    for link in yeni_yayinlanacak_linkler:
        f.write(link + "\n")
