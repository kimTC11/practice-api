# Tiki Product Data Crawler - Quick Start Guide

A high-performance Python crawler for collecting 200,000 Tiki products with built-in retry pipeline, checkpointing, and comprehensive error logging.

## Quick Setup (5 minutes)

```bash
# 1. Clone & enter directory
git clone <repository-url>
cd practice-api

# 2. Create & activate virtual environment
python3 -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate

# 3. Install dependencies
pip install -r requirements.txt

# 4. Verify product ID file exists
ls -lh list_id/products-0-200000.csv  # Should show ~1.8MB file

# 5. Run tests (optional)
python3 -m unittest tests.test_image_extraction -v

# 6. Run the crawler
python3 main.py
```

**Don't have product ID file?** Download: https://1drv.ms/u/s!AukvlU4z92FZgp4xIlzQ4giHVa5Lpw?e=qDXctn

## Output Files and Data Format

### Output Files
```
output/
- products_batch_1.json         # ~1000 products each (200 files)
- products_batch_recovered.json # Recovered by retry
- errors.jsonl                  # Failed products (newline-delimited JSON)
- permanent_failures.jsonl      # 404 errors (products don't exist)
```

### Product Data Format
```json
{
  "id": 1391347,
  "name": "Product Name",
  "url_key": "product-slug",
  "price": 245700,
  "description": "Clean text without HTML",
  "images": ["https://...", "https://..."]
}
```

## Key Features

[OK] 8 concurrent requests - 10-15x faster than sequential  
[OK] Auto-retry pipeline - 3 rounds recover 20-40% of failures  
[OK] Crash recovery - Checkpointing resumes from last batch  
[OK] Full traceback logging - Know exactly where errors occur  
[OK] 1000 products/file - Clean, manageable JSON files  
[OK] Comprehensive tests - 15+ unit tests included

## Monitor Progress

```bash
# Watch logs in real-time
tail -f logs/crawler_*.log

# Count completed batches
watch 'ls output/products_batch_*.json | wc -l'
```

## Verify Results

```bash
# Check if completed successfully (checkpoint cleared)
ls checkpoint.json 2>&1  # Should show "No such file"

# Count total products saved
python3 << 'EOF'
import json, os
total = sum(len(json.load(open(f"output/{f}"))) 
            for f in os.listdir("output") 
            if f.startswith("products_batch_") and f.endswith(".json"))
print(f"Total products: {total}")
EOF

# Validate JSON format
python3 -m json.tool output/products_batch_1.json > /dev/null && echo "[OK] Valid"
```

## Notes

- **Crash Recovery**: If interrupted, simply run again - checkpoint auto-resumes
- **Rate Limit**: If hit (HTTP 429), reduce `max_concurrent` to 4 in main.py
- **Documentation**: See [TECHNICAL_GUIDE.md](TECHNICAL_GUIDE.md) for improvements, config, and troubleshooting
