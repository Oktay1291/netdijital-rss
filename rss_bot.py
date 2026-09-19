import os
import json
import random
import time
import html
import traceback
import base64
import re
import io
import hashlib
import unicodedata
from datetime import datetime, timezone
from urllib.parse import urljoin

import requests
import feedparser

from bs4 import BeautifulSoup
from google import genai
from google.genai import types
from PIL import Image, ImageOps


# ============================================================
# AYARLAR
# ============================================================

CLIENT_ID = os.getenv("BLOGGER_CLIENT_ID")
CLIENT_SECRET = os.getenv("BLOGGER_CLIENT_SECRET")
REFRESH_TOKEN = os.getenv("BLOGGER_REFRESH_TOKEN")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
BLOGGER_BLOG_ID = os.getenv("BLOGGER_BLOG_ID")
PEXELS_API_KEY = os.getenv("PEXELS_API_KEY")

GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")
GITHUB_REPOSITORY = os.getenv("GITHUB_REPOSITORY")
GITHUB_BRANCH = os.getenv("GITHUB_REF_NAME", "main")

HISTORY_FILE = "posted_history.json"

MAX_GECMIS_LINK = 3000


# False = direkt yayınla
# True = Blogger'da taslak oluştur
TASLAK_OLARAK_KAYDET = False

# ============================================================
# GUVENLI TEST MODU
# ============================================================
# Varsayilan TRUE'dur. Bu modda Blogger OAuth/token ve posts.insert
# dahil HICBIR Blogger API cagrisi yapilmaz.
TEST_MODU = os.getenv("TEST_MODU", "true").strip().lower() in {"1", "true", "yes", "on"}


# ============================================================
# GEMINI
# ============================================================

client = genai.Client(api_key=GEMINI_API_KEY) if GEMINI_API_KEY else None


# ============================================================
# RSS KAYNAKLARI
# ============================================================

RSS_SOURCES = [
    {"kaynak": "CHIP Online", "url": "https://www.chip.com.tr/rss"},
    {"kaynak": "DonanımHaber", "url": "https://www.donanimhaber.com/rss/tumhaberler.xml"},
    {"kaynak": "ShiftDelete.Net", "url": "https://shiftdelete.net/feed"},
    {"kaynak": "Webtekno", "url": "https://www.webtekno.com/rss"},
    {"kaynak": "Tamindir", "url": "https://www.tamindir.com/rss/"},
    {"kaynak": "TechReview", "url": "https://techreview.com.tr/feed/"},
    {"kaynak": "Teknolojioku", "url": "https://www.teknolojioku.com/rss"},
    {"kaynak": "Techolay", "url": "https://techolay.net/feed/"},
    {"kaynak": "Teknoblog", "url": "https://www.teknoblog.com/feed/"}
]


# ============================================================
# ETİKETLER
# ============================================================

GENEL_ETIKET_HAVUZU = [
    "Teknoloji Haberleri",
    "Güncel Teknoloji",
    "Dijital Dünya",
    "Yapay Zeka",
    "Teknoloji",
    "Bilim ve Teknoloji",
    "Gündem",
    "İnternet",
    "Dijital Yaşam",
]


# ============================================================
# GOOGLE ACCESS TOKEN
# ============================================================

def get_access_token(client_id, client_secret, refresh_token):

    token_url = "https://oauth2.googleapis.com/token"

    payload = {
        "client_id": client_id,
        "client_secret": client_secret,
        "refresh_token": refresh_token,
        "grant_type": "refresh_token"
    }

    try:

        r = requests.post(
            token_url,
            data=payload,
            timeout=20
        )

    except requests.exceptions.RequestException as e:

        print(f"Token yenileme hatasi: {e}")
        return None

    if r.status_code == 200:

        return r.json().get("access_token")

    print(
        f"Token yenileme hatasi: "
        f"{r.status_code} - {r.text}"
    )

    return None


# ============================================================
# HISTORY
# ============================================================

def load_history():

    default_data = {
        "yayinlanan_linkler": [],
        "son_kaynak_index": 0,
        "son_paylasim_zamani": 0
    }

    if not os.path.exists(HISTORY_FILE):

        return default_data

    try:

        with open(
            HISTORY_FILE,
            "r",
            encoding="utf-8"
        ) as f:

            data = json.load(f)

        data.setdefault(
            "yayinlanan_linkler",
            []
        )

        data.setdefault(
            "son_kaynak_index",
            0
        )

        data.setdefault(
            "son_paylasim_zamani",
            0
        )

        return data

    except Exception as e:

        print(
            f"History okunamadi: {e}"
        )

        return default_data


