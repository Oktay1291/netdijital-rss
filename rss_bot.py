import os
import json
import random
import time
import html
import traceback
import base64
import re
from datetime import datetime, timezone

import requests
import feedparser

from bs4 import BeautifulSoup
from google import genai
from google.genai import types


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
# GEMINI
# ============================================================

client = genai.Client(api_key=GEMINI_API_KEY) if GEMINI_API_KEY else None


# ============================================================
# RSS KAYNAKLARI
# ============================================================

RSS_SOURCES = [

    {
        "url": "https://www.engadget.com/rss.xml",
        "kaynak": "Engadget"
    },

    {
        "url": "https://www.digitaltrends.com/feed/",
        "kaynak": "Digital Trends"
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
        "url": "https://techcrunch.com/feed/",
        "kaynak": "TechCrunch"
    },

    {
        "url": "https://www.theverge.com/rss/index.xml",
        "kaynak": "The Verge"
    },

    {
        "url": "https://www.wired.com/feed/rss",
        "kaynak": "WIRED"
    },

    {
        "url": "https://mashable.com/feed.rss",
        "kaynak": "Mashable"
    }
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
# GEMINI HABER ÜRETİMİ
# ============================================================

def llm_ile_makale_uret(
    orijinal_baslik,
    orijinal_ozet
):

    if not client:

        print(
            "GEMINI_API_KEY tanimli degil."
        )

        return None, False


    prompt = f"""
Sen Türkiye'nin en büyük teknoloji haber sitelerinden
birinde çalışan kıdemli teknoloji editörü ve SEO uzmanısın.

Aşağıdaki haber bilgisini temel alarak tamamen özgün
bir Türkçe teknoloji haberi oluştur.

ORİJİNAL BAŞLIK:
{orijinal_baslik}

ORİJİNAL ÖZET:
{orijinal_ozet}

KURALLAR:

1. Haber 750 ile 1200 Türkçe kelime arasında olsun.

2. Orijinal metni cümle cümle çevirme veya yeniden yazma.

3. Bilgileri kendi haber anlatımınla sentezle.

4. Haber doğal bir insan gazeteci tarafından yazılmış
   gibi okunmalı.

5. Gereksiz yapay zeka kalıpları kullanma.

6. Başlık Google aramalarında ilgi çekecek ancak
   clickbait olmayacak şekilde hazırlanmalı.

7. İlk paragraf haberi doğrudan anlatmalı.

8. En az 4 adet H2 başlığı kullan.

9. Gerekirse H3 başlıkları kullan.

10. Kısa paragraflar kullan.

11. Önemli bilgileri gerektiğinde madde işaretleriyle ver.

12. Anahtar kelimeleri doğal biçimde kullan.

13. Ana anahtar kelimeyi başlıkta ve girişte
    doğal biçimde kullan.

14. Haber içinde "Bu yazıda..." gibi yapay girişler kullanma.

15. Okuyucuya doğrudan bilgi veren haber dili kullan.

16. Konuya ilişkin internet dünyasındaki yankıları,
    kullanıcıların ilgisini, sektör açısından önemini
    ve olası etkilerini değerlendir.

17. Elindeki bilgilerde kesin olmayan bir iddia varsa
    bunu kesin gerçek gibi yazma.

18. Kaynak sitelerin metnini veya uzun ifadelerini
    kopyalama.

19. Haber içinde kaynak kuruluşların isimlerini
    gereksiz şekilde tekrar etme.

20. Sonuç bölümü okuyucuya konunun bundan sonra
    neden önemli olacağını açıklasın.

21. Meta açıklaması yaklaşık 140-160 karakter olsun.

22. 5-10 arası SEO etiketi üret.

23. Görsel için İngilizce bir arama terimi üret.

24. Sadece JSON döndür.

JSON ŞABLONU:

{{
  "baslik": "SEO uyumlu haber başlığı",
  "icerik_html": "<p>...</p><h2>...</h2><p>...</p>",
  "meta_aciklama": "SEO meta açıklaması",
  "kategori": "Teknoloji",
  "etiketler": [
    "Etiket 1",
    "Etiket 2"
  ],
  "gorsel_arama_terimi": "technology AI smartphone"
}}
"""


    for deneme in range(3):

        try:

            response = client.models.generate_content(

                model="gemini-3.6-flash",

                contents=prompt,

                config=types.GenerateContentConfig(

                    temperature=0.35,

                    max_output_tokens=8192,

                    response_mime_type="application/json"
                )
            )


            metin = (
                response.text or ""
            ).strip()


            if metin.startswith("```"):

                satirlar = (
                    metin.splitlines()
                )

                if satirlar:

                    satirlar = satirlar[1:]

                if (
                    satirlar
                    and satirlar[-1].startswith("```")
                ):

                    satirlar = satirlar[:-1]

                metin = "\n".join(
                    satirlar
                ).strip()


            veri = json.loads(
                metin,
                strict=False
            )


            if (
                not veri.get("baslik")
                or not veri.get("icerik_html")
            ):

                print(
                    "Gemini eksik veri döndürdü."
                )

                continue


            # Etiketleri temizle

            etiketler = veri.get(
                "etiketler",
                []
            )

            if not isinstance(
                etiketler,
                list
            ):

                etiketler = []


            etiketler = [
                str(x).strip()
                for x in etiketler
                if str(x).strip()
            ]


            etiketler = list(
                dict.fromkeys(
                    etiketler
                )
            )


            havuz = (
                GENEL_ETIKET_HAVUZU.copy()
            )

            random.shuffle(havuz)


            for etiket in havuz:

                if len(etiketler) >= 10:
                    break

                if etiket not in etiketler:

                    etiketler.append(
                        etiket
                    )


            veri["etiketler"] = etiketler[:10]


            return veri, False


        except json.JSONDecodeError as e:

            print(
                f"JSON hatasi "
                f"({deneme + 1}/3): {e}"
            )

            time.sleep(4)


        except Exception as e:

            hata = str(e)

            if (
                "429" in hata
                or "RESOURCE_EXHAUSTED" in hata
            ):

                bekleme = 45 * (
                    deneme + 1
                )

                print(
                    f"Gemini kota siniri. "
                    f"{bekleme} saniye bekleniyor."
                )

                time.sleep(
                    bekleme
                )

                continue


            print(
                f"Gemini hatasi: {e}"
            )

            if deneme < 2:

                time.sleep(5)

                continue

            return None, False


    return None, False


# ============================================================
# BLOGGER
# ============================================================

def blogger_paylas(
    access_token,
    blog_id,
    baslik,
    icerik,
    etiketler,
    is_draft=False
):

    url = (
        "https://www.googleapis.com/"
        f"blogger/v3/blogs/{blog_id}/posts/"
    )

    headers = {
        "Authorization":
            f"Bearer {access_token}",

        "Content-Type":
            "application/json"
    }

    params = {
        "isDraft":
            "true" if is_draft else "false"
    }

    data = {
        "title": baslik,
        "content": icerik,
        "labels":
            etiketler
            if isinstance(
                etiketler,
                list
            )
            else []
    }

    return requests.post(
        url,
        headers=headers,
        params=params,
        json=data,
        timeout=40
    )


# ============================================================
# GÖRSEL HTML
# ============================================================

def gorsel_html_olustur(
    gorsel_url,
    baslik
):

    if not gorsel_url:
        return ""

    try:

        safe_url = html.escape(
            gorsel_url,
            quote=True
        )

        safe_title = html.escape(
            baslik,
            quote=True
        )

        return (
            "<p>"
            f"<img src='{safe_url}' "
            f"alt='{safe_title}' "
            "style='max-width:100%;"
            "height:auto;"
            "border-radius:8px;'/>"
            "</p>"
        )

    except Exception:

        return ""


# ============================================================
# MAIN
# ============================================================

def main():

    print("=" * 60)

    print(
        "TEKNOLOJİ HABER BOTU BAŞLADI"
    )

    print(
        datetime.now(
            timezone.utc
        ).isoformat()
    )

    print("=" * 60)


    # --------------------------------------------------------
    # ENV KONTROLÜ
    # --------------------------------------------------------

    zorunlu = {
        "BLOGGER_CLIENT_ID":
            CLIENT_ID,

        "BLOGGER_CLIENT_SECRET":
            CLIENT_SECRET,

        "BLOGGER_REFRESH_TOKEN":
            REFRESH_TOKEN,

        "GEMINI_API_KEY":
            GEMINI_API_KEY,

        "BLOGGER_BLOG_ID":
            BLOGGER_BLOG_ID
    }


    eksikler = [
        isim
        for isim, deger in zorunlu.items()
        if not deger
    ]


    if eksikler:

        print(
            "Eksik GitHub Secret:"
        )

        for isim in eksikler:

            print(
                f"- {isim}"
            )

        return


    # --------------------------------------------------------
    # HISTORY
    # --------------------------------------------------------

    history = load_history()


    # --------------------------------------------------------
    # GOOGLE TOKEN
    # --------------------------------------------------------

    print(
        "Blogger kimlik doğrulaması..."
    )


    access_token = get_access_token(
        CLIENT_ID,
        CLIENT_SECRET,
        REFRESH_TOKEN
    )


    if not access_token:

        print(
            "Access token alınamadı."
        )

        return


    # --------------------------------------------------------
    # RSS KAYNAKLARINI DÖNDÜR
    # --------------------------------------------------------

    toplam_kaynak = len(
        RSS_SOURCES
    )


    mevcut_index = (
        history.get(
            "son_kaynak_index",
            0
        )
        % toplam_kaynak
    )


    sirali_kaynaklar = [

        (
            (
                mevcut_index + i
            ) % toplam_kaynak,

            RSS_SOURCES[
                (
                    mevcut_index + i
                ) % toplam_kaynak
            ]
        )

        for i in range(
            toplam_kaynak
        )
    ]


    # --------------------------------------------------------
    # HABER ARA
    # --------------------------------------------------------

    for idx, kaynak in sirali_kaynaklar:

        kaynak_adi = kaynak[
            "kaynak"
        ]

        rss_url = kaynak[
            "url"
        ]


        print(
            f"Kaynak taranıyor: "
            f"{kaynak_adi}"
        )


        feed = fetch_feed(
            rss_url,
            kaynak_adi
        )


        if not feed.entries:

            continue


        # En güncel 15 haber

        for entry in feed.entries[:15]:

            link = normalize_url(
                entry.get(
                    "link"
                )
            )


            if not link:

                continue


            # ------------------------------------------------
            # DAHA ÖNCE YAYINLANDI MI?
            # ------------------------------------------------

            if link in history[
                "yayinlanan_linkler"
            ]:

                print(
                    "Daha önce yayınlandı:"
                    f" {link}"
                )

                continue


            orijinal_baslik = (
                entry.get(
                    "title",
                    ""
                )
                or "Teknoloji Gündemi"
            )


            ham_ozet = (
                entry.get(
                    "summary",
                    ""
                )
                or entry.get(
                    "description",
                    ""
                )
                or ""
            )


            orijinal_ozet = (
                BeautifulSoup(
                    ham_ozet,
                    "html.parser"
                ).get_text(
                    separator=" ",
                    strip=True
                )
            )


            # ------------------------------------------------
            # ÖZET ÇOK KISAYSA CONTENT AL
            # ------------------------------------------------

            if len(orijinal_ozet) < 100:

                content_html = (
                    entry.get(
                        "content",
                        []
                    )
                )

                if content_html:

                    try:

                        orijinal_ozet = (
                            BeautifulSoup(
                                content_html[0].get(
                                    "value",
                                    ""
                                ),
                                "html.parser"
                            ).get_text(
                                separator=" ",
                                strip=True
                            )
                        )

                    except Exception:

                        pass


            print()
            print(
                "SEÇİLEN HABER:"
            )
            print(
                orijinal_baslik
            )


            # ------------------------------------------------
            # GEMINI
            # ------------------------------------------------

            makale, kota = (
                llm_ile_makale_uret(
                    orijinal_baslik,
                    orijinal_ozet
                )
            )


            if kota:

                print(
                    "Gemini kotası doldu."
                )

                return


            if not makale:

                print(
                    "Makale üretilemedi."
                )

                continue


            baslik = (
                makale.get(
                    "baslik",
                    orijinal_baslik
                )
            )


            icerik_html = (
                makale.get(
                    "icerik_html",
                    ""
                )
            )


            # ------------------------------------------------
            # GÖRSEL 1:
            # RSS
            # ------------------------------------------------

            gorsel_url = (
                rss_gorsel_bul(
                    entry
                )
            )


            if gorsel_url:

                print(
                    "Görsel RSS'ten alındı."
                )


            # ------------------------------------------------
            # GÖRSEL 2:
            # ORİJİNAL SAYFA OG IMAGE
            # ------------------------------------------------

            if not gorsel_url:

                print(
                    "Orijinal sayfanın görseli aranıyor..."
                )

                gorsel_url = (
                    sayfa_gorseli_bul(
                        link
                    )
                )


                if gorsel_url:

                    print(
                        "Orijinal sayfa görseli bulundu."
                    )


            # ------------------------------------------------
            # GÖRSEL 3:
            # PEXELS
            # ------------------------------------------------

            fotografci = None


            if not gorsel_url:

                print(
                    "Pexels yedek görsel aranıyor..."
                )


                gorsel_url, fotografci = (
                    pexels_gorsel_bul(
                        makale.get(
                            "gorsel_arama_terimi",
                            ""
                        )
                    )
                )


            # ------------------------------------------------
            # GÖRSEL HTML
            # ------------------------------------------------

            if gorsel_url:

                gorsel_html = (
                    gorsel_html_olustur(
                        gorsel_url,
                        baslik
                    )
                )

                icerik_html = (
                    gorsel_html
                    + icerik_html
                )


            # ------------------------------------------------
            # ETİKETLER
            # ------------------------------------------------

            etiketler = (
                makale.get(
                    "etiketler",
                    []
                )
            )


            if not isinstance(
                etiketler,
                list
            ):

                etiketler = []


            # Kategori de etikete eklenebilir

            kategori = (
                makale.get(
                    "kategori"
                )
            )


            if kategori:

                if kategori not in etiketler:

                    etiketler.insert(
                        0,
                        kategori
                    )


            # ------------------------------------------------
            # BLOGGER
            # ------------------------------------------------

            print(
                "Blogger'a gönderiliyor..."
            )


            sonuc = blogger_paylas(

                access_token=
                    access_token,

                blog_id=
                    BLOGGER_BLOG_ID,

                baslik=
                    baslik,

                icerik=
                    icerik_html,

                etiketler=
                    etiketler,

                is_draft=
                    TASLAK_OLARAK_KAYDET
            )


            # ------------------------------------------------
            # BAŞARILI
            # ------------------------------------------------

            if sonuc.status_code in (
                200,
                201
            ):

                try:

                    sonuc_data = (
                        sonuc.json()
                    )

                    blogger_url = (
                        sonuc_data.get(
                            "url"
                        )
                    )

                except Exception:

                    blogger_url = None


                print()
                print(
                    "================================"
                )

                print(
                    "HABER BAŞARIYLA YAYINLANDI"
                )

                print(
                    f"Başlık: {baslik}"
                )

                if blogger_url:

                    print(
                        f"URL: {blogger_url}"
                    )

                print(
                    "================================"
                )


                # ------------------------------------------------
                # HISTORY
                # ------------------------------------------------

                history[
                    "yayinlanan_linkler"
                ].append(
                    link
                )


                history[
                    "son_paylasim_zamani"
                ] = time.time()


                history[
                    "son_kaynak_index"
                ] = (
                    idx + 1
                ) % toplam_kaynak


                save_history(
                    history
                )


                # GitHub'a geri kaydet

                github_history_save()


                # ------------------------------------------------
                # TEK HABER
                # ------------------------------------------------

                print(
                    "Bu çalışma için "
                    "1 haber kotası tamamlandı."
                )

                return


            # ------------------------------------------------
            # BLOGGER HATASI
            # ------------------------------------------------

            else:

                print(
                    "Blogger API HATASI:"
                )

                print(
                    sonuc.status_code
                )

                print(
                    sonuc.text
                )

                return


    print(
        "Yayınlanabilecek yeni haber bulunamadı."
    )


# ============================================================
# START
# ============================================================

if __name__ == "__main__":

    try:

        main()

    except Exception as e:

        print(
            "BEKLENMEYEN HATA:"
        )

        print(e)

        print(
            traceback.format_exc()
        )

        raise
