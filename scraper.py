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
        try:
            await page.wait_for_timeout(2000)
            
            age_selectors = [
                'button[type="submit"]',
                'button:text("Yes")',
                'button:text("I am 21")',
                'button:text("Enter")',
                '.age-gate__button',
                '.age-verification button'
            ]
            
            for selector in age_selectors:
                try:
                    button = await page.wait_for_selector(selector, timeout=1000)
                    if button:
                        print(f"Found age verification button: {selector}")
                        await button.click()
                        await page.wait_for_timeout(2000)
                        return True
                except:
                    continue
                    
            return False
        except Exception as e:
            print(f"Error handling age verification: {e}")
            return False
            
    async def scrape_page(self, page, url, handle_age_gate=False):
        print(f"Loading: {url}")
        await page.goto(url, wait_until='domcontentloaded')
        
        if handle_age_gate:
            await self.handle_age_verification(page)
        
        await page.wait_for_timeout(3000)
        
        # Scroll to load lazy-loaded content
        await page.evaluate('''
            async () => {
                const delay = ms => new Promise(resolve => setTimeout(resolve, ms));
                for (let i = 0; i < 5; i++) {
                    window.scrollTo(0, document.body.scrollHeight);
                    await delay(1000);
                }
            }
        ''')
        
        # Extract products using the same approach as the original working scraper
        products = await page.evaluate('''() => {
            const products = [];
            const items = document.querySelectorAll('.grid__item');
            
            items.forEach(item => {
                try {
                    const link = item.querySelector('a.product-item__title');
                    const priceElement = item.querySelector('.product-item__price-list .price');
                    const imageElement = item.querySelector('.product-item__primary-image img');
                    
                    let price = null;
                    if (priceElement) {
                        const priceText = priceElement.textContent.trim();
                        const priceMatch = priceText.match(/\\$[\\d,]+\\.?\\d*/);
                        price = priceMatch ? priceMatch[0] : priceText;
                    }
                    
                    let imageUrl = null;
                    if (imageElement) {
                        imageUrl = imageElement.getAttribute('data-src') || imageElement.getAttribute('src');
                        if (imageUrl && imageUrl.startsWith('//')) {
                            imageUrl = 'https:' + imageUrl;
                        } else if (imageUrl && !imageUrl.startsWith('http')) {
                            imageUrl = 'https://siptequila.com' + imageUrl;
                        }
                    }
                    
                    if (link) {
                        products.push({
                            name: link.textContent.trim(),
                            url: 'https://siptequila.com' + link.getAttribute('href'),
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
            
            await context.add_init_script("""
                Object.defineProperty(navigator, 'webdriver', {
                    get: () => undefined
                });
            """)
            
            page = await context.new_page()
            
            page_num = 1
            consecutive_empty = 0
            max_pages = 40
            
            async with aiohttp.ClientSession() as session:
                while page_num <= max_pages and consecutive_empty < 3:
                    url = f"{self.base_url}?page={page_num}"
                    
                    try:
                        products = await self.scrape_page(page, url, handle_age_gate=(page_num == 1))
                        
                        if not products:
                            consecutive_empty += 1
                            print(f"Page {page_num}: No products found")
                        else:
                            consecutive_empty = 0
                            new_products = 0
                            
                            for product in products:
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
                                    print(f"  + {product['name']} - {product['price']}")
                            
                            print(f"Page {page_num}: Found {len(products)} products ({new_products} new)")
                            print(f"Total unique products: {len(self.products)}")
                        
                        page_num += 1
                        await asyncio.sleep(2)
                        
                    except Exception as e:
                        print(f"Error on page {page_num}: {e}")
                        consecutive_empty += 1
                        page_num += 1
                        
            await context.close()
            await browser.close()
            
    def save_to_json(self):
        # Always save to the same file
        with open('tequila_products.json', 'w', encoding='utf-8') as f:
            json.dump(self.products, f, indent=2, ensure_ascii=False)
        
        print(f"\n=== COMPLETE ===")
        print(f"Saved {len(self.products)} unique products to tequila_products.json")
        print(f"Timestamp: {datetime.now().isoformat()}")
        
        # Return stats for git commit message
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
    print(f"\nRun 'git add tequila_products.json && git commit -m \"Update: {stats['total_products']} products - {stats['timestamp']}\"' to save this version")