def save_history(data):

    data["yayinlanan_linkler"] = (
        data["yayinlanan_linkler"]
        [-MAX_GECMIS_LINK:]
    )

    with open(
        HISTORY_FILE,
        "w",
        encoding="utf-8"
    ) as f:

        json.dump(
            data,
            f,
            ensure_ascii=False,
            indent=2
        )


# ============================================================
# HISTORY'Yİ GITHUB'A GERİ YAZ
# ============================================================

def github_history_save():

    if not GITHUB_TOKEN:
        print(
            "GITHUB_TOKEN bulunamadi. "
            "History sadece runner'da tutulacak."
        )
        return False

    if not GITHUB_REPOSITORY:
        return False

    if not os.path.exists(HISTORY_FILE):
        return False

    try:

        with open(
            HISTORY_FILE,
            "rb"
        ) as f:

            content = base64.b64encode(
                f.read()
            ).decode("utf-8")

        api_url = (
            "https://api.github.com/repos/"
            f"{GITHUB_REPOSITORY}/contents/"
            f"{HISTORY_FILE}"
        )

        headers = {
            "Authorization": f"Bearer {GITHUB_TOKEN}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28"
        }

        mevcut = requests.get(
            api_url,
            headers=headers,
            timeout=20
        )

        sha = None

        if mevcut.status_code == 200:

            sha = mevcut.json().get("sha")

        payload = {
            "message": "Update posted history",
            "content": content,
            "branch": GITHUB_BRANCH
        }

        if sha:
            payload["sha"] = sha

        response = requests.put(
            api_url,
            headers=headers,
            json=payload,
            timeout=30
        )

        if response.status_code in (200, 201):

            print(
                "posted_history.json GitHub'a kaydedildi."
            )

            return True

        print(
            "GitHub history kayit hatasi:",
            response.status_code,
            response.text
        )

    except Exception as e:

        print(
            f"GitHub history hatasi: {e}"
        )

    return False


# ============================================================
# RSS
# ============================================================

def fetch_feed(url, kaynak_adi="Kaynak"):

    headers = {
        "User-Agent":
            "Mozilla/5.0 "
            "(Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 "
            "(KHTML, like Gecko) "
            "Chrome/153.0 Safari/537.36",

        "Accept":
            "application/rss+xml, "
            "application/xml, "
            "text/xml, "
            "*/*"
    }

    try:

        response = requests.get(
            url,
            headers=headers,
            timeout=20
        )

        response.raise_for_status()

        return feedparser.parse(
            response.content
        )

    except Exception as e:

        print(
            f"Feed alinamadi [{kaynak_adi}]: {e}"
        )

        return feedparser.parse("")


# ============================================================
# URL NORMALİZASYON
# ============================================================

def normalize_url(url):

    if not url:
        return None

    url = url.strip()

    return url


# ============================================================
# RSS GÖRSELİ
# ============================================================

def rss_gorsel_bul(entry):

    # media_content

    try:

        media_content = entry.get(
            "media_content",
            []
        )

        for media in media_content:

            url = media.get("url")

            if url:
                return url

    except Exception:
        pass


    # media_thumbnail

    try:

        thumbnails = entry.get(
            "media_thumbnail",
            []
        )

        for media in thumbnails:

            url = media.get("url")

            if url:
                return url

    except Exception:
        pass


    # enclosure

    try:

        enclosures = entry.get(
            "enclosures",
            []
        )

        for enclosure in enclosures:

            url = enclosure.get("href")

            media_type = enclosure.get(
                "type",
                ""
            )

            if (
                url
                and (
                    media_type.startswith("image/")
                    or any(
                        x in url.lower()
                        for x in [
                            ".jpg",
                            ".jpeg",
                            ".png",
                            ".webp"
                        ]
                    )
                )
            ):

                return url

    except Exception:
        pass


    return None


# ============================================================
# WEB SAYFASINDAN OG IMAGE
# ============================================================

