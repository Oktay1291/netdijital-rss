# NetDijital v2.0 - Saatlik Otomatik Haber + Ucretsiz AI Gorsel Uretimi
# Degisiklikler (v1.3.15 -> v2.0):
#   - Pexels stok fotograf aramasi kaldirildi; her haber icin Pollinations.ai
#     ile UCRETSIZ, anahtarsiz, 16:9 (1200x675) ozgun AI kapak gorseli uretiliyor.
#   - Kelime hedefi 800-1200 olarak guncellendi.
#   - RSS_SOURCES'a birinci elden buyuk teknoloji sirketi (Apple/Google/Samsung/
#     Microsoft) resmi duyuru feed'leri eklendi.
#   - YAYIN_SIKLIGI_DK ile calisma sikligini (varsayilan: saatte bir) tek yerden
#     kontrol edebilirsin; GitHub Actions cron ayari da bununla uyumlu olmali.
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
from urllib.parse import urljoin, quote

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

GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")
GITHUB_REPOSITORY = os.getenv("GITHUB_REPOSITORY")
GITHUB_BRANCH = os.getenv("GITHUB_REF_NAME", "main")

HISTORY_FILE = "posted_history.json"
MAX_GECMIS_LINK = 3000

# False = direkt yayınla / True = Blogger'da taslak oluştur
TASLAK_OLARAK_KAYDET = False

# Bilgi amacli: bu betik tek calismada TEK haber uretir. Saatte bir mi,
# 3 saatte bir mi calisacagini GitHub Actions workflow'undaki cron belirler
# (bkz. .github/workflows/saatlik-haber.yml). Icerik kalitesi ve AdSense
# acisindan 24 haber/gun yerine daha seyrek (orn. 6-8 haber/gun) baslamak
# daha guvenli bir secimdir; workflow dosyasindaki cron satirini degistirerek
# bunu istedigin an ayarlayabilirsin, kod tarafinda bir sey degismez.

# ============================================================
# GUVENLI TEST MODU
# ============================================================
TEST_MODU = os.getenv("TEST_MODU", "true").strip().lower() in {"1", "true", "yes", "on"}


# ============================================================
# GEMINI
# ============================================================

client = genai.Client(api_key=GEMINI_API_KEY) if GEMINI_API_KEY else None


# ============================================================
# RSS KAYNAKLARI
# ============================================================
# Not: Hepsi herkese acik, ucretsiz RSS feed'leridir. Google aramasi veya
# Google Haberler kazima (scraping) YAPILMAZ; bu yuzden Google tarafindan
# bot/erisim kisitlamasina takilma riski yoktur.

RSS_SOURCES = [
    # --- Turk teknoloji siteleri ---
    {"kaynak": "CHIP Online", "url": "https://www.chip.com.tr/rss"},
    {"kaynak": "DonanımHaber", "url": "https://www.donanimhaber.com/rss/tumhaberler.xml"},
    {"kaynak": "ShiftDelete.Net", "url": "https://shiftdelete.net/feed"},
    {"kaynak": "Webtekno", "url": "https://www.webtekno.com/rss"},
    {"kaynak": "Tamindir", "url": "https://www.tamindir.com/rss/"},
    {"kaynak": "TechReview", "url": "https://techreview.com.tr/feed/"},
    {"kaynak": "Teknolojioku", "url": "https://www.teknolojioku.com/rss"},
    {"kaynak": "Techolay", "url": "https://techolay.net/feed/"},
    {"kaynak": "Teknoblog", "url": "https://www.teknoblog.com/feed/"},

    # --- Birinci elden buyuk teknoloji sirketi duyurulari (resmi RSS) ---
    # Bu kaynaklar sirketlerin kendi resmi haber/blog feed'leridir; "ikinci
    # elden" bir teknoloji sitesinin yorumu degil, dogrudan sirket aciklamasidir.
    {"kaynak": "Google Blog", "url": "https://blog.google/rss/"},
    {"kaynak": "Microsoft News", "url": "https://news.microsoft.com/feed/"},
    {"kaynak": "Samsung Newsroom", "url": "https://news.samsung.com/global/feed"},
    # Apple resmi bir genel RSS yayinlamadiginda bu kaynak otomatik atlanir
    # (fetch_feed hata verirse bos donup bir sonraki kaynaga gecilir).
    {"kaynak": "Apple Newsroom", "url": "https://www.apple.com/newsroom/rss-feed.rss"},
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
        "grant_type": "refresh_token",
    }
    try:
        r = requests.post(token_url, data=payload, timeout=20)
    except requests.exceptions.RequestException as e:
        print(f"Token yenileme hatasi: {e}")
        return None
    if r.status_code == 200:
        return r.json().get("access_token")
    print(f"Token yenileme hatasi: {r.status_code} - {r.text}")
    return None


