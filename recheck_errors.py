"""
Script to recheck error IDs multiple times to detect bot detection
Runs each failed ID multiple times and tracks success/fail patterns
"""

import aiohttp
import asyncio
import json
import time
import re
import logging
from datetime import datetime
from bs4 import BeautifulSoup
from pathlib import Path
from collections import defaultdict

url = "https://api.tiki.vn/product-detail/api/v1/products/{}"

headers = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) "
                  "Chrome/120.0.0.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Referer": "https://tiki.vn/"
}

def clean_description(html_description: str) -> str:
    """Remove HTML tags and clean up description text"""
    if not html_description:
        return ""
    
    soup = BeautifulSoup(html_description, 'html.parser')
    text = soup.get_text(separator=' ', strip=True)
    text = re.sub(r'\s+', ' ', text)
    
    return text.strip()

def extract_product_fields(product_data: dict) -> dict:
    """Extract only required fields from product data"""
    if "error" in product_data:
        return product_data
    
    images_urls = []
    if "images" in product_data and isinstance(product_data["images"], list):
        images_urls = [img.get("base_url", "") for img in product_data["images"] if img.get("base_url")]
    
    description = clean_description(product_data.get("description", ""))
    
    return {
        "id": product_data.get("id"),
        "name": product_data.get("name", ""),
        "url_key": product_data.get("url_key", ""),
        "price": product_data.get("price"),
        "description": description,
        "images": images_urls
    }

async def test_product_once(session: aiohttp.ClientSession, product_id: int, semaphore: asyncio.Semaphore) -> dict:
    """Test a single product once"""
    async with semaphore:
        try:
            async with session.get(url.format(product_id), headers=headers, timeout=aiohttp.ClientTimeout(total=10)) as response:
                if response.status == 200:
                    data = await response.json()
                    return {"success": True, "status": 200, "data": data}
                else:
                    text = await response.text()
                    return {"success": False, "status": response.status, "text": text[:200]}
        except Exception as e:
            return {"success": False, "status": "error", "error": str(e)}

async def test_product_multiple_times(session: aiohttp.ClientSession, product_id: int, 
                                     num_attempts: int, semaphore: asyncio.Semaphore) -> dict:
    """Test a product multiple times and track results"""
    results = []
    
    for attempt in range(num_attempts):
        result = await test_product_once(session, product_id, semaphore)
        results.append(result)
        
        # Small delay between attempts
        if attempt < num_attempts - 1:
            await asyncio.sleep(0.5)
    
    # Analyze results
    successes = sum(1 for r in results if r.get("success"))
    failures = len(results) - successes
    
    # Get successful data if any
    successful_data = None
    for r in results:
        if r.get("success") and r.get("data"):
            successful_data = extract_product_fields(r["data"])
            break
    
    return {
        "product_id": product_id,
        "total_attempts": num_attempts,
        "successes": successes,
        "failures": failures,
        "success_rate": successes / num_attempts * 100,
        "results": results,
        "data": successful_data
    }

