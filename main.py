#api get: 
#- API get product detail: https://api.tiki.vn/product-detail/api/v1/products/138083218


# DoD: Sử dụng code Python, tải về thông tin của 200k sản phẩm (list product id bên dưới) của Tiki và lưu thành các file .json. 
# Mỗi file có thông tin của khoảng 1000 sản phẩm. 
# Các thông in cần lấy bao gồm: id, name, url_key, price, description, images url. Yêu cầu chuẩn hoá nội dung trong "description" và tìm phương án rút ngắn thời gian lấy dữ liệu.

# - List product_id: https://1drv.ms/u/s!AukvlU4z92FZgp4xIlzQ4giHVa5Lpw?e=qDXctn
# - API get product detail: https://api.tiki.vn/product-detail/api/v1/products/138083218

# Lưu ý: Cần lưu lại những sản phẩm bị lỗi và lý do lỗi.
# Tổng quan về json có thể tham khảo tại đây: https://www.youtube.com/watch?v=iiADhChRriM
# Link submit project sau khi hoàn thành:  https://docs.google.com/forms/d/1iIJavuPT7haom8NQSGiBwD-d8nMKeAGCBtXvZEEtH_A/edit

import aiohttp
import asyncio
import json
import time
import pandas as pd
import re
import logging
import traceback
from bs4 import BeautifulSoup
from pathlib import Path
from datetime import datetime

# https://tiki.vn/api/v2/products/76298252
url = "https://api.tiki.vn/product-detail/api/v1/products/{}"
# url = "https://api.tiki.vn/api/v2/products/{}"

headers = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) "
                  "Chrome/120.0.0.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Referer": "https://tiki.vn/"
}

def clean_description(html_description: str) -> str:
    """
    Remove HTML tags and clean up description text.
    
    WHY: Tiki API returns HTML in descriptions. We need plain text:
    - Removes <p>, <strong>, <br>, etc tags
    - Normalizes whitespace (prevents multiple spaces from breaking formatting)
    - Result: Clean, readable plain text suitable for display/storage
    """
    if not html_description:
        return ""
    
    # Parse HTML using BeautifulSoup
    soup = BeautifulSoup(html_description, 'html.parser')
    
    # Get text and clean up whitespace (separator=' ' adds space between elements)
    text = soup.get_text(separator=' ', strip=True)
    
    # Remove extra whitespace (multiple spaces become single space)
    # WHY: HTML often has indent and newlines that should be normalized
    text = re.sub(r'\s+', ' ', text)
    
    return text.strip()

def extract_product_fields(product_data: dict) -> dict:
    """
    Extract only required fields from product data.
    
    WHY: API returns many fields we don't need. Extraction:
    - Reduces file size (only store necessary data)
    - Makes JSON more readable
    - Prevents API changes from breaking our data format
    - Required fields: id, name, url_key, price, description, images URLs
    """
    # Handle error responses
    if "error" in product_data:
        return product_data
    
    # Extract image URLs - get base_url (original image, not thumbnail)
    # WHY: Tiki provides multiple image URLs (thumbnail, preview, original)
    # We want base_url which is the original high-quality image
    images_urls = []
    if "images" in product_data and isinstance(product_data["images"], list):
        images_urls = [img.get("base_url", "") for img in product_data["images"] if img.get("base_url")]
    
    # Extract and clean description (removes HTML tags)
    description = clean_description(product_data.get("description", ""))
    
    # Return only required fields - matches the requirements
    # WHY: This structure is what we need for downstream processing
    return {
        "id": product_data.get("id"),
        "name": product_data.get("name", ""),
        "url_key": product_data.get("url_key", ""),
        "price": product_data.get("price"),
        "description": description,
        "images": images_urls
    }

