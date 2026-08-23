import os
import google.generativeai as genai
import feedparser
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

# GitHub Secrets'tan bilgileri güvenle alıyoruz
CLIENT_ID = os.environ.get("BLOGGER_CLIENT_ID")
CLIENT_SECRET = os.environ.get("BLOGGER_CLIENT_SECRET")
REFRESH_TOKEN = os.environ.get("BLOGGER_REFRESH_TOKEN")
BLOG_ID = os.environ.get("BLOGGER_BLOG_ID")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")

# Gemini API'yi yapılandırıyoruz
if GEMINI_API_KEY:
  genai.configure(api_key=GEMINI_API_KEY)


def generate_labels_with_gemini(title, summary):
  """Gemini kullanarak haber için uygun ana kategori ve 10 SEO etiketi üretir."""
  if not GEMINI_API_KEY:
    return ["Teknoloji", "Haber"]  # API anahtarı yoksa yedek etiketler

  allowed_categories = [
      "İnceleme",
      "Teknoloji",
      "Yapay Zeka",
      "Oyun",
      "Apple",
      "Android",
      "Mobil",
      "PC",
      "Donanım",
      "Televizyon",
      "Akıllı Yaşam",
      "Otomobil",
  ]

  prompt = f"""
    Aşağıdaki habere göre bir analiz yap:
    1. Şu ana kategorilerden SADECE BİR TANESİNİ seç: {allowed_categories}
    2. Bu haber için Google'da en çok aratılacak/SEO uyumlu, aralarından ana kategorinin de bulunduğu TOPLAM 10 ADET etiket (kelime veya kısa kelime grubu) belirle.
    
    Haber Başlığı: {title}
    Haber Özeti: {summary}
    
    Lütfen yanıtı sadece aralarında virgül olacak şekilde 10 adet etiket olarak ver. İlk etiket kesinlikle seçtiğin ana kategori olsun. Başka hiçbir açıklama yazma.
    Örnek format: Teknoloji, yapay zeka, telefon özellikleri, fiyatı, inceleme, ...
    """

  try:
    model = genai.GenerativeModel("gemini-1.5-flash")
    response = model.generate_content(prompt)
    labels_text = response.text.strip()
    # Virgülle ayrılmış etiketleri listeye çeviriyoruz ve boşlukları temizliyoruz
    labels = [label.strip() for label in labels_text.split(",") if label.strip()]
    return labels[:10]  # Garanti olması için ilk 10 etiketi alıyoruz
  except Exception as e:
    print(f"Gemini etiket üretirken hata oluştu: {e}")
    return ["Teknoloji"]


def post_to_blogger():
  # OAuth 2.0 kimlik bilgilerini oluşturuyoruz
  creds = Credentials(
      token=None,
      refresh_token=REFRESH_TOKEN,
      token_uri="https://oauth2.googleapis.com/token",
      client_id=CLIENT_ID,
      client_secret=CLIENT_SECRET,
      scopes=["https://www.googleapis.com/auth/blogger"],
  )

  # Blogger API servisini başlatıyoruz
  service = build("blogger", "v3", credentials=creds)

  # TechCrunch RSS beslemesinden son yazıyı çekiyoruz
  rss_url = "https://techcrunch.com/feed/"
  feed = feedparser.parse(rss_url)

  if not feed.entries:
    print("RSS beslemesinden yazı bulunamadı.")
    return

  latest_entry = feed.entries[0]
  title = latest_entry.title
  link = latest_entry.link
  summary = latest_entry.get("summary", "")

  # Gemini ile ana kategori dahil 10 SEO etiketi üretiyoruz
  labels = generate_labels_with_gemini(title, summary)
  print(f"Seçilen Kategori ve Etiketler: {labels}")

  # Bloga gönderilecek HTML içeriği hazırlıyoruz
  content = f"<p>{summary}</p><p><a href='{link}' target='_blank'>Haberi Kaynağından Oku</a></p>"

  post_body = {"title": title, "content": content, "labels": labels}

  try:
    # Yazıyı Blogger API üzerinden etiketleriyle birlikte gönderiyoruz
    request = service.posts().insert(blogId=BLOG_ID, body=post_body)
    response = request.execute()
    print(f"Yazı başarıyla yayınlandı! Başlık: {title}")
  except Exception as e:
    print(f"Yazı yayınlanırken hata oluştu: {e}")


if __name__ == "__main__":
  post_to_blogger()
