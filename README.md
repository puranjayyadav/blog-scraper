# Blog Scraper

A Python-based web scraper for extracting blog content from various sources.

## Features

- Extracts blog posts and content
- Handles client-side rendered pages
- Supports multiple scraping strategies:
  - Direct HTML parsing
  - API endpoint access
  - JavaScript rendering
  - Next.js data extraction

## Installation

1. Clone the repository:
```bash
git clone https://github.com/yourusername/blog-scraper.git
cd blog-scraper
```

2. Install dependencies:
```bash
pip install -r requirements.txt
```

## Usage

Run the scraper:
```bash
python scraper.py
```

For specific blog scraping:
```bash
python quill_blogs_scraper.py
```

## Project Structure

- `scraper.py` - Core scraping utilities and functions
- `quill_blogs_scraper.py` - Specific scraper for Quill blog
- `requirements.txt` - Python dependencies
- `*.json` - Scraped data output files

## Dependencies

- beautifulsoup4 - HTML parsing
- requests - HTTP requests
- markdownify - HTML to Markdown conversion
- undetected-chromedriver - Browser automation
- requests-html - JavaScript rendering

## Contributing

1. Fork the repository
2. Create your feature branch (`git checkout -b feature/amazing-feature`)
3. Commit your changes (`git commit -m 'Add some amazing feature'`)
4. Push to the branch (`git push origin feature/amazing-feature`)
5. Open a Pull Request

## License

This project is licensed under the MIT License - see the LICENSE file for details.