def sayfa_gorseli_bul(url):

    if not url:
        return None

    try:

        headers = {
            "User-Agent":
                "Mozilla/5.0 "
                "(Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 "
                "Chrome/153.0 Safari/537.36"
        }

        response = requests.get(
            url,
            headers=headers,
            timeout=15
        )

        if response.status_code != 200:
            return None

        soup = BeautifulSoup(
            response.text,
            "html.parser"
        )


        # og:image

        og = soup.find(
            "meta",
            property="og:image"
        )

        if og and og.get("content"):

            return og["content"].strip()


        # twitter:image

        twitter = soup.find(
            "meta",
            attrs={
                "name": "twitter:image"
            }
        )

        if twitter and twitter.get("content"):

            return twitter["content"].strip()


        # link image_src

        image_src = soup.find(
            "link",
            rel=lambda value:
                value and
                "image_src" in value
        )

        if image_src and image_src.get("href"):

            return image_src["href"].strip()

    except Exception as e:

        print(
            f"Web gorsel hatasi: {e}"
        )

    return None


# ============================================================
# PEXELS
# ============================================================

def pexels_gorsel_bul(anahtar_kelime):

    if not PEXELS_API_KEY:
        return None, None

    if not anahtar_kelime:
        return None, None

    try:

        url = (
            "https://api.pexels.com/v1/search"
        )

        headers = {
            "Authorization":
                PEXELS_API_KEY
        }

        params = {
            "query": anahtar_kelime,
            "per_page": 1,
            "orientation": "landscape"
        }

        response = requests.get(
            url,
            headers=headers,
            params=params,
            timeout=15
        )

        if response.status_code != 200:
            return None, None

        photos = response.json().get(
            "photos",
            []
        )

        if photos:

            photo = photos[0]

            return (
                photo["src"]["large"],
                photo.get(
                    "photographer",
                    "Pexels"
                )
            )

    except Exception as e:

        print(
            f"Pexels hatasi: {e}"
        )

    return None, None


# ============================================================
# NETDIJITAL KATEGORI / GORSEL SISTEMI v1.2
# ============================================================

ANA_KATEGORILER = [
    "Yapay Zekâ", "Mobil", "Bilgisayar", "Oyun",
    "Otomotiv", "Uzay", "Dizi & Sinema", "Rehberler"
]

# NetDijital kategori fallback kapaklari repo icinde sabit tutulur.
# GITHUB_REPOSITORY GitHub Actions tarafindan otomatik gelir. Yerelde calistirirken
# tanimli degilse NetDijital reposuna geri duser.
FALLBACK_REPOSITORY = GITHUB_REPOSITORY or "Oktay1291/netdijital-rss"
FALLBACK_BRANCH = GITHUB_BRANCH or "main"
FALLBACK_BASE_URL = (
    f"https://raw.githubusercontent.com/{FALLBACK_REPOSITORY}/"
    f"{FALLBACK_BRANCH}/assets/fallback"
)

KATEGORI_FALLBACK = {
    "Yapay Zekâ": f"{FALLBACK_BASE_URL}/netdijital-fallback-yapay-zeka-1200x675.jpg",
    "Mobil": f"{FALLBACK_BASE_URL}/netdijital-fallback-mobil-1200x675.jpg",
    "Bilgisayar": f"{FALLBACK_BASE_URL}/netdijital-fallback-bilgisayar-1200x675.jpg",
    "Oyun": f"{FALLBACK_BASE_URL}/netdijital-fallback-oyun-1200x675.jpg",
    "Otomotiv": f"{FALLBACK_BASE_URL}/netdijital-fallback-otomotiv-1200x675.jpg",
    "Uzay": f"{FALLBACK_BASE_URL}/netdijital-fallback-uzay-1200x675.jpg",
    "Dizi & Sinema": f"{FALLBACK_BASE_URL}/netdijital-fallback-dizi-sinema-1200x675.jpg",
    "Rehberler": f"{FALLBACK_BASE_URL}/netdijital-fallback-rehberler-1200x675.jpg",
}

MIN_GORSEL_GENISLIK = 900
MIN_GORSEL_YUKSEKLIK = 500
MIN_ORAN = 1.35
MAX_ORAN = 2.25


