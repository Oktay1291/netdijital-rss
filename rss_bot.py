import feedparser
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import os

RSS_URL = "https://www.wired.com/feed/"
BLOGGER_EMAIL = os.environ.get("BLOGGER_EMAIL")
MAIL_PASSWORD = os.environ.get("MAIL_PASSWORD")

def fetch_and_send():
    feed = feedparser.parse(RSS_URL)
    if not feed.entries:
        print("Haber bulunamadı.")
        return

    latest_entry = feed.entries[0]
    title = latest_entry.title
    link = latest_entry.link
    summary = getattr(latest_entry, 'summary', '')

    msg = MIMEMultipart()
    msg['Subject'] = title
    msg['From'] = BLOGGER_EMAIL
    msg['To'] = BLOGGER_EMAIL

    body = f"{summary}<br><br><a href='{link}'>Haberi Kaynağından Oku</a>"
    msg.attach(MIMEText(body, 'html'))

    try:
        server = smtplib.SMTP('smtp.gmail.com', 587)
        server.starttls()
        server.login(BLOGGER_EMAIL, MAIL_PASSWORD)
        server.sendmail(BLOGGER_EMAIL, BLOGGER_EMAIL, msg.as_string())
        server.quit()
        print(f"Başarıyla gönderildi: {title}")
    except Exception as e:
        print(f"Hata oluştu: {e}")

if __name__ == "__main__":
    fetch_and_send()
