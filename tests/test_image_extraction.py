"""
Unit tests for image URL extraction and validation

WHY THESE TESTS EXIST:
- Tiki API returns multiple image URLs (thumbnail, preview, original)
- We must extract base_url (original high-quality image) not thumbnail
- Unit tests ensure correctness when API response changes
- Tests catch edge cases: missing images, empty arrays, null values
"""

import unittest
from pathlib import Path
import sys

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from main import extract_product_fields, clean_description


class TestImageExtraction(unittest.TestCase):
    """Test cases for image URL extraction"""

    def test_extract_base_urls_only(self):
        """
        TEST: Ensure base_url is extracted (not thumbnail/thumbnail_url)
        WHY: base_url is the original high-quality image
             thumbnail_url is low-quality for preview only
        CRITICAL: If this test fails, users get low-quality images
        """
        product_data = {
            "id": 123,
            "name": "Test Product",
            "url_key": "test-product",
            "price": 100,
            "description": "Test",
            "images": [
                {
                    "base_url": "https://example.com/image1.jpg",
                    "thumbnail_url": "https://example.com/image1_thumb.jpg",
                    "small_url": "https://example.com/image1_small.jpg"
                },
                {
                    "base_url": "https://example.com/image2.jpg",
                    "thumbnail_url": "https://example.com/image2_thumb.jpg"
                }
            ]
        }
        
        result = extract_product_fields(product_data)
        
        # ASSERTION: Should only contain base_url, not thumbnails
        self.assertEqual(len(result["images"]), 2)
        self.assertIn("https://example.com/image1.jpg", result["images"])
        self.assertIn("https://example.com/image2.jpg", result["images"])
        self.assertNotIn("https://example.com/image1_thumb.jpg", result["images"])
        self.assertNotIn("https://example.com/image1_small.jpg", result["images"])

    def test_empty_images_list(self):
        """
        TEST: Handle products with no images gracefully
        WHY: Some products might have no images available
        EXPECTED: Empty list instead of error
        """
        product_data = {
            "id": 123,
            "name": "Test Product",
            "url_key": "test-product",
            "price": 100,
            "description": "Test",
            "images": []  # ← Empty array
        }
        
        result = extract_product_fields(product_data)
        self.assertEqual(result["images"], [])
        self.assertIsInstance(result["images"], list)

    def test_missing_images_field(self):
        """
        TEST: Handle products without images field in API response
        WHY: Some old API responses might not have images key at all
        EXPECTED: Empty list, not None or error
        """
        product_data = {
            "id": 123,
            "name": "Test Product",
            "url_key": "test-product",
            "price": 100,
            "description": "Test"
            # images field completely missing
        }
        
        result = extract_product_fields(product_data)
        self.assertEqual(result["images"], [])

    def test_images_without_base_url(self):
        """
        TEST: Skip images that don't have base_url field
        WHY: Some image objects might be incomplete/corrupted data from Tiki API
        EXPECTED: Only include images with base_url present
        """
        product_data = {
            "id": 123,
            "name": "Test Product",
            "url_key": "test-product",
            "price": 100,
            "description": "Test",
            "images": [
                {
                    "id": 1,
                    "thumbnail_url": "https://example.com/nobase_thumb.jpg"
                    # ← Missing base_url! Should skip this
                },
                {
                    "id": 2,
                    "base_url": "https://example.com/image.jpg"  # ← Valid
                }
            ]
        }
        
        result = extract_product_fields(product_data)
        # ASSERTION: Should only have 1 image (skipped the one without base_url)
        self.assertEqual(len(result["images"]), 1)
        self.assertEqual(result["images"][0], "https://example.com/image.jpg")

    def test_empty_base_url_skipped(self):
        """
        TEST: Skip images with empty base_url value
        WHY: Empty URLs are invalid and would break downstream processing
        EXPECTED: Only include images with non-empty base_url
        """
        product_data = {
            "id": 123,
            "name": "Test Product",
            "url_key": "test-product",
            "price": 100,
            "description": "Test",
            "images": [
                {
                    "base_url": ""  # ← Empty string, invalid
                },
                {
                    "base_url": "https://example.com/valid.jpg"  # ← Valid
                }
            ]
        }
        
        result = extract_product_fields(product_data)
        # ASSERTION: Should skip empty base_url and only have valid one
        self.assertEqual(len(result["images"]), 1)
        self.assertEqual(result["images"][0], "https://example.com/valid.jpg")

    def test_images_not_list_type(self):
        """
        TEST: Handle case where images is not an array (corrupted data)
        WHY: Malformed API response might return string instead of array
        EXPECTED: Return empty list instead of crashing
        """
        product_data = {
            "id": 123,
            "name": "Test Product",
            "url_key": "test-product",
            "price": 100,
            "description": "Test",
            "images": "not_a_list"  # ← Wrong type!
        }
        
        result = extract_product_fields(product_data)
        # ASSERTION: Should handle gracefully with empty list
        self.assertEqual(result["images"], [])

    def test_required_fields_extracted(self):
        """
        TEST: Verify all 6 required fields are present in result
        WHY: Requirements specify exactly these fields:
             id, name, url_key, price, description, images
        EXPECTED: Result has exactly these 6 keys, no extra fields
        """
        product_data = {
            "id": 123,
            "name": "Test Product",
            "url_key": "test-product",
            "price": 99.99,
            "description": "<p>Test description</p>",
            "images": [{"base_url": "https://example.com/image.jpg"}],
            "extra_field": "should_be_removed",  # ← Extra field
            "another_field": "also_removed"  # ← Extra field
        }
        
        result = extract_product_fields(product_data)
        
        # ASSERTION: Should have exactly 6 required fields
        required_fields = {"id", "name", "url_key", "price", "description", "images"}
        self.assertEqual(set(result.keys()), required_fields)
        
        # ASSERTION: Should NOT have extra fields
        self.assertNotIn("extra_field", result)
        self.assertNotIn("another_field", result)

    def test_description_html_removed(self):
        """
        TEST: HTML tags from description should be removed
        WHY: Tiki API returns descriptions with HTML tags
             We need plain text without <p>, <br>, <strong> etc
        EXPECTED: Clean plain text without any HTML
        """
        product_data = {
            "id": 123,
            "name": "Test Product",
            "url_key": "test-product",
            "price": 100,
            "description": "<p>This is <strong>bold</strong> text</p>",
            "images": []
        }
        
        result = extract_product_fields(product_data)
        
        # ASSERTION: No HTML tags should remain
        self.assertNotIn("<", result["description"])
        self.assertNotIn(">", result["description"])
        self.assertNotIn("<p>", result["description"])
        self.assertNotIn("<strong>", result["description"])
        
        # ASSERTION: Text content should be preserved
        self.assertIn("bold", result["description"])

    def test_error_handling(self):
        """
        TEST: Handle error responses gracefully
        WHY: If product fetch fails, we get error response instead of product
        EXPECTED: Return error data as-is for retry logic to handle
        """
        product_data = {
            "error": "Product not found",
            "status_code": 404
        }
        
        result = extract_product_fields(product_data)
        # ASSERTION: Should return the error data unchanged
        self.assertIn("error", result)
        self.assertEqual(result["error"], "Product not found")