def kategori_normalize(kategori):
    if not kategori:
        return "Yapay Zekâ"
    k = str(kategori).strip().lower()
    esleme = {
        "yapay zeka": "Yapay Zekâ", "yapay zekâ": "Yapay Zekâ", "ai": "Yapay Zekâ",
        "mobil": "Mobil", "telefon": "Mobil",
        "bilgisayar": "Bilgisayar", "donanım": "Bilgisayar", "donanim": "Bilgisayar",
        "oyun": "Oyun",
        "otomotiv": "Otomotiv", "otomobil": "Otomotiv",
        "uzay": "Uzay", "uzay teknolojileri": "Uzay",
        "dizi & sinema": "Dizi & Sinema", "sinema": "Dizi & Sinema", "dizi": "Dizi & Sinema",
        "rehberler": "Rehberler", "rehber": "Rehberler", "inceleme": "Rehberler",
    }
    return esleme.get(k, "Yapay Zekâ")


def _gorsel_indir(url):
    """Gorseli indirir ve Pillow Image nesnesi + ham byte dondurur."""
    if not url or not url.startswith(("http://", "https://")):
        return None, None
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/153.0 Safari/537.36",
            "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
        }
        r = requests.get(url, headers=headers, timeout=20, allow_redirects=True)
        if r.status_code != 200:
            return None, None
        ct = (r.headers.get("content-type") or "").lower()
        if not ct.startswith("image/"):
            return None, None
        if len(r.content) < 25000 or len(r.content) > 15 * 1024 * 1024:
            return None, None
        im = Image.open(io.BytesIO(r.content))
        im.load()
        return im, r.content
    except Exception:
        return None, None


def gorsel_boyutu_kontrol(url):
    """Kapak icin minimum kalite/oran kontrolu."""
    im, _ = _gorsel_indir(url)
    if im is None:
        return False
    w, h = im.size
    if w < 1000 or h < 500:
        return False
    oran = w / h if h else 0
    # Cok dikey/kare veya asiri panoramik gorselleri ele.
    if oran < 1.30 or oran > 2.50:
        return False
    return True


def _slugify(text):
    text = unicodedata.normalize("NFKD", str(text or ""))
    text = "".join(c for c in text if not unicodedata.combining(c))
    text = text.encode("ascii", "ignore").decode("ascii").lower()
    text = re.sub(r"[^a-z0-9]+", "-", text).strip("-")
    return (text[:70] or "haber")


def gorseli_1200x675_hazirla(url):
    """Uzak gorseli gercek 1200x675 JPEG kapaga donusturur."""
    im, _ = _gorsel_indir(url)
    if im is None:
        return None
    w, h = im.size
    if w < 1000 or h < 500:
        return None
    oran = w / h if h else 0
    if oran < 1.30 or oran > 2.50:
        return None
    try:
        im = ImageOps.exif_transpose(im).convert("RGB")
        # Pillow fit: merkezi koruyarak 16:9 crop + resize.
        im = ImageOps.fit(im, (1200, 675), method=Image.Resampling.LANCZOS, centering=(0.5, 0.5))
        out = io.BytesIO()
        im.save(out, format="JPEG", quality=86, optimize=True, progressive=True)
        return out.getvalue()
    except Exception as e:
        print(f"Gorsel isleme hatasi: {e}")
        return None


def github_kapak_yukle(jpeg_bytes, baslik):
    """1200x675 kapagi repo'ya kaydeder ve public raw URL dondurur.
    Repo private ise raw URL Blogger okuyucularina acik olmayabilir.
    """
    if not jpeg_bytes or not GITHUB_TOKEN or not GITHUB_REPOSITORY:
        return None
    try:
        now = datetime.now(timezone.utc)
        digest = hashlib.sha1(jpeg_bytes).hexdigest()[:10]
        filename = f"{_slugify(baslik)}-{digest}.jpg"
        path = f"assets/covers/{now:%Y/%m}/{filename}"
        api_url = f"https://api.github.com/repos/{GITHUB_REPOSITORY}/contents/{path}"
        headers = {
            "Authorization": f"Bearer {GITHUB_TOKEN}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        payload = {
            "message": f"Add cover: {filename}",
            "content": base64.b64encode(jpeg_bytes).decode("ascii"),
            "branch": GITHUB_BRANCH,
        }
        r = requests.put(api_url, headers=headers, json=payload, timeout=30)
        if r.status_code not in (200, 201):
            print("Kapak GitHub yukleme hatasi:", r.status_code, r.text[:500])
            return None
        owner_repo = GITHUB_REPOSITORY.strip("/")
        return f"https://raw.githubusercontent.com/{owner_repo}/{GITHUB_BRANCH}/{path}"
    except Exception as e:
        print(f"Kapak GitHub yukleme hatasi: {e}")
        return None


