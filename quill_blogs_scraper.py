import json
import re
import time
from typing import List, Dict, Any
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup
from markdownify import markdownify as md


BLOG_ROOT = "https://quill.co/blog"
API_ROOT = "https://quill.co/api/v1"


def get_headers():
    """Get headers for API requests."""
    return {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "en-US,en;q=0.9",
        "Referer": BLOG_ROOT,
        "Origin": "https://quill.co",
        "Connection": "keep-alive",
        "Sec-Fetch-Dest": "empty",
        "Sec-Fetch-Mode": "cors",
        "Sec-Fetch-Site": "same-origin",
    }


def fetch_blog_posts() -> List[Dict[str, Any]]:
    """Fetch blog posts from the API."""
    posts = []
    
    try:
        # First try the blog API endpoint
        response = requests.get(f"{API_ROOT}/blog/posts", headers=get_headers())
        if response.ok:
            data = response.json()
            if isinstance(data, list):
                posts.extend(data)
            elif isinstance(data, dict) and "items" in data:
                posts.extend(data["items"])
    except Exception as e:
        print(f"Error fetching from blog API: {e}")
    
    # If API fails, try scraping the HTML
    if not posts:
        try:
            response = requests.get(BLOG_ROOT, headers=get_headers())
            soup = BeautifulSoup(response.text, 'lxml')
            posts = extract_blog_urls(soup, BLOG_ROOT)
        except Exception as e:
            print(f"Error scraping blog HTML: {e}")
    
    return posts


def extract_blog_urls(soup: BeautifulSoup, base_url: str) -> List[Dict[str, Any]]:
    """Extract blog posts from the page."""
    posts = []
    
    # Find all blog post titles (h1 tags)
    h1_tags = soup.find_all('h1')
    for h1 in h1_tags:
        # Skip the navigation "Blog" title
        if h1.text.strip() in ["Blog", "Product", "Docs", "Jobs"]:
            continue
            
        post = {"title": h1.text.strip()}
        
        # Find the parent container of this post
        container = h1.find_parent()
        while container and container.name != 'body':
            # Look for a larger container that might have more content
            if container.find_all(['h4', 'p']):
                break
            container = container.parent
        
        # Extract date
        date_pattern = r"(?:January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{1,2},?\s+\d{4}"
        # Look in siblings first
        siblings = container.find_next_siblings()
        for sibling in siblings:
            match = re.search(date_pattern, sibling.get_text())
            if match:
                post["date"] = match.group(0)
                break
        
        # If no date found, look in the entire container
        if "date" not in post:
            match = re.search(date_pattern, container.get_text())
            if match:
                post["date"] = match.group(0)
            
        # Extract preview text
        preview = None
        # First try to find a dedicated preview/excerpt
        for selector in [
            {'class_': re.compile('excerpt|preview|summary|description', re.I)},
            {'id': re.compile('excerpt|preview|summary|description', re.I)},
        ]:
            preview_elem = container.find('div', **selector)
            if preview_elem:
                preview = preview_elem.get_text(strip=True)
                break
        
        # If no dedicated preview found, look for h4 tags that look like previews
        if not preview:
            for h4 in container.find_all('h4'):
                text = h4.get_text(strip=True)
                if text and len(text) > 50 and not any(month in text for month in ['January', 'February', 'March', 'April', 'May', 'June', 'July', 'August', 'September', 'October', 'November', 'December']):
                    preview = text
                    break
        
        # If still no preview, look for paragraphs
        if not preview:
            for p in container.find_all('p'):
                text = p.get_text(strip=True)
                if text and len(text) > 50:
                    preview = text
                    break
        
        if preview:
            post["preview"] = preview
            
        # Generate URL from title
        if post["title"]:
            # Convert title to URL slug
            slug = post["title"].lower()
            # Remove special characters and replace spaces with hyphens
            slug = re.sub(r'[^a-z0-9\s-]', '', slug)
            slug = re.sub(r'[-\s]+', '-', slug).strip('-')
            post["url"] = urljoin(base_url, f"/blog/{slug}")
            
        posts.append(post)
    
    return posts


