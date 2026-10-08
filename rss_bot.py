# NetDijital v2.2 - Saatlik Otomatik Haber + Ucretsiz AI Gorsel Uretimi
# v2.0 degisiklikleri:
#   - Pexels kaldirildi; her haber icin Pollinations.ai ile ucretsiz 16:9 AI kapak.
#   - Kelime hedefi 800-1200.
#   - Resmi sirket RSS feed'leri (Google/Microsoft/Samsung/Apple) eklendi.
# v2.1 degisiklikleri:
#   - KISA HABER ATLAMA: kaynak metin ya da uretilen haber esigin altindaysa
#     haber atlanir, linki gecmise eklenir ve siradaki habere gecilir.
#   - GELISMIS TAM METIN: once RSS'teki content:encoded (tam icerik) kullanilir;
#     yetersizse haber sayfasi daha akilli bir yontemle okunur
#     (cok sayida secici, en uzun govde secimi, JSON-LD articleBody, tablo/liste).
#   - Gecmis listesi artik sirayi koruyor (eski surumde set kullanildigi icin
#     3000 limiti asildiginda rastgele linkler siliniyordu).
#   - main() girinti hatasi ve cift kalite kontrol cagrisi duzeltildi.
# v2.2 degisiklikleri:
#   - Yayin sonrasi otomatik sosyal medya paylasimi (Facebook, Instagram, X). Secret'i olmayan platform atlanir; test modunda paylasim yok.
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
import hmac
import secrets
from copy import copy
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

# --- Kisa haber esikleri (kelime) ---
# Kaynak metin bu sayinin altindaysa Gemini'ye hic gonderilmez (kota tasarrufu).
MIN_KAYNAK_KELIME = int(os.getenv("MIN_KAYNAK_KELIME", "250"))
# Uretilen (ve kalite kontrolunden gecen) haber bu sayinin altindaysa yayinlanmaz.
MIN_HABER_KELIME = int(os.getenv("MIN_HABER_KELIME", "400"))
# Tek calismada en fazla kac farkli haber denenecek (her biri Gemini kotasi harcar).
MAX_ADAY_DENEMESI = int(os.getenv("MAX_ADAY_DENEMESI", "5"))
# RSS'teki tam icerik bu karakter sayisindan uzunsa haber sayfasi hic cekilmez.
RSS_TAM_ICERIK_YETERLI = 2500

# Bilgi amacli: bu betik tek calismada TEK haber yayinlar. Saatte bir mi,
# 3 saatte bir mi calisacagini GitHub Actions workflow'undaki cron belirler.

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
# Google Haberler kazima (scraping) YAPILMAZ.

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
    {"kaynak": "Google Blog", "url": "https://blog.google/rss/"},
    {"kaynak": "Microsoft News", "url": "https://news.microsoft.com/feed/"},
    {"kaynak": "Samsung Newsroom", "url": "https://news.samsung.com/global/feed"},
    # Apple resmi bir genel RSS yayinlamadiginda bu kaynak otomatik atlanir.
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


def gecmisi_kaydet(history, linkler):
    """Link listesini (sirasi korunmus) history'ye yazar, diske ve GitHub'a kaydeder."""
    history["yayinlanan_linkler"] = linkler
    save_history(history)
    github_history_save()


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
# WEB SAYFASINDAN OG IMAGE (kapak gorseli artik AI ile uretildigi icin
# bu fonksiyon kullanilmiyor; ileride lazim olursa diye korunuyor)
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
        r = None
        for deneme in range(1, 4):
            r = requests.put(api_url, headers=headers, json=payload, timeout=30)
            if r.status_code in (200, 201):
                break
            print(f"Kapak GitHub yukleme hatasi (deneme {deneme}/3): {r.status_code} {r.text[:300]}")
            if r.status_code < 500 and r.status_code != 409:
                break  # kalici hata (izin vb.); tekrar denemenin anlami yok
            if r.status_code == 409:
                # sha cakismasi: guncel sha'yi al ve tekrar dene
                m = requests.get(api_url, headers=headers, params={"ref": GITHUB_BRANCH}, timeout=20)
                if m.status_code == 200:
                    payload["sha"] = m.json().get("sha")
            time.sleep(3 * deneme)
        if r is None or r.status_code not in (200, 201):
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

                kelime_sayisi = haber_kelime_sayisi(data["icerik_html"])
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
# ICERIK YARDIMCILARI - KAYNAK METNI CEKME
# ============================================================

