import os
import feedparser
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

# GitHub Secrets'tan bilgileri güvenle alıyoruz
CLIENT_ID = os.environ.get("BLOGGER_CLIENT_ID")
CLIENT_SECRET = os.environ.get("BLOGGER_CLIENT_SECRET")
REFRESH_TOKEN = os.environ.get("BLOGGER_REFRESH_TOKEN")
BLOG_ID = os.environ.get("BLOGGER_BLOG_ID")

def post_to_blogger():
    # OAuth 2.0 kimlik bilgilerini oluşturuyoruz
    creds = Credentials(
        token=None,
        refresh_token=REFRESH_TOKEN,
        token_uri="https://oauth2.googleapis.com/token",
        client_id=CLIENT_ID,
        client_secret=CLIENT_SECRET,
        scopes=["https://www.googleapis.com/auth/blogger"]
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

    # Bloga gönderilecek HTML içeriği hazırlıyoruz
    content = f"<p>{summary}</p><p><a href='{link}' target='_blank'>Haberi Kaynağından Oku</a></p>"

    post_body = {
        "title": title,
        "content": content
    }

    try:
        # Yazıyı Blogger API üzerinden bloga gönderiyoruz
        request = service.posts().insert(blogId=BLOG_ID, body=post_body)
        response = request.execute()
        print(f"Yazı başarıyla yayınlandı! Başlık: {title}")
    except Exception as e:
        print(f"Yazı yayınlanırken hata oluştu: {e}")

if __name__ == "__main__":
    post_to_blogger()
