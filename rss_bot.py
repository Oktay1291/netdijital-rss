import os
import re
import html
import json
import time
from urllib.parse import urljoin

import feedparser
import requests
from google import genai
from google.genai import types
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from googleapiclient.discovery import build

# ============================================================
# ORTAM DEĞİŞKENLERİ
# ============================================================
BLOG_ID = os.environ.get("BLOGGER_BLOG_ID")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
BLOGGER_REFRESH_TOKEN = os.environ.get("BLOGGER_REFRESH_TOKEN")
BLOGGER_CLIENT_ID = os.environ.get("BLOGGER_CLIENT_ID")
BLOGGER_CLIENT_SECRET = os.environ.get("BLOGGER_CLIENT_SECRET")

GEMINI_MODEL = "gemini-2.5-flash"
HAFIZA_DOSYASI = "posted_history.json"
MAX_HABER = 1

RSS_SOURCES = [
    {"url": "https://www.engadget.com/rss.xml", "kategori": "Teknoloji"},
    {"url": "https://www.theverge.com/rss/index.xml", "kategori": "Teknoloji"},
    {"url": "https://electrek.co/feed/", "kategori": "Otomobil"},
    {"url": "https://www.androidpolice.com/feed/", "kategori": "Mobil"},
]

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}

# ============================================================
# HAFIZA YÖNETİMİ
# ============================================================
def hafiza_oku():
    if os.path.exists(HAFIZA_DOSYASI):
        try:
            with open(HAFIZA_DOSYASI, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {"linkler": []}

def hafiza_kaydet(hafiza, link):
    hafiza["linkler"].append(link)
    hafiza["linkler"] = hafiza["linkler"][-500:]
    with open(HAFIZA_DOSYASI, "w", encoding="utf-8") as f:
        json.dump(hafiza, f, ensure_ascii=False, indent=2)

# ============================================================
# GÖRSEL BULUCU
# ============================================================
def kaynak_gorsel_bul(haber_url):
    try:
        r = requests.get(haber_url, headers=HEADERS, timeout=15, allow_redirects=True)
        if r.status_code == 200:
            m = re.search(r'<meta[^>]+property=["\']og:image["\'][^>]+content=["\']([^"\']+)["\']', r.text, re.I)
            if m:
                img_url = m.group(1).strip()
                if img_url.startswith("//"):
                    img_url = "https:" + img_url
                return img_url
    except Exception:
        pass
    return None

# ============================================================
# GEMINI İÇERİK ÜRETİCİ
# ============================================================
def haber_yazdir(baslik, ozet, kategori, kaynak_url):
    client = genai.Client(api_key=GEMINI_API_KEY)

    prompt = (
        "Sen deneyimli bir teknoloji haber editörüsün. Aşağıdaki haberi baz alarak "
        "tamamen özgün, profesyonel ve SEO uyumlu bir Türkçe haber oluştur.\n\n"
        f"Başlık: {baslik}\n"
        f"Özet: {ozet}\n"
        f"Kategori: {kategori}\n\n"
        "Kurallar:\n"
        "1. Uzunluk 750-1000 kelime arasında akıcı ve doyurucu olsun.\n"
        "2. Kesinlikle <h1> veya <html>/<body> etiketleri kullanma. Yalnızca <h2>, <h3>, <p>, <ul>, <li>, <strong> kullan.\n"
        "3. En az 4 adet <h2> başlığı ve önemli kısımlarda maddeli listeler barındırsın.\n"
        "4. Çıktıyı SADECE geçerli bir JSON objesi olarak ver.\n\n"
        'JSON Formatı: {"baslik": "SEO Uyumlu Başlık", "icerik": "<h2>Giriş</h2><p>Haber metni...</p>", "etiketler": ["'
        + kategori
        + '", "Teknoloji", "Güncel"]}'
    )

    try:
        response = client.models.generate_content(
            model=GEMINI_MODEL,
            contents=prompt,
            config=types.GenerateContentConfig(
                temperature=0.6,
                response_mime_type="application/json"
            )
        )
        temiz = response.text.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
        return json.loads(temiz)
    except Exception as e:
        print(f"Gemini İçerik Hatası: {e}")
        return None

# ============================================================
# BLOGGER RESMİ BAĞLANTISI
# ============================================================
def blogger_servisi():
    token_adresi = "[https://oauth2.googleapis.com/token](https://oauth2.googleapis.com/token)"
    kapsam = ["[https://www.googleapis.com/auth/blogger](https://www.googleapis.com/auth/blogger)"]

    creds = Credentials(
        token=None,
        refresh_token=BLOGGER_REFRESH_TOKEN,
        token_uri=token_adresi,
        client_id=BLOGGER_CLIENT_ID,
        client_secret=BLOGGER_CLIENT_SECRET,
        scopes=kapsam
    )
    creds.refresh(Request())
    return build("blogger", "v3", credentials=creds, cache_discovery=False)

def blogger_yayinla(service, veri, gorsel_url, kaynak_url):
    img_tag = ""
    if gorsel_url:
        img_tag = f"""<div style="text-align:center; margin-bottom:20px;">
<img src="{html.escape(gorsel_url, quote=True)}" alt="{html.escape(veri['baslik'], quote=True)}" style="width:100%; max-height:480px; object-fit:cover; border-radius:10px;" />
</div>"""

    kaynak_tag = f"""<hr><p style="font-size:13px; color:#777;">
Kaynak: <a href="{html.escape(kaynak_url, quote=True)}" target="_blank" rel="nofollow noopener">Orijinal Haberi Görüntüle</a>
</p>"""

    govde = {
        "title": veri["baslik"],
        "content": f"{img_tag}\n{veri['icerik']}\n{kaynak_tag}",
        "labels": veri.get("etiketler", ["Teknoloji"])
    }

    res = service.posts().insert(blogId=BLOG_ID, body=govde, isDraft=False).execute()
    return res.get("url")

# ============================================================
# ANA ÇALIŞTIRICI
# ============================================================
def main():
    if not all([BLOG_ID, GEMINI_API_KEY, BLOGGER_REFRESH_TOKEN, BLOGGER_CLIENT_ID, BLOGGER_CLIENT_SECRET]):
        print("Eksik Secret / Çevre değişkeni var!")
        return

    try:
        service = blogger_servisi()
    except Exception as e:
        print(f"Blogger Bağlantı Hatası (Token kontrol edin): {e}")
        return

    hafiza = hafiza_oku()
    yayinlandi = False

    for src in RSS_SOURCES:
        if yayinlandi:
            break
        feed = feedparser.parse(src["url"])
        for entry in feed.entries[:5]:
            link = getattr(entry, "link", "")
            baslik = getattr(entry, "title", "")
            ozet = getattr(entry, "summary", "")

            if not link or link in hafiza["linkler"]:
                continue

            print(f"Yeni Haber İşleniyor: {baslik}")
            veri = haber_yazdir(baslik, ozet, src["kategori"], link)
            if not veri or not veri.get("icerik"):
                continue

            gorsel = kaynak_gorsel_bul(link)
            try:
                post_url = blogger_yayinla(service, veri, gorsel, link)
                print(f"Başarıyla Yayına Alındı: {post_url}")
                hafiza_kaydet(hafiza, link)
                yayinlandi = True
                break
            except Exception as e:
                print(f"Yayınlama Hatası: {e}")

if __name__ == "__main__":
    main()