# ============================================================
# HISTORY
# ============================================================

def load_history():
    default_data = {
        "yayinlanan_linkler": [],
        "son_kaynak_index": 0,
        "son_paylasim_zamani": 0,
    }
    if not os.path.exists(HISTORY_FILE):
        return default_data
    try:
        with open(HISTORY_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        data.setdefault("yayinlanan_linkler", [])
        data.setdefault("son_kaynak_index", 0)
        data.setdefault("son_paylasim_zamani", 0)
        return data
    except Exception as e:
        print(f"History okunamadi: {e}")
        return default_data


def save_history(data):
    data["yayinlanan_linkler"] = data["yayinlanan_linkler"][-MAX_GECMIS_LINK:]
    with open(HISTORY_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def github_history_save():
    if not GITHUB_TOKEN or not GITHUB_REPOSITORY or not os.path.exists(HISTORY_FILE):
        return False
    try:
        with open(HISTORY_FILE, "rb") as f:
            content = base64.b64encode(f.read()).decode("utf-8")
        api_url = f"https://api.github.com/repos/{GITHUB_REPOSITORY}/contents/{HISTORY_FILE}"
        headers = {
            "Authorization": f"Bearer {GITHUB_TOKEN}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        mevcut = requests.get(api_url, headers=headers, timeout=20)
        sha = mevcut.json().get("sha") if mevcut.status_code == 200 else None
        payload = {"message": "Update posted history", "content": content, "branch": GITHUB_BRANCH}
        if sha:
            payload["sha"] = sha
        response = requests.put(api_url, headers=headers, json=payload, timeout=30)
        if response.status_code in (200, 201):
            print("posted_history.json GitHub'a kaydedildi.")
            return True
        print("GitHub history kayit hatasi:", response.status_code, response.text)
    except Exception as e:
        print(f"GitHub history hatasi: {e}")
    return False


# ============================================================
# RSS
# ============================================================

def fetch_feed(url, kaynak_adi="Kaynak"):
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                       "(KHTML, like Gecko) Chrome/153.0 Safari/537.36",
        "Accept": "application/rss+xml, application/xml, text/xml, */*",
    }
    try:
        response = requests.get(url, headers=headers, timeout=20)
        response.raise_for_status()
        return feedparser.parse(response.content)
    except Exception as e:
        print(f"Feed alinamadi [{kaynak_adi}]: {e}")
        return feedparser.parse("")


def normalize_url(url):
    if not url:
        return None
    return url.strip()


# ============================================================
# WEB SAYFASINDAN OG IMAGE (yalnizca haber dogrulama/baglam icin; kapak
# gorseli artik AI ile uretildigi icin bu fonksiyon yayinlanan gorseli
# belirlemez, yalnizca gelecekte ihtiyac olursa diye korunur)
# ============================================================

def sayfa_gorseli_bul(url):
    if not url:
        return None
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/153.0 Safari/537.36"
        }
        response = requests.get(url, headers=headers, timeout=15)
        if response.status_code != 200:
            return None
        soup = BeautifulSoup(response.text, "html.parser")
        og = soup.find("meta", property="og:image")
        if og and og.get("content"):
            return og["content"].strip()
    except Exception as e:
        print(f"Web gorsel hatasi: {e}")
    return None


# ============================================================
# NETDIJITAL KATEGORI SISTEMI
# ============================================================

ANA_KATEGORILER = [
    "Yapay Zekâ", "Mobil", "Bilgisayar", "Oyun",
    "Otomotiv", "Uzay", "Dizi & Sinema", "Rehberler"
]

FALLBACK_REPOSITORY = GITHUB_REPOSITORY or "Oktay1291/netdijital-rss"
FALLBACK_BRANCH = GITHUB_BRANCH or "main"
FALLBACK_BASE_URL = (
    f"https://raw.githubusercontent.com/{FALLBACK_REPOSITORY}/{FALLBACK_BRANCH}/assets/fallback"
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
    "Mobil": "Ömer Aylaz",
    "Bilgisayar": "İzzet Sarıkaya",
    "Oyun": "Güneş Yücel",
    "Otomotiv": "Murat Üşengeç",
    "Uzay": "Miraç Demir",
    "Dizi & Sinema": "Metin Oktay",
    "Rehberler": "Ege Özdemir",
}


def kategori_yazari(kategori):
    return YAZAR_BY_KATEGORI.get(kategori_normalize(kategori), "NetDijital")


# ============================================================
# UCRETSIZ AI GORSEL URETIMI (Pollinations.ai - anahtarsiz, ucretsiz)
# ============================================================
# Pollinations.ai herkese acik, API anahtari gerektirmeyen ucretsiz bir
# gorsel uretim servisidir. Istek basina bir Flux modeliyle gorsel uretir.
# Ticari/resmi bir SLA sunmaz; bu yuzden basarisiz olursa kategori fallback
# kapagina (KATEGORI_FALLBACK) guvenli sekilde dusulur.

POLLINATIONS_BASE = "https://image.pollinations.ai/prompt/"


def _ai_prompt_hazirla(gorsel_prompt_en, kategori):
    """Marka logosu/tanınabilir gercek kisi gibi riskli ogeleri azaltan,
    16:9 editoryal foto tarzi bir prompt üretir."""
    temel = (gorsel_prompt_en or "modern technology concept").strip()
    stil = (
        "professional editorial photography, realistic, high detail, "
        "16:9 wide shot, soft studio lighting, no text, no watermark, no logo"
    )
    return f"{temel}, {stil}"


def ai_gorsel_uret(gorsel_prompt_en, kategori=None, deneme=2):
    """Pollinations.ai ile 1200x675 (16:9) AI gorsel uretir ve ham JPEG bayt
    olarak dondurur. Basarisiz olursa None doner."""
    prompt = _ai_prompt_hazirla(gorsel_prompt_en, kategori)
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/153.0 Safari/537.36"
    }
    for i in range(1, deneme + 1):
        try:
            seed = random.randint(1, 999999)
            url = (
                f"{POLLINATIONS_BASE}{quote(prompt[:350])}"
                f"?width=1200&height=675&nologo=true&seed={seed}"
            )
            print(f"AI gorsel uretiliyor (deneme {i}/{deneme}): {prompt[:90]}...")
            r = requests.get(url, headers=headers, timeout=75)
            if r.status_code != 200:
                print(f"AI gorsel uretim hatasi: HTTP {r.status_code}")
                continue
            ct = (r.headers.get("content-type") or "").lower()
            if not ct.startswith("image/") or len(r.content) < 5000:
                print(f"AI gorsel uretim hatasi: gecersiz yanit ({ct}, {len(r.content)} bayt)")
                continue
            im = Image.open(io.BytesIO(r.content))
            im.load()
            im = im.convert("RGB")
            im = ImageOps.fit(im, (1200, 675), method=Image.Resampling.LANCZOS, centering=(0.5, 0.5))
            out = io.BytesIO()
            im.save(out, format="JPEG", quality=88, optimize=True, progressive=True)
            jpeg = out.getvalue()
            print(f"AI gorsel basarili: 1200x675 JPEG | {len(jpeg)/1024:.1f} KB")
            return jpeg
        except Exception as e:
            print(f"AI gorsel uretim hatasi (deneme {i}): {e}")
            time.sleep(2)
    return None