async def get_product_detail(session: aiohttp.ClientSession, product_id: int, semaphore: asyncio.Semaphore) -> dict:
    """
    Fetch product detail with retry logic and comprehensive error logging.
    
    WHY THIS EXISTS:
    - Demonstrates parallel execution: Uses asyncio + semaphore for concurrent requests
    - Robust error handling: Logs full traceback with line numbers for debugging
    - Exponential backoff: Handles rate limiting (status 429) gracefully
    """
    max_retries = 5
    retry_delay = 1  # Start with 1 second delay
    logger = logging.getLogger(__name__)
    
    async with semaphore:  # Limit concurrent requests - PERFORMANCE: This ensures max_concurrent requests at a time
        for attempt in range(max_retries):
            try:
                async with session.get(url.format(product_id), headers=headers, timeout=aiohttp.ClientTimeout(total=10)) as response:
                    if response.status == 200:
                        return await response.json()
                    elif response.status == 429:  # Rate limited
                        if attempt < max_retries - 1:
                            wait_time = retry_delay * (2 ** attempt)  # Exponential backoff: 1s, 2s, 4s, 8s, 16s
                            logger.info(f"Rate limited for product {product_id}, waiting {wait_time}s before retry")
                            await asyncio.sleep(wait_time)
                            continue
                        else:
                            text = await response.text()
                            return {
                                "error": f"Failed to retrieve product {product_id} after {max_retries} retries",
                                "status_code": response.status,
                                "text": text[:200],
                                "product_id": product_id,
                                "retry_count": attempt + 1
                            }
                    else:
                        text = await response.text()
                        return {
                            "error": f"Failed to retrieve product {product_id}",
                            "status_code": response.status,
                            "text": text[:200],
                            "product_id": product_id,
                            "retry_count": attempt + 1
                        }
            except Exception as e:
                # IMPROVEMENT: Log full traceback with line numbers
                # WHY: This shows exactly where the error occurred (file, line number)
                # instead of just the error message
                full_traceback = traceback.format_exc()
                
                error_context = {
                    "product_id": product_id,
                    "attempt": attempt + 1,
                    "error_type": type(e).__name__,
                    "error_message": str(e)
                }
                
                if attempt < max_retries - 1:
                    logger.debug(f"Attempt {attempt + 1} failed for product {product_id}: {str(e)}, retrying...")
                    await asyncio.sleep(retry_delay)
                    continue
                
                # Final error - log full traceback with line numbers
                # WHY: This is critical for debugging - shows stack trace with exact line numbers
                logger.error(f"Failed to fetch product {product_id} after {attempt + 1} attempts:\n{full_traceback}")
                
                return {
                    "error": str(e),
                    "product_id": product_id,
                    "error_type": type(e).__name__,
                    "full_traceback": full_traceback,  # IMPROVEMENT: Store full traceback for inspection
                    "retry_count": attempt + 1
                }
        
        return {
            "error": "Max retries exceeded",
            "product_id": product_id,
            "retry_count": max_retries
        }

# test
# if __name__ == "__main__":
#     product_id = 138083218
#     product_detail = get_product_detail(product_id)
#     print(json.dumps(product_detail, indent=4, ensure_ascii=False))
    
# 2nd test: 

#load csv file and extract id column
df = pd.read_csv("list_id/products-0-200000.csv")
product_ids = df["id"].tolist()

# For testing with smaller dataset
# product_ids = product_ids[:1000]
# To process all 200k products, comment out the line above

print(f"Loaded {len(product_ids)} product IDs to process")

# Setup logging
log_dir = Path("logs")
log_dir.mkdir(exist_ok=True)
log_file = log_dir / f"crawler_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(log_file, encoding='utf-8'),
        logging.StreamHandler()
    ]
)

logger = logging.getLogger(__name__)

logger.info(f"=== TIKI PRODUCT CRAWLER START ===")
logger.info(f"Total products to fetch: {len(product_ids)}")

#using asyncio with aiohttp to get product details concurrently

# Progress tracking (global for entire run)
completed = 0
total = 0
errors = 0
start_time = None

# Checkpoint functions
def load_checkpoint(checkpoint_file: Path) -> dict:
    """
    Load progress checkpoint.
    
    WHY: Allows resuming from last batch if crash occurs
    - Stores batch_num: which batch to resume from
    - Stores total_processed: how many products were processed
    - Returns default {"batch_num": 1} if no checkpoint exists (fresh start)
    """
    if checkpoint_file.exists():
        with open(checkpoint_file, 'r') as f:
            return json.load(f)
    return {"batch_num": 1, "total_processed": 0}

def save_checkpoint(checkpoint_file: Path, batch_num: int, total_processed: int):
    """
    Save progress checkpoint.
    
    WHY: After each batch completes, save state so we can resume if crash happens
    - batch_num: next batch to process (resume_batch = current + 1)
    - total_processed: total products saved so far
    - timestamp: when checkpoint was saved (for debugging)
    """
    checkpoint_data = {
        "batch_num": batch_num,
        "total_processed": total_processed,
        "timestamp": datetime.now().isoformat()
    }
    with open(checkpoint_file, 'w') as f:
        json.dump(checkpoint_data, f)

