import os
import json
import random
import traceback
import urllib.request

import requests
import feedparser
from google import genai

# ================== AYARLAR ==================
CLIENT_ID = os.getenv("BLOGGER_CLIENT_ID")
CLIENT_SECRET = os.getenv("BLOGGER_CLIENT_SECRET")
REFRESH_TOKEN = os.getenv("BLOGGER_REFRESH_TOKEN")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
PEXELS_API_KEY = os.getenv("PEXELS_API_KEY")

HISTORY_FILE = "posted_history.json"
HABER_SAYISI_PER_CALISMA = 2
MAX_GECMIS_LINK = 2000

TASLAK_OLARAK_KAYDET = True

RSS_SOURCES = [
    {"url": "https://techcrunch.com/feed/", "kaynak": "TechCrunch"},
    {"url": "https://www.theverge.com/rss/index.xml", "kaynak": "The Verge"},
    {"url": "https://www.engadget.com/rss.xml", "kaynak": "Engadget"},
    {"url": "https://feeds.arstechnica.com/arstechnica/index", "kaynak": "Ars Technica"},
    {"url": "https://www.wired.com/feed/rss", "kaynak": "Wired"},
    {"url": "https://thenextweb.com/feed", "kaynak": "The Next Web"},
    {"url": "https://www.digitaltrends.com/feed/", "kaynak": "Digital Trends"},
    {"url": "https://gizmodo.com/feed", "kaynak": "Gizmodo"},
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


# ================== TOKEN / BLOG ID ==================
def get_access_token(client_id, client_secret, refresh_token):
    url = "https://oauth2.googleapis.com/token"
    data = {
        "client_id": client_id,
        "client_secret": client_secret,
        "refresh_token": refresh_token,
        "grant_type": "refresh_token",
    }
    r = requests.post(url, data=data, timeout=15)
    if r.status_code == 200:
        return r.json().get("access_token")
    print(f"❌ Token yenileme hatası: {r.status_code} - {r.text}")
    return None


def get_blog_id(access_token):
    url = "https://www.googleapis.com/blogger/v3/users/self/blogs"
    headers = {"Authorization": f"Bearer {access_token}"}
    r = requests.get(url, headers=headers, timeout=15)
    if r.status_code == 200:
        items = r.json().get("items", [])
        if items:
            print(f"✅ Blog bulundu: {items[0]['name']} ({items[0]['id']})")
            return items[0]["id"]
    print(f"❌ Blog ID alınamadı: {r.status_code} - {r.text}")
    return None


# ================== GEÇMİŞ (TEKRAR ENGELLEME) ==================
def load_history():
    if os.path.exists(HISTORY_FILE):
        try:
            with open(HISTORY_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                if "yayinlanan_linkler" in data:
                    return data
        except Exception:
            pass
    return {"yayinlanan_linkler": []}


def save_history(data):
    data["yayinlanan_linkler"] = data["yayinlanan_linkler"][-MAX_GECMIS_LINK:]
    with open(HISTORY_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


# ================== RSS ÇEKME ==================
def fetch_feed(url, kaynak_adi="Kaynak"):
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        },
    )
    try:
        veri = urllib.request.urlopen(req, timeout=15).read()
        return feedparser.parse(veri)
    except Exception as e:
        print(f"  ⚠️ Feed alınamadı [{kaynak_adi}]: {e}")
        return feedparser.parse("")


# ================== TELİFSİZ GÖRSEL ==================
def pexels_gorsel_bul(anahtar_kelime):
    if not PEXELS_API_KEY or not anahtar_kelime:
        return None, None
    try:
        r = requests.get(
            "https://api.pexels.com/v1/search",
            headers={"Authorization": PEXELS_API_KEY},
            params={"query": anahtar_kelime, "per_page": 1, "orientation": "landscape"},
            timeout=10,
        )
        if r.status_code == 200:
            photos = r.json().get("photos", [])
            if photos:
                return photos[0]["src"]["large"], photos[0]["photographer"]
    except Exception as e:
        print(f"  ⚠️ Pexels görsel hatası: {e}")
    return None, None


# ================== GEMINI İLE MAKALE ÜRETİMİ ==================
def llm_ile_makale_uret(orijinal_baslik, orijinal_ozet, kaynak_adi):
    if not GEMINI_API_KEY:
        print("  ❌ GEMINI_API_KEY tanımlı değil, içerik üretilemedi.")
        return None

    prompt = f"""Sen bir Türkçe teknoloji haber sitesinde çalışan editörsün. Aşağıdaki İngilizce
kaynak habere dayanarak TAMAMEN ÖZGÜN bir Türkçe makale yaz. Kaynağı birebir çevirme;
bilgiyi kendi cümlelerinle, farklı bir yapıda ve okuyucuya değer katacak şekilde anlat.

Kaynak Başlık: {orijinal_baslik}
Kaynak Özet: {orijinal_ozet}
Kaynak Site: {kaynak_adi}

Kurallar:
- En az 3 paragraf ve en az 2 tane <h2> alt başlık kullan (giriş, gelişme, değerlendirme).
- Cümle yapılarını ve kelime seçimini kaynaktan tamamen bağımsız kur, birebir çeviri OLMASIN.
- Sona "Kaynak: {kaynak_adi}" ifadesini ekle (link verme, sadece isim yaz).
- Sadece verilen bilgiyle sınırlı kal, uydurma bilgi ekleme.
- Ayrıca üret: 150 karakteri geçmeyen SEO meta açıklaması, 1 ana kategori,
  en az 9 adet Türkçe etiket, ve görsel aramak için 2-3 kelimelik İNGİLİZCE anahtar kelime.

SADECE şu JSON formatında cevap ver, Markdown kod bloğu (```json gibi) veya başka hiçbir metin ekleme:
{{
  "baslik": "...",
  "icerik_html": "<p>...</p><h2>...</h2><p>...</p>",
  "meta_aciklama": "...",
  "kategori": "...",
  "etiketler": ["...", "..."],
  "gorsel_arama_terimi": "..."
}}"""

    try:
        client = genai.Client(api_key=GEMINI_API_KEY)
        response = client.models.generate_content(
            model="gemini-3.6-flash",
            contents=prompt,
        )
        metin = response.text.strip()
        metin = metin.replace("```json", "").replace("```", "").strip()
        veri = json.loads(metin)

        # En az 9 etiket tamamlama
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
        return veri

    except Exception as e:
        print(f"  ⚠️ Gemini makale üretme hatası: {e}")
        return None


# ================== BLOGGER'A GÖNDER ==================
def blogger_paylas(access_token, blog_id, baslik, icerik, etiketler, meta_aciklama):
    url = f"[https://www.googleapis.com/blogger/v3/blogs/](https://www.googleapis.com/blogger/v3/blogs/){blog_id}/posts/"
    if TASLAK_OLARAK_KAYDET:
        url += "?isDraft=true"
    headers = {"Authorization": f"Bearer {access_token}", "Content-Type": "application/json"}
    post_data = {
        "kind": "blogger#post",
        "blog": {"id": blog_id},
        "title": baslik,
        "content": icerik,
        "labels": etiketler,
        "searchDescription": (meta_aciklama or baslik)[:150],
    }
    return requests.post(url, headers=headers, json=post_data, timeout=30)


# ================== ANA AKIŞ ==================
def main():
    print("🔄 Kimlik doğrulaması yapılıyor...")
    access_token = get_access_token(CLIENT_ID, CLIENT_SECRET, REFRESH_TOKEN)
    if not access_token:
        print("❌ Token alınamadı, bot durduruldu.")
        return

    blog_id = get_blog_id(access_token)
    if not blog_id:
        return

    if TASLAK_OLARAK_KAYDET:
        print("📝 Mod: TASLAK (yazılar otomatik yayınlanmıyor, Blogger panelinden onay bekliyor)")

    history = load_history()
    bu_calismada_paylasilan = 0

    kaynaklar = RSS_SOURCES.copy()
    random.shuffle(kaynaklar)

    for kaynak in kaynaklar:
        if bu_calismada_paylasilan >= HABER_SAYISI_PER_CALISMA:
            break

        rss_url, kaynak_adi = kaynak["url"], kaynak["kaynak"]
        print(f"🔎 Taranıyor: {kaynak_adi}...")
        feed = fetch_feed(rss_url, kaynak_adi)

        for entry in feed.entries[:5]:
            if bu_calismada_paylasilan >= HABER_SAYISI_PER_CALISMA:
                break

            link = getattr(entry, "link", None)
            if not link or link in history["yayinlanan_linkler"]:
                continue

            try:
                orijinal_baslik = entry.title
                orijinal_ozet = getattr(entry, "summary", "")

                makale = llm_ile_makale_uret(orijinal_baslik, orijinal_ozet, kaynak_adi)
                if not makale:
                    print(f"  ⏭️ Atlandı (içerik üretilemedi): {orijinal_baslik}")
                    continue

                gorsel_url, fotografci = pexels_gorsel_bul(makale.get("gorsel_arama_terimi", ""))

                icerik_html = makale["icerik_html"]
                if gorsel_url:
                    gorsel_etiketi = (
                        f"<p><img src='{gorsel_url}' alt='{makale['baslik']}' "
                        f"style='max-width:100%; height:auto; border-radius:8px;'/></p>"
                        f"<p><small>Görsel: Pexels / {fotografci}</small></p>"
                    )
                    icerik_html = gorsel_etiketi + icerik_html

                sonuc = blogger_paylas(
                    access_token, blog_id,
                    makale["baslik"], icerik_html,
                    makale["etiketler"], makale.get("meta_aciklama", ""),
                )

                if sonuc.status_code in (200, 201):
                    durum = "taslak olarak kaydedildi" if TASLAK_OLARAK_KAYDET else "yayınlandı"
                    print(f"  ✅ Başarılı ({durum}) [{kaynak_adi} | {makale.get('kategori')}]: {makale['baslik']}")
                    history["yayinlanan_linkler"].append(link)
                    bu_calismada_paylasilan += 1
                    save_history(history)
                else:
                    print(f"  ❌ Blogger Hatası [{kaynak_adi}]: {sonuc.status_code} - {sonuc.text}")

            except Exception as e:
                print(f"  ❌ İşlem Hatası [{kaynak_adi}]: {e}")
                print(traceback.format_exc())
                continue

    if bu_calismada_paylasilan == 0:
        print("ℹ️ Bu çalıştırmada uygun yeni haber bulunamadı veya hiçbiri paylaşılamadı.")
    else:
        print(f"🏁 Bu çalıştırmada toplam {bu_calismada_paylasilan} yazı işlendi.")


if __name__ == "__main__":
    main()
