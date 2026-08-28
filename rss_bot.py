import os
import re
import html
import time
import feedparser
import requests

from urllib.parse import urljoin
from google import genai
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from googleapiclient.discovery import build


# ============================================================
# AYARLAR
# ============================================================

BLOG_ID = os.environ.get("BLOGGER_BLOG_ID")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
REFRESH_TOKEN = os.environ.get("BLOGGER_REFRESH_TOKEN")
CLIENT_ID = os.environ.get("BLOGGER_CLIENT_ID")
CLIENT_SECRET = os.environ.get("BLOGGER_CLIENT_SECRET")

# Bir çalıştırmada kaç haber yayınlansın?
MAX_HABER = 3

# Aynı haberleri tekrar yayınlamamak için
HAFIZA_DOSYASI = "yayinlanan_haberler.txt"

# Gemini modeli
GEMINI_MODEL = "gemini-3.6-flash"

# Haberler arasında bekleme
BEKLEME_SURESI = 15


# ============================================================
# RSS KAYNAKLARI (20 ADET GLOBAL YABANCI SİTE)
# ============================================================

RSS_SOURCES = [
    {
        "url": "https://techcrunch.com/feed/",
        "kaynak": "TechCrunch"
    },
    {
        "url": "https://www.theverge.com/rss/index.xml",
        "kaynak": "The Verge"
    },
    {
        "url": "https://www.engadget.com/rss.xml",
        "kaynak": "Engadget"
    },
    {
        "url": "https://feeds.arstechnica.com/arstechnica/index",
        "kaynak": "Ars Technica"
    },
    {
        "url": "https://www.wired.com/feed/rss",
        "kaynak": "Wired"
    },
    {
        "url": "https://thenextweb.com/feed",
        "kaynak": "The Next Web"
    },
    {
        "url": "https://www.digitaltrends.com/feed/",
        "kaynak": "Digital Trends"
    },
    {
        "url": "https://gizmodo.com/feed",
        "kaynak": "Gizmodo"
    },
    {
        "url": "https://electrek.co/feed/",
        "kaynak": "Electrek"
    },
    {
        "url": "https://www.androidpolice.com/feed/",
        "kaynak": "Android Police"
    },
    {
        "url": "https://bgr.com/feed/",
        "kaynak": "BGR"
    },
    {
        "url": "https://www.tomshardware.com/rss.xml",
        "kaynak": "Tom's Hardware"
    },
    {
        "url": "https://www.anandtech.com/rss/",
        "kaynak": "AnandTech"
    },
    {
        "url": "https://readwrite.com/feed/",
        "kaynak": "ReadWrite"
    }
]


# ============================================================
# HTTP AYARLARI
# ============================================================

HEADERS = {
    "User-Agent":
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 "
        "(KHTML, like Gecko) "
        "Chrome/151.0 Safari/537.36",
    "Accept-Language":
        "en-US,en;q=0.9"
}


# ============================================================
# ORTAM DEĞİŞKENLERİNİ KONTROL
# ============================================================

def ayarlari_kontrol_et():
    eksikler = []

    if not BLOG_ID:
        eksikler.append("BLOGGER_BLOG_ID")
    if not GEMINI_API_KEY:
        eksikler.append("GEMINI_API_KEY")
    if not REFRESH_TOKEN:
        eksikler.append("BLOGGER_REFRESH_TOKEN")
    if not CLIENT_ID:
        eksikler.append("BLOGGER_CLIENT_ID")
    if not CLIENT_SECRET:
        eksikler.append("BLOGGER_CLIENT_SECRET")

    if eksikler:
        print()
        print("=" * 70)
        print("❌ EKSİK ORTAM DEĞİŞKENLERİ")
        print("=" * 70)
        for item in eksikler:
            print("❌", item)
        print()
        return False

    print("✅ Gerekli ortam değişkenleri bulundu.")
    return True


