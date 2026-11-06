#!/usr/bin/env python3
"""Builds /blog, sitemap.xml and robots.txt from content/posts/*.md.
Posts dated in the future (IST) or containing 'TODO' are NOT published."""
import re, sys, json, html, shutil
from datetime import datetime, date
from pathlib import Path
from zoneinfo import ZoneInfo
import markdown, yaml

ROOT = Path(__file__).resolve().parent.parent
SITE = "https://automationintelligence.in"
POSTS, TPL, OUT = ROOT / "content" / "posts", ROOT / "templates", ROOT / "blog"
TODAY = datetime.now(ZoneInfo("Asia/Kolkata")).date()
esc = lambda s: html.escape(str(s), quote=True)
fmt = lambda d: f"{d.day} {d:%B %Y}"

def fill(t, **kw):
    for k, v in kw.items():
        t = t.replace("{{" + k + "}}", v)
    return t

def load(p):
    m = re.match(r"^---\n(.*?)\n---\n(.*)$", p.read_text(encoding="utf-8"), re.S)
    if not m:
        raise ValueError(f"{p.name}: missing front matter")
    meta = yaml.safe_load(m.group(1)) or {}
    for k in ("title", "description", "date", "slug"):
        if not meta.get(k):
            raise ValueError(f"{p.name}: missing '{k}'")
    for k in ("date", "updated"):
        if meta.get(k) and not isinstance(meta[k], date):
            meta[k] = date.fromisoformat(str(meta[k]))
    meta["body"] = m.group(2)
    return meta

def render_post(m, tpl):
    body = markdown.markdown(m["body"], extensions=["tables", "sane_lists", "fenced_code"])
    faq = m.get("faq") or []
    faq_html = ""
    if faq:
        faq_html = "<h2>Frequently asked questions</h2>" + "".join(
            f"<h3>{esc(f['q'])}</h3><p>{esc(f['a'])}</p>" for f in faq)
    url = f"{SITE}/blog/{m['slug']}/"
    modified = m.get("updated") or m["date"]
    graph = [
        {"@type": "Article", "headline": m["title"], "description": m["description"],
         "datePublished": m["date"].isoformat(), "dateModified": modified.isoformat(),
         "mainEntityOfPage": url, "image": f"{SITE}/og-image.png",
         "author": {"@type": "Person", "name": "Rishikesh Perja"},
         "publisher": {"@type": "Organization", "name": "Automation Intelligence",
                       "logo": {"@type": "ImageObject", "url": f"{SITE}/web-app-manifest-512x512.png"}}},
        {"@type": "BreadcrumbList", "itemListElement": [
            {"@type": "ListItem", "position": 1, "name": "Home", "item": SITE + "/"},
            {"@type": "ListItem", "position": 2, "name": "Blog", "item": SITE + "/blog/"},
            {"@type": "ListItem", "position": 3, "name": m["title"], "item": url}]},
    ]
    if faq:
        graph.append({"@type": "FAQPage", "mainEntity": [
            {"@type": "Question", "name": f["q"],
             "acceptedAnswer": {"@type": "Answer", "text": f["a"]}} for f in faq]})
    schema = json.dumps({"@context": "https://schema.org", "@graph": graph}, ensure_ascii=False)
    minutes = max(1, round(len(re.findall(r"\w+", m["body"])) / 200))
    return fill(tpl, title=esc(m["title"]), description=esc(m["description"]), url=url,
                date_iso=m["date"].isoformat(), date_human=fmt(m["date"]), minutes=str(minutes),
                body=body, faq=faq_html, schema=schema), body

def main():
    post_tpl = (TPL / "post.html").read_text(encoding="utf-8")
    idx_tpl = (TPL / "blog-index.html").read_text(encoding="utf-8")
    live, slugs = [], set()
    for f in sorted(POSTS.glob("*.md")):
        try:
            m = load(f)
        except Exception as e:
            sys.exit(f"ERROR: {e}")
        if m["slug"] in slugs:
            sys.exit(f"ERROR: duplicate slug '{m['slug']}'")
        slugs.add(m["slug"])
        if m["date"] > TODAY:
            print(f"scheduled for {m['date']}: {f.name}"); continue
        if "TODO" in f.read_text(encoding="utf-8"):
            print(f"SKIPPED (contains TODO): {f.name}"); continue
        live.append(m)
    live.sort(key=lambda m: m["date"], reverse=True)

    shutil.rmtree(OUT, ignore_errors=True)
    OUT.mkdir()
    shutil.copy(TPL / "blog.css", OUT / "blog.css")
    for m in live:
        page, body = render_post(m, post_tpl)
        d = OUT / m["slug"]; d.mkdir()
        (d / "index.html").write_text(page, encoding="utf-8")
        for href in re.findall(r'href="(/[^"#]*)"', body):  # non-fatal link check
            t = ROOT / href.strip("/")
            if href != "/" and not (t.exists() or (t / "index.html").exists()
                                    or href.strip("/").split("/")[-1] in slugs):
                print(f"WARNING: {m['slug']} links to missing {href}")
    cards = "".join(
        f'<a class="card" href="/blog/{m["slug"]}/"><time datetime="{m["date"].isoformat()}">{fmt(m["date"])}</time>'
        f'<h2>{esc(m["title"])}</h2><p>{esc(m["description"])}</p></a>' for m in live
    ) or "<p>New articles are on the way.</p>"
    (OUT / "index.html").write_text(fill(idx_tpl, cards=cards), encoding="utf-8")

    urls = [("/", None), ("/blog/", None), ("/privacy-policy.html", None), ("/terms-of-service.html", None)]
    urls += [(f"/blog/{m['slug']}/", (m.get("updated") or m["date"]).isoformat()) for m in live]
    xml = "".join(f"<url><loc>{SITE}{u}</loc>" + (f"<lastmod>{l}</lastmod>" if l else "") + "</url>"
                  for u, l in urls)
    (ROOT / "sitemap.xml").write_text('<?xml version="1.0" encoding="UTF-8"?>\n'
        f'<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">{xml}</urlset>\n', encoding="utf-8")
    if not (ROOT / "robots.txt").exists():
        (ROOT / "robots.txt").write_text(f"User-agent: *\nAllow: /\n\nSitemap: {SITE}/sitemap.xml\n")
    print(f"Published {len(live)} post(s). Today (IST): {TODAY}")

if __name__ == "__main__":
    main()