def haber_kelime_sayisi(icerik_html):
    """HTML icerikteki gorunur kelime sayisini dondurur."""
    return len(BeautifulSoup(icerik_html or "", "html.parser").get_text(" ").split())


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


# Icerik disi (galeri, paylasim, ilgili haberler, yorum vb.) bloklari tanimlayan
# sinif adi parcalari.
_GURULTU_SINIF_RE = re.compile(
    r"gallery|lightbox|wp-caption|share|social|related|comment|newsletter|advert|sidebar",
    re.I,
)
_GURULTU_ETIKETLER = [
    "script", "style", "noscript", "iframe", "figure", "figcaption",
    "form", "button", "svg", "aside", "nav", "footer", "header",
]


def _temiz_metin(el):
    metin = " ".join(el.stripped_strings)
    metin = html.unescape(metin)
    return re.sub(r"\s+", " ", metin).strip()


def _paragraflari_cikar(kapsayici):
    """Bir BeautifulSoup elemanindan haber govdesini paragraf/baslik/liste/tablo
    satiri olarak temiz bir liste halinde dondurur. Elemani DEGISTIRIR; cagirmadan
    once copy() almak gerekir."""
    for t in kapsayici(_GURULTU_ETIKETLER):
        try:
            t.decompose()
        except Exception:
            pass
    for t in kapsayici.find_all(class_=_GURULTU_SINIF_RE):
        try:
            t.decompose()
        except Exception:
            pass

    parcalar = []
    gorulen = set()
    for el in kapsayici.find_all(["h2", "h3", "h4", "p", "li", "tr"]):
        if el.name == "tr":
            hucreler = [_temiz_metin(td) for td in el.find_all(["td", "th"])]
            metin = " | ".join(h for h in hucreler if h)
            min_uzunluk = 10
        elif el.name in ("h2", "h3", "h4"):
            metin = _temiz_metin(el)
            min_uzunluk = 5
            if metin:
                metin = "## " + metin
        elif el.name == "li":
            if el.find(["p", "li"]):
                continue  # ic ice yapi; icerigi zaten p/li olarak alinacak
            metin = _temiz_metin(el)
            min_uzunluk = 20
        else:  # p
            if el.find_parent(["td", "th"]):
                continue  # tablo hucresi icinde zaten alindi
            metin = _temiz_metin(el)
            min_uzunluk = 40

        if len(metin) < min_uzunluk:
            continue
        anahtar = metin.lower()
        if anahtar in gorulen:
            continue
        gorulen.add(anahtar)
        parcalar.append(metin)
    return parcalar


def _parcalari_metne_cevir(parcalar):
    return "\n\n".join(parcalar).strip()


def entry_tam_metin(entry):
    """RSS'teki content:encoded alanindan tam haber metnini cikarir (WordPress
    tabanli sitelerin cogu tam icerigi feed'e koyar). Yetersizse None dondurur."""
    try:
        icerikler = entry.get("content") or []
        ham = max((c.get("value", "") for c in icerikler), key=len, default="")
    except Exception:
        ham = ""
    if not ham:
        return None
    try:
        soup = BeautifulSoup(ham, "html.parser")
        metin = _parcalari_metne_cevir(_paragraflari_cikar(soup))
    except Exception as e:
        print(f"RSS tam icerik ayristirma hatasi: {e}")
        return None
    if len(metin) < 500:
        return None
    return metin[:30000]


_GOVDE_SECICILER = [
    "article",
    '[itemprop="articleBody"]',
    ".article-content", ".article-body", ".article-text", ".article_content",
    ".post-content", ".post-body", ".post_content", ".entry-content",
    ".single-content", ".the-content", ".td-post-content",
    ".news-content", ".news-detail", ".news-text", ".detail-text",
    ".content-detail", ".content-text", ".haber-metni", ".story-body",
    ".elementor-widget-theme-post-content",
    "#article-body", "#content-body", "main",
]