def sayfa_gorsel_adaylari(url):
    """Sayfadaki sosyal kapak adaylarini sirali dondurur."""
    if not url:
        return []
    try:
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/153.0 Safari/537.36"}
        r = requests.get(url, headers=headers, timeout=15)
        if r.status_code != 200:
            return []
        soup = BeautifulSoup(r.text, "html.parser")
        adaylar = []
        for attr, key, value in [
            ("property", "og:image", "content"),
            ("property", "og:image:secure_url", "content"),
            ("name", "twitter:image", "content"),
            ("name", "twitter:image:src", "content"),
        ]:
            tag = soup.find("meta", attrs={attr: key})
            if tag and tag.get(value):
                adaylar.append(urljoin(url, tag.get(value).strip()))
        link = soup.find("link", rel=lambda v: v and "image_src" in v)
        if link and link.get("href"):
            adaylar.append(urljoin(url, link["href"].strip()))
        return list(dict.fromkeys(adaylar))
    except Exception as e:
        print(f"Web gorsel adaylari hatasi: {e}")
        return []


def rss_gorsel_adaylari(entry):
    adaylar = []
    for key in ("media_content", "media_thumbnail"):
        try:
            for media in entry.get(key, []) or []:
                u = media.get("url")
                if u:
                    adaylar.append(u)
        except Exception:
            pass
    try:
        for enclosure in entry.get("enclosures", []) or []:
            u = enclosure.get("href")
            t = enclosure.get("type", "")
            if u and (t.startswith("image/") or re.search(r"\.(jpe?g|png|webp)(\?|$)", u, re.I)):
                adaylar.append(u)
    except Exception:
        pass
    return list(dict.fromkeys(adaylar))


def en_iyi_gorseli_sec(entry, haber_url, arama_terimi, kategori, baslik="haber"):
    """RSS -> kaynak sayfa -> Pexels -> NetDijital kategori fallback.

    Gercek/Pexels adaylari kalite kontrolunden gecerse 1200x675'e donusturulur
    ve GitHub assets/covers altinda barindirilir. Hicbir aday uygun degilse
    assets/fallback altindaki hazir 1200x675 kategori kapagi dogrudan kullanilir.
    """
    adaylar = []
    adaylar.extend((u, "RSS", None) for u in rss_gorsel_adaylari(entry))
    adaylar.extend((u, "Kaynak sayfa", None) for u in sayfa_gorsel_adaylari(haber_url))

    p_url, fotografci = pexels_gorsel_bul(arama_terimi)
    if p_url:
        adaylar.append((p_url, "Pexels", fotografci))

    gorulen = set()
    for u, kaynak, fotografci in adaylar:
        if not u or u in gorulen:
            continue
        gorulen.add(u)
        if not gorsel_boyutu_kontrol(u):
            print(f"Gorsel elendi ({kaynak}): {u[:120]}")
            continue

        jpeg = gorseli_1200x675_hazirla(u)
        if not jpeg:
            continue

        hosted = github_kapak_yukle(jpeg, baslik)
        if hosted:
            return hosted, kaynak + " / 1200x675", fotografci

        # GitHub'a islenmis kapak yuklenemezse uygun orijinal adayi kullan.
        print(f"Islenmis kapak yuklenemedi; orijinal URL kullaniliyor ({kaynak}).")
        return u, kaynak, fotografci

    # Son guvenli katman: kategoriye ait hazir NetDijital 1200x675 kapagi.
    fallback = KATEGORI_FALLBACK.get(kategori)
    if fallback:
        print(f"Kategori fallback kapagi kullaniliyor: {kategori}")
        return fallback, "NetDijital kategori kapağı / 1200x675", None

    print(f"Fallback bulunamadi: {kategori}")
    return None, None, None


# ============================================================
# GEMINI HABER URETIMI
# ============================================================

