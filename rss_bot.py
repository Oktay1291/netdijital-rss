import feedparser
import os
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import google.generativeai as genai

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
SENDER_EMAIL = os.environ.get("SENDER_EMAIL") 
SENDER_PASSWORD = os.environ.get("SENDER_PASSWORD") 
BLOGGER_EMAIL = "ktysarikaya.netdijital1291@blogger.com"

genai.configure(api_key=GEMINI_API_KEY)
# En kararlı çalışan güncel model adı
model = genai.GenerativeModel('gemini-3.6-flash')
RSS_FEEDS = [
    "https://techcrunch.com/feed/" # Test için şimdilik ilk beslemeyle başlayalım
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
    
    with smtplib.SMTP_SSL('smtp.gmail.com', 465) as server:
        server.login(SENDER_EMAIL, SENDER_PASSWORD)
        server.send_message(msg)

for feed in RSS_FEEDS:
    if islenen_haber_sayisi >= 1: # Kotaya takılmamak ve test etmek için sadece 1 haber
        break
        
    parsed_feed = feedparser.parse(feed)
    for entry in parsed_feed.entries:
        if islenen_haber_sayisi >= 1:
            break
            
        haber_linki = entry.link
        
        if haber_linki not in yayinlananlar:
            print(f"İşleniyor: {entry.title}")
            
            try:
                prompt = f"Şu İngilizce haberi Türkçe, teknoloji blogum NetDijital için SEO uyumlu ve profesyonel bir dille yeniden yaz. Haberin sonuna 'Kaynak: {entry.title}' şeklinde link ekle. HTML formatında (sadece <h2>, <p>, <strong> etiketleri kullanarak) ver. Haber içeriği: {entry.title} - {entry.summary}"
                response = model.generate_content(prompt)
                turkce_icerik = response.text.replace("```html", "").replace("```", "").strip()
                
                send_email_to_blogger(entry.title, turkce_icerik)
                
                yeni_yayinlanacak_linkler.append(haber_linki)
                yayinlananlar.add(haber_linki)
                islenen_haber_sayisi += 1
                print("Başarıyla Blogger'a gönderildi!")
                
            except Exception as e:
                print(f"Hata oluştu: {e}")

with open(MEMORY_FILE, "a", encoding="utf-8") as f:
    for link in yeni_yayinlanacak_linkler:
        f.write(link + "\n")
