import argparse
import asyncio
import json
from urllib.parse import urlparse, urljoin

import httpx
import feedparser
from bs4 import BeautifulSoup
from readability import Document
from markdownify import markdownify as md
import trafilatura

USER_AGENT = (
	"Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
	"(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)


async def fetch_text(client: httpx.AsyncClient, url: str) -> str:
	try:
		r = await client.get(url)
		if r.status_code >= 400:
			return ""
		return r.text or ""
	except Exception:
		return ""


def is_substack_host(html: str, host: str) -> bool:
	if host.endswith("substack.com"):
		return True
	soup = BeautifulSoup(html or "", "lxml")
	gen = soup.find("meta", attrs={"name": "generator"})
	if gen and "substack" in (gen.get("content") or "").lower():
		return True
	return False


def extract_with_trafilatura(url: str, html: str):
	try:
		md_text = trafilatura.extract(html, output_format="markdown", include_comments=False, include_tables=True, url=url)
		if md_text:
			meta = trafilatura.metadata.extract_metadata(html, url=url)
			title = meta.title if meta and getattr(meta, "title", None) else None
			return title, md_text
	except Exception:
		return None
	return None


def extract_with_readability(url: str, html: str):
	try:
		doc = Document(html)
		content_html = doc.summary(html_partial=True)
		title = doc.short_title()
		markdown = md(content_html or "", heading_style="ATX")
		if markdown and markdown.strip():
			return title, markdown
	except Exception:
		return None
	return None


def extract_substack_fallback(html: str):
	soup = BeautifulSoup(html or "", "lxml")
	# paywall/teaser check
	if soup.find(string=lambda s: s and "paid subscribers" in s.lower()):
		return None
	# fix lazy images
	for img in soup.find_all("img"):
		if img.get("src"):
			continue
		ds = img.get("data-src") or img.get("data-image-src") or img.get("data-asset-url")
		if ds:
			img["src"] = ds
	node = (
		soup.select_one("[data-post-body]") or
		soup.select_one("article [data-post-body]") or
		soup.select_one("article") or
		soup.select_one(".post-body") or
		soup.select_one(".available-content")
	)
	if not node:
		return None
	title = None
	h = soup.find("h1")
	if h and h.get_text(strip=True):
		title = h.get_text(strip=True)
	markdown = md(str(node), heading_style="ATX")
	if markdown and len(markdown.strip()) >= 40:
		return title, markdown
	return None


async def fetch_post(client: httpx.AsyncClient, url: str):
	html = await fetch_text(client, url)
	if not html:
		return None
	res = extract_with_trafilatura(url, html)
	if not res:
		res = extract_with_readability(url, html)
	if not res:
		res = extract_substack_fallback(html)
	if not res:
		return None
	title, content = res
	return {
		"title": title or (BeautifulSoup(html, "lxml").title.string if BeautifulSoup(html, "lxml").title else url),
		"content": content.strip(),
		"content_type": "blog",
		"source_url": url,
	}


async def main():
	p = argparse.ArgumentParser(description="Substack feed-first scraper test")
	p.add_argument("--url", required=True)
	p.add_argument("--max", type=int, default=5)
	p.add_argument("--out", default="substack.json")
	args = p.parse_args()

	seed = args.url if args.url.startswith("http") else f"https://{args.url}"
	host = urlparse(seed).netloc
	async with httpx.AsyncClient(timeout=httpx.Timeout(20.0), headers={
		"User-Agent": USER_AGENT,
		"Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
		"Accept-Language": "en-US,en;q=0.9",
	}, follow_redirects=True) as client:
		html = await fetch_text(client, seed)
		feed_url = None
		if is_substack_host(html, host):
			feed_url = urljoin(seed, "/feed")
		else:
			# fallback try /feed
			feed_url = urljoin(seed, "/feed")
			
		posts = []
		try:
			fp = feedparser.parse(feed_url)
			for e in fp.entries[: args.max]:
				link = e.get("link")
				if not link:
					continue
				item = await fetch_post(client, link)
				if item:
					posts.append(item)
		except Exception:
			pass

		result = {"site": seed, "items": posts}
		with open(args.out, "w", encoding="utf-8") as f:
			json.dump(result, f, ensure_ascii=False, indent=2)
		print(f"Wrote {len(posts)} items to {args.out}")


if __name__ == "__main__":
	asyncio.run(main())
