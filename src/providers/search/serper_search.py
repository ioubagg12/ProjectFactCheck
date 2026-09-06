import os
import requests


class SerperSearcher:
    def __init__(self):
        self.api_key = os.getenv("SERPER_API_KEY", "").strip()
        self.endpoint = "https://google.serper.dev/search"
        self.default_gl = os.getenv("SERPER_GL", "us").strip() or "us"
        self.default_hl = os.getenv("SERPER_HL", "en").strip() or "en"

    def search_web(self, query, num_results=5, gl=None, hl=None):
        if not self.api_key:
            print("SERPER_API_KEY is missing. Live search disabled.")
            return []

        payload = {
            "q": query,
            "num": max(1, min(int(num_results), 10)),
            "gl": (gl or self.default_gl),
            "hl": (hl or self.default_hl)
        }
        headers = {
            "X-API-KEY": self.api_key,
            "Content-Type": "application/json"
        }

        try:
            response = requests.post(self.endpoint, headers=headers, json=payload, timeout=12)
            response.raise_for_status()
            data = response.json()
        except Exception as e:
            print(f"Serper request failed: {e}")
            return []

        organic = data.get("organic", []) or []
        news = data.get("news", []) or []
        combined = (news + organic)[:max(1, min(int(num_results), 10))]

        results = []
        for item in combined:
            results.append(
                {
                    "title": item.get("title", ""),
                    "snippet": item.get("snippet", ""),
                    "url": item.get("link", "")
                }
            )

        print(f"Serper returned {len(results)} results for query: {query}")
        return results
