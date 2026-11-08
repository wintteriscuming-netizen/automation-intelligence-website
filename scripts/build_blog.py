#!/usr/bin/env python3
"""Builds blog posts (content/posts/*.md) and pages (content/pages/*.md),
plus /blog/ index, sitemap.xml and robots.txt.
Future-dated items and items containing 'TODO' are NOT published.
A broken file is skipped with a red error note; everything else still builds."""
import re, sys, json, html, shutil
from datetime import datetime, date
from pathlib import Path
from zoneinfo import ZoneInfo
import markdown, yaml

ROOT = Path(__file__).resolve().parent.parent
SITE = "https://automationintelligence.in"
POSTS, PAGES = ROOT / "content" / "posts", ROOT / "content" / "pages"
TPL, OUT = ROOT / "templates", ROOT / "blog"
TODAY = datetime.now(ZoneInfo("Asia/Kolkata")).date()
MARK = "<!-- generated-by-build_blog -->"
RESERVED = {"blog", "content", "templates", "scripts", "assets", "images"}
esc = lambda s: html.escape(str(s), quote=True)
fmt = lambda d: f"{d.day} {d:%B %Y}"
md = lambda t: markdown.markdown(t, extensions=["tables", "sane_lists", "fenced_code"])

def fill(t, **kw):
    for k, v in kw.items():
        t = t.replace("{{" + k + "}}", v)
    return t

def load(p, need_date):
    m = re.match(r"^---\n(.*?)\n---\n(.*)$", p.read_text(encoding="utf-8").replace("\r\n", "\n"), re.S)
    if not m:
        raise ValueError("missing front matter (the --- lines at the top)")
    meta = yaml.safe_load(m.group(1)) or {}
    for k in ("title", "description", "slug") + (("date",) if need_date else ()):
        if not meta.get(k):
            raise ValueError(f"missing '{k}'")
    for k in ("date", "updated"):
        if meta.get(k) and not isinstance(meta[k], date):
            meta[k] = date.fromisoformat(str(meta[k]))
    meta["body"] = m.group(2)
    return meta

def collect(folder, need_date):
    live, all_slugs = [], set()
    for f in sorted(folder.glob("*.md")):
        rel = f.relative_to(ROOT)
        try:
            m = load(f, need_date)
            slug = str(m["slug"])
            if not re.fullmatch(r"[a-z0-9-]+", slug):
                raise ValueError("slug may only use lowercase letters, numbers and hyphens")
            if slug in all_slugs:
                raise ValueError(f"duplicate slug '{slug}'")
        except Exception as e:
            print(f"::error file={rel}::SKIPPED - {e}"); continue
        m["slug"] = slug; all_slugs.add(slug)
        if m.get("date") and m["date"] > TODAY:
            print(f"scheduled for {m['date']}: {rel.name}"); continue
        if "TODO" in f.read_text(encoding="utf-8"):
            print(f"::warning file={rel}::contains TODO - not published"); continue
        live.append(m)
    return live, all_slugs

def faq_parts(m):
    faq = m.get("faq") or []
    h = ("<h2>Frequently asked questions</h2>" + "".join(
        f"<h3>{esc(f['q'])}</h3><p>{esc(f['a'])}</p>" for f in faq)) if faq else ""
    node = [{"@type": "FAQPage", "mainEntity": [{"@type": "Question", "name": f["q"],
             "acceptedAnswer": {"@type": "Answer", "text": f["a"]}} for f in faq]}] if faq else []
    return h, node

def crumbs(items):
    return {"@type": "BreadcrumbList", "itemListElement": [
        {"@type": "ListItem", "position": i + 1, "name": n, "item": u} for i, (n, u) in enumerate(items)]}

def render_post(m, tpl):
    body = md(m["body"]); faq_html, faq_node = faq_parts(m)
    url = f"{SITE}/blog/{m['slug']}/"
    graph = [{"@type": "Article", "headline": m["title"], "description": m["description"],
              "datePublished": m["date"].isoformat(), "dateModified": (m.get("updated") or m["date"]).isoformat(),
              "mainEntityOfPage": url, "image": f"{SITE}/og-image.png",
              "author": {"@type": "Person", "name": "Rishikesh Perja"},
              "publisher": {"@type": "Organization", "name": "Automation Intelligence",
                            "logo": {"@type": "ImageObject", "url": f"{SITE}/web-app-manifest-512x512.png"}}},
             crumbs([("Home", SITE + "/"), ("Blog", SITE + "/blog/"), (m["title"], url)])] + faq_node
    minutes = max(1, round(len(re.findall(r"\w+", m["body"])) / 200))
    return fill(tpl, title=esc(m["title"]), description=esc(m["description"]), url=url,
                date_iso=m["date"].isoformat(), date_human=fmt(m["date"]), minutes=str(minutes), body=body,
                faq=faq_html, schema=json.dumps({"@context": "https://schema.org", "@graph": graph},
                                                ensure_ascii=False)), body