def _jsonld_article_body(soup):
    """Sayfadaki JSON-LD bloklarindan articleBody alanini bulmaya calisir."""
    for s in soup.find_all("script", type="application/ld+json"):
        try:
            veri = json.loads(s.string or s.get_text() or "")
        except Exception:
            continue
        kuyruk = [veri]
        while kuyruk:
            o = kuyruk.pop()
            if isinstance(o, list):
                kuyruk.extend(o)
            elif isinstance(o, dict):
                govde = o.get("articleBody")
                if isinstance(govde, str) and len(govde) > 500:
                    return re.sub(r"\s+", " ", html.unescape(govde)).strip()
                kuyruk.extend(v for v in o.values() if isinstance(v, (list, dict)))
    return None


def haber_tam_metni_cek(url):
    """Haber sayfasindaki asil metni cekmeye calisir. Basarisiz veya yetersiz
    olursa None dondurur."""
    if not url:
        return None

    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/153.0 Safari/537.36"
        ),
        "Accept-Language": "tr-TR,tr;q=0.9,en-US;q=0.8,en;q=0.7",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    }

    response = None
    for deneme in range(1, 3):
        try:
            response = requests.get(url, headers=headers, timeout=20)
            response.raise_for_status()
            break
        except requests.exceptions.RequestException as e:
            print(f"Tam metin HTTP hatasi (deneme {deneme}/2): {e}")
            response = None
            time.sleep(2)
    if response is None:
        return None

    try:
        soup = BeautifulSoup(response.text, "html.parser")

        # Aday govdeleri topla; her biri icin ayri kopya uzerinden metin cikar
        # ve EN UZUN sonucu sec (yanlis/kucuk <article> secme riskini azaltir).
        en_iyi = ""
        gorulen_idler = set()
        for secici in _GOVDE_SECICILER:
            try:
                adaylar = soup.select(secici)
            except Exception:
                continue
            for aday in adaylar[:5]:
                if id(aday) in gorulen_idler:
                    continue
                gorulen_idler.add(id(aday))
                try:
                    metin = _parcalari_metne_cevir(_paragraflari_cikar(copy(aday)))
                except Exception:
                    continue
                if len(metin) > len(en_iyi):
                    en_iyi = metin

        # JSON-LD articleBody daha uzunsa onu kullan.
        jsonld = _jsonld_article_body(soup)
        if jsonld and len(jsonld) > len(en_iyi):
            print("Tam metin: JSON-LD articleBody kullanildi.")
            en_iyi = jsonld

        if len(en_iyi) < 500:
            print(f"Tam metin yetersiz: {len(en_iyi)} karakter.")
            return None

        en_iyi = en_iyi[:30000]
        print(
            f"Sayfadan tam metin cekildi: {len(en_iyi)} karakter | "
            f"{len(en_iyi.split())} kelime"
        )
        return en_iyi

    except Exception as e:
        print(f"Tam metin cekme hatasi: {e}")
        return None


def kaynak_metnini_hazirla(entry, url, ozet):
    """Gemini'ye verilecek kaynak metni secer. Oncelik:
    1) RSS content:encoded (yeterince uzunsa sayfa hic cekilmez)
    2) Haber sayfasi (RSS metniyle karsilastirilip en uzunu secilir)
    3) RSS ozeti (yedek)
    Donus: (metin, tur_aciklamasi)"""
    rss_metin = entry_tam_metin(entry)
    if rss_metin:
        print(f"RSS tam icerik bulundu: {len(rss_metin)} karakter | {len(rss_metin.split())} kelime")
        if len(rss_metin) >= RSS_TAM_ICERIK_YETERLI:
            return rss_metin, "RSS TAM ICERIK"

    sayfa_metin = haber_tam_metni_cek(url)

    adaylar = [(m, t) for m, t in ((rss_metin, "RSS TAM ICERIK"), (sayfa_metin, "SAYFA TAM METNI")) if m]
    if adaylar:
        return max(adaylar, key=lambda x: len(x[0]))

    return ozet, "RSS OZETI (yedek)"


