import os
import json
import random
import time
import html
import traceback
import urllib.request
import requests
import feedparser
from google import genai
from bs4 import BeautifulSoup

CLIENT_ID = os.getenv("BLOGGER_CLIENT_ID")
CLIENT_SECRET = os.getenv("BLOGGER_CLIENT_SECRET")
REFRESH_TOKEN = os.getenv("BLOGGER_REFRESH_TOKEN")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
PEXELS_API_KEY = os.getenv("PEXELS_API_KEY")
HISTORY_FILE = "posted_history.json"
MAX_GECMIS_LINK = 2000

MIN_PAYLASIM_ARALIGI_DAKIKA = 80
TASLAK_OLARAK_KAYDET = True

# Not: Google, eski client.models.generate_content() + gemini-2.5-flash kombinasyonunu
# yeni kullanicilar icin kapatti ve "Interactions API" (client.interactions.create) kullanimini
# oneriyor. Guncel model adi da degisebiliyor; asagidaki liste eskiden yeniye fallback sirasi.
GEMINI_MODEL = "gemini-3.7-flash"
GEMINI_MODEL_FALLBACKS = ["gemini-3.7-flash", "gemini-3.6-flash", "gemini-3.5-flash"]

RSS_SOURCES = [
    {"url": "https://techcrunch.com/feed/", "kaynak": "TechCrunch"},
    {"url": "https://www.theverge.com/rss/index.xml", "kaynak": "The Verge"},
    {"url": "https://www.engadget.com/rss.xml", "kaynak": "Engadget"},
    {"url": "https://feeds.arstechnica.com/arstechnica/index", "kaynak": "Ars Technica"},
    {"url": "https://thenextweb.com/feed", "kaynak": "The Next Web"},
    {"url": "https://www.digitaltrends.com/feed/", "kaynak": "Digital Trends"},
    {"url": "https://electrek.co/feed/", "kaynak": "Electrek"},
    {"url": "https://www.androidpolice.com/feed/", "kaynak": "Android Police"},
    {"url": "https://bgr.com/feed/", "kaynak": "BGR"},
    {"url": "https://www.tomshardware.com/rss.xml", "kaynak": "Tom's Hardware"},
    {"url": "https://readwrite.com/feed/", "kaynak": "ReadWrite"},
]

GENEL_ETIKET_HAVUZU = [
    "Teknoloji Haberleri", "Güncel", "Dijital Dünya", "İnceleme",
    "Haberler", "Bilim ve Teknoloji", "Gündem",
]


def get_access_token(client_id, client_secret, refresh_token):
    token_url = "https://oauth2.googleapis.com/token"
    payload = {
        "client_id": client_id,
        "client_secret": client_secret,
        "refresh_token": refresh_token,
        "grant_type": "refresh_token",
    }
    try:
        r = requests.post(token_url, data=payload, timeout=15)
    except requests.exceptions.RequestException as e:
        print(f"Token yenileme istegi basarisiz (ag hatasi): {e}")
        return None

    if r.status_code == 200:
        return r.json().get("access_token")
    print(f"Token yenileme hatasi: {r.status_code} - {r.text}")
    return None


def get_blog_id(access_token):
    blogs_url = "https://www.googleapis.com/blogger/v3/users/self/blogs"
    headers = {"Authorization": f"Bearer {access_token}"}
    try:
        r = requests.get(blogs_url, headers=headers, timeout=15)
    except requests.exceptions.RequestException as e:
        print(f"Blog ID istegi basarisiz (ag hatasi): {e}")
        return None

    if r.status_code == 200:
        items = r.json().get("items", [])
        if items:
            print(f"Blog bulundu: {items[0]['name']} ({items[0]['id']})")
            return items[0]["id"]
    print(f"Blog ID alinamadi: {r.status_code} - {r.text}")
    return None


def load_history():
    default_data = {"yayinlanan_linkler": [], "son_kaynak_index": 0, "son_paylasim_zamani": 0}
    if os.path.exists(HISTORY_FILE):
        try:
            with open(HISTORY_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                if "yayinlanan_linkler" in data:
                    data.setdefault("son_kaynak_index", 0)
                    data.setdefault("son_paylasim_zamani", 0)
                    return data
        except Exception:
            pass
    return default_data


def save_history(data):
    data["yayinlanan_linkler"] = data["yayinlanan_linkler"][-MAX_GECMIS_LINK:]
    with open(HISTORY_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def fetch_feed(url, kaynak_adi="Kaynak"):
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        },
    )
    try:
        data = urllib.request.urlopen(req, timeout=15).read()
        return feedparser.parse(data)
    except Exception as e:
        print(f"Feed alinamadi [{kaynak_adi}]: {e}")
        return feedparser.parse("")


