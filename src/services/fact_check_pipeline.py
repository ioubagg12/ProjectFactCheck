from datetime import date
import json
import re


class FactCheckPipeline:
    def __init__(self, transcriber, fact_checker, serper_searcher, groq_client, default_mode="offline"):
        self.transcriber = transcriber
        self.fact_checker = fact_checker
        self.serper_searcher = serper_searcher
        self.groq_client = groq_client
        self.default_mode = default_mode if default_mode in {"offline", "online"} else "offline"

    def resolve_mode(self, requested_mode=None):
        if not requested_mode:
            return self.default_mode
        normalized = str(requested_mode).strip().lower()
        return normalized if normalized in {"offline", "online"} else self.default_mode

    def transcribe_audio(self, input_path, audio_data):
        transcript = ""

        if self.groq_client:
            try:
                print("Transcribing and translating with Groq Whisper...")
                with open(input_path, "rb") as file:
                    transcription = self.groq_client.audio.translations.create(
                        file=(input_path, file.read()),
                        model="whisper-large-v3",
                        response_format="text"
                    )
                transcript = str(transcription).strip()
            except Exception as error:
                print(f"Groq Transcription Error: {error}")
                print("Falling back to Vosk...")
                transcript = self.transcriber.transcribe_wav_bytes(audio_data)
        else:
            transcript = self.transcriber.transcribe_wav_bytes(audio_data)

        return transcript

    def clean_query(self, text):
        text = (text or "").strip()

        # If user provides a double-quoted claim, prefer that exact quoted proposition.
        quoted_chunks = re.findall(r'["\u201c\u201d]([^"\u201c\u201d]{8,})["\u201c\u201d]', text)
        if quoted_chunks:
            quoted_chunks.sort(key=lambda item: len(item.strip()), reverse=True)
            best = quoted_chunks[0].strip()
            if best:
                return best
        if self.groq_client and text:
            try:
                print("Refining query with Groq...")
                completion = self.groq_client.chat.completions.create(
                    model="llama-3.3-70b-versatile",
                    messages=[
                        {
                            "role": "system",
                            "content": "You are a query refiner for a fact-checking API. Extract the core factual claim from user speech. Remove filler words like 'I heard that', 'check if'. If non-English, translate to English. Return only the refined query."
                        },
                        {
                            "role": "user",
                            "content": text
                        }
                    ],
                    temperature=0.1,
                    max_tokens=100
                )
                refined_text = completion.choices[0].message.content.strip()
                if refined_text.startswith('"') and refined_text.endswith('"'):
                    refined_text = refined_text[1:-1]
                return refined_text
            except Exception as error:
                print(f"Groq Query Cleaner Error: {error}")

        while True:
            text_lower = text.lower()
            found = False
            fillers = [
                "i heard that", "i heard", "people say", "is it true that", "tell me if",
                "they say", "check if", "fact check", "can you tell me if", "did you know that",
                "rumor has it", "rumor says", "please check"
            ]
            for filler in fillers:
                if text_lower.startswith(filler):
                    text = text[len(filler):].strip()
                    found = True
                    break
            if not found:
                break
        return text

    def _format_factcheck_results(self, raw_results):
        formatted = []
        for result in raw_results:
            verdict = self._normalize_verdict(result.rating)

            formatted.append(
                {
                    "claim": result.claim,
                    "text": result.text,
                    "rating": result.rating,
                    "verdict": verdict,
                    "how_compared": "Compared directly with a published fact-check article from the listed source.",
                    "corrected_claim": result.claim,
                    "key_corrections": [],
                    "sources": [],
                    "publisher": result.publisher,
                    "url": result.url
                }
            )
        return formatted

    def _tokenize(self, text):
        text = (text or "").lower()
        words = re.findall(r"[a-z0-9]+", text)
        stop_words = {
            "the", "a", "an", "is", "are", "was", "were", "in", "on", "of", "to", "and", "or",
            "for", "with", "by", "that", "this", "it", "as", "at", "from", "be", "about", "into"
        }
        return {word for word in words if word not in stop_words and len(word) > 2}

    def _relevance_score(self, search_query, candidate_text):
        query_tokens = self._tokenize(search_query)
        candidate_tokens = self._tokenize(candidate_text)
        if not query_tokens or not candidate_tokens:
            return 0.0
        overlap = query_tokens.intersection(candidate_tokens)
        return len(overlap) / max(len(query_tokens), 1)

    def _select_relevant_factcheck_results(self, search_query, results, claim_country=None):
        if not results:
            return []

        # Detect if the user's claim is about a specific country
        if not claim_country:
            claim_country = self._extract_country_from_claim(search_query)

        scored = []
        for item in results:
            combined_text = f"{item.get('claim', '')} {item.get('text', '')} {item.get('publisher', '')}"
            score = self._relevance_score(search_query, combined_text)

            # Geographic mismatch penalty: if the user's claim is about a specific country
            # but the fact-check result is about a different country, penalize heavily
            if claim_country:
                result_country = self._extract_country_from_claim(combined_text)
                if result_country and result_country.lower() != claim_country.lower():
                    print(f"Geographic mismatch: claim about {claim_country}, result about {result_country} — penalizing")
                    score *= 0.2  # heavy penalty

            scored.append((score, item))

        scored.sort(key=lambda x: x[0], reverse=True)

        semantically_filtered = []
        for score, item in scored[:3]:
            if score < 0.12:
                continue
            if self._is_semantically_same_claim(
                query_claim=search_query,
                source_claim=item.get("claim", ""),
                source_text=item.get("text", "")
            ):
                semantically_filtered.append((score, item))

        if semantically_filtered:
            semantically_filtered.sort(key=lambda x: x[0], reverse=True)
            return [item for _, item in semantically_filtered[:2]]

        filtered = [item for score, item in scored if score >= 0.15][:2]
        if filtered:
            return filtered

        best_score, best_item = scored[0]
        if best_score >= 0.12:
            return [best_item]

        # If best score is very low (e.g. after geographic penalty), return empty
        # so the pipeline falls through to AI analysis with web evidence
        if best_score < 0.10:
            return []

        return [best_item]

    def _is_semantically_same_claim(self, query_claim, source_claim, source_text):
        query_claim = (query_claim or "").strip()
        source_claim = (source_claim or "").strip()
        source_text = (source_text or "").strip()

        if not query_claim:
            return False

        if not self.groq_client:
            query_tokens = self._tokenize(query_claim)
            source_tokens = self._tokenize(f"{source_claim} {source_text}")
            if not query_tokens or not source_tokens:
                return False
            overlap = len(query_tokens.intersection(source_tokens)) / max(len(query_tokens), 1)
            return overlap >= 0.35

        try:
            completion = self.groq_client.chat.completions.create(
                model="llama-3.3-70b-versatile",
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "You are a strict claim-matching judge. Determine whether a fact-check article is about the SAME factual proposition AND the SAME country/jurisdiction as the user's claim. "
                            "If the geographic context or country differs between the user's claim and the fact-check article, return false. "
                            "If it only shares people/places but addresses a different proposition, return false. "
                            "Return strict JSON only: {\"same_claim\": true|false, \"reason\": \"short\"}."
                        )
                    },
                    {
                        "role": "user",
                        "content": (
                            f"User claim: {query_claim}\n"
                            f"Fact-check claim: {source_claim}\n"
                            f"Fact-check title/text: {source_text}\n"
                        )
                    }
                ],
                temperature=0.0,
                max_tokens=120
            )
            raw = completion.choices[0].message.content.strip()
            parsed = self._extract_json_block(raw)
            if parsed and isinstance(parsed.get("same_claim"), bool):
                return parsed.get("same_claim")
            return False
        except Exception as error:
            print(f"Semantic claim match failed: {error}")
            return False

    def _precheck_and_correct_claim(self, claim_text):
        claim_text = (claim_text or "").strip()
        if not claim_text:
            return {
                "original_claim": "",
                "corrected_claim": "",
                "key_corrections": []
            }

        if not self.groq_client:
            return {
                "original_claim": claim_text,
                "corrected_claim": claim_text,
                "key_corrections": []
            }

        try:
            completion = self.groq_client.chat.completions.create(
                model="llama-3.3-70b-versatile",
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "You are a claim normalizer for factual precision. "
                            "Validate factual framing before research: entity role/title, office or institution, "
                            "location or jurisdiction, date/time period, and numeric units. "
                            "Apply minimal edits only; preserve the claim's original intent. "
                            "Never replace a stated number with vague wording like 'unknown number' unless the user already said it is unknown. "
                            "Do not add speculative facts. "
                            "Do not add new countries, nationalities, people, or organizations unless explicitly present in the claim text itself. "
                            "Return strict JSON only with fields: corrected_claim, key_corrections. "
                            "key_corrections must be an array of short, concrete strings. "
                            "If no correction is needed, return the original claim and an empty array."
                        )
                    },
                    {
                        "role": "user",
                        "content": (
                            f"Claim: {claim_text}\n"
                            "Return JSON only. Example: "
                            "{\"corrected_claim\":\"<minimally corrected claim>\","
                            "\"key_corrections\":[\"Entity role corrected\"]}"
                        )
                    }
                ],
                temperature=0.0,
                max_tokens=180
            )

            raw_text = completion.choices[0].message.content.strip()
            parsed = self._extract_json_block(raw_text)

            if parsed:
                corrected_claim = (parsed.get("corrected_claim") or claim_text).strip()
                key_corrections = parsed.get("key_corrections", [])
                if not isinstance(key_corrections, list):
                    key_corrections = [str(key_corrections)]

                if self._has_numeric_value(claim_text) and not self._has_numeric_value(corrected_claim):
                    corrected_claim = claim_text
                    key_corrections.append("Numeric value preserved from original claim")
            else:
                corrected_claim = claim_text
                key_corrections = []

            return {
                "original_claim": claim_text,
                "corrected_claim": corrected_claim,
                "key_corrections": key_corrections
            }
        except Exception as error:
            print(f"Precheck correction failed: {error}")
            return {
                "original_claim": claim_text,
                "corrected_claim": claim_text,
                "key_corrections": []
            }

    def _normalize_verdict(self, value):
        lowered = (value or "").strip().lower()
        if not lowered:
            return "Unverified"

        if "not true" in lowered or "not correct" in lowered or "no evidence" in lowered:
            return "False"

        tokens = set(re.findall(r"[a-z]+", lowered))

        if "incorrect" in tokens or "wrong" in tokens or "false" in tokens:
            return "False"
        if "misleading" in lowered or "partly" in lowered or "partially" in lowered or "mixed" in lowered:
            return "Partially Correct"
        if lowered in {"true", "correct", "mostly true"}:
            return "Correct"
        if lowered in {"false", "incorrect", "mostly false"}:
            return "False"
        if lowered in {"partial", "partially correct", "partly true", "mixed", "half true", "half-true"}:
            return "Partially Correct"
        if lowered in {"unverified", "unknown", "not enough evidence"}:
            return "Unverified"
        if "false" in lowered or "incorrect" in lowered or "wrong" in lowered:
            return "False"
        if "true" in tokens or "correct" in tokens:
            return "Correct"
        if "mix" in lowered or "partial" in lowered or "half" in lowered:
            return "Partially Correct"
        return "Unverified"

    def _result_confidence(self, item):
        verdict = (item.get("verdict") or "").strip()
        if verdict == "False":
            return 4
        if verdict == "Partially Correct":
            return 3
        if verdict == "Correct":
            return 2
        return 1

    def _dedupe_results(self, results):
        deduped = {}
        for item in results:
            publisher = (item.get("publisher") or "").strip().lower()
            claim = (item.get("claim") or "").strip().lower()
            url = (item.get("url") or "").strip().lower()
            key = f"{publisher}|{url}" if url else f"{publisher}|{claim}"

            existing = deduped.get(key)
            if not existing or self._result_confidence(item) > self._result_confidence(existing):
                deduped[key] = item

        ranked = list(deduped.values())
        ranked.sort(key=self._result_confidence, reverse=True)
        return ranked

    def _derive_final_verdict(self, results):
        if not results:
            return "Unverified", "No matching evidence found."

        verdicts = [item.get("verdict", "Unverified") for item in results]
        unique_verdicts = sorted(set(verdicts))

        if len(unique_verdicts) == 1:
            return unique_verdicts[0], f"Based on {len(results)} matching source(s)."

        non_unverified = [value for value in verdicts if value != "Unverified"]
        if non_unverified:
            strongest = sorted(non_unverified, key=lambda value: {
                "False": 4,
                "Partially Correct": 3,
                "Correct": 2
            }.get(value, 1), reverse=True)[0]
            if all(value in {strongest, "Unverified"} for value in verdicts):
                return strongest, "Primary verdict selected from strongest matching evidence; weaker entries were unverified."

        return "Unverified", "Conflicting verdicts across matched sources."

    def _build_evidence_sources(self, web_results):
        sources = []
        for item in web_results[:10]:
            sources.append(
                {
                    "title": item.get("title", ""),
                    "url": item.get("url", "")
                }
            )
        return sources

    def _extract_json_block(self, text):
        if not text:
            return None
        block_match = re.search(r"\{.*\}", text, re.DOTALL)
        if not block_match:
            return None
        try:
            return json.loads(block_match.group(0))
        except Exception:
            return None

    def _has_numeric_value(self, text):
        return bool(re.search(r"\d", text or ""))

    def _build_search_queries(self, search_query):
        base = (search_query or "").strip()
        if not base:
            return []

        queries = [base]
        lowered = base.lower()
        migration_terms = {
            "emigrants": "out-migration",
            "emigrant": "out-migration",
            "emigration": "out-migration",
            "emigrated": "out-migration",
            "immigrants": "in-migration",
            "immigrant": "in-migration",
            "immigration": "in-migration",
            "immigrated": "in-migration",
            "migration": "net migration"
        }

        for term, replacement in migration_terms.items():
            if term in lowered:
                queries.append(re.sub(term, replacement, base, flags=re.IGNORECASE))
                break

        if any(token in lowered for token in ["migration", "emigration", "emigrants", "emigrated", "immigration", "immigrants", "immigrated"]):
            queries.append(f"{base} site:data.unhcr.org")
            queries.append(f"{base} site:oecd.org")

        unique = []
        seen = set()
        for item in queries:
            key = item.strip().lower()
            if key and key not in seen:
                seen.add(key)
                unique.append(item.strip())
        return unique[:5]

    def _infer_search_locale(self, search_query):
        lowered = (search_query or "").lower()
        country_map = {
            ("ireland", "irish"): ("ie", "en"),
            ("romania", "romanian"): ("ro", "en"),
            ("denmark", "danish"): ("dk", "en"),
            ("germany", "german"): ("de", "en"),
            ("france", "french"): ("fr", "en"),
            ("italy", "italian"): ("it", "en"),
            ("spain", "spanish"): ("es", "en"),
            ("sweden", "swedish"): ("se", "en"),
            ("norway", "norwegian"): ("no", "en"),
            ("netherlands", "dutch"): ("nl", "en"),
            ("poland", "polish"): ("pl", "en"),
            ("portugal", "portuguese"): ("pt", "en"),
            ("greece", "greek"): ("gr", "en"),
            ("belgium", "belgian"): ("be", "en"),
            ("austria", "austrian"): ("at", "en"),
            ("hungary", "hungarian"): ("hu", "en"),
            ("finland", "finnish"): ("fi", "en"),
            ("uk", "united kingdom", "british", "britain"): ("gb", "en"),
            ("canada", "canadian"): ("ca", "en"),
            ("australia", "australian"): ("au", "en"),
            ("india", "indian"): ("in", "en"),
            ("brazil", "brazilian"): ("br", "en"),
            ("mexico", "mexican"): ("mx", "en"),
            ("japan", "japanese"): ("jp", "en"),
            ("south korea", "korean"): ("kr", "en"),
            ("china", "chinese"): ("cn", "en"),
            ("turkey", "turkish"): ("tr", "en"),
            ("south africa",): ("za", "en"),
        }
        for keywords, locale in country_map.items():
            if any(kw in lowered for kw in keywords):
                return locale
        return "us", "en"

    def _extract_country_from_claim(self, claim_text):
        """Return the country name mentioned in the claim, or None."""
        lowered = (claim_text or "").lower()
        countries = [
            "ireland", "romania", "denmark", "germany", "france", "italy", "spain",
            "sweden", "norway", "netherlands", "poland", "portugal", "greece",
            "belgium", "austria", "hungary", "finland", "united kingdom", "uk",
            "canada", "australia", "india", "brazil", "mexico", "japan",
            "south korea", "china", "turkey", "south africa",
        ]
        demonyms = {
            "irish": "Ireland", "romanian": "Romania", "danish": "Denmark",
            "german": "Germany", "french": "France", "italian": "Italy",
            "spanish": "Spain", "swedish": "Sweden", "norwegian": "Norway",
            "dutch": "Netherlands", "polish": "Poland", "portuguese": "Portugal",
            "greek": "Greece", "belgian": "Belgium", "austrian": "Austria",
            "hungarian": "Hungary", "finnish": "Finland", "british": "United Kingdom",
            "canadian": "Canada", "australian": "Australia", "indian": "India",
            "brazilian": "Brazil", "mexican": "Mexico", "japanese": "Japan",
            "korean": "South Korea", "chinese": "China", "turkish": "Turkey",
        }
        for country in countries:
            if country in lowered:
                return country.title()
        for demonym, country in demonyms.items():
            if demonym in lowered:
                return country
        return None

    def _domain_boost_score(self, url):
        normalized = (url or "").lower()
        boosts = {
            "data.unhcr.org": 0.20,
            "unhcr.org": 0.18,
            "oecd.org": 0.15,
            "europa.eu": 0.12,
            "worldbank.org": 0.12
        }
        for domain, boost in boosts.items():
            if domain in normalized:
                return boost
        return 0.0

    def _rank_live_results(self, search_query, results):
        if not results:
            return []

        query_numbers = set(re.findall(r"\d+", search_query or ""))
        scored = []
        for item in results:
            title = item.get("title", "")
            snippet = item.get("snippet", "")
            url = item.get("url", "")
            combined = f"{title} {snippet}"
            score = self._relevance_score(search_query, combined)
            score += self._domain_boost_score(url)

            if query_numbers:
                snippet_numbers = set(re.findall(r"\d+", combined))
                if query_numbers.intersection(snippet_numbers):
                    score += 0.10

            scored.append((score, item))

        scored.sort(key=lambda x: x[0], reverse=True)
        return [item for _, item in scored[:10]]

    def _generate_ai_overview(self, original_claim, search_query, web_results):
        if not self.groq_client or not web_results:
            return None

        today = date.today().strftime("%B %d, %Y")
        chunks = []
        for index, item in enumerate(web_results[:10], start=1):
            chunks.append(
                f"[{index}] Title: {item.get('title', '')}\n"
                f"Snippet: {item.get('snippet', '')}\n"
                f"URL: {item.get('url', '')}"
            )
        evidence_text = "\n\n".join(chunks)

        try:
            completion = self.groq_client.chat.completions.create(
                model="llama-3.3-70b-versatile",
                messages=[
                    {
                        "role": "system",
                        "content": (
                            f"You are a data-extraction assistant. Today is {today}. "
                            "Given an ORIGINAL factual claim and web search snippets, extract the ACTUAL data relevant to the claim. "
                            "Focus on finding real numbers, dates, names, and official figures from the snippets. "
                            "Then compare what the ORIGINAL claim states against the actual data you found. "
                            "IMPORTANT: Your verdict must reflect whether the ORIGINAL claim is correct or false. "
                            "If the original claim says X but reality is Y, the verdict is False — even if a corrected version was provided. "
                            "The 'Refined claim' is only provided as context showing what corrections were needed; do NOT verify the refined claim. "
                            "Return strict JSON only with fields: "
                            "actual_data (string, 1-3 sentences summarizing the real data found), "
                            "claimed_value (string, what the ORIGINAL claim states), "
                            "actual_value (string, what the evidence shows), "
                            "data_sources (array of strings, which snippet indexes like [1], [3] contained the data), "
                            "assessment (string, 1 sentence: how the ORIGINAL claimed value compares to actual data), "
                            "verdict (Correct, False, Partially Correct, or Unverified). "
                            "Be precise with numbers and units. If no relevant data is found, set verdict to Unverified."
                        )
                    },
                    {
                        "role": "user",
                        "content": (
                            f"Claim to verify: {original_claim}\n"
                            f"Refined claim: {search_query}\n\n"
                            f"Web evidence:\n{evidence_text}\n\n"
                            "Extract real data from snippets, compare to the claim, and return strict JSON only."
                        )
                    }
                ],
                temperature=0.0,
                max_tokens=350
            )
            raw = completion.choices[0].message.content.strip()
            parsed = self._extract_json_block(raw)
            if parsed and parsed.get("actual_data"):
                return {
                    "actual_data": parsed.get("actual_data", ""),
                    "claimed_value": parsed.get("claimed_value", ""),
                    "actual_value": parsed.get("actual_value", ""),
                    "data_sources": parsed.get("data_sources", []),
                    "assessment": parsed.get("assessment", ""),
                    "verdict": self._normalize_verdict(parsed.get("verdict", "Unverified"))
                }
            return None
        except Exception as error:
            print(f"AI Overview generation failed: {error}")
            return None

    def _collect_live_evidence(self, search_query):
        queries = self._build_search_queries(search_query)
        if not queries:
            return []

        gl, hl = self._infer_search_locale(search_query)
        collected = []
        seen_urls = set()

        for query in queries:
            batch = self.serper_searcher.search_web(query, num_results=6, gl=gl, hl=hl)
            for item in batch:
                url = (item.get("url") or "").strip().lower()
                if url and url in seen_urls:
                    continue
                if url:
                    seen_urls.add(url)
                collected.append(item)

        return self._rank_live_results(search_query, collected)

    def _analyze_with_ai(self, original_claim, search_query, mode, web_results=None, precheck_corrections=None):
        if not self.groq_client:
            return None

        if precheck_corrections is None:
            precheck_corrections = []

        today = date.today().strftime("%B %d, %Y")
        live_context = ""

        if web_results:
            chunks = []
            for index, item in enumerate(web_results[:10], start=1):
                chunks.append(
                    f"[{index}] Title: {item.get('title', '')}\n"
                    f"Snippet: {item.get('snippet', '')}\n"
                    f"URL: {item.get('url', '')}"
                )
            live_context = "\n\n".join(chunks)

        if mode == "online" and live_context:
            system_prompt = (
                f"You are a fact-check assistant. Today is {today}. "
                "You are given live web snippets. Use only these snippets as evidence. "
                "IMPORTANT: Your verdict must reflect whether the ORIGINAL claim is correct or false. "
                "The 'Corrected claim for research' is context showing what corrections were needed — do NOT verify the corrected claim. "
                "If the original claim states something false but the correction fixes it, the verdict for the ORIGINAL claim is False. "
                "First, validate factual framing: entity role/title, office or institution, "
                "location/jurisdiction, date/time period, and numeric values/units. "
                "If any framing error exists, produce a minimally corrected claim and list each correction. "
                "If evidence is conflicting or insufficient, choose Unverified. "
                "Return VALID JSON only with fields: verdict, corrected_claim, key_corrections, summary, how_compared. "
                "Allowed verdict values: Correct, False, Partially Correct, Unverified. "
                "summary must be 1-2 sentences, factual, and <= 45 words. "
                "how_compared must be <= 35 words and reference evidence indexes like [1], [2] when relevant."
            )
            user_prompt = (
                f"Original claim: {original_claim}\n"
                f"Corrected claim for research: {search_query}\n"
                f"Precheck corrections: {precheck_corrections}\n\n"
                f"Evidence:\n{live_context}\n\n"
                "Your response must be strict JSON only. "
                "Example: {\"verdict\":\"False\",\"corrected_claim\":\"The claim corrected for factual framing\","
                "\"key_corrections\":[\"Date corrected\",\"Unit normalized\"],\"summary\":\"...\",\"how_compared\":\"...\"}. "
                "Do not use markdown, code fences, or extra keys. key_corrections must contain at most 4 items."
            )
            publisher = "Llama 3 (Groq) + Serper Live"
            rating = "AI Research"
        else:
            system_prompt = (
                f"You are a fact-checking assistant. Today is {today}. "
                "Analyze using your internal knowledge only. "
                "If live web search is unavailable, explicitly say that. "
                "IMPORTANT: Your verdict must reflect whether the ORIGINAL claim is correct or false. "
                "The 'Corrected claim for research' is context showing what corrections were needed — do NOT verify the corrected claim. "
                "If the original claim states something false but the correction fixes it, the verdict for the ORIGINAL claim is False. "
                "First, validate factual framing: entity role/title, office or institution, "
                "location/jurisdiction, date/time period, and numeric values/units. "
                "If any framing error exists, produce a minimally corrected claim and list each correction. "
                "When confidence is limited without live evidence, prefer Unverified over overconfident verdicts. "
                "Return VALID JSON only with fields: verdict, corrected_claim, key_corrections, summary, how_compared. "
                "Allowed verdict values: Correct, False, Partially Correct, Unverified. "
                "summary must be 1-2 sentences, factual, and <= 45 words. "
                "how_compared must be <= 35 words and explicitly note the no-live-search limitation."
            )
            user_prompt = (
                f"Original claim: {original_claim}\n"
                f"Corrected claim for research: {search_query}\n"
                f"Precheck corrections: {precheck_corrections}\n"
                "Analyze this claim using internal knowledge only.\n"
                "Return strict JSON only. Example: "
                "{\"verdict\":\"Unverified\",\"corrected_claim\":\"...\",\"key_corrections\":[],\"summary\":\"...\",\"how_compared\":\"...\"}. "
                "Do not use markdown, code fences, or extra keys. key_corrections must contain at most 4 items."
            )
            publisher = "Llama 3 (Groq)"
            rating = "AI Analysis"

        try:
            completion = self.groq_client.chat.completions.create(
                model="llama-3.3-70b-versatile",
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                temperature=0.1,
                max_tokens=220
            )
            raw_text = completion.choices[0].message.content.strip()
            parsed = self._extract_json_block(raw_text)

            if parsed:
                verdict = self._normalize_verdict(parsed.get("verdict"))
                summary = parsed.get("summary", raw_text)
                how_compared = parsed.get("how_compared", "Compared claim against available evidence and generated a verdict.")
                corrected_claim = parsed.get("corrected_claim", search_query)
                key_corrections = parsed.get("key_corrections", [])
                if not isinstance(key_corrections, list):
                    key_corrections = [str(key_corrections)]
            else:
                verdict = self._normalize_verdict(raw_text)
                summary = raw_text
                how_compared = "Compared claim against available evidence and generated a verdict."
                corrected_claim = search_query
                key_corrections = []

            evidence_sources = self._build_evidence_sources(web_results or [])
            return {
                "claim": original_claim,
                "corrected_claim": corrected_claim,
                "key_corrections": key_corrections,
                "text": summary,
                "rating": rating,
                "verdict": verdict,
                "how_compared": how_compared,
                "sources": evidence_sources,
                "publisher": publisher,
                "url": "#"
            }
        except Exception as error:
            print(f"AI Analysis Failed: {error}")
            return {
                "claim": original_claim,
                "corrected_claim": search_query,
                "key_corrections": [],
                "text": f"Error detail: {str(error)}",
                "rating": "System Error",
                "verdict": "Unverified",
                "how_compared": "Could not complete AI comparison due to a system error.",
                "sources": [],
                "publisher": "Debug",
                "url": "#"
            }

    def process_claim_from_audio(self, input_path, audio_data, requested_mode=None):
        mode = self.resolve_mode(requested_mode)
        transcript = self.transcribe_audio(input_path, audio_data)

        # Extract country from the ORIGINAL transcript BEFORE clean_query strips it
        claim_country = self._extract_country_from_claim(transcript)

        initial_query = self.clean_query(transcript)

        # If country was in the original but got lost during cleaning, re-add it
        if claim_country and not self._extract_country_from_claim(initial_query):
            initial_query = f"In {claim_country}, {initial_query}"
            print(f"Re-injected country context: '{claim_country}' into cleaned query")

        precheck = self._precheck_and_correct_claim(initial_query)
        search_query = precheck["corrected_claim"]
        gl, hl = self._infer_search_locale(search_query if self._extract_country_from_claim(search_query) else transcript)
        fc_lang = "en"
        print(
            f"Original: '{transcript}', Cleaned: '{initial_query}', "
            f"Corrected for research: '{search_query}', Mode: {mode}, Locale: {gl}/{hl}, Country: {claim_country}"
        )

        results = []
        if search_query.strip():
            raw_results = self.fact_checker.search_claims(initial_query, language_code=fc_lang)
            if not raw_results and initial_query.strip().lower() != search_query.strip().lower():
                raw_results = self.fact_checker.search_claims(search_query, language_code=fc_lang)
            results = self._format_factcheck_results(raw_results)
            results = self._select_relevant_factcheck_results(search_query, results, claim_country=claim_country)
            results = self._dedupe_results(results)

            if results:
                for item in results:
                    item["corrected_claim"] = precheck["corrected_claim"]
                    item["key_corrections"] = precheck["key_corrections"]

            if not results:
                live_results = []
                if mode == "online":
                    live_results = self._collect_live_evidence(search_query)

                ai_overview = None
                if live_results:
                    ai_overview = self._generate_ai_overview(
                        original_claim=precheck["original_claim"],
                        search_query=search_query,
                        web_results=live_results,
                    )

                ai_result = self._analyze_with_ai(
                    original_claim=precheck["original_claim"],
                    search_query=search_query,
                    mode=mode,
                    web_results=live_results,
                    precheck_corrections=precheck["key_corrections"],
                )
                if ai_result:
                    if ai_overview:
                        ai_result["verdict"] = ai_overview["verdict"]
                        assessment = ai_overview.get("assessment", "")
                        actual_data = ai_overview.get("actual_data", "")
                        if assessment:
                            ai_result["how_compared"] = assessment
                        if actual_data:
                            ai_result["text"] = actual_data
                    results.append(ai_result)

        final_verdict, final_verdict_note = self._derive_final_verdict(results)

        return {
            "transcript": transcript,
            "search_query": search_query,
            "original_query": precheck["original_claim"],
            "key_corrections": precheck["key_corrections"],
            "results": results,
            "final_verdict": final_verdict,
            "final_verdict_note": final_verdict_note,
            "mode": mode
        }

    def process_claim_from_text(self, claim_text, requested_mode=None):
        mode = self.resolve_mode(requested_mode)
        transcript = (claim_text or "").strip()

        # Extract country from the ORIGINAL transcript BEFORE clean_query strips it
        claim_country = self._extract_country_from_claim(transcript)

        initial_query = self.clean_query(transcript)

        # If country was in the original but got lost during cleaning, re-add it
        if claim_country and not self._extract_country_from_claim(initial_query):
            initial_query = f"In {claim_country}, {initial_query}"
            print(f"Re-injected country context: '{claim_country}' into cleaned query")

        precheck = self._precheck_and_correct_claim(initial_query)
        search_query = precheck["corrected_claim"]
        gl, hl = self._infer_search_locale(search_query if self._extract_country_from_claim(search_query) else transcript)
        fc_lang = "en"
        print(
            f"Original text: '{transcript}', Cleaned: '{initial_query}', "
            f"Corrected for research: '{search_query}', Mode: {mode}, Locale: {gl}/{hl}, Country: {claim_country}"
        )

        results = []
        if search_query.strip():
            raw_results = self.fact_checker.search_claims(initial_query, language_code=fc_lang)
            if not raw_results and initial_query.strip().lower() != search_query.strip().lower():
                raw_results = self.fact_checker.search_claims(search_query, language_code=fc_lang)
            results = self._format_factcheck_results(raw_results)
            results = self._select_relevant_factcheck_results(search_query, results, claim_country=claim_country)
            results = self._dedupe_results(results)

            if results:
                for item in results:
                    item["corrected_claim"] = precheck["corrected_claim"]
                    item["key_corrections"] = precheck["key_corrections"]

            if not results:
                live_results = []
                if mode == "online":
                    live_results = self._collect_live_evidence(search_query)

                ai_overview = None
                if live_results:
                    ai_overview = self._generate_ai_overview(
                        original_claim=precheck["original_claim"],
                        search_query=search_query,
                        web_results=live_results,
                    )

                ai_result = self._analyze_with_ai(
                    original_claim=precheck["original_claim"],
                    search_query=search_query,
                    mode=mode,
                    web_results=live_results,
                    precheck_corrections=precheck["key_corrections"],
                )
                if ai_result:
                    if ai_overview:
                        ai_result["verdict"] = ai_overview["verdict"]
                        assessment = ai_overview.get("assessment", "")
                        actual_data = ai_overview.get("actual_data", "")
                        if assessment:
                            ai_result["how_compared"] = assessment
                        if actual_data:
                            ai_result["text"] = actual_data
                    results.append(ai_result)

        final_verdict, final_verdict_note = self._derive_final_verdict(results)

        return {
            "transcript": transcript,
            "search_query": search_query,
            "original_query": precheck["original_claim"],
            "key_corrections": precheck["key_corrections"],
            "results": results,
            "final_verdict": final_verdict,
            "final_verdict_note": final_verdict_note,
            "mode": mode
        }