async def fetch_with_progress(session: aiohttp.ClientSession, product_id: int, semaphore: asyncio.Semaphore) -> dict:
    """
    Fetch single product with progress tracking.
    
    WHY: Global progress tracking helps users understand:
    - Current progress percentage
    - Requests per second (throughput)
    - Estimated time remaining
    - Total errors so far
    
    PERFORMANCE: Updates every 50 requests to avoid excessive stdout writing
    """
    global completed, errors, start_time
    result = await get_product_detail(session, product_id, semaphore)
    completed += 1
    
    if "error" in result:
        errors += 1
    
    # IMPROVEMENT: Update progress every 50 requests or at completion
    # WHY: Balances UX (frequent updates) with performance (not too much I/O)
    if completed % 50 == 0 or completed == total:
        elapsed = time.perf_counter() - start_time
        rate = completed / elapsed if elapsed > 0 else 0
        eta_seconds = (total - completed) / rate if rate > 0 else 0
        percentage = (completed / total) * 100
        
        print(f"\rProgress: {completed}/{total} ({percentage:.1f}%) | "
              f"Rate: {rate:.1f} req/s | ETA: {eta_seconds:.0f}s | Errors: {errors}", 
              end="", flush=True)
    
    return result

async def process_batch(session: aiohttp.ClientSession, batch_ids: list, batch_num: int, 
                       semaphore: asyncio.Semaphore, output_dir: Path, error_file: Path) -> tuple:
    """
    Process a batch of product IDs and save immediately.
    
    IMPROVEMENTS:
    - Handles remainder products correctly (even if batch_ids < 1000)
    - Separates errors from successes cleanly (Filter step)
    - Returns failed_product_ids for retry pipeline
    
    WHY:
    - JSON Batching: Division logic ensures last batch with fewer products works correctly
    - Error Handling: Immediate error logging prevents data loss on crash
    """
    logger = logging.getLogger(__name__)
    
    # PERFORMANCE: Fetch all products in this batch concurrently (asyncio + semaphore)
    tasks = [fetch_with_progress(session, product_id, semaphore) for product_id in batch_ids]
    results = await asyncio.gather(*tasks)
    
    # IMPROVEMENT: Separate successful results from errors (Filter step in pipeline)
    successful_results = []
    error_results = []
    failed_product_ids = []
    
    for result in results:
        if "error" in result:
            error_results.append(result)
            # Keep product_id and error data for retry pipeline
            failed_product_ids.append((result.get("product_id"), result))
        else:
            # Extract only required fields and clean data
            cleaned_product = extract_product_fields(result)
            successful_results.append(cleaned_product)
    
    # IMPROVEMENT: Save successful results immediately to file
    # WHY: Even if crash happens, data isn't lost. 1000-product chunks ensure clean splits.
    if successful_results:
        filename = output_dir / f"products_batch_{batch_num}.json"
        with open(filename, "w", encoding="utf-8") as f:
            json.dump(successful_results, f, ensure_ascii=False, indent=2)
        logger.info(f"Saved {len(successful_results)} products to {filename}")
    
    # IMPROVEMENT: Save errors immediately (append mode)
    # WHY: JSONL format (newline-delimited JSON) allows incremental errors without loading all in memory
    if error_results:
        with open(error_file, "a", encoding="utf-8") as f:
            for error in error_results:
                # IMPROVEMENT: Include timestamp for error debugging
                error["timestamp"] = datetime.now().isoformat()
                f.write(json.dumps(error, ensure_ascii=False) + "\n")
        logger.warning(f"Batch {batch_num}: {len(error_results)} errors logged to {error_file}")
    
    # Return counts and failed product IDs for retry pipeline
    return len(successful_results), len(error_results), failed_product_ids