def llm_ile_makale_uret(orijinal_baslik, orijinal_ozet):
    if not client:
        print("GEMINI_API_KEY tanimli degil.")
        return None, False

    prompt = f"""
Sen NetDijital icin calisan deneyimli bir Turkce teknoloji editorusun.
Asagidaki RSS bilgisini temel alarak ozgun, dogal ve olgusal bir teknoloji haberi yaz.

ORIJINAL BASLIK:
{orijinal_baslik}

ORIJINAL OZET:
{orijinal_ozet}

KURALLAR:
1. Yalnizca verilen bilgilerden desteklenebilen olgulari kesin ifade et; eksik bilgiyi uydurma.
2. Kaynak metni cumle cumle yeniden yazma veya uzun ifadeleri kopyalama.
3. 600-1000 Turkce kelime hedefle; bilgi yetersizse metni yapay olarak uzatma.
4. Baslik bilgilendirici ve clickbait olmayan bir haber basligi olsun.
5. Giris paragrafi haberi dogrudan anlatsin; kisa paragraflar ve gerekli yerlerde H2 kullan.
6. "Bu yazida", "gelin bakalim", "heyecan verici" gibi kalip dolgu ifadelerinden kacın.
7. Spekulasyon, kullanici tepkisi veya sektor etkisi icin veri verilmemisse bunu olgu gibi uydurma.
8. Ana kategori TAM OLARAK su sekiz degerden biri olmali:
   Yapay Zekâ, Mobil, Bilgisayar, Oyun, Otomotiv, Uzay, Dizi & Sinema, Rehberler
9. Etiketler ana kategori disinda 2-5 adet olsun. Marka, urun, platform veya spesifik teknoloji adlarini kullan.
10. "Teknoloji", "Teknoloji Haberleri", "Guncel Teknoloji", "Gundem", kaynak site adi gibi genel etiketler uretme.
11. Gorsel arama terimi 3-7 kelimelik, somut ve Ingilizce olsun.
12. Meta aciklamasi yaklasik 140-160 karakter olsun.
13. Sadece gecerli JSON dondur.

JSON:
{{
  "baslik": "...",
  "icerik_html": "<p>...</p><h2>...</h2><p>...</p>",
  "meta_aciklama": "...",
  "kategori": "Yapay Zekâ",
  "etiketler": ["Gemini", "Google"],
  "gorsel_arama_terimi": "Google Gemini AI interface"
}}
"""

    # Birincil model gecici olarak yogunsa ikinci modele gecilir.
    # 429 / 408 / 5xx gibi gecici hatalarda exponential backoff + jitter uygulanir.
    modeller = ["gemini-3.6-flash", "gemini-3.5-flash-lite"]
    gecici_isaretler = ("429", "408", "500", "502", "503", "504",
                        "RESOURCE_EXHAUSTED", "UNAVAILABLE", "DEADLINE_EXCEEDED")
    beklemeler = (5, 10, 20)

    for model in modeller:
        print(f"Gemini modeli deneniyor: {model}")
        for deneme, temel_bekleme in enumerate(beklemeler, start=1):
            try:
                response = client.models.generate_content(
                    model=model,
                    contents=prompt,
                    config=types.GenerateContentConfig(
                        max_output_tokens=8192,
                        response_mime_type="application/json",
                    ),
                )
                metin = (response.text or "").strip()
                if metin.startswith("```"):
                    satirlar = metin.splitlines()[1:]
                    if satirlar and satirlar[-1].startswith("```"):
                        satirlar = satirlar[:-1]
                    metin = "\n".join(satirlar).strip()
                data = json.loads(metin)
                for alan in ("baslik", "icerik_html", "kategori", "etiketler", "gorsel_arama_terimi"):
                    if alan not in data:
                        raise ValueError(f"Eksik JSON alani: {alan}")
                data["kategori"] = kategori_normalize(data.get("kategori"))
                temiz = []
                yasak = {"teknoloji", "teknoloji haberleri", "güncel teknoloji", "guncel teknoloji", "gündem", "gundem", "dijital dünya", "dijital dunya"}
                for e in data.get("etiketler", []):
                    e = str(e).strip()
                    if e and e.lower() not in yasak and e.lower() != data["kategori"].lower() and e not in temiz:
                        temiz.append(e)
                data["etiketler"] = temiz[:5]
                print(f"Gemini basarili: {model}")
                return data, True
            except Exception as e:
                hata = str(e)
                gecici = any(isaret in hata for isaret in gecici_isaretler)
                print(f"Gemini {model} deneme {deneme}/{len(beklemeler)} hatasi: {e}")

                if not gecici:
                    print(f"Kalici/istek hatasi gorundu; {model} icin tekrar denenmeyecek.")
                    break

                if deneme < len(beklemeler):
                    bekle = temel_bekleme + random.uniform(0.5, 2.0)
                    print(f"Gecici hata; {bekle:.1f} saniye sonra yeniden denenecek.")
                    time.sleep(bekle)
                else:
                    print(f"{model} gecici hatalar nedeniyle kullanilamadi; fallback modele geciliyor.")

    return None, False


