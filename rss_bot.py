# NetDijital v1.3.12 - Tam Genislik 16:9 Kapak + v1.3.11 Guvenli Sistem
# NetDijital rss_bot.py v1.3.6 - Gorsel alaka kontrolu ve gelismis Pexels aramasi
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

def pexels_gorsel_bul(anahtar_kelime, adet=5):
    if not PEXELS_API_KEY or not anahtar_kelime: return []
    try:
        response=requests.get("https://api.pexels.com/v1/search",headers={"Authorization":PEXELS_API_KEY},params={"query":anahtar_kelime,"per_page":max(1,min(int(adet),10)),"orientation":"landscape"},timeout=15)
        if response.status_code!=200:
            print(f"Pexels arama hatasi: HTTP {response.status_code}"); return []
        sonuc=[]
        for photo in response.json().get("photos",[]) or []:
            src=photo.get("src",{}) or {}; url=src.get("large2x") or src.get("large") or src.get("original")
            if url: sonuc.append({"url":url,"fotografci":photo.get("photographer","Pexels"),"alt":(photo.get("alt") or "").strip()})
        print(f"Pexels aramasi: '{anahtar_kelime}' | {len(sonuc)} aday"); return sonuc
    except Exception as e:
        print(f"Pexels hatasi: {e}"); return []

def gorsel_alaka_kontrol(im, haber_basligi, arama_terimi, kaynak):
    """Gemini kotasi harcamadan kapak adayini kabul eder.

    Teknik kalite/boyut/oran kontrolu gorsel_tani_kontrol() tarafindan yapilir.
    RSS ve kaynak sayfa gorselleri haber baglamindan geldigi icin; Pexels
    adaylari ise botun somut Ingilizce arama terimiyle getirildigi icin burada
    ek bir Gemini vision istegi yapilmaz.
    """
    if kaynak == "Pexels":
        neden = f"Pexels arama terimiyle eslesti: {arama_terimi}"
    else:
        neden = "Haber RSS/kaynak sayfasindan gelen gorsel adayi"
    print(f"Gorsel alaka ({kaynak}): AI kullanilmadi | {neden}")
    return True, neden


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


YAZAR_BY_KATEGORI = {
    "Yapay Zekâ": "Sıla Elif",
    "Mobil": "Ömer Cin",
    "Bilgisayar": "İzzet Sarıkaya",
    "Oyun": "Güneş Yücel",
    "Otomotiv": "Murat Üşengeç",
    "Uzay": "Miraç Demir",
    "Dizi & Sinema": "Metin Oktay",
    "Rehberler": "Ege Özdemir",
}


def kategori_yazari(kategori):
    return YAZAR_BY_KATEGORI.get(kategori_normalize(kategori), "NetDijital")


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
        # AVIF/WebP gibi modern formatlar cok iyi sikistirilabildigi icin
        # dosya boyutunu kalite olcutu olarak kullanmiyoruz.
        if not r.content or len(r.content) > 15 * 1024 * 1024:
            return None, None
        im = Image.open(io.BytesIO(r.content))
        im.load()
        return im, r.content
    except Exception:
        return None, None