async def retry_failed_products(session: aiohttp.ClientSession, failed_ids: list, 
                                semaphore: asyncio.Semaphore, output_dir: Path) -> tuple:
    """
    Retry failed products - 3-attempt retry pipeline.
    
    Pipeline Flow:
    1. Crawl: Initial fetch attempt
    2. Filter: Separate successful from failed (error in response)
    3. Retry: Attempt up to 3 times (exponential backoff handled in get_product_detail)
    4. Log: Permanently failed IDs logged to permanent_failures.jsonl
    
    WHY THIS MATTERS:
    - Network glitches: Temporary timeouts often resolve on retry
    - Rate limiting: Exponential backoff respects API limits
    - Data integrity: Failed IDs are tracked for manual investigation
    """
    max_retry_attempts = 3
    logger = logging.getLogger(__name__)
    
    if not failed_ids:
        logger.info("No failed products to retry")
        return 0, 0, []
    
    logger.info(f"\n{'='*70}")
    logger.info(f"=== RETRY PIPELINE START ===")
    logger.info(f"Total failed products to retry: {len(failed_ids)}")
    logger.info(f"{'='*70}")
    
    recovered_products = []
    current_failed_ids = failed_ids.copy()  # IMPROVEMENT: Keep original for counting
    
    for retry_round in range(1, max_retry_attempts + 1):
        if not current_failed_ids:
            logger.info(f"All products recovered by round {retry_round - 1}")
            break
        
        logger.info(f"\n[Retry Round {retry_round}/{max_retry_attempts}] Attempting {len(current_failed_ids)} products")
        
        # Extract product IDs for retry
        remaining_product_ids = [pid for pid, _ in current_failed_ids]
        
        # IMPROVEMENT: Fetch with concurrent requests (same as initial batch)
        tasks = [get_product_detail(session, product_id, semaphore) for product_id in remaining_product_ids]
        results = await asyncio.gather(*tasks)
        
        # IMPROVEMENT: Track recovery status clearly
        new_failed = []
        round_recovered = 0
        
        for product_id, result in zip(remaining_product_ids, results):
            if "error" not in result:
                # SUCCESS: Product recovered
                recovered_product = extract_product_fields(result)
                recovered_products.append(recovered_product)
                round_recovered += 1
                logger.info(f"   ✓ Recovered product_id={product_id} on retry {retry_round}")
            else:
                # FAILURE: Still failing
                new_failed.append((product_id, result))
                # Store latest error attempt for permanent failure log
                if retry_round == max_retry_attempts:
                    logger.debug(f"   ✗ product_id={product_id} failed retry {retry_round}: {result.get('error')[:50]}")
        
        # Update for next round
        current_failed_ids = new_failed
        logger.info(f"   [Round {retry_round} Summary] Recovered: {round_recovered}, Still failing: {len(current_failed_ids)}")
    
    # IMPROVEMENT: Log permanently failed products with detailed error info
    permanent_failures = current_failed_ids
    
    if permanent_failures:
        permanent_ids = [pid for pid, _ in permanent_failures]
        permanent_file = output_dir / "permanent_failures.jsonl"
        
        with open(permanent_file, 'a', encoding='utf-8') as f:
            for product_id, error_data in permanent_failures:
                # Include full error context for investigation
                error_entry = {
                    "product_id": product_id,
                    "error": error_data.get("error"),
                    "status_code": error_data.get("status_code"),
                    "error_type": error_data.get("error_type"),
                    "traceback_summary": error_data.get("full_traceback", "")[:200] if error_data.get("full_traceback") else None,
                    "final_timestamp": datetime.now().isoformat()
                }
                f.write(json.dumps(error_entry, ensure_ascii=False) + "\n")
        
        logger.warning(f"\n   ✗ {len(permanent_failures)} products permanently failed after {max_retry_attempts} retries")
        logger.warning(f"   → Permanent failure log: {permanent_file}")
    
    logger.info(f"\n{'='*70}")
    logger.info(f"=== RETRY PIPELINE END ===")
    logger.info(f"Total recovered: {len(recovered_products)}, Total permanent failures: {len(permanent_failures)}")
    logger.info(f"{'='*70}\n")
    
    return len(recovered_products), len(permanent_failures), recovered_products