def pexels_gorsel_bul(anahtar_kelime):
    if not PEXELS_API_KEY or not anahtar_kelime:
        return None, None
    try:
        search_url = "https://api.pexels.com/v1/search"
        headers = {"Authorization": PEXELS_API_KEY}
        params = {
            "query": anahtar_kelime,
            "per_page": 1,
            "orientation": "landscape",
        }
        r = requests.get(search_url, headers=headers, params=params, timeout=10)
        if r.status_code == 200:
            photos = r.json().get("photos", [])
            if photos:
                return photos[0]["src"]["large"], photos[0]["photographer"]
    except Exception as e:
        print(f"Pexels hatasi: {e}")
    return None, None


def llm_ile_makale_uret(orijinal_baslik, orijinal_ozet, kaynak_adi):
    if not GEMINI_API_KEY:
        print("GEMINI_API_KEY eksik.")
        return None, False

    prompt = f"""Sen profesyonel bir teknoloji editorusun.
Asagidaki habere dayanarak tamamen ozgun, SEO uyumlu ve zengin bir Turkce haber yaz.
Baslik: {orijinal_baslik}
Ozet: {orijinal_ozet}
Kaynak: {kaynak_adi}

Kurallar:
- Uzunluk 750-1200 kelime arasi olmali.
- En az 4 adet h2 basligi ve listeler icermeli.
- Sona "Kaynak: {kaynak_adi}" ifadesini ekle.
- SADECE JSON verisi dondur, kod bloklari ekleme:
{{
  "baslik": "Turkce Baslik",
  "icerik_html": "<p>Giris...</p><h2>Detay</h2><p>Metin...</p>",
  "meta_aciklama": "150 karakterlik ozet",
  "kategori": "Teknoloji",
  "etiketler": ["Etiket1", "Etiket2"],
  "gorsel_arama_terimi": "technology device"
}}"""

    client = genai.Client(api_key=GEMINI_API_KEY)

    modeller = GEMINI_MODEL_FALLBACKS if GEMINI_MODEL_FALLBACKS else [GEMINI_MODEL]

    for model_adi in modeller:
        for deneme in range(2):
            try:
                # Eski client.models.generate_content() yerine guncel Interactions API.
                interaction = client.interactions.create(
                    model=model_adi,
                    input=prompt,
                )
                metin = (interaction.output_text or "").strip()
                metin = metin.replace("```json", "").replace("```", "").strip()
                veri = json.loads(metin)

                # Zorunlu alanlar eksikse taslagi atla (KeyError yerine kontrollu red)
                if not veri.get("baslik") or not veri.get("icerik_html"):
                    print("Gemini yaniti eksik alan icerdi, atlaniyor.")
                    return None, False

                etiketler = list(dict.fromkeys(veri.get("etiketler", [])))
                if kaynak_adi not in etiketler:
                    etiketler.append(kaynak_adi)
                havuz = GENEL_ETIKET_HAVUZU.copy()
                random.shuffle(havuz)
                for e in havuz:
                    if len(etiketler) >= 9:
                        break
                    if e not in etiketler:
                        etiketler.append(e)
                veri["etiketler"] = etiketler[:14]

                if model_adi != modeller[0]:
                    print(f"Not: '{modeller[0]}' calismadi, '{model_adi}' ile uretildi.")
                return veri, False

            except json.JSONDecodeError as e:
                print(f"Gemini yaniti JSON olarak parse edilemedi: {e}")
                return None, False

            except Exception as e:
                hata_mesaji = str(e)
                if "429" in hata_mesaji or "RESOURCE_EXHAUSTED" in hata_mesaji:
                    print("Gemini kota siniri (429).")
                    return None, True
                if "404" in hata_mesaji or "NOT_FOUND" in hata_mesaji:
                    print(f"Model '{model_adi}' artik kullanilamiyor, siradaki modele geciliyor.")
                    break  # ic donguden cik, disaridaki 'modeller' listesinde bir sonrakine gec
                if "503" in hata_mesaji and deneme == 0:
                    print("Gemini 503 mesgul, 5 sn bekleniyor...")
                    time.sleep(5)
                    continue
                print(f"Gemini hatasi: {e}")
                return None, False

    print("Denenen hicbir Gemini modeli calismadi.")
    return None, False


