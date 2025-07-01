# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

This is a web scraper for siptequila.com that extracts product information (name, URL, price, images) from their tequila and mezcal collection. The scraper handles age verification, pagination, and downloads product images.

## Commands

### Running the Scraper
```bash
python scraper.py
```

### Installing Dependencies
```bash
pip install -r requirements.txt
playwright install chromium
```

### Git Workflow
After each scrape run:
```bash
git add scraper.py tequila_products.json
git commit -m "Update: [number] products scraped on [date]"
git tag -a v[YYYYMMDD_HHMMSS] -m "Scrape run: [number] products"
```

## Architecture

### Core Components

- **TequilaScraper class**: Main scraper logic
  - `handle_age_verification()`: Bypasses age verification popup
  - `scrape_page()`: Extracts products from a single page
  - `download_image()`: Downloads and saves product images
  - `scrape_all_pages()`: Orchestrates multi-page scraping
  - `save_to_json()`: Saves results to tequila_products.json

### Data Flow

1. Initialize Playwright browser with stealth settings
2. Navigate to collection page and handle age verification
3. Extract product data using DOM selectors
4. Download product images to `tequila_images/` directory
5. Save all data to `tequila_products.json`
6. Track progress with git commits and tags

### Key Technical Details

- Uses Playwright for JavaScript-heavy site rendering
- Implements age verification bypass with multiple selectors
- Handles lazy-loaded images through scrolling
- Deduplicates products across pages using URL tracking
- Downloads images asynchronously with aiohttp
- Respects rate limits with 2-second delays between pages

### Site Structure

The target site (siptequila.com) uses:
- Age verification popup on first visit
- Paginated product grid with `?page=N` URLs
- Shopify-based product structure with `.grid__item` containers
- Lazy-loaded images with `data-src` attributes
- Product links in format `/products/[slug]`

### Current Limitations

- Pagination detection may not capture all pages (site might have more than 24 products)
- Price extraction often returns "Price not found" (prices may be loaded dynamically)
- Age verification selectors may need updates if site changes

## File Structure

- `scraper.py`: Main scraper script
- `tequila_products.json`: Output data file (versioned in git)
- `tequila_images/`: Downloaded product images (not versioned)
- `requirements.txt`: Python dependencies
- `.gitignore`: Excludes images and Python cache files