def _slugify(text):
    text = unicodedata.normalize("NFKD", str(text or ""))
    text = "".join(c for c in text if not unicodedata.combining(c))
    text = text.encode("ascii", "ignore").decode("ascii").lower()
    text = re.sub(r"[^a-z0-9]+", "-", text).strip("-")
    return (text[:70] or "haber")


def github_kapak_yukle(jpeg_bytes, baslik):
    """Uretilen 1200x675 kapagi repo'ya kaydeder ve public raw URL dondurur."""
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
        sha = None
        mevcut = requests.get(api_url, headers=headers, params={"ref": GITHUB_BRANCH}, timeout=20)
        if mevcut.status_code == 200:
            sha = mevcut.json().get("sha")
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


def kapak_gorseli_hazirla(gorsel_prompt_en, kategori, baslik):
    """Kapak gorseli secim sirasi: AI uretimi -> kategori fallback kapagi."""
    jpeg = ai_gorsel_uret(gorsel_prompt_en, kategori)
    if jpeg:
        hosted = github_kapak_yukle(jpeg, baslik)
        if hosted:
            return hosted, "NetDijital AI Görsel"
        print("AI gorsel GitHub'a yuklenemedi; kategori fallback kapagina duseluyor.")

    fallback = KATEGORI_FALLBACK.get(kategori)
    if fallback:
        print(f"Kategori fallback kapagi kullaniliyor: {kategori}")
        return fallback, "NetDijital kategori kapağı"

    print(f"Fallback bulunamadi: {kategori}")
    return None, None


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
3. 800-1200 Turkce kelime hedefle; bilgi yetersizse metni yapay olarak uzatma, ama
   mumkun oldugunca bu araliga yaklasmaya calis (baglam, karsilastirma, kullanici
   icin anlami gibi katma deger bolumleriyle).
