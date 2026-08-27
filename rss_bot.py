import os
import re
import html
import time
import feedparser
import requests

from urllib.parse import urljoin

from google import genaigemini-1.5-flash

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
GEMINI_MODEL = "gemini-2.5-flash"


# Haberler arasında bekleme
BEKLEME_SURESI = 15


# ============================================================
# RSS KAYNAKLARI
# ============================================================

RSS_SOURCES = [

    {
        "url":
        "https://news.google.com/rss/search?q=teknoloji&hl=tr&gl=TR&ceid=TR:tr",

        "kaynak":
        "Teknoloji"
    },

    {
        "url":
        "https://news.google.com/rss/search?q=yapay+zeka&hl=tr&gl=TR&ceid=TR:tr",

        "kaynak":
        "Yapay Zeka"
    },

    {
        "url":
        "https://news.google.com/rss/search?q=telefon&hl=tr&gl=TR&ceid=TR:tr",

        "kaynak":
        "Telefon"
    },

    {
        "url":
        "https://news.google.com/rss/search?q=bilgisayar&hl=tr&gl=TR&ceid=TR:tr",

        "kaynak":
        "Bilgisayar"
    },

    {
        "url":
        "https://news.google.com/rss/search?q=oyun&hl=tr&gl=TR&ceid=TR:tr",

        "kaynak":
        "Oyun"
    },

    {
        "url":
        "https://news.google.com/rss/search?q=otomobil+teknoloji&hl=tr&gl=TR&ceid=TR:tr",

        "kaynak":
        "Otomobil"
    },

    {
        "url":
        "https://techcrunch.com/feed/",

        "kaynak":
        "Teknoloji"
    },

    {
        "url":
        "https://www.theverge.com/rss/index.xml",

        "kaynak":
        "Teknoloji"
    },

    {
        "url":
        "https://www.engadget.com/rss.xml",

        "kaynak":
        "Teknoloji"
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
        "tr-TR,tr;q=0.9,en-US;q=0.8,en;q=0.7"
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

        baslik = baslik.rsplit(
            " - ",
            1
        )[0]

    baslik = re.sub(
        r"\s+",
        " ",
        baslik
    )

    return baslik.strip()


# ============================================================
# ÖZET TEMİZLE
# ============================================================

def ozet_temizle(ozet):

    if not ozet:
        return ""

    ozet = html.unescape(ozet)

    ozet = re.sub(
        r"<script.*?</script>",
        " ",
        ozet,
        flags=re.I | re.S
    )

    ozet = re.sub(
        r"<style.*?</style>",
        " ",
        ozet,
        flags=re.I | re.S
    )

    ozet = re.sub(
        r"<[^>]+>",
        " ",
        ozet
    )

    ozet = re.sub(
        r"\s+",
        " ",
        ozet
    )

    return ozet.strip()


# ============================================================
# URL TEMİZLE
# ============================================================

def url_temizle(url, temel_url=None):

    if not url:
        return None

    url = html.unescape(
        url.strip()
    )

    url = url.replace(
        "\\/",
        "/"
    )

    url = url.replace(
        "\\u002F",
        "/"
    )

    if url.startswith("//"):

        url = "https:" + url

    elif url.startswith("/") and temel_url:

        url = urljoin(
            temel_url,
            url
        )

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

    uzantilar = [
        ".jpg",
        ".jpeg",
        ".png",
        ".webp",
        ".gif"
    ]

    return any(
        url.endswith(
            uzanti
        )
        for uzanti in uzantilar
    )


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


        content_type = cevap.headers.get(
            "Content-Type",
            ""
        ).lower()


        print(
            "   HTTP:",
            cevap.status_code
        )

        print(
            "   Tür:",
            content_type
        )


        if cevap.status_code != 200:

            print(
                "   ❌ Görsel açılmadı."
            )

            return False


        if "image" not in content_type:

            print(
                "   ❌ Bu URL görsel değil."
            )

            return False


        if len(cevap.content) < 5000:

            print(
                "   ❌ Görsel dosyası çok küçük."
            )

            return False


        print(
            "   ✅ Görsel kullanılabilir."
        )

        return True


    except Exception as hata:

        print(
            "   ❌ Görsel kontrol hatası:",
            hata
        )

        return False


# ============================================================
# RSS İÇİNDEN GÖRSEL BUL
# ============================================================

def rss_gorseli_bul(entry):

    # --------------------------------------------------------
    # media_content
    # --------------------------------------------------------

    try:

        medya = getattr(
            entry,
            "media_content",
            []
        )


        for item in medya:

            url = item.get(
                "url"
            )

            url = url_temizle(
                url
            )

            if url:

                print(
                    "✅ RSS media_content görseli bulundu."
                )

                return url


    except Exception:
        pass


    # --------------------------------------------------------
    # media_thumbnail
    # --------------------------------------------------------

    try:

        medya = getattr(
            entry,
            "media_thumbnail",
            []
        )


        for item in medya:

            url = item.get(
                "url"
            )

            url = url_temizle(
                url
            )

            if url:

                print(
                    "✅ RSS thumbnail bulundu."
                )

                return url


    except Exception:
        pass


    # --------------------------------------------------------
    # enclosure
    # --------------------------------------------------------

    try:

        enclosures = getattr(
            entry,
            "enclosures",
            []
        )


        for item in enclosures:

            url = (
                item.get("href")
                or item.get("url")
            )


            url = url_temizle(
                url
            )


            content_type = item.get(
                "type",
                ""
            ).lower()


            if url and (
                "image" in content_type
                or gorsel_url_mu(url)
            ):

                print(
                    "✅ RSS enclosure görseli bulundu."
                )

                return url


    except Exception:
        pass


    # --------------------------------------------------------
    # summary içindeki img
    # --------------------------------------------------------

    try:

        summary = getattr(
            entry,
            "summary",
            ""
        )


        matches = re.findall(
            r'<img[^>]+(?:src|data-src)=["\']([^"\']+)',
            summary,
            re.I
        )


        for url in matches:

            url = url_temizle(
                url
            )

            if url:

                print(
                    "✅ RSS HTML görseli bulundu."
                )

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
        print(
            "🔎 Kaynak haber açılıyor..."
        )

        print(
            haber_url
        )


        cevap = requests.get(
            haber_url,
            headers=HEADERS,
            timeout=30,
            allow_redirects=True
        )


        print(
            "🌐 Son URL:",
            cevap.url
        )

        print(
            "🌐 HTTP:",
            cevap.status_code
        )


        if cevap.status_code != 200:

            return None


        sayfa = cevap.text

        temel_url = cevap.url


        # ----------------------------------------------------
        # OG IMAGE
        # ----------------------------------------------------

        patterns = [

            r'<meta[^>]+property=["\']og:image["\'][^>]+content=["\']([^"\']+)',

            r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+property=["\']og:image["\']',

            r'<meta[^>]+property=["\']og:image:url["\'][^>]+content=["\']([^"\']+)',

            r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+property=["\']og:image:url["\']',

            r'<meta[^>]+name=["\']twitter:image["\'][^>]+content=["\']([^"\']+)',

            r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+name=["\']twitter:image["\']'
        ]


        for pattern in patterns:

            matches = re.findall(
                pattern,
                sayfa,
                re.I
            )


            for url in matches:

                url = url_temizle(
                    url,
                    temel_url
                )


                if url:

                    print()
                    print(
                        "🎯 ORİJİNAL HABER GÖRSELİ BULUNDU:"
                    )

                    print(
                        url
                    )

                    return url


    except Exception as hata:

        print(
            "❌ Kaynak görsel hatası:",
            hata
        )


    print(
        "⚠️ Kaynak sayfada og:image bulunamadı."
    )

    return None


# ============================================================
# DUCKDUCKGO GÖRSEL ARAMA
# ============================================================

def duckduckgo_gorsel_bul(sorgu):

    try:

        print()
        print(
            "🦆 DuckDuckGo görsel aranıyor..."
        )


        # Önce ana sayfadan VQD al
        cevap = requests.get(
            "https://duckduckgo.com/",
            params={
                "q": sorgu
            },
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

            match = re.search(
                pattern,
                sayfa
            )


            if match:

                vqd = match.group(
                    1
                )

                break


        if not vqd:

            print(
                "⚠️ DuckDuckGo VQD bulunamadı."
            )

            return None


        headers = HEADERS.copy()

        headers["Referer"] = (
            "https://duckduckgo.com/"
        )


        sonuc = requests.get(
            "https://duckduckgo.com/i.js",
            params={
                "l": "tr-tr",
                "o": "json",
                "q": sorgu,
                "vqd": vqd,
                "f": ",,,",
                "p": "1"
            },
            headers=headers,
            timeout=30
        )


        print(
            "   HTTP:",
            sonuc.status_code
        )


        if sonuc.status_code != 200:

            return None


        veri = sonuc.json()


        for item in veri.get(
            "results",
            []
        )[:10]:


            image_url = (
                item.get("image")
                or item.get("thumbnail")
            )


            image_url = url_temizle(
                image_url
            )


            if not image_url:

                continue


            if gorsel_kontrol(
                image_url
            ):

                print(
                    "🎯 DuckDuckGo görseli bulundu!"
                )

                return image_url


    except Exception as hata:

        print(
            "❌ DuckDuckGo hatası:",
            hata
        )


    return None


# ============================================================
# YANDEX GÖRSEL ARAMA
# ============================================================

def yandex_gorsel_bul(sorgu):

    try:

        print()
        print(
            "🔴 Yandex görsel aranıyor..."
        )


        cevap = requests.get(
            "https://yandex.com/images/search",
            params={
                "text": sorgu
            },
            headers=HEADERS,
            timeout=30
        )


        print(
            "   HTTP:",
            cevap.status_code
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

            matches = re.findall(
                pattern,
                sayfa,
                re.I
            )


            for url in matches:

                url = url_temizle(
                    url
                )


                if (
                    url
                    and
                    url not in bulunanlar
                ):

                    bulunanlar.append(
                        url
                    )


        print(
            "   Aday görsel:",
            len(bulunanlar)
        )


        for image_url in bulunanlar[:15]:

            if gorsel_kontrol(
                image_url
            ):

                print(
                    "🎯 Yandex görseli bulundu!"
                )

                return image_url


    except Exception as hata:

        print(
            "❌ Yandex hatası:",
            hata
        )


    return None


# ============================================================
# HABER GÖRSELİ BULMA MOTORU
# ============================================================

def haber_gorseli_bul(
    entry,
    baslik
):

    print()
    print(
        "=" * 70
    )

    print(
        "🖼️ HABER GÖRSELİ ARANIYOR"
    )

    print(
        "=" * 70
    )


    # ========================================================
    # 1. RSS
    # ========================================================

    print(
        "1️⃣ RSS görseli kontrol ediliyor..."
    )


    gorsel = rss_gorseli_bul(
        entry
    )


    if gorsel:

        if gorsel_kontrol(
            gorsel
        ):

            return gorsel


    # ========================================================
    # 2. KAYNAK HABER
    # ========================================================

    print()
    print(
        "2️⃣ Kaynak haberin gerçek görseli aranıyor..."
    )


    haber_url = getattr(
        entry,
        "link",
        ""
    )


    gorsel = kaynak_gorseli_bul(
        haber_url
    )


    if gorsel:

        if gorsel_kontrol(
            gorsel
        ):

            return gorsel


    # ========================================================
    # 3. DUCKDUCKGO
    # ========================================================

    print()
    print(
        "3️⃣ DuckDuckGo deneniyor..."
    )


    gorsel = duckduckgo_gorsel_bul(
        baslik
    )


    if gorsel:

        return gorsel


    # ========================================================
    # 4. YANDEX
    # ========================================================

    print()
    print(
        "4️⃣ Yandex deneniyor..."
    )


    gorsel = yandex_gorsel_bul(
        baslik
    )


    if gorsel:

        return gorsel


    # ========================================================
    # GÖRSEL YOK
    # ========================================================

    print()
    print(
        "❌ HABER İÇİN UYGUN GÖRSEL BULUNAMADI."
    )

    print(
        "⏭️ Haber yayınlanmayacak."
    )


    return None


# ============================================================
# GEMINI İLE HABER ÜRET
# ============================================================

def generate_seo_article_and_labels(
    title,
    summary,
    kategori
):

    if not GEMINI_API_KEY:

        return (
            f"<p>{summary}</p>",
            [kategori, "Haber"]
        )


    allowed_categories = [

        "Yapay Zeka",

        "Telefon",

        "Bilgisayar",

        "Teknoloji",

        "Oyun",

        "Akıllı Ev",

        "Donanım",

        "Bilim ve Uzay",

        "Sinema",

        "Otomobil"
    ]


    prompt = f"""
Sen deneyimli bir Türkçe teknoloji haber editörüsün.

Aşağıdaki kaynak haber bilgilerini kullan.

KAYNAK BAŞLIK:
{title}

KAYNAK ÖZET:
{summary}

KAYNAK KATEGORİ:
{kategori}


GÖREV:

Haberi özgün Türkçe ile yeniden yaz.

Kaynakta olmayan bilgi UYDURMA.

Haberi birebir kopyalama.

Haber doğal ve gazetecilik üslubunda olsun.


KURALLAR:

1. 750 ile 1200 kelime arasında yaz.

2. Haber Türkçe olacak.

3. SEO uyumlu bir ana başlık oluştur.

4. Metni HTML olarak oluştur.

5. <h2> ve <h3> başlıkları kullan.

6. Paragrafları <p> etiketiyle yaz.

7. Gerektiğinde <ul> ve <li> kullan.

8. Önemli noktaları <strong> ile vurgula.

9. Kaynakta olmayan rakam, tarih, kişi veya açıklama uydurma.

10. Haber sonunda kısa bir değerlendirme bölümü olabilir.

11. Şu kategorilerden SADECE BİR TANESİNİ seç:

{allowed_categories}


12. Toplam 10 SEO etiketi oluştur.

İlk etiket seçilen ana kategori olsun.


ÇIKTI FORMATI:

İlk satır:

[BAŞLIK: Haber başlığı]


Sonra:

HTML haber içeriği


En son:

[ETİKETLER: kategori, etiket2, etiket3, etiket4, etiket5, etiket6, etiket7, etiket8, etiket9, etiket10]


Başka açıklama yazma.
"""


    try:

        print()
        print(
            "🤖 Gemini haber oluşturuyor..."
        )


        client = genai.Client(
            api_key=GEMINI_API_KEY
        )


        response = client.models.generate_content(

            model=GEMINI_MODEL,

            contents=prompt
        )


        text = response.text.strip()


        # ----------------------------------------------------
        # BAŞLIK
        # ----------------------------------------------------

        baslik_match = re.search(
            r"\[BAŞLIK:\s*(.*?)\]",
            text,
            re.I | re.S
        )


        if baslik_match:

            yeni_baslik = (
                baslik_match
                .group(1)
                .strip()
            )

            text = re.sub(
                r"\[BAŞLIK:\s*.*?\]",
                "",
                text,
                count=1,
                flags=re.I | re.S
            )

        else:

            yeni_baslik = title


        # ----------------------------------------------------
        # ETİKETLER
        # ----------------------------------------------------

        labels_match = re.search(
            r"\[ETİKETLER:\s*(.*?)\]",
            text,
            re.I | re.S
        )


        if labels_match:

            labels_part = (
                labels_match
                .group(1)
                .strip()
            )


            labels = [

                x.strip()

                for x in labels_part.split(",")

                if x.strip()
            ]


            text = re.sub(
                r"\[ETİKETLER:\s*.*?\]",
                "",
                text,
                count=1,
                flags=re.I | re.S
            )

        else:

            labels = [
                kategori,
                "Teknoloji",
                "Haber"
            ]


        # ----------------------------------------------------
        # ETİKET SAYISINI SINIRLA
        # ----------------------------------------------------

        labels = labels[:10]


        # ----------------------------------------------------
        # BOŞ HTML TEMİZLE
        # ----------------------------------------------------

        article_html = text.strip()


        article_html = re.sub(
            r"^```html",
            "",
            article_html,
            flags=re.I
        )


        article_html = re.sub(
            r"```$",
            "",
            article_html
        )


        article_html = article_html.strip()


        print(
            "✅ Gemini haber oluşturdu."
        )


        print(
            "📰 Yeni başlık:",
            yeni_baslik
        )


        print(
            "🏷️ Etiketler:",
            labels
        )


        return (
            yeni_baslik,
            article_html,
            labels
        )


    except Exception as hata:

        print()
        print(
            "❌ GEMINI HATASI:"
        )

        print(
            hata
        )

        return None


# ============================================================
# BLOGGER KİMLİK DOĞRULAMA
# ============================================================

def blogger_service_olustur():

    try:

        print()
        print(
            "🔐 Blogger kimlik doğrulaması başlıyor..."
        )


        creds = Credentials(

            token=None,

            refresh_token=REFRESH_TOKEN,

            token_uri=
            "https://oauth2.googleapis.com/token",

            client_id=CLIENT_ID,

            client_secret=CLIENT_SECRET,

            scopes=[
                "https://www.googleapis.com/auth/blogger"
            ]
        )


        auth_request = Request()


        creds.refresh(
            auth_request
        )


        print(
            "✅ Blogger OAuth başarılı."
        )


        service = build(
            "blogger",
            "v3",
            credentials=creds,
            cache_discovery=False
        )


        # ====================================================
        # BLOG ERİŞİM TESTİ
        # ====================================================

        print(
            "🔎 Blogger blog erişimi test ediliyor..."
        )


        blog = (
            service
            .blogs()
            .get(
                blogId=BLOG_ID
            )
            .execute()
        )


        print(
            "✅ Blog bulundu:"
        )


        print(
            blog.get(
                "name",
                "İsimsiz blog"
            )
        )


        return service


    except Exception as hata:

        print()
        print(
            "=" * 70
        )

        print(
            "❌ BLOGGER KİMLİK / YETKİ HATASI"
        )

        print(
            "=" * 70
        )

        print(
            hata
        )

        print()
        print(
            "Muhtemel nedenler:"
        )

        print(
            "1. BLOGGER_REFRESH_TOKEN yanlış."
        )

        print(
            "2. Refresh token başka Google hesabına ait."
        )

        print(
            "3. OAuth token Blogger scope'una sahip değil."
        )

        print(
            "4. BLOGGER_BLOG_ID yanlış."
        )

        print(
            "5. Google hesabının bu blog üzerinde yetkisi yok."
        )

        print()

        return None


# ============================================================
# HAFIZA OKU
# ============================================================

def hafiza_oku():

    if not os.path.exists(
        HAFIZA_DOSYASI
    ):

        return set()


    try:

        with open(
            HAFIZA_DOSYASI,
            "r",
            encoding="utf-8"
        ) as dosya:

            return set(

                satir.strip()

                for satir in dosya

                if satir.strip()
            )


    except Exception as hata:

        print(
            "⚠️ Hafıza okunamadı:",
            hata
        )

        return set()


# ============================================================
# HAFIZAYA KAYDET
# ============================================================

def hafizaya_kaydet(
    link
):

    try:

        with open(
            HAFIZA_DOSYASI,
            "a",
            encoding="utf-8"
        ) as dosya:

            dosya.write(
                link + "\n"
            )


    except Exception as hata:

        print(
            "⚠️ Hafıza kaydedilemedi:",
            hata
        )


# ============================================================
# BLOGGER'A HABER GÖNDER
# ============================================================

def blogger_a_gonder(

    service,

    title,

    article_html,

    labels,

    image_url,

    source_url

):

    try:

        # ====================================================
        # GÖRSEL
        # ====================================================

        title_safe = html.escape(
            title
        )


        image_html = f"""
<div style="text-align:center; margin:0 0 25px 0;">

<img
src="{html.escape(image_url, quote=True)}"
alt="{title_safe}"
title="{title_safe}"
style="
width:100%;
max-width:1200px;
height:auto;
display:block;
margin:0 auto;
border-radius:12px;
"
/>

</div>
"""


        # ====================================================
        # KAYNAK
        # ====================================================

        source_html = f"""
<hr>

<p style="
font-size:14px;
color:#666;
">

Kaynak:
<a
href="{html.escape(source_url, quote=True)}"
target="_blank"
rel="nofollow noopener"
>

Haberi kaynağından oku

</a>

</p>
"""


        # ====================================================
        # TAM İÇERİK
        # ====================================================

        content = (

            image_html

            + "\n"

            + article_html

            + "\n"

            + source_html
        )


        post_body = {

            "title":
                title,

            "content":
                content,

            "labels":
                labels
        }


        print()
        print(
            "📤 Blogger'a gönderiliyor..."
        )


        response = (

            service

            .posts()

            .insert(

                blogId=BLOG_ID,

                body=post_body
            )

            .execute()
        )


        post_url = response.get(
            "url",
            ""
        )


        print()
        print(
            "🎉 HABER BAŞARIYLA YAYINLANDI!"
        )


        print(
            "📰",
            title
        )


        print(
            "🔗",
            post_url
        )


        return post_url


    except Exception as hata:

        print()
        print(
            "❌ BLOGGER YAYINLAMA HATASI:"
        )

        print(
            hata
        )

        return None


# ============================================================
# RSS'TEN HABERLERİ TOPLA
# ============================================================

def rss_haberlerini_getir():

    haberler = []


    for source in RSS_SOURCES:

        try:

            print()
            print(
                "📡 RSS kontrol ediliyor:"
            )

            print(
                source["url"]
            )


            feed = feedparser.parse(
                source["url"]
            )


            if not feed.entries:

                print(
                    "⚠️ Haber bulunamadı."
                )

                continue


            for entry in feed.entries[:5]:

                haberler.append({

                    "entry":
                        entry,

                    "kategori":
                        source["kaynak"],

                    "rss":
                        source["url"]
                })


        except Exception as hata:

            print(
                "❌ RSS hatası:",
                hata
            )


    return haberler


# ============================================================
# ANA PROGRAM
# ============================================================

def main():

    print()
    print("=" * 70)

    print(
        "🚀 OTOMATİK BLOGGER HABER SİSTEMİ"
    )

    print("=" * 70)


    # ========================================================
    # AYARLAR
    # ========================================================

    if not ayarlari_kontrol_et():

        return


    print()
    print(
        "🤖 Gemini modeli:",
        GEMINI_MODEL
    )


    # ========================================================
    # BLOGGER
    # ========================================================

    service = blogger_service_olustur()


    if not service:

        return


    # ========================================================
    # HAFIZA
    # ========================================================

    yayinlananlar = hafiza_oku()


    print()
    print(
        "📚 Daha önce yayınlanan:",
        len(yayinlananlar)
    )


    # ========================================================
    # RSS
    # ========================================================

    haberler = rss_haberlerini_getir()


    if not haberler:

        print(
            "❌ Hiç haber bulunamadı."
        )

        return


    print()
    print(
        "📰 Toplam aday haber:",
        len(haberler)
    )


    # ========================================================
    # YAYIN SAYACI
    # ========================================================

    yayinlanan_sayi = 0


    # ========================================================
    # HABERLER
    # ========================================================

    for haber in haberler:

        if yayinlanan_sayi >= MAX_HABER:

            break


        entry = haber["entry"]

        kategori = haber["kategori"]


        # ====================================================
        # LINK
        # ====================================================

        source_url = getattr(
            entry,
            "link",
            ""
        )


        if not source_url:

            continue


        # ====================================================
        # TEKRAR KONTROLÜ
        # ====================================================

        if source_url in yayinlananlar:

            print()
            print(
                "⏭️ Bu haber daha önce yayınlanmış."
            )

            continue


        # ====================================================
        # BAŞLIK
        # ====================================================

        original_title = baslik_temizle(

            getattr(
                entry,
                "title",
                ""
            )
        )


        if not original_title:

            continue


        # ====================================================
        # ÖZET
        # ====================================================

        summary = ozet_temizle(

            getattr(
                entry,
                "summary",
                ""
            )
        )


        print()
        print("=" * 70)

        print(
            "📰 YENİ HABER"
        )

        print(
            original_title
        )

        print(
            "📂 Kategori:",
            kategori
        )

        print(
            "=" * 70
        )


        # ====================================================
        # GÖRSEL
        # ====================================================

        image_url = haber_gorseli_bul(

            entry,

            original_title
        )


        if not image_url:

            print()
            print(
                "⏭️ Görsel bulunamadı."
            )

            print(
                "Bu haber yayınlanmayacak."
            )

            continue


        # ====================================================
        # GEMINI
        # ====================================================

        sonuc = generate_seo_article_and_labels(

            original_title,

            summary,

            kategori
        )


        if not sonuc:

            print(
                "⏭️ Gemini haber oluşturamadı."
            )

            continue


        new_title = sonuc[0]

        article_html = sonuc[1]

        labels = sonuc[2]


        # ====================================================
        # BLOGGER
        # ====================================================

        post_url = blogger_a_gonder(

            service,

            new_title,

            article_html,

            labels,

            image_url,

            source_url
        )


        if not post_url:

            print(
                "❌ Blogger yayınlamadı."
            )

            continue


        # ====================================================
        # HAFIZA
        # ====================================================

        hafizaya_kaydet(
            source_url
        )


        yayinlananlar.add(
            source_url
        )


        yayinlanan_sayi += 1


        print()
        print(
            f"✅ {yayinlanan_sayi}/{MAX_HABER} haber yayınlandı."
        )


        # ====================================================
        # BEKLE
        # ====================================================

        if yayinlanan_sayi < MAX_HABER:

            print()
            print(
                f"⏳ {BEKLEME_SURESI} saniye bekleniyor..."
            )

            time.sleep(
                BEKLEME_SURESI
            )


    # ========================================================
    # BİTİŞ
    # ========================================================

    print()
    print("=" * 70)

    print(
        "🏁 İŞLEM TAMAMLANDI"
    )

    print("=" * 70)

    print(
        "📢 Yayınlanan haber:",
        yayinlanan_sayi
    )

    print()


# ============================================================
# PROGRAMI ÇALIŞTIR
# ============================================================

if __name__ == "__main__":

    main()