async def main():
    """
    MAIN EXECUTION: Orchestrates the complete data collection pipeline
    
    PIPELINE FLOW:
    1. Load product IDs from CSV
    2. Process in batches of 1000 (to minimize memory usage)
    3. Save successful results immediately to JSON files
    4. Save errors to JSONL for retry
    5. Run retry pipeline on failed products (3 attempts)
    6. Save recovered products to separate file
    7. Save permanent failures to permanent_failures.jsonl
    8. Clear checkpoint on completion
    
    KEY FEATURES:
    - Checkpointing: Can resume from last batch if crash occurs
    - Concurrent execution: Uses asyncio for parallel requests (8 concurrent)
    - Memory optimal: Processes in 1000-product batches, not all at once
    - Error tracking: Full traceback logging with line numbers
    """
    global start_time, total, completed, errors
    start_time = time.perf_counter()
    total = len(product_ids)
    completed = 0
    errors = 0
    
    logger = logging.getLogger(__name__)
    
    # Configuration
    max_concurrent = 8  # Concurrent requests - balances speed vs server load
    batch_size = 1000    # Products per file - 200k products = 200 files
    
    # Create output directory
    output_dir = Path("output")
    output_dir.mkdir(exist_ok=True)
    
    # IMPROVEMENT: Checkpoint file for crash recovery
    # WHY: If script crashes, we can resume from last completed batch
    checkpoint_file = Path("checkpoint.json")
    checkpoint = load_checkpoint(checkpoint_file)
    resume_batch = checkpoint.get("batch_num", 1)
    total_processed = checkpoint.get("total_processed", 0)
    
    if resume_batch > 1:
        logger.warning(f"⚠️ RESUMING from batch {resume_batch} (already processed {total_processed} products)")
    
    # Initialize error file (clear if exists and create empty file)
    error_file = output_dir / "errors.jsonl"
    if not error_file.exists():
        error_file.touch()
    
    logger.info(f"Starting to fetch {total} products...")
    logger.info(f"- Batch size: {batch_size} products per file")
    logger.info(f"- Concurrency: {max_concurrent} requests at a time")
    logger.info(f"- Processing in chunks to minimize memory usage")
    logger.info(f"- Errors saved incrementally to {error_file}\n")
    
    semaphore = asyncio.Semaphore(max_concurrent)
    
    total_success = 0
    total_errors = 0
    failed_products_for_retry = []
    
    async with aiohttp.ClientSession() as session:
        # IMPROVEMENT: Batch processing logic
        # WHY: Process in 1000-product batches instead of all at once
        # This ensures:
        # - Memory stays low (only 1000 products in memory per batch)
        # - JSON files are clean 1000-product chunks
        # - Handles remainder products correctly (last batch may have < 1000)
        
        # Calculate number of batches needed
        # Formula: (200000 + 1000 - 1) // 1000 = 200 batches
        # This ensures last batch is included even if not full
        num_batches = (len(product_ids) + batch_size - 1) // batch_size
        
        for batch_num in range(resume_batch, num_batches + 1):
            # Calculate indices for this batch
            start_idx = (batch_num - 1) * batch_size
            end_idx = min(batch_num * batch_size, len(product_ids))
            batch_ids = product_ids[start_idx:end_idx]
            
            logger.info(f"Processing batch {batch_num}/{num_batches} ({len(batch_ids)} products)")
            
            # Process this batch (errors saved immediately inside process_batch)
            success_count, error_count, batch_failed_ids = await process_batch(
                session, batch_ids, batch_num, semaphore, output_dir, error_file
            )
            
            total_success += success_count
            total_errors += error_count
            failed_products_for_retry.extend(batch_failed_ids)
            
            # IMPROVEMENT: Save checkpoint after each batch
            # WHY: If crash happens, we only lose current batch (not all progress)
            save_checkpoint(checkpoint_file, batch_num + 1, total_processed + success_count + error_count)
            
            # Clear batch from memory to keep memory usage low
            del batch_ids
        
        # IMPROVEMENT: Retry pipeline for failed products
        # WHY: Network glitches often resolve on retry
        # Pipeline: Crawl -> Filter -> Retry 3x -> Log permanent failures
        if failed_products_for_retry:
            logger.info(f"\n{len(failed_products_for_retry)} products failed initial fetch - starting retry pipeline")
            recovered_count, permanent_fail_count, recovered_data = await retry_failed_products(
                session, failed_products_for_retry, semaphore, output_dir
            )
            
            # Save recovered products to a special batch file
            if recovered_data:
                retry_file = output_dir / "products_batch_recovered.json"
                with open(retry_file, 'w', encoding='utf-8') as f:
                    json.dump(recovered_data, f, ensure_ascii=False, indent=2)
                logger.info(f"✓ Saved {len(recovered_data)} recovered products to {retry_file}")
            
            total_success += recovered_count
            total_errors = permanent_fail_count
        
        # Summary report
        logger.info(f"\n{'='*70}")
        logger.info(f"✓ EXECUTION COMPLETE")
        logger.info(f"{'='*70}")
        logger.info(f"✓ Total successful: {total_success} products")
        logger.info(f"✓ Total permanent failures: {total_errors} products")
        
        if total_errors > 0:
            logger.info(f"✓ Error details saved to {error_file}")
            logger.info(f"✓ Permanent failures saved to {output_dir / 'permanent_failures.jsonl'}")
        
        logger.info(f"✓ All files saved to {output_dir}/ directory")
        
        # Clean up checkpoint on success
        # WHY: When process completes successfully, remove checkpoint
        # This way, next run starts fresh instead of resuming
        if checkpoint_file.exists():
            checkpoint_file.unlink()
            logger.info(f"✓ Checkpoint cleared (process complete)")

if __name__ == "__main__":
    asyncio.run(main())
    end_time = time.perf_counter()
    elapsed_time = end_time - start_time
    print(f"Total execution time: {elapsed_time:.2f} seconds ({elapsed_time/60:.2f} minutes)")


 