def gorsel_tani_kontrol(url, kaynak="Bilinmeyen"):
    """Kapak adayini ayrintili kontrol eder ve neden kabul/red edildigini loglar.

    Donus: (uygun_mu, image, ham_bytes)
    """
    if not url or not str(url).startswith(("http://", "https://")):
        print(f"Gorsel RED ({kaynak}) - neden: gecersiz URL: {url}")
        return False, None, None

    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/153.0 Safari/537.36",
            "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
            "Referer": url,
        }
        r = requests.get(url, headers=headers, timeout=20, allow_redirects=True)
        print(f"Gorsel kontrol ({kaynak}): HTTP {r.status_code} | {r.url[:140]}")
        if r.status_code != 200:
            print(f"Gorsel RED ({kaynak}) - neden: HTTP {r.status_code}")
            return False, None, None

        ct = (r.headers.get("content-type") or "").lower()
        boyut = len(r.content)
        print(f"  Content-Type: {ct or 'bilinmiyor'} | Dosya: {boyut/1024:.1f} KB")
        if not ct.startswith("image/"):
            print(f"Gorsel RED ({kaynak}) - neden: yanit bir gorsel degil ({ct or 'Content-Type yok'})")
            return False, None, None
        # Dosya boyutu tek basina kalite gostergesi degildir. Ozellikle AVIF/WebP
        # 25 KB altinda olsa bile yeterli piksel boyutunda olabilir.
        if boyut <= 0:
            print(f"Gorsel RED ({kaynak}) - neden: bos dosya")
            return False, None, None
        if boyut > 15 * 1024 * 1024:
            print(f"Gorsel RED ({kaynak}) - neden: dosya cok buyuk ({boyut/1024/1024:.1f} MB > 15 MB)")
            return False, None, None

        try:
            im = Image.open(io.BytesIO(r.content))
            im.load()
        except Exception as e:
            print(f"Gorsel RED ({kaynak}) - neden: Pillow acamadi: {type(e).__name__}: {e}")
            return False, None, None

        w, h = im.size
        oran = w / h if h else 0
        print(f"  Piksel: {w}x{h} | Oran: {oran:.3f} | Format: {im.format or 'bilinmiyor'}")
        if w < 800:
            print(f"Gorsel RED ({kaynak}) - neden: genislik yetersiz ({w}px < 800px)")
            return False, None, None
        if h < 450:
            print(f"Gorsel RED ({kaynak}) - neden: yukseklik yetersiz ({h}px < 450px)")
            return False, None, None
        if oran < 1.30:
            print(f"Gorsel RED ({kaynak}) - neden: fazla dikey/kare (oran {oran:.3f} < 1.30)")
            return False, None, None
        if oran > 2.50:
            print(f"Gorsel RED ({kaynak}) - neden: fazla panoramik (oran {oran:.3f} > 2.50)")
            return False, None, None

        print(f"Gorsel KABUL ({kaynak}): {w}x{h} -> 1200x675 islenecek")
        return True, im, r.content
    except requests.Timeout:
        print(f"Gorsel RED ({kaynak}) - neden: indirme zaman asimi")
    except requests.RequestException as e:
        print(f"Gorsel RED ({kaynak}) - neden: HTTP/Ag hatasi: {type(e).__name__}: {e}")
    except Exception as e:
        print(f"Gorsel RED ({kaynak}) - neden: beklenmeyen hata: {type(e).__name__}: {e}")
    return False, None, None


def gorsel_boyutu_kontrol(url):
    """Eski cagri uyumlulugu; ayrintili kontrol yeni secicide kullanilir."""
    uygun, _, _ = gorsel_tani_kontrol(url)
    return uygun


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
    if w < 800 or h < 450:
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
        # GitHub Contents API: ayni path zaten varsa guncelleme icin SHA zorunludur.
        # Tekrarlanan testlerde ayni baslik + ayni JPEG ayni dosya adini uretebilir.
        # Once mevcut dosyayi kontrol edip SHA'yi PUT payload'ina ekliyoruz.
        sha = None
        mevcut = requests.get(
            api_url,
            headers=headers,
            params={"ref": GITHUB_BRANCH},
            timeout=20,
        )
        if mevcut.status_code == 200:
            sha = mevcut.json().get("sha")
            print(f"Kapak GitHub'da zaten mevcut; SHA ile guncellenecek: {path}")
        elif mevcut.status_code != 404:
            print(
                "Kapak GitHub mevcut dosya kontrol hatasi:",
                mevcut.status_code,
                mevcut.text[:500],
            )

        payload = {
            "message": (f"Update cover: {filename}" if sha else f"Add cover: {filename}"),
            "content": base64.b64encode(jpeg_bytes).decode("ascii"),
            "branch": GITHUB_BRANCH,
        }
        if sha:
            payload["sha"] = sha

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

    for p in pexels_gorsel_bul(arama_terimi, adet=5):
        adaylar.append((p["url"], "Pexels", p.get("fotografci")))

    gorulen = set()
    for u, kaynak, fotografci in adaylar:
        if not u or u in gorulen:
            continue
        gorulen.add(u)
        uygun, im, ham = gorsel_tani_kontrol(u, kaynak)
        if not uygun:
            continue
        alakali, alaka_nedeni = gorsel_alaka_kontrol(im, baslik, arama_terimi, kaynak)
        if not alakali:
            print(f"Gorsel RED ({kaynak}) - neden: haberle alaka yetersiz: {alaka_nedeni}")
            continue

        try:
            im = ImageOps.exif_transpose(im).convert("RGB")
            im = ImageOps.fit(im, (1200, 675), method=Image.Resampling.LANCZOS, centering=(0.5, 0.5))
            out = io.BytesIO()
            im.save(out, format="JPEG", quality=86, optimize=True, progressive=True)
            jpeg = out.getvalue()
            print(f"Gorsel islendi ({kaynak}): 1200x675 JPEG | {len(jpeg)/1024:.1f} KB")
        except Exception as e:
            print(f"Gorsel RED ({kaynak}) - neden: 1200x675 isleme hatasi: {type(e).__name__}: {e}")
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
9. Blogger etiketi olarak SADECE ana kategori kullanilacak. Ek etiket/TAG uretme.
10. Marka, urun, platform, kaynak site adi veya genel teknoloji terimlerini etiket olarak uretme.
11. Gorsel arama terimi 3-7 kelimelik, somut ve Ingilizce olsun. Urun/marka/model haberinde marka + model + nesne turunu mutlaka icersin. technology, AI, innovation gibi tek basina genel stok terimleri kullanma.
12. Meta aciklamasi yaklasik 140-160 karakter olsun.
13. Sadece gecerli JSON dondur.

