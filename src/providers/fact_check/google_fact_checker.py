import os
import sys
import requests
from dataclasses import dataclass
from typing import List, Optional

# Add project root to path for config import
current_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(os.path.dirname(os.path.dirname(current_dir)))
if project_root not in sys.path:
    sys.path.append(project_root)

import config

@dataclass
class FactCheckResult:
    claim: str          # The claim statement
    text: str           # The title or text of the fact check article
    rating: str         # The verdict (True, False, Misleading, etc.)
    publisher: str      # Who checked it (Snopes, PolitiFact, etc.)
    url: str            # Link to the full fact check

class FactChecker:
    def __init__(self, api_key: Optional[str] = None):
        """
        Initialize the FactChecker client.
        
        :param api_key: Google Fact Check Tools API Key. 
                        Tries argument -> env var FACTCHECK_API_KEY -> config.GOOGLE_API_KEY.
        """
        self.api_key = api_key or os.environ.get("FACTCHECK_API_KEY")
        
        if not self.api_key and hasattr(config, 'GOOGLE_API_KEY'):
             val = config.GOOGLE_API_KEY
             if val and val != "YOUR_API_KEY_HERE":
                 self.api_key = val
                 
        if not self.api_key:
            print("Warning: No Fact Check API Key found. Set FACTCHECK_API_KEY or config.py.")

    def search_claims(self, query: str, max_results: int = 3, language_code: str = "en") -> List[FactCheckResult]:
        """
        Search for fact checks for a given query string.
        """
        if not self.api_key:
            print("Error: Missing API Key.")
            return []
            
        endpoint = "https://factchecktools.googleapis.com/v1alpha1/claims:search"
        
        # Clean up the query a bit to help search relevance
        # Remove common "I heard" prefixes which might confuse strict matching
        clean_query = query.lower().replace("i heard that ", "").replace("i heard ", "").replace("people say ", "")
        
        params = {
            "key": self.api_key,
            "query": clean_query,
            "pageSize": max_results,
            "languageCode": language_code
        }
        
        print(f"Searching Fact Check API for: '{clean_query}' (lang={language_code})") # Debug

        
        try:
            response = requests.get(endpoint, params=params)
            response.raise_for_status()
            data = response.json()
            
            # Debug print
            print(f"API Response Status: {response.status_code}")
            if "claims" not in data:
                 print(f"API returned no claims. Full response: {data}")
            
        except Exception as e:
            print(f"Fact Check API request failed: {e}")
            # If it's a 403 or 400, print more details
            if isinstance(e, requests.exceptions.HTTPError):
                 print(f"Response content: {e.response.text}")
            return []
            
        results = []
        claims = data.get("claims", [])
        
        for item in claims:
            input_claim = item.get("text", "Unknown Claim")
            reviews = item.get("claimReview", [])
            
            for review in reviews:
                title = review.get("title", input_claim)
                publisher = review.get("publisher", {}).get("name", "Unknown")
                rating = review.get("textualRating", "Unknown")
                url = review.get("url", "")
                
                res = FactCheckResult(
                    claim=input_claim,
                    text=title,
                    rating=rating,
                    publisher=publisher,
                    url=url
                )
                results.append(res)
                
                # If we've reached max_results total (across all claims), we could stop?
                # But usually max_results applies to claims returned by API.
                # Just adding all reviews for the returned claims.
                
        return results

if __name__ == "__main__":
    def test_client():
        print("Testing FactCheck API Client...")
        
        # You can set this env var in your terminal before running:
        # $env:FACTCHECK_API_KEY="your_key"
        
        api_key = os.environ.get("FACTCHECK_API_KEY")
        if not api_key:
            print("Note: FACTCHECK_API_KEY not set. Attempting to use config...")
        
        checker = FactChecker()
        
        # Sample query (a common debunked claim for testing)
        query = "Earth is flat" 
        print(f"Searching for: '{query}'")
        
        results = checker.search_claims(query)
        
        if not results:
            print("No results found (or API key invalid).")
        else:
            print(f"\nFound {len(results)} results:")
            for i, res in enumerate(results, 1):
                print(f"{i}. [{res.rating.upper()}] {res.claim} ({res.publisher})")
                print(f"   Article: {res.text}")
                print(f"   Link: {res.url}\n")

    test_client()
