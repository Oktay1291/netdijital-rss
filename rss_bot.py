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

# Kararlı ve kotayı boğmayan model
GEMINI_MODEL = "gemini-2.5-flash"
HAFIZA_DOSYASI = "posted_history.json"
MAX_HABER = 1

# Güvenilir RSS Kaynakları
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
    hafiza["linkler"] = hafiza["linkler"][-500:]  # Son 500 linki tut
    with open(HAFIZA_DOSYASI, "w", encoding="utf-8") as f:
        json.dump(hafiza, f, ensure_ascii=False, indent=2)

# ============================================================
# GÖRSEL TEMİNİ (OG:IMAGE - TELİF VE API SORUNSUZ)
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
# GEMINI İÇERİK ÜRETİCİSİ (KOTA DOSTU VE SAĞLAM JSON)
# ============================================================
def haber_yazdir(baslik, ozet, kategori, kaynak_url):
    client = genai.Client(api_key=GEMINI_API_KEY)
    
    prompt = f"""Sen deneyimli bir teknoloji haber editörüsün. Aşağıdaki haberi baz alarak tamamen özgün, profesyonel ve SEO uyumlu bir Türkçe haber oluştur.

Başlık: {baslik}
Özet: {ozet}
Kategori: {kategori}

Kurallar:
1. Uzunluk 750-1000 kelime arasında akıcı ve doyurucu olsun.
2. Kesinlikle <h1> veya <html>/<body> etiketleri kullanma. Yalnızca <h2>, <h3>, <p>, <ul>, <li>, <strong> kullan.
3. En az 4 adet <h2> başlığı ve önemli kısımlarda maddeli listeler barındırsın.
4. Çıktıyı SADECE geçerli bir JSON objesi olarak ver.

JSON Formatı:
{{
  "baslik": "SEO Uyumlu Çarpıcı Başlık",
  "icerik": "<h2>Giriş</h2><p>Haber metni...</p>",
  "etiketler": ["{kategori}", "Teknoloji", "Güncel", "Haber"]
}}"""

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
        data = json.loads(temiz)
        return data
    except Exception as e:
        print(f"Gemini İçerik Hatası: {e}")
        return None

# ============================================================
# BLOGGER RESMİ BAĞLANTISI (403 VE TOKEN HATASINI BİTİRİR)
# ============================================================
def blogger_servisi():
    creds = Credentials(
        token=None,
        refresh_token=BLOGGER_REFRESH_TOKEN,
        token_uri="[https://oauth2.googleapis.com/token](https://oauth2.googleapis.com/token)",
        client_id=BLOGGER_CLIENT_ID,
        client_secret=BLOGGER_CLIENT_SECRET,
        scopes=["[https://www.googleapis.com/auth/blogger](https://www.googleapis.com/auth/blogger)"]
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

    # isDraft=False -> Doğrudan SİTEDE YAYINLAR!
    res = service.posts().insert(blogId=BLOG_ID, body=govde, isDraft=False).execute()
    return res.get("url")

# ============================================================
# ÇALIŞTIRICI
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