JSON:
{{
  "baslik": "...",
  "icerik_html": "<p>...</p><h2>...</h2><p>...</p>",
  "meta_aciklama": "...",
  "kategori": "Yapay Zekâ",
  "gorsel_arama_terimi": "Google Gemini AI interface"
}}
"""

    # Kota optimizasyonu:
    # - 429/RESOURCE_EXHAUSTED: ayni modele tekrar istek atma, hemen fallback'e gec.
    # - 503/UNAVAILABLE ve diger gecici 5xx: ayni modelde yalnizca 1 kez tekrar dene.
    # Normal akista haber uretimi tek Gemini istegidir.
    modeller = ["gemini-3.6-flash", "gemini-3.5-flash-lite"]
    gecici_isaretler = ("408", "500", "502", "503", "504",
                        "UNAVAILABLE", "DEADLINE_EXCEEDED")
    kota_isaretleri = ("429", "RESOURCE_EXHAUSTED", "quota", "Quota")
    max_deneme = 2

    for model in modeller:
        print(f"Gemini modeli deneniyor: {model}")
        for deneme in range(1, max_deneme + 1):
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
                for alan in ("baslik", "icerik_html", "kategori", "gorsel_arama_terimi"):
                    if alan not in data:
                        raise ValueError(f"Eksik JSON alani: {alan}")
                data["kategori"] = kategori_normalize(data.get("kategori"))
                # NetDijital kurali: Blogger tarafinda tam olarak 1 etiket = ana kategori.
                data["etiketler"] = [data["kategori"]]
                print(f"Gemini basarili: {model}")
                return data, True
            except Exception as e:
                hata = str(e)
                kota = any(isaret in hata for isaret in kota_isaretleri)
                gecici = any(isaret in hata for isaret in gecici_isaretler)
                print(f"Gemini {model} deneme {deneme}/{max_deneme} hatasi: {e}")

                if kota:
                    print(f"Kota siniri algilandi; {model} tekrar denenmeden fallback modele geciliyor.")
                    break
                if not gecici:
                    print(f"Kalici/istek hatasi gorundu; {model} icin tekrar denenmeyecek.")
                    break
                if deneme < max_deneme:
                    bekle = 5 + random.uniform(0.5, 1.5)
                    print(f"Gecici servis hatasi; yalnizca 1 tekrar yapilacak. {bekle:.1f} saniye bekleniyor.")
                    time.sleep(bekle)
                else:
                    print(f"{model} gecici hata nedeniyle kullanilamadi; fallback modele geciliyor.")

    return None, False


# ============================================================
# AI ICERIK KALITE KONTROLU
# ============================================================

def makale_kalite_kontrol(makale, orijinal_baslik, orijinal_ozet):
    """Uretilen haberi kaynak RSS bilgisiyle ikinci kez kontrol eder.

    Baslik ve icerik_html duzeltilebilir. Kategori, etiketler ve gorsel arama
    terimi ilk uretimden korunur; boylece kalite kontrolu yayin siniflandirmasini
    gereksiz yere degistirmez.
    """
    if not client or not makale:
        return makale, False, ["Kalite kontrolu calistirilamadi"]

    prompt = f"""
Sen NetDijital'in ikinci asama Turkce haber kalite editorusun.

KAYNAK BASLIK:
{orijinal_baslik}

KAYNAK OZET:
{orijinal_ozet}

URETILEN BASLIK:
{makale.get("baslik", "")}

URETILEN HABER HTML:
{makale.get("icerik_html", "")}

GOREV:
Uretilen haberi yalnizca yukaridaki kaynak baslik ve kaynak ozet ile
karsilastir. Disaridan yeni bilgi ekleme.

KONTROL KURALLARI:
1. Kaynakta desteklenmeyen rakam, teknik ozellik, tarih, fiyat, alinti,
   sirket aciklamasi, kesin gelecek iddiasi veya neden-sonuc iddiasi varsa kaldir.