# ============================================================
# ICERIK YARDIMCILARI - HTML BLOKLARI
# ============================================================

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
# SOSYAL MEDYA PAYLASIMI (Facebook, Instagram, X)
# ============================================================
# Her platform bagimsiz ve istege baglidir: ilgili GitHub Secret'lari
# tanimli degilse platform sessizce atlanir. Bir platformdaki hata digerlerini
# ve blog yayinini ETKILEMEZ. Test modunda hicbir paylasim yapilmaz.
#
# Gerekli ortam degiskenleri (GitHub Secrets -> workflow'daki env):
#   Facebook : FACEBOOK_PAGE_ID, FACEBOOK_PAGE_TOKEN
#   Instagram: INSTAGRAM_USER_ID, INSTAGRAM_TOKEN (yoksa FACEBOOK_PAGE_TOKEN kullanilir)
#   X        : X_API_KEY, X_API_SECRET, X_ACCESS_TOKEN, X_ACCESS_SECRET
# SOSYAL_PAYLASIM=false yapilirsa tum paylasimlar kapatilir.

FB_GRAPH_BASE = "https://graph.facebook.com/v26.0"
SOSYAL_PAYLASIM = os.getenv("SOSYAL_PAYLASIM", "true").strip().lower() in {"1", "true", "yes", "on"}


def _env(ad):
    return (os.getenv(ad) or "").strip()


def sosyal_platform_durumu():
    """Hangi platformlarin yapilandirildigini dondurur."""
    return {
        "Facebook": bool(_env("FACEBOOK_PAGE_ID") and _env("FACEBOOK_PAGE_TOKEN")),
        "Instagram": bool(
            _env("INSTAGRAM_USER_ID") and (_env("INSTAGRAM_TOKEN") or _env("FACEBOOK_PAGE_TOKEN"))
        ),
        "X": all(_env(k) for k in ("X_API_KEY", "X_API_SECRET", "X_ACCESS_TOKEN", "X_ACCESS_SECRET")),
    }


def _hashtagler(kategori):
    kat = re.sub(r"[\W_]+", "", str(kategori or ""))
    etiketler = ["#NetDijital", "#teknoloji"]
    if kat:
        etiketler.append(f"#{kat}")
    return " ".join(etiketler)


def _kisalt(metin, uzunluk):
    metin = re.sub(r"\s+", " ", str(metin or "")).strip()
    if len(metin) <= uzunluk:
        return metin
    return metin[: max(0, uzunluk - 1)].rstrip() + "…"


def facebook_paylas(baslik, aciklama, post_url):
    sayfa_id, token = _env("FACEBOOK_PAGE_ID"), _env("FACEBOOK_PAGE_TOKEN")
    mesaj = f"{baslik}\n\n{_kisalt(aciklama, 300)}".strip()
    try:
        r = requests.post(
            f"{FB_GRAPH_BASE}/{sayfa_id}/feed",
            data={"message": mesaj, "link": post_url, "access_token": token},
            timeout=30,
        )
        if r.status_code in (200, 201):
            print(f"Facebook paylasimi basarili: {r.json().get('id')}")
            return True
        print("Facebook paylasim hatasi:", r.status_code, r.text[:500])
    except Exception as e:
        print(f"Facebook istek hatasi: {e}")
    return False


