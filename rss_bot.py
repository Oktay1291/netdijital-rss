import feedparser
import os
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import urllib.request
import json

SENDER_EMAIL = os.environ.get("SENDER_EMAIL") 
SENDER_PASSWORD = os.environ.get("SENDER_PASSWORD") 
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
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

def ai_cevir(metin):
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={GEMINI_API_KEY}"
    
    prompt = f"Şu İngilizce haberi teknoloji blogum NetDijital için SEO uyumlu, profesyonel bir dille Türkçe'ye çevir ve özetle. Sadece <h2>, <p>, <strong> etiketleri kullanarak HTML formatında ver. Haber: {metin}"
    
    data = {
        "contents": [{"parts": [{"text": prompt}]}]
    }
    
    req = urllib.request.Request(url, data=json.dumps(data).encode('utf-8'), headers={'Content-Type': 'application/json'})
    try:
        with urllib.request.urlopen(req) as response:
            res_data = json.loads(response.read().decode('utf-8'))
            return res_data['candidates'][0]['content']['parts'][0]['text'].replace("```html", "").replace("```", "").strip()
    except Exception as e:
        print(f"AI Çeviri Hatası: {e}")
        return metin

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
                gorsel_url = ""
                if hasattr(entry, 'media_content') and entry.media_content:
                    gorsel_url = entry.media_content[0].get('url', '')
                elif hasattr(entry, 'enclosures') and entry.enclosures:
                    gorsel_url = entry.enclosures[0].get('href', '')

                tr_baslik = ai_cevir(f"Bu haber başlığını dikkat çekici ve akıcı bir Türkçe teknoloji haberi başlığına çevir: {entry.title}")
                tr_baslik = tr_baslik.replace("<h2>", "").replace("</h2>", "").replace("<p>", "").replace("</p>", "").strip()
                
                ham_icerik = entry.summary if hasattr(entry, 'summary') else entry.title
                tr_icerik = ai_cevir(ham_icerik)

                gorsel_html = f"<img src='{gorsel_url}' style='width:100%; border-radius:8px; margin-bottom:15px;' /><br>" if gorsel_url else ""
                kaynak_html = f"<br><p><strong>Kaynak:</strong> <a href='{haber_linki}'>{entry.title}</a></p>"
                
                final_icerik = gorsel_html + tr_icerik + kaynak_html

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
