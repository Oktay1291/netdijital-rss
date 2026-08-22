import feedparser
import os
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

SENDER_EMAIL = os.environ.get("SENDER_EMAIL") 
SENDER_PASSWORD = os.environ.get("SENDER_PASSWORD") 
BLOGGER_EMAIL = "ktysarikaya.netdijital1291@blogger.com"

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
    msg['Subject'] = title
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
                # Haberin kapak görselini RSS'ten yakalıyoruz
                gorsel_url = ""
                if hasattr(entry, 'media_content') and entry.media_content:
                    gorsel_url = entry.media_content[0].get('url', '')
                elif hasattr(entry, 'enclosures') and entry.enclosures:
                    gorsel_url = entry.enclosures[0].get('href', '')

                haber_icerigi = entry.summary if hasattr(entry, 'summary') else entry.title
                
                # Görseli en üste ekleyip, içeriği ve kaynak linkini HTML olarak düzenliyoruz
                gorsel_html = f"<img src='{gorsel_url}' style='width:100%; border-radius:8px; margin-bottom:15px;' /><br>" if gorsel_url else ""
                html_icerik = f"{gorsel_html}<p>{haber_icerigi}</p><br><p><strong>Kaynak:</strong> <a href='{haber_linki}'>{entry.title}</a></p>"
                
                send_email_to_blogger(entry.title, html_icerik)
                
                yeni_yayinlanacak_linkler.append(haber_linki)
                yayinlananlar.add(haber_linki)
                islenen_haber_sayisi += 1
                print("Başarıyla Blogger'a gönderildi!")
                
            except Exception as e:
                print(f"Hata oluştu: {e}")

with open(MEMORY_FILE, "a", encoding="utf-8") as f:
    for link in yeni_yayinlanacak_linkler:
        f.write(link + "\n")