class TestCleanDescription(unittest.TestCase):
    """Specific tests for description cleaning function"""
    
    def test_remove_html_tags(self):
        """
        TEST: All HTML tags should be removed
        WHY: Tiki returns descriptions with HTML formatting
        EXPECTED: Plain text only
        """
        html = "<p>Clean <strong>description</strong></p>"
        result = clean_description(html)
        
        self.assertEqual(result, "Clean description")
        self.assertNotIn("<", result)
        self.assertNotIn(">", result)
    
    def test_normalize_whitespace(self):
        """
        TEST: Multiple spaces should normalize to single space
        WHY: HTML has indentation/newlines that create multiple spaces
        EXPECTED: Single spaces only
        """
        html = "<p>Text   with    multiple     spaces</p>"
        result = clean_description(html)
        
        # Should normalize to single spaces
        self.assertNotIn("   ", result)
        self.assertEqual(result, "Text with multiple spaces")
    
    def test_handle_empty_description(self):
        """
        TEST: Empty description should return empty string
        WHY: Some products might have no description
        EXPECTED: Empty string, not None
        """
        result = clean_description("")
        self.assertEqual(result, "")
        
        result = clean_description(None)
        self.assertEqual(result, "")
    
    def test_preserve_content(self):
        """
        TEST: Important text content should be preserved (without tags)
        WHY: HTML contains important product information
        EXPECTED: Text preserved, tags removed
        """
        html = "<div>Product <strong>Features</strong>: <ul><li>Feature 1</li><li>Feature 2</li></ul></div>"
        result = clean_description(html)
        
        # Content should be preserved
        self.assertIn("Product", result)
        self.assertIn("Features", result)
        self.assertIn("Feature 1", result)
        self.assertIn("Feature 2", result)
        
        # Tags should be gone
        self.assertNotIn("<div>", result)
        self.assertNotIn("<ul>", result)

    def test_handle_special_characters(self):
        """
        TEST: Special characters and unicode should be preserved
        WHY: Product descriptions might have Vietnamese characters
        EXPECTED: Characters preserved, only HTML tags removed
        """
        html = "<p>Sản phẩm tốt! 100% chính hãng!</p>"
        result = clean_description(html)
        
        # Vietnamese characters should be preserved
        self.assertIn("Sản", result)
        self.assertIn("phẩm", result)
        self.assertIn("100%", result)


if __name__ == "__main__":
    unittest.main(verbosity=2)