def render_page(m, tpl):
    body = md(m["body"]); faq_html, faq_node = faq_parts(m)
    url = f"{SITE}/{m['slug']}/"
    graph = [{"@type": "WebPage", "name": m["title"], "description": m["description"], "url": url,
              "isPartOf": {"@type": "WebSite", "name": "Automation Intelligence", "url": SITE + "/"}},
             crumbs([("Home", SITE + "/"), (m["title"], url)])]
    if m.get("type") == "service":
        graph.append({"@type": "Service", "name": m["title"], "description": m["description"], "areaServed": "India",
                      "provider": {"@type": "Organization", "name": "Automation Intelligence", "url": SITE + "/"}})
    return fill(tpl, title=esc(m["title"]), description=esc(m["description"]), url=url, body=body, faq=faq_html,
                schema=json.dumps({"@context": "https://schema.org", "@graph": graph + faq_node},
                                  ensure_ascii=False)), body

def check_links(slug, body, known):
    for href in re.findall(r'href="(/[^"#]*)"', body):
        t = ROOT / href.strip("/")
        if href != "/" and not (t.exists() or (t / "index.html").exists() or href.strip("/").split("/")[-1] in known):
            print(f"::warning::{slug} links to missing {href}")

def main():
    post_tpl, page_tpl, idx_tpl = [(TPL / n).read_text(encoding="utf-8") for n in ("post.html", "page.html", "blog-index.html")]
    posts, post_slugs = collect(POSTS, True)
    pages, page_slugs = collect(PAGES, False)
    known = post_slugs | page_slugs
    posts.sort(key=lambda m: m["date"], reverse=True)

    for d in ROOT.iterdir():  # remove pages generated by an earlier run
        i = d / "index.html"
        if d.is_dir() and d.name not in RESERVED and not d.name.startswith(".") and i.exists() \
                and MARK in i.read_text(encoding="utf-8", errors="ignore"):
            shutil.rmtree(d)
    shutil.rmtree(OUT, ignore_errors=True); OUT.mkdir()
    shutil.copy(TPL / "blog.css", OUT / "blog.css")

    live_posts, live_pages = [], []
    for m in posts:
        try:
            page, body = render_post(m, post_tpl)
        except Exception as e:
            print(f"::error file=content/posts::{m['slug']} SKIPPED - {e}"); continue
        (OUT / m["slug"]).mkdir(); (OUT / m["slug"] / "index.html").write_text(page, encoding="utf-8")
        check_links(m["slug"], body, known); live_posts.append(m)
    for m in pages:
        s = m["slug"]
        if s in RESERVED or (ROOT / s).exists():
            print(f"::error file=content/pages::{s} SKIPPED - clashes with an existing file or folder"); continue
        try:
            page, body = render_page(m, page_tpl)
        except Exception as e:
            print(f"::error file=content/pages::{s} SKIPPED - {e}"); continue
        (ROOT / s).mkdir(); (ROOT / s / "index.html").write_text(page, encoding="utf-8")
        check_links(s, body, known); live_pages.append(m)

    cards = "".join(
        f'<a class="card" href="/blog/{m["slug"]}/"><time datetime="{m["date"].isoformat()}">{fmt(m["date"])}</time>'
        f'<h2>{esc(m["title"])}</h2><p>{esc(m["description"])}</p></a>' for m in live_posts
    ) or "<p>New articles are on the way.</p>"
    (OUT / "index.html").write_text(fill(idx_tpl, cards=cards), encoding="utf-8")

    urls = [("/", None), ("/blog/", None), ("/privacy-policy.html", None), ("/terms-of-service.html", None)]
    urls += [(f"/{m['slug']}/", (m.get("updated") or m.get("date") or TODAY).isoformat()) for m in live_pages]
    urls += [(f"/blog/{m['slug']}/", (m.get("updated") or m["date"]).isoformat()) for m in live_posts]
    xml = "".join(f"<url><loc>{SITE}{u}</loc>" + (f"<lastmod>{l}</lastmod>" if l else "") + "</url>" for u, l in urls)
    (ROOT / "sitemap.xml").write_text('<?xml version="1.0" encoding="UTF-8"?>\n'
        f'<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">{xml}</urlset>\n', encoding="utf-8")
    if not (ROOT / "robots.txt").exists():
        (ROOT / "robots.txt").write_text(f"User-agent: *\nAllow: /\n\nSitemap: {SITE}/sitemap.xml\n")
    print(f"Published {len(live_posts)} post(s) and {len(live_pages)} page(s). Today (IST): {TODAY}")

if __name__ == "__main__":
    main()