# ============================================================
# BAŞLIK TEMİZLE
# ============================================================

def baslik_temizle(baslik):
    if not baslik:
        return ""
    baslik = html.unescape(baslik)
    if " - " in baslik:
        baslik = baslik.rsplit(" - ", 1)[0]
    baslik = re.sub(r"\s+", " ", baslik)
    return baslik.strip()


# ============================================================
# ÖZET TEMİZLE
# ============================================================

def ozet_temizle(ozet):
    if not ozet:
        return ""
    ozet = html.unescape(ozet)
    ozet = re.sub(r"<script.*?</script>", " ", ozet, flags=re.I | re.S)
    ozet = re.sub(r"<style.*?</style>", " ", ozet, flags=re.I | re.S)
    ozet = re.sub(r"<[^>]+>", " ", ozet)
    ozet = re.sub(r"\s+", " ", ozet)
    return ozet.strip()


# ============================================================
# URL TEMİZLE
# ============================================================

def url_temizle(url, temel_url=None):
    if not url:
        return None
    url = html.unescape(url.strip())
    url = url.replace("\\/", "/")
    url = url.replace("\\u002F", "/")
    if url.startswith("//"):
        url = "https:" + url
    elif url.startswith("/") and temel_url:
        url = urljoin(temel_url, url)
    if not url.startswith("http"):
        return None
    return url


# ============================================================
# GÖRSEL URL Mİ?
# ============================================================

def gorsel_url_mu(url):
    if not url:
        return False
    url = url.lower().split("?")[0]
    uzantilar = [".jpg", ".jpeg", ".png", ".webp", ".gif"]
    return any(url.endswith(uzanti) for uzanti in uzantilar)


# ============================================================
# GÖRSEL ÇALIŞIYOR MU?
# ============================================================

def gorsel_kontrol(url):
    try:
        print()
        print("🖼️ Görsel kontrol ediliyor:")
        print(url)

        cevap = requests.get(
            url,
            headers=HEADERS,
            timeout=20,
            allow_redirects=True
        )

        content_type = cevap.headers.get("Content-Type", "").lower()

        print("   HTTP:", cevap.status_code)
        print("   Tür:", content_type)

        if cevap.status_code != 200:
            print("   ❌ Görsel açılmadı.")
            return False

        if "image" not in content_type:
            print("   ❌ Bu URL görsel değil.")
            return False

        if len(cevap.content) < 5000:
            print("   ❌ Görsel dosyası çok küçük.")
            return False

        print("   ✅ Görsel kullanılabilir.")
        return True

    except Exception as hata:
        print("   ❌ Görsel kontrol hatası:", hata)
        return False


# ============================================================
# RSS İÇİNDEN GÖRSEL BUL
# ============================================================

def rss_gorseli_bul(entry):
    try:
        medya = getattr(entry, "media_content", [])
        for item in medya:
            url = item.get("url")
            url = url_temizle(url)
            if url:
                print("✅ RSS media_content görseli bulundu.")
                return url
    except Exception:
        pass

    try:
        medya = getattr(entry, "media_thumbnail", [])
        for item in medya:
            url = item.get("url")
            url = url_temizle(url)
            if url:
                print("✅ RSS thumbnail bulundu.")
                return url
    except Exception:
        pass

    try:
        enclosures = getattr(entry, "enclosures", [])
        for item in enclosures:
            url = item.get("href") or item.get("url")
            url = url_temizle(url)
            content_type = item.get("type", "").lower()
            if url and ("image" in content_type or gorsel_url_mu(url)):
                print("✅ RSS enclosure görseli bulundu.")
                return url
    except Exception:
        pass

    try:
        summary = getattr(entry, "summary", "")
        matches = re.findall(r'<img[^>]+(?:src|data-src)=["\']([^"\']+)', summary, re.I)
        for url in matches:
            url = url_temizle(url)
            if url:
                print("✅ RSS HTML görseli bulundu.")
                return url
    except Exception:
        pass

    return None