def blogger_paylas(access_token, blog_id, baslik, icerik, etiketler, is_draft=True):
    post_url = "https://www.googleapis.com/blogger/v3/blogs/" + str(blog_id) + "/posts"
    params = {"isDraft": "true" if is_draft else "false"}
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
    }
    post_data = {
        "title": baslik,
        "content": icerik,
        "labels": etiketler,
    }
    return requests.post(post_url, headers=headers, params=params, json=post_data, timeout=30)


def main():
    history = load_history()

    simdi = time.time()
    son_paylasim = history.get("son_paylasim_zamani", 0)
    gecen_dakika = (simdi - son_paylasim) / 60
    if son_paylasim > 0 and gecen_dakika < MIN_PAYLASIM_ARALIGI_DAKIKA:
        kalan = round(MIN_PAYLASIM_ARALIGI_DAKIKA - gecen_dakika, 1)
        print(f"Bekleme suresi aktif ({round(gecen_dakika, 1)} dk gecti, {kalan} dk kaldi).")
        return

    print("Kimlik dogrulamasi yapiliyor...")
    access_token = get_access_token(CLIENT_ID, CLIENT_SECRET, REFRESH_TOKEN)
    if not access_token:
        print("Token alinamadi, islem iptal.")
        return

    blog_id = get_blog_id(access_token)
    if not blog_id:
        return

    toplam_kaynak = len(RSS_SOURCES)
    mevcut_index = history.get("son_kaynak_index", 0) % toplam_kaynak

    secilen_kaynak = RSS_SOURCES[mevcut_index]
    rss_url = secilen_kaynak["url"]
    kaynak_adi = secilen_kaynak["kaynak"]

    print(f"Taranacak kaynak [{mevcut_index + 1}/{toplam_kaynak}]: {kaynak_adi}")

    history["son_kaynak_index"] = (mevcut_index + 1) % toplam_kaynak
    save_history(history)

    feed = fetch_feed(rss_url, kaynak_adi)
    paylasildi = False

    for entry in feed.entries[:10]:
        link = getattr(entry, "link", None)
        if not link or link in history["yayinlanan_linkler"]:
            continue

        try:
            orijinal_baslik = getattr(entry, "title", "") or "(Basliksiz)"
            ham_ozet = getattr(entry, "summary", "")
            orijinal_ozet = BeautifulSoup(ham_ozet, "html.parser").get_text(separator=" ", strip=True)

            print(f"Gemini uretimi basladi: {orijinal_baslik}")
            makale, kota_asildi = llm_ile_makale_uret(orijinal_baslik, orijinal_ozet, kaynak_adi)

            if kota_asildi:
                print("Kota bitti, donguden cikiliyor.")
                break

            if not makale:
                time.sleep(5)
                continue

            gorsel_url, fotografci = pexels_gorsel_bul(makale.get("gorsel_arama_terimi", ""))

            icerik_html = makale.get("icerik_html", "")
            baslik_guvenli = html.escape(makale.get("baslik", orijinal_baslik), quote=True)

            if gorsel_url:
                fotografci_guvenli = html.escape(fotografci or "Pexels", quote=True)
                gorsel_etiketi = (
                    f"<p><img src='{html.escape(gorsel_url, quote=True)}' alt='{baslik_guvenli}' "
                    f"style='max-width:100%; height:auto; border-radius:8px;'/></p>"
                    f"<p><small>Gorsel: Pexels / {fotografci_guvenli}</small></p>"
                )
                icerik_html = gorsel_etiketi + icerik_html

            etiketler = makale.get("etiketler", [kaynak_adi])

            sonuc = blogger_paylas(
                access_token=access_token,
                blog_id=blog_id,
                baslik=makale.get("baslik", orijinal_baslik),
                icerik=icerik_html,
                etiketler=etiketler,
                is_draft=TASLAK_OLARAK_KAYDET,
            )

            if sonuc.status_code in (200, 201):
                durum = "taslak" if TASLAK_OLARAK_KAYDET else "yayin"
                print(f"Basarili ({durum}) [{kaynak_adi}]: {makale.get('baslik', orijinal_baslik)}")
                history["yayinlanan_linkler"].append(link)
                history["son_paylasim_zamani"] = simdi
                save_history(history)
                paylasildi = True
                break
            else:
                print(f"Blogger API Hatasi: {sonuc.status_code} - {sonuc.text}")

            time.sleep(20)

        except Exception as e:
            print(f"Dongu hatasi: {e}")
            print(traceback.format_exc())

    if not paylasildi:
        print(f"{kaynak_adi} kaynagindan paylasim yapilamadi.")


if __name__ == "__main__":
    main()