4. Baslik bilgilendirici ve clickbait olmayan bir haber basligi olsun.
5. Giris paragrafi haberi dogrudan anlatsin; kisa paragraflar ve gerekli yerlerde H2 kullan.
6. "Bu yazida", "gelin bakalim", "heyecan verici" gibi kalip dolgu ifadelerinden kacın.
7. Spekulasyon, kullanici tepkisi veya sektor etkisi icin veri verilmemisse bunu olgu gibi uydurma.
8. Ana kategori TAM OLARAK su sekiz degerden biri olmali:
   Yapay Zekâ, Mobil, Bilgisayar, Oyun, Otomotiv, Uzay, Dizi & Sinema, Rehberler
9. Blogger etiketi olarak SADECE ana kategori kullanilacak. Ek etiket/TAG uretme.
10. Marka, urun, platform, kaynak site adi veya genel teknoloji terimlerini etiket olarak uretme.
11. gorsel_prompt alanini Ingilizce, 10-20 kelimelik, somut bir SAHNE tarifi olarak yaz
    (orn. "a sleek black smartphone on a wooden desk with soft blue light reflections").
    Gercek marka logosu, tanınabilir gercek bir kisi veya ekran goruntusu metni ISTEME;
    bunun yerine konuyu temsil eden genel/kavramsal bir sahne tarif et.
12. Meta aciklamasi yaklasik 140-160 karakter olsun.
13. Sadece gecerli JSON dondur.