# ============================================================
# ICERIK YARDIMCILARI
# ============================================================

def entry_ozet(entry):
    ham = entry.get("summary") or entry.get("description") or ""
    if not ham and entry.get("content"):
        try:
            ham = entry.content[0].value
        except Exception:
            ham = ""
    soup = BeautifulSoup(ham, "html.parser")
    metin = " ".join(soup.stripped_strings)
    return html.unescape(metin)[:12000]


def kapak_html(gorsel_url, baslik, gorsel_kaynagi=None, fotografci=None):
    if not gorsel_url:
        return ""
    alt = html.escape(baslik, quote=True)
    url = html.escape(gorsel_url, quote=True)
    kredi = ""
    if gorsel_kaynagi == "Pexels" and fotografci:
        kredi = f'<p style="font-size:12px;color:#777;margin:6px 0 18px">Görsel: Pexels / {html.escape(str(fotografci))}</p>'
    return (
        '<div class="netdijital-cover" style="width:100%;aspect-ratio:16/9;overflow:hidden;'
        'border-radius:8px;margin:0 0 18px">'
        f'<img src="{url}" alt="{alt}" loading="eager" style="width:100%;height:100%;object-fit:cover;object-position:center;display:block" />'
        '</div>' + kredi
    )


def kaynak_html(kaynak_adi, kaynak_url):
    ad = html.escape(kaynak_adi or "Orijinal kaynak")
    u = html.escape(kaynak_url or "#", quote=True)
    return (
        '<hr style="margin:28px 0 16px;border:0;border-top:1px solid #e5e5e5">'
        '<p style="font-size:14px"><strong>Kaynak:</strong> '
        f'<a href="{u}" rel="nofollow noopener" target="_blank">{ad}</a></p>'
    )


# ============================================================
# BLOGGER
# ============================================================

def blogger_yayinla(access_token, baslik, icerik, etiketler, taslak=False):
    if not access_token or not BLOGGER_BLOG_ID:
        return None
    endpoint = f"https://www.googleapis.com/blogger/v3/blogs/{BLOGGER_BLOG_ID}/posts/"
    params = {"isDraft": "true" if taslak else "false"}
    headers = {"Authorization": f"Bearer {access_token}", "Content-Type": "application/json; charset=UTF-8"}
    payload = {"kind": "blogger#post", "title": baslik, "content": icerik, "labels": etiketler}
    try:
        r = requests.post(endpoint, headers=headers, params=params, json=payload, timeout=30)
        if r.status_code in (200, 201):
            return r.json()
        print("Blogger yayin hatasi:", r.status_code, r.text)
    except Exception as e:
        print(f"Blogger istek hatasi: {e}")
    return None


def gerekli_ayarlar_tamam():
    # Test modunda Blogger kimlik bilgilerine ihtiyac yoktur ve
    # Blogger'a hicbir baglanti kurulmaz.
    gerekli = {"GEMINI_API_KEY": GEMINI_API_KEY}
    if not TEST_MODU:
        gerekli.update({
            "BLOGGER_CLIENT_ID": CLIENT_ID,
            "BLOGGER_CLIENT_SECRET": CLIENT_SECRET,
            "BLOGGER_REFRESH_TOKEN": REFRESH_TOKEN,
            "BLOGGER_BLOG_ID": BLOGGER_BLOG_ID,
        })
    eksik = [k for k, v in gerekli.items() if not v]
    if eksik:
        print("Eksik ortam degiskenleri:", ", ".join(eksik))
        return False
    return True


# ============================================================
# ANA AKIS
# ============================================================

