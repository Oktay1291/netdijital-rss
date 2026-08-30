"""
BİR KEZ çalıştırılacak yardımcı script.
AdSense başvurusu için Blogger sitende Hakkımızda, Gizlilik Politikası ve
İletişim sayfalarının bulunması neredeyse zorunludur. Bu script bu 3 sayfayı
Blogger'a otomatik ekler (taslak olarak - içerikleri kontrol edip yayınla).

Kullanım: python setup_pages.py
"""

import os
import requests

CLIENT_ID = os.getenv("BLOGGER_CLIENT_ID")
CLIENT_SECRET = os.getenv("BLOGGER_CLIENT_SECRET")
REFRESH_TOKEN = os.getenv("BLOGGER_REFRESH_TOKEN")

SITE_ADI = "https://netdijital.blogspot.com/"  # 
IletisIM_EPOSTA = "ktysarikaya@gmail.com"  # 


def get_access_token():
    r = requests.post(
        "https://oauth2.googleapis.com/token",
        data={
            "client_id": CLIENT_ID,
            "client_secret": CLIENT_SECRET,
            "refresh_token": REFRESH_TOKEN,
            "grant_type": "refresh_token",
        },
        timeout=15,
    )
    return r.json().get("access_token") if r.status_code == 200 else None


def get_blog_id(token):
    r = requests.get(
        "https://www.googleapis.com/blogger/v3/users/self/blogs",
        headers={"Authorization": f"Bearer {token}"},
        timeout=15,
    )
    items = r.json().get("items", [])
    return items[0]["id"] if items else None


def sayfa_olustur(token, blog_id, baslik, icerik):
    url = f"https://www.googleapis.com/blogger/v3/blogs/{blog_id}/pages/"
    r = requests.post(
        url,
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        json={"kind": "blogger#page", "title": baslik, "content": icerik},
        timeout=20,
    )
    if r.status_code in (200, 201):
        print(f"✅ Oluşturuldu: {baslik}")
    else:
        print(f"❌ Hata [{baslik}]: {r.status_code} - {r.text}")


SAYFALAR = {
    "Hakkımızda": f"""
<p>{SITE_ADI}, teknoloji dünyasındaki güncel gelişmeleri takip edip
okuyucularına özgün, anlaşılır ve derlenmiş haberler sunmayı amaçlayan bir
teknoloji haber platformudur.</p>
<p>Ekibimiz, uluslararası teknoloji kaynaklarını takip ederek en önemli
gelişmeleri Türkçe okuyucuya ulaştırmak için çalışır.</p>
""",
    "Gizlilik Politikası": f"""
<p>{SITE_ADI} olarak ziyaretçilerimizin gizliliğine önem veriyoruz.</p>
<h2>Çerezler (Cookies)</h2>
<p>Sitemiz, kullanıcı deneyimini geliştirmek ve reklam hizmetleri (Google
AdSense dahil) sunmak amacıyla çerezler kullanabilir. Google, çerezleri
kullanarak sitemize ve internetteki diğer sitelere yapılan ziyaretlere
dayanarak reklam sunabilir.</p>
<p>Google'ın reklam ayarlarını
<a href="https://adssettings.google.com" target="_blank" rel="nofollow">
buradan</a> yönetebilirsiniz.</p>
<h2>Kişisel Veriler</h2>
<p>Sitemiz, ziyaretçilerinden doğrudan kişisel veri talep etmez. Üçüncü
taraf reklam sağlayıcıları kendi gizlilik politikalarına tabidir.</p>
<h2>İletişim</h2>
<p>Gizlilik politikamızla ilgili sorularınız için: {IletisIM_EPOSTA}</p>
""",
    "İletişim": f"""
<p>Bizimle iletişime geçmek için aşağıdaki e-posta adresini
kullanabilirsiniz:</p>
<p><strong>E-posta:</strong> {IletisIM_EPOSTA}</p>
<p>Görüş, öneri ve içerik düzeltme talepleriniz için bize yazabilirsiniz.</p>
""",
}


if __name__ == "__main__":
    token = get_access_token()
    if not token:
        print("❌ Token alınamadı.")
        raise SystemExit(1)

    blog_id = get_blog_id(token)
    if not blog_id:
        print("❌ Blog ID alınamadı.")
        raise SystemExit(1)

    for baslik, icerik in SAYFALAR.items():
        sayfa_olustur(token, blog_id, baslik, icerik.strip())

    print("\n📌 Not: Sayfalar oluşturuldu ama Blogger panelinden içerikleri gözden")
    print("geçirip (özellikle e-posta adresini) düzenleyip YAYINLAMAN gerekiyor.")