JSON:
{{
  "baslik": "...",
  "icerik_html": "<p>...</p><h2>...</h2><p>...</p>",
  "meta_aciklama": "...",
  "kategori": "Yapay Zekâ",
  "gorsel_prompt": "a sleek black smartphone on a wooden desk with soft blue light reflections"
}}
"""

    modeller = ["gemini-3.6-flash", "gemini-3.5-flash-lite"]
    gecici_isaretler = ("408", "500", "502", "503", "504", "UNAVAILABLE", "DEADLINE_EXCEEDED")
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
                for alan in ("baslik", "icerik_html", "kategori", "gorsel_prompt"):
                    if alan not in data:
                        raise ValueError(f"Eksik JSON alani: {alan}")
                data["kategori"] = kategori_normalize(data.get("kategori"))
                data["etiketler"] = [data["kategori"]]

                kelime_sayisi = len(BeautifulSoup(data["icerik_html"], "html.parser").get_text().split())
                print(f"Uretilen icerik kelime sayisi: {kelime_sayisi}")
                if not (700 <= kelime_sayisi <= 1300):
                    print("UYARI: kelime sayisi hedeflenen 800-1200 araligindan belirgin sapiyor.")

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
   800-1200 kelime hedefine ulasmaya calisma.
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
    gecici_isaretler = ("408", "500", "502", "503", "504", "UNAVAILABLE", "DEADLINE_EXCEEDED")
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
                for sorun in sorunlar:
                    print(f"  Kalite notu: {sorun}")
                return duzeltilmis, True, sorunlar
            except Exception as e:
                hata = str(e)
                kota = any(isaret in hata for isaret in kota_isaretleri)
                gecici = any(isaret in hata for isaret in gecici_isaretler)
                print(f"Kalite kontrol {model} deneme {deneme}/{max_deneme} hatasi: {e}")
                if kota:
                    break
                if not gecici:
                    break
                if deneme < max_deneme:
                    time.sleep(5 + random.uniform(0.5, 1.5))

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


def haber_tam_metni_cek(url):
    """
    Haber sayfasindaki asil metni cekmeye calisir.
    Basarisiz veya yetersiz olursa None dondurur.
    """
    Basarisiz veya yetersiz olursa None dondurur.
    """
    if not url:
        return None

    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/153.0 Safari/537.36"
        ),
        "Accept-Language": "tr-TR,tr;q=0.9,en-US;q=0.8,en;q=0.7",
    }

    try:
        response = requests.get(url, headers=headers, timeout=20)
        response.raise_for_status()

        soup = BeautifulSoup(response.text, "html.parser")

        # Icerikle ilgisi olmayan bolumleri temizle.
        for etiket in soup([
            "script", "style", "noscript", "iframe",
            "nav", "footer", "header", "form",
            "aside", "button", "svg"
        ]):
            etiket.decompose()

        # Once standart <article> etiketini dene.
        aday = soup.find("article")

        # Article yoksa yaygin haber govdesi siniflarini dene.
        if not aday:
            seciciler = [
                '[itemprop="articleBody"]',
                ".article-content",
                ".article-body",
                ".post-content",
                ".post-body",
                ".entry-content",
                ".news-content",
                ".news-detail",
                ".content-detail",
                ".story-body",
            ]

            for secici in seciciler:
                aday = soup.select_one(secici)
                if aday:
                    break

        if not aday:
            print("Tam metin: haber govdesi bulunamadi.")
            return None

        # Haber govdesi icindeki paragraflari al.
        paragraflar = []

        for p in aday.find_all("p"):
            metin = " ".join(p.stripped_strings)
            metin = html.unescape(metin)
            metin = re.sub(r"\s+", " ", metin).strip()

            # Cok kisa / anlamsiz paragraflari alma.
            if len(metin) < 40:
                continue

            paragraflar.append(metin)

        # Tekrarlanan paragraflari temizle.
        temiz = []
        gorulen = set()

        for paragraf in paragraflar:
            anahtar = paragraf.lower()

            if anahtar in gorulen:
                continue

            gorulen.add(anahtar)
            temiz.append(paragraf)

        tam_metin = "\n\n".join(temiz).strip()

        # Cok az metin geldiyse guvenme.
        if len(tam_metin) < 500:
            print(
                f"Tam metin yetersiz: {len(tam_metin)} karakter. "
                "RSS ozetine geri donulecek."
            )
            return None

        # Gemini'ye kontrolsuz devasa sayfa gondermeyelim.
        tam_metin = tam_metin[:30000]

        print(
            f"Tam haber metni cekildi: "
            f"{len(tam_metin)} karakter | "
            f"{len(tam_metin.split())} kelime"
        )

        return tam_metin

    except requests.exceptions.RequestException as e:
        print(f"Tam metin HTTP hatasi: {e}")
        return None

    except Exception as e:
        print(f"Tam metin cekme hatasi: {e}")
        return None
    ham = entry.get("summary") or entry.get("description") or ""
    if not ham and entry.get("content"):
        try:
            ham = entry.content[0].value
        except Exception:
            ham = ""
    soup = BeautifulSoup(ham, "html.parser")
    metin = " ".join(soup.stripped_strings)
    return html.unescape(metin)[:12000]


