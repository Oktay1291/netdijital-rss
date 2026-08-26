def post_to_blogger():
  import google.auth.transport.requests
  
  creds = Credentials(
      token=None,
      refresh_token=REFRESH_TOKEN,
      token_uri="https://oauth2.googleapis.com/token",
      client_id=CLIENT_ID,
      client_secret=CLIENT_SECRET,
      scopes=["https://www.googleapis.com/auth/blogger"],
  )
  
  # Token'ın süresini/geçerliliğini zorla yenile ve hata olasılığını sıfırla
  try:
      auth_req = google.auth.transport.requests.Request()
      creds.refresh(auth_req)
  except Exception as e:
      print(f"Kimlik doğrulama (Token yenileme) hatası: {e}")
      return

  service = build("blogger", "v3", credentials=creds)

  latest_entry = None
  used_source = ""

  for rss_url in RSS_SOURCES:
    feed = feedparser.parse(rss_url)
    if feed.entries:
      latest_entry = feed.entries[0]
      used_source = rss_url
      break

  if not latest_entry:
    print("Hiçbir RSS beslemesinden yazı bulunamadı.")
    return

  title = latest_entry.title
  link = latest_entry.link
  summary = latest_entry.get("summary", "")

  print(f"Kaynak: {used_source} | İşlenen Haber: {title}")

  article_html, labels = generate_seo_article_and_labels(title, summary)
  print(f"Seçilen Kategori ve Etiketler: {labels}")

  content = (
      f"{article_html}<p><br></p><p><a href='{link}' target='_blank'"
      " rel='nofollow'>Haberi Kaynağından Oku</a></p>"
  )

  post_body = {"title": title, "content": content, "labels": labels}

  try:
    request = service.posts().insert(blogId=BLOG_ID, body=post_body)
    response = request.execute()
    print(f"750-1200 kelimelik SEO uyumlu yazı başarıyla yayınlandı! {title}")

    post_url = response.get("url")
    if post_url:
      post_to_facebook(title, post_url)

  except Exception as e:
    print(f"Yazı yayınlanırken hata oluştu: {e}")
