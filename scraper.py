import asyncio
import json
import os
from pathlib import Path
from urllib.parse import urljoin, urlparse
from playwright.async_api import async_playwright
import aiohttp
import aiofiles
from datetime import datetime

class TequilaScraper:
    def __init__(self):
        self.base_url = "https://siptequila.com/collections/all-tequila-mezcal"
        self.products = []
        self.images_dir = Path("tequila_images")
        self.images_dir.mkdir(exist_ok=True)
        self.seen_products = set()
        
    async def download_image(self, session, image_url, product_name):
        try:
            clean_name = "".join(c for c in product_name if c.isalnum() or c in (' ', '-', '_')).rstrip()
            clean_name = clean_name.replace(' ', '_')[:100]
            
            parsed_url = urlparse(image_url)
            ext = os.path.splitext(parsed_url.path)[1] or '.jpg'
            filename = f"{clean_name}{ext}"
            filepath = self.images_dir / filename
            
            if filepath.exists():
                return filename
            
            async with session.get(image_url) as response:
                if response.status == 200:
                    async with aiofiles.open(filepath, 'wb') as f:
                        await f.write(await response.read())
                    return filename
        except Exception as e:
            print(f"Error downloading image {image_url}: {e}")
            return None
    
    async def handle_age_verification(self, page):
        """Handle age verification if present"""
        try:
            # Wait a bit to see if age verification appears
            await page.wait_for_timeout(2000)
            
            # Try common age verification button selectors
            age_selectors = [
                'button:has-text("Yes")',
                'button:has-text("I am 21")',
                'button:has-text("Enter")',
                'button:has-text("I\'m 21")',
                'button:has-text("I am over 21")',
                'button:has-text("YES")',
                'a:has-text("Yes")',
                'a:has-text("Enter")',
                '.age-gate__button',
                '.age-verification button',
                '[data-age-gate-submit]',
                'button[type="submit"]'
            ]
            
            for selector in age_selectors:
                try:
                    button = await page.wait_for_selector(selector, timeout=1000)
                    if button:
                        print(f"Found age verification button with selector: {selector}")
                        await button.click()
                        await page.wait_for_timeout(2000)
                        return True
                except:
                    continue
            
            return False
        except Exception as e:
            print(f"Error handling age verification: {e}")
            return False
            
    async def scrape_page(self, page, url):
        await page.goto(url, wait_until='domcontentloaded')
        
        # Handle age verification if it's the first page
        if "?page=" not in url:
            await self.handle_age_verification(page)
        
        # Wait for page to stabilize
        await page.wait_for_timeout(3000)
        
        # Scroll to load lazy-loaded images
        await page.evaluate('''
            async () => {
                await new Promise((resolve) => {
                    let totalHeight = 0;
                    const distance = 100;
                    const timer = setInterval(() => {
                        const scrollHeight = document.body.scrollHeight;
                        window.scrollBy(0, distance);
                        totalHeight += distance;
                        
                        if(totalHeight >= scrollHeight){
                            clearInterval(timer);
                            resolve();
                        }
                    }, 100);
                });
            }
        ''')
        
        # Wait after scrolling
        await page.wait_for_timeout(2000)
        
        # Extract products
        products = await page.evaluate('''() => {
            const products = [];
            
            // Try different selectors
            const selectors = [
                '.product-item',
                '.grid__item',
                '.collection__product',
                'article[data-product-id]',
                '[data-product-handle]',
                '.product-grid-item',
                '.product-card'
            ];
            
            let items = [];
            for (const selector of selectors) {
                const found = document.querySelectorAll(selector);
                if (found.length > 0) {
                    items = found;
                    console.log(`Found ${found.length} items with selector: ${selector}`);
                    break;
                }
            }
            
            // If no specific product items found, try to find any links with product info
            if (items.length === 0) {
                const links = document.querySelectorAll('a[href*="/products/"]');
                const productLinks = new Map();
                
                links.forEach(link => {
                    const href = link.getAttribute('href');
                    if (href && href.includes('/products/') && !href.includes('/collections/')) {
                        const parent = link.closest('.grid__item') || link.closest('[class*="product"]') || link.parentElement;
                        if (parent && !productLinks.has(href)) {
                            productLinks.set(href, parent);
                        }
                    }
                });
                
                items = Array.from(productLinks.values());
                console.log(`Found ${items.length} product links`);
            }
            
            items.forEach(item => {
                try {
                    // Find product name
                    const nameSelectors = [
                        '.product-item__title',
                        '.product__title',
                        '.product-card__title',
                        '.product-card__name',
                        'h3 a',
                        'h2 a',
                        'h3',
                        'h2',
                        'a[href*="/products/"]'
                    ];
                    
                    let name = null;
                    let productUrl = null;
                    
                    for (const selector of nameSelectors) {
                        const elem = item.querySelector(selector);
                        if (elem) {
                            name = elem.textContent.trim();
                            if (elem.tagName === 'A') {
                                productUrl = elem.getAttribute('href');
                            } else {
                                const link = elem.querySelector('a') || item.querySelector('a[href*="/products/"]');
                                if (link) productUrl = link.getAttribute('href');
                            }
                            if (name && name.length > 0) break;
                        }
                    }
                    
                    // Find price
                    const priceSelectors = [
                        '.price',
                        '.product-item__price',
                        '.product__price',
                        '.product-card__price',
                        '.money',
                        '[data-price]',
                        'span[class*="price"]'
                    ];
                    
                    let price = null;
                    for (const selector of priceSelectors) {
                        const elem = item.querySelector(selector);
                        if (elem) {
                            const priceText = elem.textContent.trim();
                            const priceMatch = priceText.match(/\\$[\\d,]+\\.?\\d*/);
                            if (priceMatch) {
                                price = priceMatch[0];
                                break;
                            }
                        }
                    }
                    
                    // Find image
                    const imgSelectors = [
                        'img[data-src]',
                        'img[src*="cdn.shopify"]',
                        'img.product__image',
                        'img.product-card__image',
                        'img',
                        '.responsive-image__image'
                    ];
                    
                    let imageUrl = null;
                    for (const selector of imgSelectors) {
                        const img = item.querySelector(selector);
                        if (img) {
                            imageUrl = img.getAttribute('data-src') || 
                                      img.getAttribute('src') ||
                                      img.getAttribute('data-srcset');
                            if (imageUrl) {
                                // Clean up srcset if needed
                                if (imageUrl.includes(' ')) {
                                    imageUrl = imageUrl.split(' ')[0];
                                }
                                // Skip placeholder images
                                if (!imageUrl.includes('placeholder') && !imageUrl.includes('no-image')) {
                                    break;
                                }
                            }
                        }
                    }
                    
                    if (name && productUrl) {
                        // Ensure full URLs
                        if (productUrl && !productUrl.startsWith('http')) {
                            productUrl = 'https://siptequila.com' + productUrl;
                        }
                        if (imageUrl && imageUrl.startsWith('//')) {
                            imageUrl = 'https:' + imageUrl;
                        } else if (imageUrl && !imageUrl.startsWith('http')) {
                            imageUrl = 'https://siptequila.com' + imageUrl;
                        }
                        
                        products.push({
                            name: name,
                            url: productUrl,
                            price: price || 'Price not found',
                            image_url: imageUrl
                        });
                    }
                } catch (e) {
                    console.error('Error parsing product:', e);
                }
            });
            
            return products;
        }''')
        
        return products
        
    async def check_next_page(self, page):
        """Check if there's a next page"""
        try:
            next_link = await page.query_selector('a:has-text("Next")')
            if next_link:
                is_disabled = await next_link.evaluate('el => el.classList.contains("disabled") || el.hasAttribute("disabled")')
                return not is_disabled
            return False
        except:
            return False
            
    async def scrape_all_pages(self):
        async with async_playwright() as p:
            browser = await p.chromium.launch(
                headless=True,
                args=['--no-sandbox', '--disable-setuid-sandbox', '--disable-blink-features=AutomationControlled']
            )
            context = await browser.new_context(
                user_agent='Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                viewport={'width': 1920, 'height': 1080}
            )
            
            # Add stealth scripts
            await context.add_init_script("""
                Object.defineProperty(navigator, 'webdriver', {
                    get: () => undefined
                });
            """)
            
            page = await context.new_page()
            
            page_num = 1
            consecutive_empty_pages = 0
            
            async with aiohttp.ClientSession() as session:
                while page_num <= 50 and consecutive_empty_pages < 3:  # Stop after 3 consecutive empty pages
                    current_url = f"{self.base_url}?page={page_num}"
                    print(f"\nScraping page {page_num}: {current_url}")
                    
                    try:
                        products = await self.scrape_page(page, current_url)
                        
                        if not products:
                            consecutive_empty_pages += 1
                            print(f"No products found on page {page_num}")
                            if consecutive_empty_pages >= 3:
                                print("No products found on 3 consecutive pages, stopping.")
                                break
                        else:
                            consecutive_empty_pages = 0
                            new_products = 0
                            
                            for product in products:
                                # Check if we already have this product
                                if product['url'] not in self.seen_products:
                                    self.seen_products.add(product['url'])
                                    
                                    if product['image_url']:
                                        image_filename = await self.download_image(
                                            session, 
                                            product['image_url'], 
                                            product['name']
                                        )
                                        product['image_filename'] = image_filename
                                    else:
                                        product['image_filename'] = None
                                        
                                    self.products.append(product)
                                    new_products += 1
                                    print(f"Scraped: {product['name']} - {product['price']}")
                            
                            print(f"Found {len(products)} products on page {page_num} ({new_products} new)")
                            print(f"Total unique products: {len(self.products)}")
                        
                        # Check if there's a next page
                        has_next = await self.check_next_page(page)
                        if not has_next and products:
                            print("No next page found, stopping.")
                            break
                            
                        page_num += 1
                        await asyncio.sleep(2)  # Be respectful
                        
                    except Exception as e:
                        print(f"Error scraping page {current_url}: {e}")
                        consecutive_empty_pages += 1
                        if consecutive_empty_pages >= 3:
                            break
                        page_num += 1
                        
            await context.close()
            await browser.close()
            
    def save_to_json(self):
        with open('tequila_products.json', 'w', encoding='utf-8') as f:
            json.dump(self.products, f, indent=2, ensure_ascii=False)
        print(f"\nSaved {len(self.products)} unique products to tequila_products.json")
        
        return {
            'total_products': len(self.products),
            'timestamp': datetime.now().isoformat()
        }
        
async def main():
    scraper = TequilaScraper()
    await scraper.scrape_all_pages()
    stats = scraper.save_to_json()
    return stats
    
if __name__ == "__main__":
    stats = asyncio.run(main())
    print(f"\nSuggested git commands:")
    print(f"git add scraper.py tequila_products.json")
    print(f"git commit -m \"Update: {stats['total_products']} products scraped on {stats['timestamp'][:10]}\"")
    print(f"git tag -a v{datetime.now().strftime('%Y%m%d_%H%M%S')} -m \"Scrape run: {stats['total_products']} products\"")