def kapak_html(gorsel_url, baslik, gorsel_kaynagi=None):
    if not gorsel_url:
        return ""
    alt = html.escape(baslik, quote=True)
    url = html.escape(gorsel_url, quote=True)
    kredi = ""
    if gorsel_kaynagi == "NetDijital AI Görsel":
        kredi = (
            '<p style="font-size:12px;color:#777;margin:6px 0 18px">'
            'Görsel: Yapay zekâ ile oluşturuldu</p>'
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

print(f"Secilen haber: {orijinal_baslik} [{secilen_kaynak['kaynak']}]")

# Once kaynak sayfadaki tam haber metnini cekmeye calis.
tam_metin = haber_tam_metni_cek(kaynak_url)

if tam_metin:
    kaynak_metin = tam_metin
    print("Gemini kaynak metni: TAM HABER METNI")
else:
    kaynak_metin = ozet
    print("Gemini kaynak metni: RSS OZETI (fallback)")

makale, ok = llm_ile_makale_uret(orijinal_baslik, kaynak_metin)
    if not ok or not makale:
        print("Makale uretilemedi; yayin yapilmadi.")
        return

    makale, kalite_ok, kalite_sorunlari = makale_kalite_kontrol(
    makale,
    orijinal_baslik,
    kaynak_metin
)
    if not kalite_ok:
        print("AI kalite kontrolu tamamlanamadi; guvenlik geregi yayin yapilmadi.")
        return

    kategori = kategori_normalize(makale.get("kategori"))
    yazar = kategori_yazari(kategori)
    etiketler = [kategori]

    gorsel_url, gorsel_kaynagi = kapak_gorseli_hazirla(
        makale.get("gorsel_prompt", "modern technology concept"),
        kategori,
        makale.get("baslik", orijinal_baslik),
    )

    icerik = (
        kapak_html(gorsel_url, makale["baslik"], gorsel_kaynagi)
        + makale.get("icerik_html", "")
        + cta_html(kategori)
        + kaynak_html(secilen_kaynak["kaynak"], kaynak_url)
    )

    if TEST_MODU:
        print("\n" + "=" * 64)
        print("[NETDIJITAL GUVENLI TEST MODU]")
        print("Blogger API: DEVRE DISI (OAuth/token ve posts.insert cagrilmaz)")
        print(f"Baslik         : {makale.get('baslik', orijinal_baslik)}")
        print(f"Ana kategori   : {kategori}")
        print(f"Kategori yazari: {yazar}")
        print(f"Etiketler      : {', '.join(etiketler)}")
        print(f"Gorsel kaynagi : {gorsel_kaynagi or 'yok'}")
        print(f"Kapak URL      : {gorsel_url or 'yok'}")
        print(f"Kaynak         : {secilen_kaynak['kaynak']}")
        print(f"Kalite kontrol : BASARILI")
        if kalite_sorunlari:
            print(f"Kalite notlari : {' | '.join(kalite_sorunlari)}")
        print(f"HTML uzunlugu  : {len(icerik)} karakter")
        print("SONUC          : BLOGGER YAYINI ATLANDI")
        print("=" * 64)
        return

    token = get_access_token(CLIENT_ID, CLIENT_SECRET, REFRESH_TOKEN)
    if not token:
        print("Google access token alinamadi.")
        return

    sonuc = blogger_yayinla(token, makale["baslik"], icerik, etiketler, TASLAK_OLARAK_KAYDET)
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
    print(f"Kategori: {kategori} | Yazar: {yazar} | Etiketler: {', '.join(etiketler)}")
    print(f"Gorsel: {gorsel_kaynagi or 'yok'} - {gorsel_url or 'fallback tanimsiz'}")


if __name__ == "__main__":
    try:
        main()
    except Exception:
        traceback.print_exc()
        raise
