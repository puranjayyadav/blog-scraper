# Blog Scraper

A Python-based web scraper for extracting blog content from various sources. Features a web interface for easy scraping and content downloading.

## Features

- Extracts blog posts and content
- Handles client-side rendered pages
- Web interface for easy scraping
- Downloads content in JSON format
- Supports multiple scraping strategies:
  - Direct HTML parsing
  - API endpoint access
  - JavaScript rendering

## Current Limitations

- Next.js websites: We are actively working on improving support for Next.js-based websites. Some content from Next.js sites might not be fully scraped due to their client-side rendering nature.

## Installation

1. Clone the repository:
```bash
git clone https://github.com/puranjayyadav/blog-scraper.git
cd blog-scraper
```

2. Install dependencies:
```bash
pip install -r requirements.txt
```

## Usage

Simply run:
```bash
python app.py
```

This will:
1. Start a web server at http://localhost:5000
2. Open your browser and navigate to http://localhost:5000
3. Enter a URL to scrape
4. Set the maximum number of pages to scrape
5. Click "Scrape" to start
6. Download the results as JSON

## Project Structure

- `app.py` - Main web application and entry point
- `scraper.py` - Core scraping utilities and functions
- `requirements.txt` - Python dependencies
- `*.json` - Scraped data output files

## Dependencies

- Flask - Web framework
- beautifulsoup4 - HTML parsing
- requests - HTTP requests
- markdownify - HTML to Markdown conversion
- undetected-chromedriver - Browser automation
- requests-html - JavaScript rendering

## API Endpoints

The application provides the following endpoints:

- `GET /` - Web interface for scraping
- `POST /scrape` - Form-based scraping endpoint
- `POST /api/scrape` - JSON API endpoint for scraping
- `POST /download` - Download scraped data as JSON

## Contributing

1. Fork the repository
2. Create your feature branch (`git checkout -b feature/amazing-feature`)
3. Commit your changes (`git commit -m 'Add some amazing feature'`)
4. Push to the branch (`git push origin feature/amazing-feature`)
5. Open a Pull Request

## License

This project is licensed under the MIT License - see the LICENSE file for details.