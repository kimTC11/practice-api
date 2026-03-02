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
from bs4 import BeautifulSoup
from pathlib import Path

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
    """Remove HTML tags and clean up description text"""
    if not html_description:
        return ""
    
    # Parse HTML
    soup = BeautifulSoup(html_description, 'html.parser')
    
    # Get text and clean up whitespace
    text = soup.get_text(separator=' ', strip=True)
    
    # Remove extra whitespace
    text = re.sub(r'\s+', ' ', text)
    
    return text.strip()

def extract_product_fields(product_data: dict) -> dict:
    """Extract only required fields from product data"""
    # Handle error responses
    if "error" in product_data:
        return product_data
    
    # Extract image URLs
    images_urls = []
    if "images" in product_data and isinstance(product_data["images"], list):
        images_urls = [img.get("base_url", "") for img in product_data["images"] if img.get("base_url")]
    
    # Extract and clean description
    description = clean_description(product_data.get("description", ""))
    
    # Return only required fields
    return {
        "id": product_data.get("id"),
        "name": product_data.get("name", ""),
        "url_key": product_data.get("url_key", ""),
        "price": product_data.get("price"),
        "description": description,
        "images": images_urls
    }

async def get_product_detail(session: aiohttp.ClientSession, product_id: int, semaphore: asyncio.Semaphore) -> dict:
    max_retries = 5
    retry_delay = 1  # Start with 1 second delay
    
    async with semaphore:  # Limit concurrent requests
        for attempt in range(max_retries):
            try:
                async with session.get(url.format(product_id), headers=headers, timeout=aiohttp.ClientTimeout(total=10)) as response:
                    if response.status == 200:
                        return await response.json()
                    elif response.status == 429:  # Rate limited
                        if attempt < max_retries - 1:
                            wait_time = retry_delay * (2 ** attempt)  # Exponential backoff
                            await asyncio.sleep(wait_time)
                            continue
                        else:
                            text = await response.text()
                            return {
                                "error": f"Failed to retrieve product {product_id} after {max_retries} retries",
                                "status_code": response.status,
                                "text": text[:200],
                                "product_id": product_id
                            }
                    else:
                        text = await response.text()
                        return {
                            "error": f"Failed to retrieve product {product_id}",
                            "status_code": response.status,
                            "text": text[:200],
                            "product_id": product_id
                        }
            except Exception as e:
                if attempt < max_retries - 1:
                    await asyncio.sleep(retry_delay)
                    continue
                return {"error": str(e), "product_id": product_id}
        
        return {"error": "Max retries exceeded", "product_id": product_id}

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

#using asyncio with aiohttp to get product details concurrently

# Progress tracking (global for entire run)
completed = 0
total = 0
errors = 0
start_time = None

async def fetch_with_progress(session: aiohttp.ClientSession, product_id: int, semaphore: asyncio.Semaphore) -> dict:
    global completed, errors, start_time
    result = await get_product_detail(session, product_id, semaphore)
    completed += 1
    
    if "error" in result:
        errors += 1
    
    # Update progress every 50 requests
    if completed % 50 == 0 or completed == total:
        elapsed = time.perf_counter() - start_time
        rate = completed / elapsed if elapsed > 0 else 0
        eta = (total - completed) / rate if rate > 0 else 0
        percentage = (completed / total) * 100
        
        print(f"\rProgress: {completed}/{total} ({percentage:.1f}%) | "
              f"Rate: {rate:.1f} req/s | ETA: {eta:.0f}s | Errors: {errors}", 
              end="", flush=True)
    
    return result

async def process_batch(session: aiohttp.ClientSession, batch_ids: list, batch_num: int, 
                       semaphore: asyncio.Semaphore, output_dir: Path, error_file: Path) -> tuple:
    """Process a batch of product IDs and save immediately"""
    
    # Fetch all products in this batch
    tasks = [fetch_with_progress(session, product_id, semaphore) for product_id in batch_ids]
    results = await asyncio.gather(*tasks)
    
    # Separate successful results from errors
    successful_results = []
    error_results = []
    
    for result in results:
        if "error" in result:
            error_results.append(result)
        else:
            # Extract only required fields and clean data
            cleaned_product = extract_product_fields(result)
            successful_results.append(cleaned_product)
    
    # Save successful results immediately to file
    if successful_results:
        filename = output_dir / f"products_batch_{batch_num}.json"
        with open(filename, "w", encoding="utf-8") as f:
            json.dump(successful_results, f, ensure_ascii=False, indent=2)  # indent=2 to save space
    
    # Save errors immediately (append mode to not keep in memory)
    if error_results:
        with open(error_file, "a", encoding="utf-8") as f:
            for error in error_results:
                f.write(json.dumps(error, ensure_ascii=False) + "\n")
    
    # Return counts (no need to return error_results anymore)
    return len(successful_results), len(error_results)

async def main():
    global start_time, total, completed, errors
    start_time = time.perf_counter()
    total = len(product_ids)
    completed = 0
    errors = 0
    
    # Configuration
    max_concurrent = 8  # Concurrent requests
    batch_size = 1000    # Products per file
    
    # Create output directory
    output_dir = Path("output")
    output_dir.mkdir(exist_ok=True)
    
    # Initialize error file (clear if exists and create empty file)
    error_file = output_dir / "errors.jsonl"  # Using JSONL format (one JSON object per line)
    if error_file.exists():
        error_file.unlink()  # Delete old error file
    # Tạo file trống để có thể track ngay từ đầu
    error_file.touch()
    
    print(f"Starting to fetch {total} products...")
    print(f"- Batch size: {batch_size} products per file")
    print(f"- Concurrency: {max_concurrent} requests at a time")
    print(f"- Processing in chunks to minimize memory usage")
    print(f"- Errors saved incrementally to {error_file}\n")
    
    semaphore = asyncio.Semaphore(max_concurrent)
    
    total_success = 0
    total_errors = 0
    
    async with aiohttp.ClientSession() as session:
        # Process in batches to avoid loading everything into memory
        num_batches = (len(product_ids) + batch_size - 1) // batch_size
        
        for batch_num in range(1, num_batches + 1):
            start_idx = (batch_num - 1) * batch_size
            end_idx = min(batch_num * batch_size, len(product_ids))
            batch_ids = product_ids[start_idx:end_idx]
            
            # Process this batch (errors saved immediately inside process_batch)
            success_count, error_count = await process_batch(
                session, batch_ids, batch_num, semaphore, output_dir, error_file
            )
            
            total_success += success_count
            total_errors += error_count
            
            # Clear batch from memory
            del batch_ids
        
        print(f"\n\n✓ Completed: {total_success} successful, {total_errors} errors")
        
        if total_errors > 0:
            print(f"✓ Error details saved to {error_file}")
        
        print(f"✓ All files saved to {output_dir}/ directory")

if __name__ == "__main__":
    asyncio.run(main())
    end_time = time.perf_counter()
    elapsed_time = end_time - start_time
    print(f"Total execution time: {elapsed_time:.2f} seconds ({elapsed_time/60:.2f} minutes)")

 