def load_error_ids(error_file: Path) -> list:
    """Load product IDs from errors.jsonl"""
    product_ids = []
    
    if not error_file.exists():
        print(f"ERROR: Error file {error_file} not found!")
        return product_ids
    
    with open(error_file, "r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                try:
                    error_data = json.loads(line)
                    if "product_id" in error_data:
                        product_ids.append(error_data["product_id"])
                except json.JSONDecodeError:
                    continue
    
    return product_ids

async def main():
    # Configuration
    NUM_ATTEMPTS = 10  # Test mỗi ID 5 lần
    max_concurrent = 10  # Không quá cao để tránh bị detect
    
    # Setup logging
    output_dir = Path("output/recheck_analysis")
    output_dir.mkdir(exist_ok=True)
    
    log_file = output_dir / f"recheck_log_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
    
    # Setup double logging (console + file)
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S',
        handlers=[
            logging.FileHandler(log_file, encoding='utf-8'),
            logging.StreamHandler()
        ]
    )
    
    logger = logging.getLogger(__name__)
    
    logger.info("="*70)
    logger.info("RECHECK ERROR IDs - DETECT BOT BLOCKING")
    logger.info("="*70)
    logger.info(f"Log file: {log_file}")
    
    # Load error IDs
    error_file = Path("output/errors.jsonl")
    product_ids = load_error_ids(error_file)
    
    if not product_ids:
        logger.error("ERROR: No error IDs found!")
        return
    
    logger.info(f"\nConfiguration:")
    logger.info(f"   - Total error IDs: {len(product_ids)}")
    logger.info(f"   - Attempts per ID: {NUM_ATTEMPTS}")
    logger.info(f"   - Concurrency: {max_concurrent}")
    logger.info(f"   - Total requests: {len(product_ids) * NUM_ATTEMPTS:,}")
    logger.info(f"\nEstimated time: ~{len(product_ids) * NUM_ATTEMPTS * 0.6 / max_concurrent / 60:.1f} minutes\n")
    
    # Create output directory
    output_dir.mkdir(exist_ok=True)
    
    # Progress tracking
    completed = 0
    total = len(product_ids)
    start_time = time.perf_counter()
    
    semaphore = asyncio.Semaphore(max_concurrent)
    
    # Categories for results
    recovered = []  # 100% success
    intermittent = []  # Mixed success/fail (BOT DETECTION!)
    persistent_404 = []  # 100% fail
    
    async with aiohttp.ClientSession() as session:
        # Process all IDs
        tasks = []
        for product_id in product_ids:
            task = test_product_multiple_times(session, product_id, NUM_ATTEMPTS, semaphore)
            tasks.append(task)
        
        # Gather results with progress
        logger.info("Testing products...")
        for i, coro in enumerate(asyncio.as_completed(tasks)):
            result = await coro
            completed += 1
            
            # Categorize result
            if result["success_rate"] == 100:
                recovered.append(result)
            elif result["success_rate"] == 0:
                persistent_404.append(result)
            else:
                intermittent.append(result)
            
            # Progress update
            if completed % 50 == 0 or completed == total:
                elapsed = time.perf_counter() - start_time
                rate = completed / elapsed if elapsed > 0 else 0
                eta = (total - completed) / rate if rate > 0 else 0
                percentage = (completed / total) * 100
                
                progress_msg = f"Progress: {completed}/{total} ({percentage:.1f}%) | Rate: {rate:.1f} IDs/s | ETA: {eta:.0f}s"
                logger.info(progress_msg)
        
        logger.info("\n" + "="*70)
        logger.info("ANALYSIS RESULTS")
        logger.info("="*70)
        
        logger.info(f"\n[SUCCESS] Recovered (100% success): {len(recovered)} IDs")
        logger.info(f"   -> These products are now back online or temporarily hidden")
        
        logger.info(f"\n[WARNING] Intermittent (mixed): {len(intermittent)} IDs")
        logger.info(f"   -> POSSIBLE BOT DETECTION - sometimes pass, sometimes fail!")
        
        logger.info(f"\n[FAIL] Persistent 404 (100% fail): {len(persistent_404)} IDs")
        logger.info(f"   -> Products truly deleted/don't exist")
        
        # Save results
        logger.info(f"\nSaving results...")
        
        # 1. Recovered products (full data)
        if recovered:
            recovered_data = [r["data"] for r in recovered if r["data"]]
            with open(output_dir / "recovered_products.json", "w", encoding="utf-8") as f:
                json.dump(recovered_data, f, ensure_ascii=False, indent=2)
            logger.info(f"   [SUCCESS] {len(recovered_data)} recovered -> {output_dir}/recovered_products.json")
        
        # 2. Intermittent IDs (detailed analysis)
        if intermittent:
            intermittent_analysis = []
            for r in intermittent:
                intermittent_analysis.append({
                    "product_id": r["product_id"],
                    "success_rate": r["success_rate"],
                    "successes": r["successes"],
                    "failures": r["failures"],
                    "pattern": [1 if res.get("success") else 0 for res in r["results"]],
                    "data": r["data"]
                })
            
            with open(output_dir / "intermittent_ids.json", "w", encoding="utf-8") as f:
                json.dump(intermittent_analysis, f, ensure_ascii=False, indent=2)
            logger.info(f"   [WARNING] {len(intermittent)} intermittent -> {output_dir}/intermittent_ids.json")
            
            # Show some examples
            logger.info(f"\n   Examples of intermittent patterns:")
            for item in intermittent_analysis[:5]:
                pattern_str = "".join(["S" if x else "F" for x in item["pattern"]])
                logger.info(f"      ID {item['product_id']}: {pattern_str} ({item['success_rate']:.0f}%)")
        
        # 3. Persistent 404s (just IDs)
        if persistent_404:
            persistent_ids = [r["product_id"] for r in persistent_404]
            with open(output_dir / "persistent_404_ids.json", "w", encoding="utf-8") as f:
                json.dump(persistent_ids, f, ensure_ascii=False, indent=2)
            logger.info(f"   [FAIL] {len(persistent_404)} persistent 404s -> {output_dir}/persistent_404_ids.json")
        
        # Summary report
        logger.info(f"\n" + "="*70)
        logger.info("SUMMARY REPORT")
        logger.info("="*70)
        summary = f"""
Total error IDs tested: {total}
Testing attempts per ID: {NUM_ATTEMPTS}

Results:
  [SUCCESS] Recovered:         {len(recovered):4d} ({len(recovered)/total*100:5.2f}%)
  [WARNING] Intermittent:      {len(intermittent):4d} ({len(intermittent)/total*100:5.2f}%) <- BOT DETECTION?
  [FAIL]    Persistent 404:    {len(persistent_404):4d} ({len(persistent_404)/total*100:5.2f}%)

Interpretation:
  - Recovered: Products are back online or were temporarily hidden
  - Intermittent: Inconsistent results suggest bot detection
  - Persistent 404: Products truly deleted/don't exist

[WARNING] If intermittent rate > 5-10%, consider:
     1. Reducing concurrency in main.py
     2. Adding random delays between requests
     3. Using the recovered data for your dataset
        """
        logger.info(summary)
        
        if len(intermittent) / total > 0.05:
            logger.warning("[WARNING] High intermittent rate detected!")
            logger.warning("   -> Tiki may be using bot detection on these IDs")
            logger.warning("   -> Recommend reducing concurrency and adding delays")
        
        logger.info(f"\nFull log saved to: {log_file}")

if __name__ == "__main__":
    start = time.perf_counter()
    asyncio.run(main())
    end_time = time.perf_counter()
    elapsed = end_time - start
    print(f"\nTotal execution time: {elapsed:.2f} seconds ({elapsed/60:.2f} minutes)")
