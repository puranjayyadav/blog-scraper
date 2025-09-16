import asyncio
import argparse
import json
import re
import sys
import time
from typing import Any, Dict, List, Optional, Set, Tuple
from urllib.parse import urljoin, urlparse, urlunparse

import httpx
import tldextract
import feedparser
from bs4 import BeautifulSoup

from readability import Document
from markdownify import markdownify as md
import trafilatura

# -----------------------------
# URL utilities
# -----------------------------

BLOG_HINT_PATHS = [
	"/blog",
	"/blogs",
	"/articles",
	"/article",
	"/posts",
	"/post",
	"/stories",
	"/learn",
	"/guides",
	"/guide",
	"/topics",
	"/resources",
]

COMMON_FEEDS = [
	"/feed",
	"/rss",
	"/atom.xml",
	"/index.xml",
	"/blog/feed",
	"/blog/rss.xml",
	"/blog/atom.xml",
]

SITEMAP_CANDIDATES = [
	"/sitemap.xml",
	"/sitemap_index.xml",
	"/sitemap-index.xml",
]

USER_AGENT = (
	"Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
	"(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)


def normalize_url(url: str) -> str:
	parsed = urlparse(url)
	# Remove fragments and normalize scheme/host casing
	clean = parsed._replace(fragment="")
	return urlunparse(clean)


def same_registered_domain(a: str, b: str) -> bool:
	ad = tldextract.extract(a)
	bd = tldextract.extract(b)
	return ad.registered_domain == bd.registered_domain and ad.registered_domain != ""


def within_seed_scope(candidate: str, seed: str) -> bool:
	# Domain must match; if seed includes a non-root path, restrict to that subpath
	if not same_registered_domain(candidate, seed):
		return False
	seed_parsed = urlparse(seed)
	cand_parsed = urlparse(candidate)
	seed_path = seed_parsed.path.rstrip("/")
	if seed_path:
		return cand_parsed.path.startswith(seed_path)
	return True


# -----------------------------
# HTTP client and helpers
# -----------------------------

class HttpClient:
	def __init__(self, timeout: float = 20.0, max_connections: int = 10):
		self.client = httpx.AsyncClient(
			timeout=httpx.Timeout(timeout),
			headers={
				"User-Agent": USER_AGENT,
				"Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
				"Accept-Language": "en-US,en;q=0.9",
			},
			follow_redirects=True,
			limits=httpx.Limits(max_connections=max_connections, max_keepalive_connections=20),
		)

	async def _request(self, method: str, url: str) -> Optional[httpx.Response]:
		for attempt in range(3):
			try:
				resp = await self.client.request(method, url)
				if resp.status_code >= 500:
					# retry on server errors
					delay = 0.5 * (2 ** attempt)
					await asyncio.sleep(delay)
					continue
				return resp if resp.status_code < 400 else None
			except Exception:
				delay = 0.5 * (2 ** attempt)
				await asyncio.sleep(delay)
		return None

	async def get(self, url: str) -> Optional[httpx.Response]:
		return await self._request("GET", url)

	async def head(self, url: str) -> Optional[httpx.Response]:
		return await self._request("HEAD", url)

	async def close(self):
		await self.client.aclose()


# -----------------------------
# Discovery: robots/sitemaps, feeds, and on-page
# -----------------------------

async def fetch_text(client: HttpClient, url: str) -> Optional[str]:
	resp = await client.get(url)
	if not resp:
		return None
	try:
		return resp.text
	except Exception:
		return None


async def discover_sitemaps(client: HttpClient, base_url: str) -> Set[str]:
	found: Set[str] = set()
	parsed = urlparse(base_url)
	root = f"{parsed.scheme}://{parsed.netloc}"
	robots_url = urljoin(root, "/robots.txt")
	robots_txt = await fetch_text(client, robots_url)
	if robots_txt:
		for line in robots_txt.splitlines():
			if line.lower().startswith("sitemap:"):
				candidate = line.split(":", 1)[1].strip()
				if candidate:
					found.add(normalize_url(candidate))
	for suffix in SITEMAP_CANDIDATES:
		found.add(normalize_url(urljoin(root, suffix)))
	return found


def parse_xml_for_loc(xml_text: str) -> List[str]:
	# Very lenient parse to get <loc>... URLs
	soup = BeautifulSoup(xml_text, "xml")
	locs = [loc.get_text(strip=True) for loc in soup.find_all("loc")]
	return [u for u in locs if u]


async def _expand_single_sitemap(client: HttpClient, sitemap_url: str, seed_url: str, visited: Set[str], acc: Set[str], depth: int = 0):
	if sitemap_url in visited or depth > 3:  # Prevent infinite recursion
		return
	visited.add(sitemap_url)
	text = await fetch_text(client, sitemap_url)
	if not text:
		return
	for u in parse_xml_for_loc(text):
		nu = normalize_url(u)
		# Recurse into nested sitemap indexes
		if nu.endswith(".xml") or "/sitemap" in urlparse(nu).path:
			await _expand_single_sitemap(client, nu, seed_url, visited, acc, depth + 1)
			continue
		if within_seed_scope(nu, seed_url):
			acc.add(nu)


async def expand_sitemaps(client: HttpClient, sitemap_urls: Set[str], seed_url: str) -> Set[str]:
	urls: Set[str] = set()
	visited: Set[str] = set()
	for sm in list(sitemap_urls):
		await _expand_single_sitemap(client, sm, seed_url, visited, urls)
	return urls


async def discover_feeds(client: HttpClient, base_url: str) -> Set[str]:
	parsed = urlparse(base_url)
	root = f"{parsed.scheme}://{parsed.netloc}"
	candidates = {normalize_url(urljoin(root, path)) for path in COMMON_FEEDS}
	# Also try feed endpoints relative to the provided base_url path (e.g., /blog/feed)
	path_relative_candidates = [
		"/feed",
		"/rss",
		"/atom.xml",
		"/index.xml",
	]
	for p in path_relative_candidates:
		candidates.add(normalize_url(urljoin(base_url, p)))
	# Also scan the HTML for <link rel="alternate" type="application/rss+xml">
	html = await fetch_text(client, base_url)
	if html:
		soup = BeautifulSoup(html, "lxml")
		for link in soup.find_all("link", rel=lambda x: x and "alternate" in x):
			type_attr = (link.get("type") or "").lower()
			if "rss" in type_attr or "atom" in type_attr or "xml" in type_attr:
				href = link.get("href")
				if href:
					candidates.add(normalize_url(urljoin(base_url, href)))
		# Substack detection and feed hint
		host = parsed.netloc.lower()
		is_substack = host.endswith("substack.com")
		if not is_substack:
			gen = soup.find("meta", attrs={"name": "generator"})
			if gen and "substack" in (gen.get("content") or "").lower():
				is_substack = True
		if is_substack:
			candidates.add(normalize_url(urljoin(base_url, "/feed")))
	feeds: Set[str] = set()
	for href in candidates:
		resp = await client.get(href)
		if not resp:
			continue
		content_type = (resp.headers.get("content-type") or "").lower()
		body = None
		try:
			body = resp.text
		except Exception:
			body = None
		if ("xml" in content_type) or (body and ("<rss" in body or "<feed" in body)):
			feeds.add(href)
	return feeds


async def extract_feed_entries(client: HttpClient, feed_url: str, seed_url: str) -> Set[str]:
	urls: Set[str] = set()
	try:
		parsed = feedparser.parse(feed_url)
		for e in parsed.entries:
			link = e.get("link")
			if link:
				nu = normalize_url(link)
				if within_seed_scope(nu, seed_url):
					urls.add(nu)
	except Exception:
		pass
	return urls


def extract_links_from_html(html: str, base_url: str) -> Set[str]:
	soup = BeautifulSoup(html, "lxml")
	links: Set[str] = set()
	for a in soup.find_all("a", href=True):
		href = a.get("href")
		if not href:
			continue
		full = normalize_url(urljoin(base_url, href))
		links.add(full)
	return links


def looks_like_article_html(html: str) -> bool:
	# Heuristics: presence of <article>, long text, og:type=article, time tags
	soup = BeautifulSoup(html, "lxml")
	if soup.find("article"):
		return True
	if soup.find("meta", attrs={"property": "og:type", "content": "article"}):
		return True
	if soup.find("time"):
		return True
	text = soup.get_text(" ", strip=True)
	return len(text.split()) > 250


async def onpage_discovery(client: HttpClient, seed_url: str, max_pages: int) -> Set[str]:
	to_visit: List[str] = [seed_url]
	seen: Set[str] = set()
	collected: Set[str] = set()
	while to_visit and len(collected) < max_pages and len(seen) < max_pages * 3:
		url = to_visit.pop(0)
		if url in seen:
			continue
		seen.add(url)
		resp = await client.get(url)
		if not resp or not resp.text:
			continue
		links = extract_links_from_html(resp.text, url)
		# Try to detect rel=next pagination
		soup = BeautifulSoup(resp.text, "lxml")
		for link_tag in soup.find_all("link", rel=lambda x: x and "next" in x):
			h = link_tag.get("href")
			if h:
				links.add(normalize_url(urljoin(url, h)))
		for link in links:
			if not within_seed_scope(link, seed_url):
				continue
			if link in seen or link in collected:
				continue
			path = urlparse(link).path
			# Prioritize blog-like paths
			if any(h in path for h in BLOG_HINT_PATHS):
				to_visit.append(link)
				collected.add(link)
			else:
				to_visit.append(link)
				# only collect if it looks like article to reduce noise
				page = await client.get(link)
				if page and page.text and looks_like_article_html(page.text):
					collected.add(link)
			if len(collected) >= max_pages:
				break
	return collected


# -----------------------------
# Extraction: title + markdown content
# -----------------------------

def guess_content_type(url: str, html: str, title: str) -> str:
	u = url.lower()
	t = (title or "").lower()
	h = (html or "").lower()
	if "linkedin.com" in u:
		return "linkedin_post"
	if "reddit.com" in u:
		return "reddit_comment"
	if "podcast" in u or "podcast" in t or ("<audio" in h):
		return "podcast_transcript"
	if "transcript" in u or "transcript" in t:
		return "call_transcript"
	if "/book" in u or "chapter" in t:
		return "book"
	return "blog"


def extract_with_trafilatura(url: str, html: Optional[str]) -> Optional[Tuple[str, str]]:
	try:
		if html is None:
			return None
		# Trafilatura can do markdown directly
		md_text = trafilatura.extract(html, output_format="markdown", include_comments=False, include_tables=True, url=url)
		if md_text:
			# Title via metadata
			meta = trafilatura.metadata.extract_metadata(html, url=url)
			title = meta.title if meta and getattr(meta, "title", None) else None
			return title, md_text
	except Exception:
		return None
	return None


def extract_with_readability(url: str, html: Optional[str]) -> Optional[Tuple[str, str]]:
	try:
		if html is None:
			return None
		doc = Document(html)
		content_html = doc.summary(html_partial=True)
		title = doc.short_title()
		markdown = md(content_html or "", heading_style="ATX")
		if markdown and markdown.strip():
			return title, markdown
	except Exception:
		return None
	return None


def extract_substack_fallback(html: str) -> Optional[Tuple[str, str]]:
	soup = BeautifulSoup(html or "", "lxml")
	# paywall indicator
	if soup.find(string=lambda s: s and isinstance(s, str) and "paid subscribers" in s.lower()):
		return None
	# fix lazy images
	for img in soup.find_all("img"):
		if img.get("src"):
			continue
		ds = img.get("data-src") or img.get("data-image-src") or img.get("data-asset-url")
		if ds:
			img["src"] = ds
	# main content node candidates
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


async def fetch_and_extract(client: HttpClient, url: str) -> Optional[Dict[str, Any]]:
	resp = await client.get(url)
	if not resp or not resp.text:
		return None
	html = resp.text
	# Try trafilatura first
	res = extract_with_trafilatura(url, html)
	if not res:
		res = extract_with_readability(url, html)
	# Substack-specific fallback
	if not res:
		if "substack.com" in url or ("name=\"generator\"" in html and "Substack" in html):
			res = extract_substack_fallback(html)
	if not res:
		return None
	title, markdown = res
	if not markdown or len(markdown.strip()) < 80:
		return None
	ctype = guess_content_type(url, html, title or "")
	return {
		"title": title or BeautifulSoup(html, "lxml").title.string if BeautifulSoup(html, "lxml").title else url,
		"content": markdown.strip(),
		"content_type": ctype,
		"source_url": url,
	}


# -----------------------------
# Main pipeline
# -----------------------------

async def gather_discovery_urls(client: HttpClient, seed_url: str, max_pages: int) -> Set[str]:
	all_urls: Set[str] = set()
	# Sitemaps
	sitemaps = await discover_sitemaps(client, seed_url)
	if sitemaps:
		from_sitemaps = await expand_sitemaps(client, sitemaps, seed_url)
		all_urls.update(from_sitemaps)
	# Feeds
	feeds = await discover_feeds(client, seed_url)
	for f in feeds:
		all_urls.update(await extract_feed_entries(client, f, seed_url))
	# On-page
	onpage = await onpage_discovery(client, seed_url, max_pages=max_pages)
	all_urls.update(onpage)
	# If very low coverage, broaden crawl depth from root domain ONLY when seed has no subpath
	parsed_seed = urlparse(seed_url)
	if len(all_urls) < max_pages // 5 and (parsed_seed.path == "" or parsed_seed.path == "/"):
		root = f"{parsed_seed.scheme}://{parsed_seed.netloc}"
		all_urls.update(await onpage_discovery(client, root, max_pages=max_pages))
	# Filter to HTML-like paths
	filtered: Set[str] = set()
	for u in all_urls:
		path = urlparse(u).path.lower()
		if any(ext for ext in [".jpg", ".png", ".gif", ".svg", ".pdf", ".zip", ".mp3", ".mp4", ".xml", ".gz"] if path.endswith(ext)):
			continue
		filtered.add(u)
	return set(list(filtered))


def _format_eta(seconds: float) -> str:
	if seconds <= 0 or seconds == float("inf"):
		return "--:--"
	m = int(seconds) // 60
	s = int(seconds) % 60
	return f"{m:02d}:{s:02d}"


async def scrape(seed: str, max_pages: int = 200, concurrency: int = 10, show_progress: bool = True) -> Dict[str, Any]:
	seed_url = seed if seed.startswith("http") else f"https://{seed}"
	seed_url = normalize_url(seed_url)
	client = HttpClient(max_connections=concurrency)
	try:
		candidate_urls = await gather_discovery_urls(client, seed_url, max_pages=max_pages)
		# Cap
		candidate_list = list(candidate_urls)[: max_pages]
		results: List[Dict[str, Any]] = []
		progress = {"done": 0}
		start_ts = time.monotonic()
		sem = asyncio.Semaphore(concurrency)

		async def worker(u: str):
			async with sem:
				item = await fetch_and_extract(client, u)
				if item:
					results.append(item)
				progress["done"] += 1

		async def progress_bar():
			# Only draw if desired and output is a TTY
			if not show_progress:
				return
			while progress["done"] < len(candidate_list):
				elapsed = time.monotonic() - start_ts
				done = progress["done"]
				total = max(1, len(candidate_list))
				rate = done / elapsed if elapsed > 0 else 0.0
				remaining = (total - done) / rate if rate > 0 else float("inf")
				bar_len = 24
				filled = int(bar_len * done / total)
				bar = "#" * filled + "-" * (bar_len - filled)
				msg = f"\r[ {bar} ] {done}/{total} ETA {_format_eta(remaining)}"
				sys.stdout.write(msg)
				sys.stdout.flush()
				await asyncio.sleep(1.0)
			# Final line
			elapsed = time.monotonic() - start_ts
			msg = f"\r[ {'#'*24} ] {progress['done']}/{len(candidate_list)} Done in {_format_eta(elapsed)}\n"
			sys.stdout.write(msg)
			sys.stdout.flush()

		# Kick off tasks
		bar_task = asyncio.create_task(progress_bar()) if show_progress and sys.stderr.isatty() or sys.stdout.isatty() else asyncio.create_task(asyncio.sleep(0))
		await asyncio.gather(*(worker(u) for u in candidate_list))
		await bar_task

		# Deduplicate by source_url
		seen: Set[str] = set()
		deduped: List[Dict[str, Any]] = []
		for it in results:
			su = it["source_url"]
			if su in seen:
				continue
			seen.add(su)
			deduped.append(it)
		return {"site": seed_url, "items": deduped}
	finally:
		await client.close()


def main():
	parser = argparse.ArgumentParser(description="Aline Knowledgebase Scraper")
	parser.add_argument("--url", required=True, help="Seed URL or domain (e.g., https://quill.co/blog or interviewing.io)")
	parser.add_argument("--max-pages", type=int, default=200, help="Max pages to process")
	parser.add_argument("--concurrency", type=int, default=10, help="Concurrent requests")
	parser.add_argument("--out", default="", help="Write JSON output to file; default stdout")
	parser.add_argument("--no-progress", action="store_true", help="Disable console progress bar")
	args = parser.parse_args()

	data = asyncio.run(scrape(args.url, max_pages=args.max_pages, concurrency=args.concurrency, show_progress=not args.no_progress))
	output = json.dumps(data, ensure_ascii=False, indent=2)
	if args.out:
		with open(args.out, "w", encoding="utf-8") as f:
			f.write(output)
	else:
		print(output)


if __name__ == "__main__":
	main()