def fetch_post_content(url: str) -> Dict[str, Any]:
    """Fetch full blog post content."""
    metadata = {}
    
    try:
        # First try the API endpoint
        slug = url.split("/")[-1]
        response = requests.get(f"{API_ROOT}/blog/posts/{slug}", headers=get_headers())
        if response.ok:
            data = response.json()
            if isinstance(data, dict):
                # Extract content
                content = data.get("content") or data.get("body")
                if content:
                    metadata["content"] = md(content)
                
                # Extract metadata
                metadata["author"] = data.get("author")
                metadata["reading_time"] = data.get("readingTime") or data.get("reading_time")
                metadata["published_at"] = data.get("publishedAt") or data.get("published_at")
                return metadata
    except Exception as e:
        print(f"Error fetching from post API: {e}")
    
    # If API fails, try scraping the HTML
    try:
        # First try to get the post data from the Next.js data endpoint
        next_url = f"https://quill.co/_next/data/latest/blog/{slug}.json"
        response = requests.get(next_url, headers=get_headers())
        if response.ok:
            data = response.json()
            if isinstance(data, dict) and "pageProps" in data:
                post = data["pageProps"].get("post")
                if post:
                    # Extract content
                    content = post.get("content") or post.get("body")
                    if content:
                        metadata["content"] = md(content)
                    
                    # Extract metadata
                    metadata["author"] = post.get("author")
                    metadata["reading_time"] = post.get("readingTime") or post.get("reading_time")
                    metadata["published_at"] = post.get("publishedAt") or post.get("published_at")
                    return metadata
    except Exception as e:
        print(f"Error fetching from Next.js data endpoint: {e}")
    
    # If both API and Next.js data fail, try scraping the HTML
    try:
        response = requests.get(url, headers=get_headers())
        soup = BeautifulSoup(response.text, 'lxml')
        
        # Try to extract from Next.js state
        try:
            next_data = soup.find("script", id="__NEXT_DATA__")
            if next_data and next_data.string:
                data = json.loads(next_data.string)
                props = data.get("props", {}).get("pageProps", {})
                post = props.get("post") or props.get("article") or props
                
                # Extract content from Next.js data
                if post:
                    # Get author info
                    author = post.get("author")
                    if author:
                        if isinstance(author, dict):
                            metadata["author"] = author.get("name")
                        elif isinstance(author, str):
                            metadata["author"] = author
                    
                    # Get reading time
                    reading_time = post.get("readingTime") or post.get("reading_time")
                    if reading_time:
                        metadata["reading_time"] = reading_time
                    
                    # Get content
                    post_content = post.get("content") or post.get("body")
                    if post_content:
                        metadata["content"] = md(post_content)
                        return metadata
        except Exception:
            pass
        
        # If Next.js data extraction failed, try HTML parsing
        article = soup.find('article')
        if not article:
            # Try other common content containers
            for selector in [
                {'class_': re.compile('content|post|article', re.I)},
                {'id': re.compile('content|post|article', re.I)},
                {'role': 'main'},
            ]:
                article = soup.find('div', **selector)
                if article:
                    break
        
        if article:
            # Extract author info if available
            author_elem = article.find(class_=re.compile('author|byline', re.I))
            if author_elem:
                metadata['author'] = author_elem.get_text(strip=True)
            
            # Extract reading time if available
            time_elem = article.find(string=re.compile(r'\d+\s*minute read', re.I))
            if time_elem:
                metadata['reading_time'] = time_elem.strip()
            
            # First remove unwanted elements
            for unwanted in article.find_all(['script', 'style', 'nav', 'header', 'footer', 'aside']):
                unwanted.decompose()
            
            # Convert to markdown
            metadata["content"] = md(str(article))
    except Exception as e:
        print(f"Error scraping post HTML: {e}")
    
    return metadata


def scrape_blog():
    """Main scraping function."""
    # Create a session for connection reuse
    session = requests.Session()
    session.headers.update(get_headers())
    
    try:
        # Fetch blog posts
        print("\nFetching blog posts...")
        posts = fetch_blog_posts()
        
        # Now fetch each blog post's full content
        for post in posts:
            if "url" in post:
                try:
                    print(f"\nFetching content from {post['url']}...")
                    metadata = fetch_post_content(post["url"])
                    post.update(metadata)
                    
                    # Add a small delay between requests
                    time.sleep(1)
                    
                except Exception as e:
                    print(f"Error fetching {post['url']}: {e}")
        
        # Save to JSON
        data = {
            "site": BLOG_ROOT,
            "items": posts
        }
        
        with open('quill_blogs.json', 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        
        print(f"\nExtracted {len(posts)} blog posts:")
        for post in posts:
            print(f"\nTitle: {post['title']}")
            if "date" in post:
                print(f"Date: {post['date']}")
            if "author" in post:
                print(f"Author: {post['author']}")
            if "reading_time" in post:
                print(f"Reading time: {post['reading_time']}")
            if "url" in post:
                print(f"URL: {post['url']}")
            if "preview" in post:
                print(f"Preview: {post['preview'][:200]}...")
            if "content" in post:
                print(f"Content length: {len(post['content'])} characters")
                
    finally:
        session.close()


if __name__ == "__main__":
    scrape_blog()