def instagram_paylas(baslik, aciklama, kategori, gorsel_url):
    ig_id = _env("INSTAGRAM_USER_ID")
    token = _env("INSTAGRAM_TOKEN") or _env("FACEBOOK_PAGE_TOKEN")
    if not gorsel_url:
        print("Instagram: gorsel URL'si yok; atlandi.")
        return False
    # Instagram aciklamalarindaki linkler tiklanmaz; bio'ya yonlendirme eklenir.
    caption = (
        f"{baslik}\n\n{_kisalt(aciklama, 300)}\n\n"
        f"Haberin tamami icin profilimizdeki linke tiklayin.\n\n{_hashtagler(kategori)}"
    )
    try:
        r = requests.post(
            f"{FB_GRAPH_BASE}/{ig_id}/media",
            data={"image_url": gorsel_url, "caption": caption[:2200], "access_token": token},
            timeout=60,
        )
        if r.status_code not in (200, 201):
            print("Instagram medya olusturma hatasi:", r.status_code, r.text[:500])
            return False
        container_id = r.json().get("id")

        for _ in range(10):  # container hazir olana kadar bekle
            d = requests.get(
                f"{FB_GRAPH_BASE}/{container_id}",
                params={"fields": "status_code", "access_token": token},
                timeout=30,
            )
            durum = d.json().get("status_code") if d.status_code == 200 else None
            if durum == "FINISHED":
                break
            if durum == "ERROR":
                print("Instagram medya isleme hatasi:", d.text[:300])
                return False
            time.sleep(3)

        p = requests.post(
            f"{FB_GRAPH_BASE}/{ig_id}/media_publish",
            data={"creation_id": container_id, "access_token": token},
            timeout=60,
        )
        if p.status_code in (200, 201):
            print(f"Instagram paylasimi basarili: {p.json().get('id')}")
            return True
        print("Instagram yayinlama hatasi:", p.status_code, p.text[:500])
    except Exception as e:
        print(f"Instagram istek hatasi: {e}")
    return False


def _oauth1_header(method, url, ck, cs, at, ats):
    """X API icin OAuth 1.0a (kullanici baglami) imzali Authorization basligi.
    JSON govde imzaya dahil edilmez."""
    enc = lambda v: quote(str(v), safe="~")
    params = {
        "oauth_consumer_key": ck,
        "oauth_nonce": secrets.token_hex(16),
        "oauth_signature_method": "HMAC-SHA1",
        "oauth_timestamp": str(int(time.time())),
        "oauth_token": at,
        "oauth_version": "1.0",
    }
    param_str = "&".join(f"{enc(k)}={enc(v)}" for k, v in sorted(params.items()))
    base = "&".join([method.upper(), enc(url), enc(param_str)])
    key = f"{enc(cs)}&{enc(ats)}"
    imza = base64.b64encode(hmac.new(key.encode(), base.encode(), hashlib.sha1).digest()).decode()
    params["oauth_signature"] = imza
    return "OAuth " + ", ".join(f'{enc(k)}="{enc(v)}"' for k, v in sorted(params.items()))


def x_paylas(baslik, post_url, kategori):
    # Link X'te 23 karakter sayilir. Link icerdigi icin bu paylasim X tarafinda
    # link ucretiyle faturalanabilir (bkz. X API pay-per-use fiyatlari).
    etiket = _hashtagler(kategori).split()[0:2]
    metin = f"{_kisalt(baslik, 200)}\n\n{post_url}\n{' '.join(etiket)}"
    url = "https://api.x.com/2/tweets"
    try:
        auth = _oauth1_header(
            "POST", url,
            _env("X_API_KEY"), _env("X_API_SECRET"), _env("X_ACCESS_TOKEN"), _env("X_ACCESS_SECRET"),
        )
        r = requests.post(
            url,
            headers={"Authorization": auth, "Content-Type": "application/json"},
            json={"text": metin},
            timeout=30,
        )
        if r.status_code in (200, 201):
            print(f"X paylasimi basarili: {(r.json().get('data') or {}).get('id')}")
            return True
        print("X paylasim hatasi:", r.status_code, r.text[:500])
    except Exception as e:
        print(f"X istek hatasi: {e}")
    return False


def sosyal_medyada_paylas(baslik, aciklama, kategori, post_url, gorsel_url):
    """Yapilandirilmis tum platformlara paylasir. Hicbir hata disari firlatilmaz."""
    if not SOSYAL_PAYLASIM:
        print("Sosyal medya paylasimi kapali (SOSYAL_PAYLASIM=false).")
        return
    durum = sosyal_platform_durumu()
    aktifler = [ad for ad, ok in durum.items() if ok]
    if not aktifler:
        print("Sosyal medya: yapilandirilmis platform yok; atlandi.")
        return
    print(f"Sosyal medya paylasimi baslatiliyor: {', '.join(aktifler)}")

    gorevler = {
        "Facebook": lambda: facebook_paylas(baslik, aciklama, post_url),
        "Instagram": lambda: instagram_paylas(baslik, aciklama, kategori, gorsel_url),
        "X": lambda: x_paylas(baslik, post_url, kategori),
    }
    for ad in aktifler:
        try:
            gorevler[ad]()
        except Exception as e:
            print(f"{ad} paylasimi beklenmeyen hata verdi: {e}")