# ============================================================
# KAYNAK HABER SAYFASINDAN OG:IMAGE BUL
# ============================================================

def kaynak_gorseli_bul(haber_url):
    try:
        if not haber_url:
            return None

        print()
        print("🔎 Kaynak haber açılıyor...")
        print(haber_url)

        cevap = requests.get(
            haber_url,
            headers=HEADERS,
            timeout=30,
            allow_redirects=True
        )

        print("🌐 Son URL:", cevap.url)
        print("🌐 HTTP:", cevap.status_code)

        if cevap.status_code != 200:
            return None

        sayfa = cevap.text
        temel_url = cevap.url

        patterns = [
            r'<meta[^>]+property=["\']og:image["\'][^>]+content=["\']([^"\']+)',
            r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+property=["\']og:image["\']',
            r'<meta[^>]+property=["\']og:image:url["\'][^>]+content=["\']([^"\']+)',
            r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+property=["\']og:image:url["\']',
            r'<meta[^>]+name=["\']twitter:image["\'][^>]+content=["\']([^"\']+)',
            r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+name=["\']twitter:image["\']'
        ]

        for pattern in patterns:
            matches = re.findall(pattern, sayfa, re.I)
            for url in matches:
                url = url_temizle(url, temel_url)
                if url:
                    print()
                    print("🎯 ORİJİNAL HABER GÖRSELİ BULUNDU:")
                    print(url)
                    return url

    except Exception as hata:
        print("❌ Kaynak görsel hatası:", hata)

    print("⚠️ Kaynak sayfada og:image bulunamadı.")
    return None


# ============================================================
# DUCKDUCKGO GÖRSEL ARAMA
# ============================================================

def duckduckgo_gorsel_bul(sorgu):
    try:
        print()
        print("🦆 DuckDuckGo görsel aranıyor...")
        cevap = requests.get(
            "https://duckduckgo.com/",
            params={"q": sorgu},
            headers=HEADERS,
            timeout=20
        )
        if cevap.status_code != 200:
            return None

        sayfa = cevap.text
        vqd = None
        patterns = [
            r'vqd=([\d-]+)',
            r'vqd["\']?\s*[:=]\s*["\']([^"\']+)',
            r'vqd["\']\s*:\s*["\']([^"\']+)'
        ]

        for pattern in patterns:
            match = re.search(pattern, sayfa)
            if match:
                vqd = match.group(1)
                break

        if not vqd:
            return None

        headers = HEADERS.copy()
        headers["Referer"] = "https://duckduckgo.com/"

        sonuc = requests.get(
            "https://duckduckgo.com/i.js",
            params={
                "l": "en-us",
                "o": "json",
                "q": sorgu,
                "vqd": vqd,
                "f": ",,,",
                "p": "1"
            },
            headers=headers,
            timeout=30
        )

        if sonuc.status_code != 200:
            return None

        veri = sonuc.json()
        for item in veri.get("results", [])[:10]:
            image_url = item.get("image") or item.get("thumbnail")
            image_url = url_temizle(image_url)
            if not image_url:
                continue
            if gorsel_kontrol(image_url):
                print("🎯 DuckDuckGo görseli bulundu!")
                return image_url

    except Exception as hata:
        print("❌ DuckDuckGo hatası:", hata)

    return None


# ============================================================
# YANDEX GÖRSEL ARAMA
# ============================================================

def yandex_gorsel_bul(sorgu):
    try:
        print()
        print("🔴 Yandex görsel aranıyor...")
        cevap = requests.get(
            "https://yandex.com/images/search",
            params={"text": sorgu},
            headers=HEADERS,
            timeout=30
        )
        if cevap.status_code != 200:
            return None

        sayfa = cevap.text
        patterns = [
            r'"origUrl":"(https?://[^"]+)"',
            r'"img_href":"(https?://[^"]+)"',
            r'"imageUrl":"(https?://[^"]+)"',
            r'"url":"(https?://[^"]+\.(?:jpg|jpeg|png|webp)[^"]*)'
        ]

        bulunanlar = []
        for pattern in patterns:
            matches = re.findall(pattern, sayfa, re.I)
            for url in matches:
                url = url_temizle(url)
                if url and url not in bulunanlar:
                    bulunanlar.append(url)

        for image_url in bulunanlar[:15]:
            if gorsel_kontrol(image_url):
                print("🎯 Yandex görseli bulundu!")
                return image_url

    except Exception as hata:
        print("❌ Yandex hatası:", hata)

    return None


# ============================================================
# HABER GÖRSELİ BULMA MOTORU
# ============================================================

def haber_gorseli_bul(entry, baslik):
    print()
    print("=" * 70)
    print("🖼️ HABER GÖRSELİ ARANIYOR")
    print("=" * 70)

    print("1️⃣ RSS görseli kontrol ediliyor...")
    gorsel = rss_gorseli_bul(entry)
    if gorsel and gorsel_kontrol(gorsel):
        return gorsel

    print()
    print("2️⃣ Kaynak haberin gerçek görseli aranıyor...")
    haber_url = getattr(entry, "link", "")
    gorsel = kaynak_gorseli_bul(haber_url)
    if gorsel and gorsel_kontrol(gorsel):
        return gorsel

    print()
    print("3️⃣ DuckDuckGo deneniyor...")
    gorsel = duckduckgo_gorsel_bul(baslik)
    if gorsel:
        return gorsel

    print()
    print("4️⃣ Yandex deneniyor...")
    gorsel = yandex_gorsel_bul(baslik)
    if gorsel:
        return gorsel

    print()
    print("❌ HABER İÇİN UYGUN GÖRSEL BULUNAMADI.")
    return None


# ============================================================
# GEMINI İLE HABER ÜRET
# ============================================================

def generate_seo_article_and_labels(title, summary, kategori):
    if not GEMINI_API_KEY:
        return f"<p>{summary}</p>", [kategori, "Technology"]

    allowed_categories = [
        "Artificial Intelligence",
        "Mobile",
        "Hardware",
        "Technology",
        "Gaming",
        "Smart Home",
        "Science & Space",
        "Cinema",
        "Automotive"
    ]

    prompt = f"""
You are an experienced technology news editor. Translate and rewrite the following global tech news article into fluent, professional Turkish.

SOURCE TITLE:
{title}

SOURCE SUMMARY:
{summary}

CATEGORY:
{kategori}

RULES:
1. Write an original, engaging news article in Turkish (between 750 and 1200 words).
2. Do not fabricate facts, dates, or numbers not present in the source.
3. Format the text in HTML.
4. Use <h2> and <h3> tags for subheadings.
5. Use <p> tags for paragraphs.
6. Use <strong> for key highlights.
7. Select ONLY ONE category from this list: {allowed_categories}
8. Create 10 SEO tags in Turkish. First tag must be the selected category.

OUTPUT FORMAT:
First line:
[BAŞLIK: Özgün Türkçe Başlık]

Then:
HTML article body

Finally:
[ETİKETLER: kategori, etiket2, etiket3, etiket4, etiket5, etiket6, etiket7, etiket8, etiket9, etiket10]

Do not write any extra explanations.
"""

    try:
        print()
        print("🤖 Gemini haber oluşturuyor...")

        client = genai.Client(api_key=GEMINI_API_KEY)
        response = client.models.generate_content(
            model=GEMINI_MODEL,
            contents=prompt
        )

        text = response.text.strip()

        baslik_match = re.search(r"\[BAŞLIK:\s*(.*?)\]", text, re.I | re.S)
        if baslik_match:
            yeni_baslik = baslik_match.group(1).strip()
            text = re.sub(r"\[BAŞLIK:\s*.*?\]", "", text, count=1, flags=re.I | re.S)
        else:
            yeni_baslik = title

        labels_match = re.search(r"\[ETİKETLER:\s*(.*?)\]", text, re.I | re.S)
        if labels_match:
            labels_part = labels_match.group(1).strip()
            labels = [x.strip() for x in labels_part.split(",") if x.strip()]
            text = re.sub(r"\[ETİKETLER:\s*.*?\]", "", text, count=1, flags=re.I | re.S)
        else:
            labels = [kategori, "Teknoloji", "Haber"]

        labels = labels[:10]
        article_html = text.strip()
        article_html = re.sub(r"^```html", "", article_html, flags=re.I)
        article_html = re.sub(r"```$", "", article_html)
        article_html = article_html.strip()

        print("✅ Gemini haber oluşturdu.")
        print("📰 Yeni başlık:", yeni_baslik)
        print("🏷️ Etiketler:", labels)

        return yeni_baslik, article_html, labels

    except Exception as hata:
        print()
        print("❌ GEMINI HATASI:", hata)
        return None


# ============================================================
# BLOGGER KİMLİK DOĞRULAMA
# ============================================================

def blogger_service_olustur():
    try:
        print()
        print("🔐 Blogger kimlik doğrulaması başlıyor...")

        creds = Credentials(
            token=None,
            refresh_token=REFRESH_TOKEN,
            token_uri="https://oauth2.googleapis.com/token",
            client_id=CLIENT_ID,
            client_secret=CLIENT_SECRET,
            scopes=["https://www.googleapis.com/auth/blogger"]
        )

        auth_request = Request()
        creds.refresh(auth_request)

        print("✅ Blogger OAuth başarılı.")

        service = build(
            "blogger",
            "v3",
            credentials=creds,
            cache_discovery=False
        )

        print("🔎 Blogger blog erişimi test ediliyor...")
        blog = service.blogs().get(blogId=BLOG_ID).execute()
        print("✅ Blog bulundu:", blog.get("name", "İsimsiz blog"))

        return service

    except Exception as hata:
        print()
        print("=" * 70)
        print("❌ BLOGGER KİMLİK / YETKİ HATASI")
        print("=" * 70)
        print(hata)
        print()
        return None


# ============================================================
# HAFIZA İŞLEMLERİ
# ============================================================

def hafiza_oku():
    if not os.path.exists(HAFIZA_DOSYASI):
        return set()
    try:
        with open(HAFIZA_DOSYASI, "r", encoding="utf-8") as dosya:
            return set(satir.strip() for satir in dosya if satir.strip())
    except Exception as hata:
        print("⚠️ Hafıza okunamadı:", hata)
        return set()


def hafizaya_kaydet(link):
    try:
        with open(HAFIZA_DOSYASI, "a", encoding="utf-8") as dosya:
            dosya.write(link + "\n")
    except Exception as hata:
        print("⚠️ Hafıza kaydedilemedi:", hata)


# ============================================================
# BLOGGER'A HABER GÖNDER
# ============================================================

def blogger_a_gonder(service, title, article_html, labels, image_url, source_url):
    try:
        title_safe = html.escape(title)
        image_html = f"""
<div style="text-align:center; margin:0 0 25px 0;">
<img src="{html.escape(image_url, quote=True)}" alt="{title_safe}" title="{title_safe}" style="width:100%; max-width:1200px; height:auto; display:block; margin:0 auto; border-radius:12px;" />
</div>
"""

        source_html = f"""
<hr>
<p style="font-size:14px; color:#666;">
Source: <a href="{html.escape(source_url, quote=True)}" target="_blank" rel="nofollow noopener">Read original article</a>
</p>
"""

        content = image_html + "\n" + article_html + "\n" + source_html
        post_body = {
            "title": title,
            "content": content,
            "labels": labels
        }

        print()
        print("📤 Blogger'a gönderiliyor...")

        response = service.posts().insert(
            blogId=BLOG_ID,
            body=post_body
        ).execute()

        post_url = response.get("url", "")

        print()
        print("🎉 HABER BAŞARIYLA YAYINLANDI!")
        print("📰", title)
        print("🔗", post_url)

        return post_url

    except Exception as hata:
        print()
        print("❌ BLOGGER YAYINLAMA HATASI:", hata)
        return None


# ============================================================
# RSS'TEN HABERLERİ TOPLA
# ============================================================

def rss_haberlerini_getir():
    haberler = []
    for source in RSS_SOURCES:
        try:
            print()
            print("📡 RSS kontrol ediliyor:", source["url"])
            feed = feedparser.parse(source["url"])

            if not feed.entries:
                print("⚠️ Haber bulunamadı.")
                continue

            for entry in feed.entries[:5]:
                haberler.append({
                    "entry": entry,
                    "kategori": source["kaynak"],
                    "rss": source["url"]
                })
        except Exception as hata:
            print("❌ RSS hatası:", hata)

    return haberler


# ============================================================
# ANA PROGRAM
# ============================================================

def main():
    print()
    print("=" * 70)
    print("🚀 OTOMATİK GLOBAL BLOGGER HABER SİSTEMİ")
    print("=" * 70)

    if not ayarlari_kontrol_et():
        return

    print()
    print("🤖 Gemini modeli:", GEMINI_MODEL)

    service = blogger_service_olustur()
    if not service:
        return

    yayinlananlar = hafiza_oku()
    print()
    print("📚 Daha önce yayınlanan:", len(yayinlananlar))

    haberler = rss_haberlerini_getir()
    if not haberler:
        print("❌ Hiç haber bulunamadı.")
        return

    print()
    print("📰 Toplam aday haber:", len(haberler))

    yayinlanan_sayi = 0

    for haber in haberler:
        if yayinlanan_sayi >= MAX_HABER:
            break

        entry = haber["entry"]
        kategori = haber["kategori"]

        source_url = getattr(entry, "link", "")
        if not source_url:
            continue

        if source_url in yayinlananlar:
            print()
            print("⏭️ Bu haber daha önce yayınlanmış.")
            continue

        original_title = baslik_temizle(getattr(entry, "title", ""))
        if not original_title:
            continue

        summary = ozet_temizle(getattr(entry, "summary", ""))

        print()
        print("=" * 70)
        print("📰 YENİ HABER:", original_title)
        print("📂 Kaynak:", kategori)
        print("=" * 70)

        image_url = haber_gorseli_bul(entry, original_title)
        if not image_url:
            print("⏭️ Görsel bulunamadı, atlanıyor.")
            continue

        sonuc = generate_seo_article_and_labels(original_title, summary, kategori)
        if not sonuc:
            print("⏭️ Gemini haber oluşturamadı.")
            continue

        new_title = sonuc[0]
        article_html = sonuc[1]
        labels = sonuc[2]

        post_url = blogger_a_gonder(
            service,
            new_title,
            article_html,
            labels,
            image_url,
            source_url
        )

        if not post_url:
            print("❌ Blogger yayınlamadı.")
            continue

        hafizaya_kaydet(source_url)
        yayinlananlar.add(source_url)
        yayinlanan_sayi += 1

        print()
        print(f"✅ {yayinlanan_sayi}/{MAX_HABER} haber yayınlandı.")

        if yayinlanan_sayi < MAX_HABER:
            print()
            print(f"⏳ {BEKLEME_SURESI} saniye bekleniyor...")
            time.sleep(BEKLEME_SURESI)

    print()
    print("=" * 70)
    print("🏁 İŞLEM TAMAMLANDI")
    print("=" * 70)
    print("📢 Yayınlanan haber:", yayinlanan_sayi)
    print()


if __name__ == "__main__":
    main()
