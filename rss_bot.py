import os
import feedparser
import google.generativeai as genai
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


def generate_seo_article_and_labels(title, summary):
  """Gemini kullanarak haberi 750-1200 kelimelik SEO makalesine dönüştürür

  ve etiket üretir.
  """
  if not GEMINI_API_KEY:
    return (
        f"<p>{summary}</p>",
        ["Teknoloji", "Haber"],
    )  # API anahtarı yoksa yedekler

  allowed_categories = [
      "İNCELEME",
      "TEKNOLOJİ",
      "YAPAY ZEKA",
      "OYUN",
      "APPLE",
      "ANDROID",
      "MOBİL",
      "PC",
      "DONANIM",
      "TELEVİZYON",
      "AKILLI YAŞAM",
      "OTOMOBİL",
  ]

  prompt = f"""
    Aşağıdaki haber başlığını ve özetini temel alarak kapsamlı bir blog makalesi oluştur:
    
    Orijinal Başlık: {title}
    Orijinal Özet: {summary}
    
    Lütfen şu kurallara kesinlikle uy:
    1. İÇERİK UZUNLUĞU: Kesinlikle 750 ile 1200 kelime arasında detaylı, doyurucu ve akıcı bir makale yaz. Konuyu yüzeysel geçme, derinlemesine açıkla.
    2. HTML FORMATI: Makaleyi HTML etiketleri kullanarak biçimlendir (örn: <h2> ve <h3> alt başlıklar, <p> paragraflar, <ul> ve <li> maddeler kullan).
    3. KATEGORİ VE ETİKETLER: Şu ana kategorilerden SADECE BİR TANESİNİ seç ve bunu etiket listesinin ilk elemanı yap: {allowed_categories}
    4. TOPLAM ETİKET: Ana kategori dahil olmak üzere, Google'da en çok aratılacak toplam 10 adet SEO uyumlu etiketi makalenin en sonunda tam olarak şu formatta ver:
    
    [ETIKETLER: Kategori, etiket2, etiket3, ..., etiket10]
    
    Başka hiçbir açıklama yapma, sadece HTML makaleyi ve en alttaki etiket formatını üret.
    """

  try:
    model = genai.GenerativeModel("gemini-1.5-flash")
    response = model.generate_content(prompt)
    text = response.text.strip()

    # Etiketleri ve makale içeriğini birbirinden ayırıyoruz
    if "[ETIKETLER:" in text:
      parts = text.split("[ETIKETLER:")
      article_content = parts[0].strip()
      labels_part = parts[1].replace("]", "").strip()
      labels = [l.strip() for l in labels_part.split(",") if l.strip()]
    else:
      article_content = text
      labels = ["TEKNOLOJİ"]

    return article_content, labels[:10]

  except Exception as e:
    print(f"Gemini makale üretirken hata oluştu: {e}")
    return f"<p>{summary}</p>", ["TEKNOLOJİ"]


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

  # Gemini ile 750-1200 kelimelik makale ve 10 SEO etiketi üretiyoruz
  print("Gemini makaleyi ve etiketleri hazırlıyor...")
  article_html, labels = generate_seo_article_and_labels(title, summary)
  print(f"Seçilen Kategori ve Etiketler: {labels}")

  # Bloga gönderilecek nihai HTML içeriği (Makale + Kaynak Linki)
  content = (
      f"{article_html}<p><br></p><p><a href='{link}' target='_blank'"
      " rel='nofollow'>Haberi Kaynağından Oku</a></p>"
  )

  post_body = {"title": title, "content": content, "labels": labels}

  try:
    # Yazıyı Blogger API üzerinden gönderiyoruz
    request = service.posts().insert(blogId=BLOG_ID, body=post_body)
    response = request.execute()
    print(f"750-1200 kelimelik SEO uyumlu yazı başarıyla yayınlandı! {title}")
  except Exception as e:
    print(f"Yazı yayınlanırken hata oluştu: {e}")


if __name__ == "__main__":
  post_to_blogger()