# ============================================================
# ADAY HABER SECIMI
# ============================================================

def aday_haberler(yayinlanan, baslangic):
    """Kaynaklari sirayla gezer ve her kaynaktan, daha once islenmemis ilk haberi
    (idx, kaynak, entry) olarak uretir. Tembel calisir: bir sonraki kaynagin
    feed'i yalnizca onceki aday kabul edilmediyse indirilir."""
    kaynak_sayisi = len(RSS_SOURCES)
    for offset in range(kaynak_sayisi):
        idx = (baslangic + offset) % kaynak_sayisi
        kaynak = RSS_SOURCES[idx]
        feed = fetch_feed(kaynak["url"], kaynak["kaynak"])
        for entry in feed.entries[:12]:
            link = normalize_url(entry.get("link"))
            baslik = (entry.get("title") or "").strip()
            if link and baslik and link not in yayinlanan:
                yield idx, kaynak, entry
                break


# ============================================================
# ANA AKIS
# ============================================================

def main():
    if not gerekli_ayarlar_tamam():
        return

    history = load_history()
    linkler = list(history.get("yayinlanan_linkler", []))  # sirasi korunur
    yayinlanan = set(linkler)
    kaynak_sayisi = len(RSS_SOURCES)
    baslangic = int(history.get("son_kaynak_index", 0)) % kaynak_sayisi

    atlanan = 0
    denenen = 0
    son_idx = None
    hazir = None      # basarili aday burada toplanir
    durdur = False    # Gemini/kalite kontrol altyapi hatasi: tum calismayi durdur

    def atla(url, neden):
        """Haberi gecmise 'islendi' diye ekler; bir daha secilmez."""
        nonlocal atlanan
        atlanan += 1
        print(f"ATLANDI ({neden}): {url}")
        if url and url not in yayinlanan:
            yayinlanan.add(url)
            linkler.append(url)

    for idx, kaynak, entry in aday_haberler(yayinlanan, baslangic):
        if denenen >= MAX_ADAY_DENEMESI:
            print(f"En fazla {MAX_ADAY_DENEMESI} aday denendi; bu calismada durduruluyor.")
            break
        denenen += 1
        son_idx = idx

        kaynak_url = normalize_url(entry.get("link"))
        orijinal_baslik = html.unescape((entry.get("title") or "").strip())
        ozet = entry_ozet(entry)

        print(f"\n--- Aday {denenen}/{MAX_ADAY_DENEMESI} ---")
        print(f"Secilen haber: {orijinal_baslik} [{kaynak['kaynak']}]")

        # 1) Kaynak metni (RSS tam icerik -> sayfa -> RSS ozeti)
        kaynak_metin, metin_turu = kaynak_metnini_hazirla(entry, kaynak_url, ozet)
        kaynak_kelime = len(kaynak_metin.split())
        print(f"Gemini kaynak metni: {metin_turu} | {kaynak_kelime} kelime")

        if kaynak_kelime < MIN_KAYNAK_KELIME:
            atla(kaynak_url, f"kaynak metin kisa: {kaynak_kelime} < {MIN_KAYNAK_KELIME} kelime")
            continue

        # 2) Haber uretimi
        makale, ok = llm_ile_makale_uret(orijinal_baslik, kaynak_metin)
        if not ok or not makale:
            print("Makale uretilemedi; yayin yapilmadi.")
            durdur = True
            break

        kelime = haber_kelime_sayisi(makale.get("icerik_html", ""))
        if kelime < MIN_HABER_KELIME:
            atla(kaynak_url, f"uretilen haber kisa: {kelime} < {MIN_HABER_KELIME} kelime")
            continue

        # 3) Kalite kontrolu (tek sefer)
        makale, kalite_ok, kalite_sorunlari = makale_kalite_kontrol(
            makale, orijinal_baslik, kaynak_metin
        )
        if not kalite_ok:
            print("AI kalite kontrolu tamamlanamadi; guvenlik geregi yayin yapilmadi.")
            durdur = True
            break

        kelime = haber_kelime_sayisi(makale.get("icerik_html", ""))
        print(f"Kalite kontrolu sonrasi kelime sayisi: {kelime}")
        if kelime < MIN_HABER_KELIME:
            atla(kaynak_url, f"kalite kontrolu sonrasi haber kisa: {kelime} < {MIN_HABER_KELIME} kelime")
            continue

        hazir = {
            "idx": idx,
            "kaynak": kaynak,
            "kaynak_url": kaynak_url,
            "orijinal_baslik": orijinal_baslik,
            "makale": makale,
            "kalite_sorunlari": kalite_sorunlari,
            "kelime": kelime,
            "metin_turu": metin_turu,
        }
        break

    # Atlanan haberleri kalici olarak kaydet (test modunda gecmise dokunma).
    if atlanan and not TEST_MODU:
        if son_idx is not None:
            history["son_kaynak_index"] = (son_idx + 1) % kaynak_sayisi
        gecmisi_kaydet(history, linkler)

    if not hazir:
        if denenen == 0:
            print("Yeni haber bulunamadi.")
        elif not durdur:
            print(f"{denenen} aday denendi, {atlanan} tanesi kisa/yetersiz oldugu icin atlandi; yayin yapilmadi.")
        return

    secilen_index = hazir["idx"]
    secilen_kaynak = hazir["kaynak"]
    kaynak_url = hazir["kaynak_url"]
    orijinal_baslik = hazir["orijinal_baslik"]
    makale = hazir["makale"]
    kalite_sorunlari = hazir["kalite_sorunlari"]

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
        print(f"Kaynak metin   : {hazir['metin_turu']}")
        print(f"Haber kelime   : {hazir['kelime']}")
        print(f"Atlanan haber  : {atlanan} (test modunda gecmise kaydedilmez)")
        _sd = sosyal_platform_durumu()
        print("Sosyal medya   : " + ", ".join(f"{k}={'HAZIR' if v else 'ayarsiz'}" for k, v in _sd.items())
              + " (test modunda paylasim yapilmaz)")
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
        print("Yayin basarisiz; yayinlanan haberin linki gecmise eklenmedi.")
        return

    if kaynak_url and kaynak_url not in yayinlanan:
        yayinlanan.add(kaynak_url)
        linkler.append(kaynak_url)
    history["son_kaynak_index"] = (secilen_index + 1) % kaynak_sayisi
    history["son_paylasim_zamani"] = int(time.time())
    gecmisi_kaydet(history, linkler)

    durum = "Taslak" if TASLAK_OLARAK_KAYDET else "Yayinlandi"
    print(f"{durum}: {sonuc.get('url') or sonuc.get('id')}")
    print(f"Kategori: {kategori} | Yazar: {yazar} | Etiketler: {', '.join(etiketler)}")
    print(f"Gorsel: {gorsel_kaynagi or 'yok'} - {gorsel_url or 'fallback tanimsiz'}")

    # Blog yayini basarili oldu; sosyal medya paylasimi ayri ve hataya dayanikli.
    post_url = sonuc.get("url")
    if post_url and not TASLAK_OLARAK_KAYDET:
        try:
            sosyal_medyada_paylas(
                makale["baslik"],
                makale.get("meta_aciklama") or "",
                kategori,
                post_url,
                gorsel_url,
            )
        except Exception as e:
            print(f"Sosyal medya paylasimi hatasi (blog yayini etkilenmedi): {e}")
    else:
        print("Sosyal medya: taslak veya URL yok; paylasim yapilmadi.")


if __name__ == "__main__":
    try:
        main()
    except Exception:
        traceback.print_exc()
        raise
