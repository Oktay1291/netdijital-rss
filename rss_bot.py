import feedparser
import os
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import google.generativeai as genai

# --- GÜVENLİK VE AYARLAR ---
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
SENDER_EMAIL = os.environ.get("SENDER_EMAIL") 
SENDER_PASSWORD = os.environ.get("SENDER_PASSWORD") 
BLOGGER_EMAIL = "ktysarikaya.netdijital1291@blogger.com" # Blogger yayın adresi

genai.configure(api_key=GEMINI_API_KEY)
model = genai.GenerativeModel('gemini-flash')

# --- 20 ADET GLOBAL KAYNAK ---
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
    "https://www.eurogamer.net/feed",                
    "https://feeds.arstechnica.com/arstechnica/index", 
    "https://www.polygon.com/rss/index.xml",         
    "https://www.ign.com/rss/articles/feed"          
]

MEMORY_FILE = "yayinlanan_haberler.txt"

# --- HAFIZA KONTROLÜ (Daha önce yayınlananları oku) ---
yayinlananlar = set()
if os.path.exists(MEMORY_FILE):
    with open(MEMORY_FILE, "r", encoding="utf-8") as f:
        yayinlananlar = set(f.read().splitlines())

islenen_haber_sayisi = 0
yeni_yayinlanacak_linkler = []

# --- MAİL GÖNDERME FONKSİYONU ---
def send_email_to_blogger(title, content):
    msg = MIMEMultipart()
    msg['From'] = SENDER_EMAIL
    msg['To'] = BLOGGER_EMAIL
    msg['Subject'] = title
    
    msg.attach(MIMEText(content, 'html', 'utf-8'))
    
    with smtplib.SMTP_SSL('smtp.gmail.com', 465) as server:
        server.login(SENDER_EMAIL, SENDER_PASSWORD)
        server.send_message(msg)

# --- HABER TARAMA VE İŞLEME ---
for feed in RSS_FEEDS:
    if islenen_haber_sayisi >= 2:
        break # 2 habere ulaştıysak taramayı durdur
        
    parsed_feed = feedparser.parse(feed)
    for entry in parsed_feed.entries:
        if islenen_haber_sayisi >= 2:
            break
            
        haber_linki = entry.link
        
        # Eğer haber daha önce yayınlanmadıysa
        if haber_linki not in yayinlananlar:
            print(f"Yeni Haber Bulundu ve İşleniyor: {entry.title}")
            
            try:
                # 1. Gemini ile Çeviri ve Özgünleştirme
                prompt = f"Şu İngilizce haberi Türkçe, teknoloji blogum NetDijital için SEO uyumlu ve profesyonel bir dille yeniden yaz. Haberin sonuna 'Kaynak: {entry.title}' şeklinde link ekle. HTML formatında (sadece <h2>, <p>, <strong> etiketleri kullanarak) ver. Haber içeriği: {entry.title} - {entry.summary}"
                response = model.generate_content(prompt)
                turkce_icerik = response.text.replace("```html", "").replace("```", "").strip()
                
                # 2. Blogger'a Gönder
                send_email_to_blogger(entry.title, turkce_icerik)
                
                # 3. Hafızaya Ekle
                yeni_yayinlanacak_linkler.append(haber_linki)
                yayinlananlar.add(haber_linki)
                islenen_haber_sayisi += 1
                print("Başarıyla gönderildi!")
                
            except Exception as e:
                print(f"Hata oluştu: {e}")

# --- YENİ HABERLERİ HAFIZAYA YAZ ---
with open(MEMORY_FILE, "a", encoding="utf-8") as f:
    for link in yeni_yayinlanacak_linkler:
        f.write(link + "\n")