2. Baslik kaynak tarafindan desteklenmeli; clickbait, abarti veya kaynakta
   olmayan kesinlik icermemeli.
3. Ayni bilgi tekrar ediyorsa tek ve guclu anlatima indir.
4. Turkce dogal, haber diliyle ve akici olsun.
5. "teknoloji dunyasinda heyecan yaratti", "dikkatleri uzerine cekiyor",
   "gelecege isik tutuyor", "devrim yaratacak", "oyunun kurallarini degistirecek"
   gibi kanitsiz AI/clickbait kaliplarini temizle.
6. Kaynak bilgi azsa haberi yapay olarak uzatma. Kaynakta olmayan bilgiyle
   600-1000 kelime hedefine ulasmaya calisma.
7. HTML'de yalnizca temiz paragraf ve gerektiginde h2 kullan; kaynak linki,
   kaynak site adresi veya yeni kaynak ekleme.
8. Anlami degistirmeden yazim ve noktalama sorunlarini duzelt.
9. Sadece gecerli JSON dondur.

JSON:
{{
  "durum": "TEMIZ" veya "DUZELTILDI",
  "sorunlar": ["kisa sorun aciklamasi"],
  "baslik": "...",
  "icerik_html": "<p>...</p>..."
}}
"""

    modeller = ["gemini-3.6-flash", "gemini-3.5-flash-lite"]
    gecici_isaretler = ("408", "500", "502", "503", "504",
                        "UNAVAILABLE", "DEADLINE_EXCEEDED")
    kota_isaretleri = ("429", "RESOURCE_EXHAUSTED", "quota", "Quota")
    max_deneme = 2

    for model in modeller:
        print(f"Kalite kontrol modeli deneniyor: {model}")
        for deneme in range(1, max_deneme + 1):
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

                kontrol = json.loads(metin)
                yeni_baslik = str(kontrol.get("baslik") or makale.get("baslik") or "").strip()
                yeni_html = str(kontrol.get("icerik_html") or makale.get("icerik_html") or "").strip()
                if not yeni_baslik or not yeni_html:
                    raise ValueError("Kalite kontrolu bos baslik/icerik dondurdu.")

                sorunlar = kontrol.get("sorunlar") or []
                if not isinstance(sorunlar, list):
                    sorunlar = [str(sorunlar)]
                sorunlar = [str(s).strip() for s in sorunlar if str(s).strip()][:8]

                duzeltilmis = dict(makale)
                duzeltilmis["baslik"] = yeni_baslik
                duzeltilmis["icerik_html"] = yeni_html

                durum = str(kontrol.get("durum") or "TEMIZ").upper()
                print(f"Kalite kontrolu tamamlandi: {durum} | model={model}")
                if sorunlar:
                    for sorun in sorunlar:
                        print(f"  Kalite notu: {sorun}")
                else:
                    print("  Kalite notu: sorun bulunmadi")

                return duzeltilmis, True, sorunlar

            except Exception as e:
                hata = str(e)
                kota = any(isaret in hata for isaret in kota_isaretleri)
                gecici = any(isaret in hata for isaret in gecici_isaretler)
                print(f"Kalite kontrol {model} deneme {deneme}/{max_deneme} hatasi: {e}")

                if kota:
                    print(f"Kalite kontrolunde kota siniri algilandi; {model} tekrar denenmeden fallback modele geciliyor.")
                    break
                if not gecici:
                    print(f"Kalite kontrolunde kalici/istek hatasi; {model} tekrar denenmeyecek.")
                    break
                if deneme < max_deneme:
                    bekle = 5 + random.uniform(0.5, 1.5)
                    print(f"Kalite kontrol gecici servis hatasi; yalnizca 1 tekrar yapilacak. {bekle:.1f} saniye bekleniyor.")
                    time.sleep(bekle)
                else:
                    print(f"Kalite kontrol icin {model} kullanilamadi; fallback modele geciliyor.")

    print("Kalite kontrolu tamamlanamadi; guvenlik geregi yayin akisi durdurulacak.")
    return makale, False, ["Kalite kontrolu tamamlanamadi"]


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
    """Ana kapagi Blogger icerik kolonunda responsive ve tam genislikte gosterir.

    Kaynak dosya 1200x675 olarak korunur. Sabit piksel genisligi verilmez;
    boylece tema masaustunde kapagi gereksiz yere 400-500 px'e sikistiramaz,
    mobilde ise gorsel tasma yapmaz.
    """
    if not gorsel_url:
        return ""

    alt = html.escape(baslik, quote=True)
    url = html.escape(gorsel_url, quote=True)
    kredi = ""

    if gorsel_kaynagi == "Pexels" and fotografci:
        kredi = (
            '<p style="font-size:12px;color:#777;margin:6px 0 18px">'
            f'Görsel: Pexels / {html.escape(str(fotografci))}</p>'
        )

    return (
        '<div class="netdijital-cover" '
        'style="display:block;width:100%;max-width:none;margin:0 0 22px;'
        'padding:0;overflow:hidden;border-radius:8px;line-height:0">'
        f'<img src="{url}" alt="{alt}" loading="eager" fetchpriority="high" '
        'width="1200" height="675" '
        'style="display:block;width:100% !important;max-width:100% !important;'
        'height:auto !important;aspect-ratio:16/9;object-fit:cover;'
        'object-position:center;margin:0 !important;padding:0 !important" />'
        '</div>' + kredi
    )

def cta_html(kategori=None):
    """Her haberin sonunda gosterilen standart NetDijital takip kutusu."""
    kategori = kategori_normalize(kategori)
    kategori_guvenli = html.escape(kategori)
    return (
        '<div class="netdijital-cta" style="margin:30px 0 26px;padding:24px 26px;'
        'border:1px solid #dbeafe;border-radius:12px;background:#f8fbff;text-align:center">'
        '<div style="font-size:28px;line-height:1;margin-bottom:10px">&#128240;</div>'
        '<h3 style="margin:0 0 8px;font-size:20px;line-height:1.35">'
        'Teknoloji dünyasındaki gelişmeleri kaçırmayın</h3>'
        '<p style="margin:0 auto 16px;max-width:680px;color:#555;line-height:1.65">'
        f'{kategori_guvenli} ve teknoloji dünyasından güncel gelişmeleri NetDijital’de takip edin.</p>'
        '<a href="https://netdijital.blogspot.com/" '
        'style="display:inline-block;padding:10px 18px;border-radius:7px;background:#1565c0;'
        'color:#fff;text-decoration:none;font-weight:600">Daha Fazla Haber &#8594;</a>'
        '</div>'
    )


def kaynak_html(kaynak_adi, kaynak_url=None):
    """Haber sonunda yalnizca kaynak adini gosterir; URL gorunmez ve tiklanamaz."""
    # kaynak_url botun haber secimi/dogrulamasi icin tutulur; makale HTML'ine eklenmez.
    ad = html.escape(kaynak_adi or "Orijinal kaynak")
    return (
        '<div class="netdijital-sources" style="margin:26px 0 20px;padding-top:18px;'
        'border-top:1px solid #e5e7eb">'
        '<h3 style="margin:0 0 10px;font-size:18px;line-height:1.4">Kaynaklar</h3>'
        '<p style="margin:0;font-size:14px;line-height:1.7">'
        f'<strong>Kaynak:</strong> {ad}</p>'
        '</div>'
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

    makale, kalite_ok, kalite_sorunlari = makale_kalite_kontrol(
        makale, orijinal_baslik, ozet
    )
    if not kalite_ok:
        print("AI kalite kontrolu tamamlanamadi; guvenlik geregi yayin yapilmadi.")
        return

    kategori = kategori_normalize(makale.get("kategori"))
    yazar = kategori_yazari(kategori)
    # NetDijital kurali: 1 haber = 1 Blogger etiketi = ana kategori.
    # Marka/urun/platform adlari artik Blogger TAG olarak gonderilmez.
    etiketler = [kategori]

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
        + cta_html(kategori)
        + kaynak_html(secilen_kaynak["kaynak"], kaynak_url)
    )

    if TEST_MODU:
        print("\n" + "=" * 64)
        print("[NETDIJITAL GUVENLI TEST MODU]")
        print("Blogger API: DEVRE DISI (OAuth/token ve posts.insert cagrilmaz)")
        print(f"Baslik        : {makale.get('baslik', orijinal_baslik)}")
        print(f"Ana kategori  : {kategori}")
        print(f"Kategori yazari: {yazar}")
        print(f"Etiketler     : {', '.join(etiketler)}")
        print(f"Gorsel kaynagi: {gorsel_kaynagi or 'yok'}")
        print(f"Kapak URL     : {gorsel_url or 'yok'}")
        print(f"Kapak hedefi  : 1200x675")
        print(f"Kaynak        : {secilen_kaynak['kaynak']}")
        print(f"Kalite kontrol: BASARILI")
        if kalite_sorunlari:
            print(f"Kalite notlari: {' | '.join(kalite_sorunlari)}")
        else:
            print("Kalite notlari: sorun bulunmadi")
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