def main():
    if not gerekli_ayarlar_tamam():
        return

    history = load_history()
    yayinlanan = set(history.get("yayinlanan_linkler", []))
    kaynak_sayisi = len(RSS_SOURCES)
    baslangic = int(history.get("son_kaynak_index", 0)) % kaynak_sayisi

    secilen = None
    secilen_kaynak = None
    secilen_index = None

    # Her calismada kaynaklari sirayla dolas; ilk yeni haberi sec.
    for offset in range(kaynak_sayisi):
        idx = (baslangic + offset) % kaynak_sayisi
        kaynak = RSS_SOURCES[idx]
        feed = fetch_feed(kaynak["url"], kaynak["kaynak"])
        for entry in feed.entries[:12]:
            link = normalize_url(entry.get("link"))
            baslik = (entry.get("title") or "").strip()
            if link and baslik and link not in yayinlanan:
                secilen = entry
                secilen_kaynak = kaynak
                secilen_index = idx
                break
        if secilen:
            break

    if not secilen:
        print("Yeni haber bulunamadi.")
        return

    kaynak_url = normalize_url(secilen.get("link"))
    orijinal_baslik = html.unescape((secilen.get("title") or "").strip())
    ozet = entry_ozet(secilen)
    print(f"Secilen haber: {orijinal_baslik}")

    makale, ok = llm_ile_makale_uret(orijinal_baslik, ozet)
    if not ok or not makale:
        print("Makale uretilemedi; yayin yapilmadi.")
        return

    kategori = kategori_normalize(makale.get("kategori"))
    etiketler = [kategori] + [e for e in makale.get("etiketler", []) if e != kategori]
    etiketler = etiketler[:6]  # 1 ana kategori + en fazla 5 kontrollu etiket

    gorsel_url, gorsel_kaynagi, fotografci = en_iyi_gorseli_sec(
        secilen,
        kaynak_url,
        makale.get("gorsel_arama_terimi", "technology"),
        kategori,
        makale.get("baslik", orijinal_baslik),
    )

    icerik = (
        kapak_html(gorsel_url, makale["baslik"], gorsel_kaynagi, fotografci)
        + makale.get("icerik_html", "")
        + kaynak_html(secilen_kaynak["kaynak"], kaynak_url)
    )

    if TEST_MODU:
        print("\n" + "=" * 64)
        print("[NETDIJITAL GUVENLI TEST MODU]")
        print("Blogger API: DEVRE DISI (OAuth/token ve posts.insert cagrilmaz)")
        print(f"Baslik        : {makale.get('baslik', orijinal_baslik)}")
        print(f"Ana kategori  : {kategori}")
        print(f"Etiketler     : {', '.join(etiketler)}")
        print(f"Gorsel kaynagi: {gorsel_kaynagi or 'yok'}")
        print(f"Kapak URL     : {gorsel_url or 'yok'}")
        print(f"Kapak hedefi  : 1200x675")
        print(f"Kaynak        : {secilen_kaynak['kaynak']} - {kaynak_url}")
        print(f"HTML uzunlugu : {len(icerik)} karakter")
        print("SONUC          : BLOGGER YAYINI ATLANDI")
        print("=" * 64)
        # Testte history guncellenmez; ayni haber tekrar test edilebilir.
        return

    token = get_access_token(CLIENT_ID, CLIENT_SECRET, REFRESH_TOKEN)
    if not token:
        print("Google access token alinamadi.")
        return

    sonuc = blogger_yayinla(
        token,
        makale["baslik"],
        icerik,
        etiketler,
        TASLAK_OLARAK_KAYDET,
    )
    if not sonuc:
        print("Yayin basarisiz; history guncellenmedi.")
        return

    yayinlanan.add(kaynak_url)
    history["yayinlanan_linkler"] = list(yayinlanan)
    history["son_kaynak_index"] = (secilen_index + 1) % kaynak_sayisi
    history["son_paylasim_zamani"] = int(time.time())
    save_history(history)
    github_history_save()

    durum = "Taslak" if TASLAK_OLARAK_KAYDET else "Yayinlandi"
    print(f"{durum}: {sonuc.get('url') or sonuc.get('id')}")
    print(f"Kategori: {kategori} | Etiketler: {', '.join(etiketler)}")
    print(f"Gorsel: {gorsel_kaynagi or 'yok'} - {gorsel_url or 'fallback tanimsiz'}")


if __name__ == "__main__":
    try:
        main()
    except Exception:
        traceback.print_exc()
        raise
