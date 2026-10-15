import asyncio
import logging
import re
import xml.etree.ElementTree as ET
import httpx
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from db import DatabaseManager

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("fully_hardened_scraper")

ATOM = "{http://www.w3.org/2005/Atom}"
DC = "{http://purl.org/dc/elements/1.1/}"

def _now() -> str:
    return datetime.now(timezone.utc).isoformat()

def _first(item: ET.Element, *paths: str):
    for p in paths:
        el = item.find(p)
        if el is not None:
            return el
    return None

class FullyHardenedScraper:
    FEEDS = {
        "GitHub Issues": "https://github.com/trending/developers?format=atom",
        "StackOverflow": "https://stackoverflow.com/feeds/tag?tagnames=python&sort=newest",
        "HackerNews": "https://hnrss.org/newest?points=50",
        "Reddit Programming": "https://www.reddit.com/r/programming/new/.rss",
        "Lobsters": "https://lobste.rs/rss",
    }

    def __init__(self, db: DatabaseManager, interval_seconds: int = 300):
        self.db = db
        self.interval_seconds = interval_seconds
        self._running = False
        self._task = None

    async def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._run_loop())
        logger.info("Fully Hardened Scraper started.")

    async def stop(self) -> None:
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("Fully Hardened Scraper stopped.")

    async def _run_loop(self) -> None:
        while self._running:
            try:
                await self.poll_all_feeds()
            except Exception as e:
                logger.error(f"Error in RSS scraping cycle: {str(e)}", exc_info=True)
            await asyncio.sleep(self.interval_seconds)

    async def poll_all_feeds(self) -> int:
        total_ingested = 0
        headers = {"User-Agent": "Pain2AssetForge/4.0 (HardenedMonitor)"}
        async with httpx.AsyncClient(timeout=15.0, headers=headers, follow_redirects=True) as client:
            for source_name, feed_url in self.FEEDS.items():
                try:
                    resp = await client.get(feed_url)
                    if resp.status_code == 200:
                        total_ingested += await asyncio.to_thread(
                            self._parse_and_store_feed_hardened, source_name, resp.text
                        )
                    else:
                        logger.warning(f"Feed [{source_name}] returned HTTP {resp.status_code}")
                except Exception as e:
                    logger.warning(f"Feed fetch warning [{source_name}]: {str(e)}")
        logger.info(f"Ingestion cycle complete. Successfully ingested {total_ingested} normalized items.")
        return total_ingested

    def _sanitize_xml(self, raw_xml: str) -> str:
        return re.sub(r'&(?!amp;|lt;|gt;|quot;|apos;|#\d+;|#x[0-9a-fA-F]+;)', '&amp;', raw_xml)

    def _normalize_datetime(self, raw_date_str: str) -> str:
        if not raw_date_str:
            return _now()
        try:
            return parsedate_to_datetime(raw_date_str).isoformat()
        except Exception:
            try:
                return datetime.fromisoformat(raw_date_str.replace('Z', '+00:00')).isoformat()
            except Exception:
                return _now()

    def _parse_and_store_feed_hardened(self, source_name: str, raw_content: str) -> int:
        count = 0
        clean_xml = self._sanitize_xml(raw_content)
        # ET.fromstring rejects str input carrying an encoding declaration
        clean_xml = re.sub(r'^\s*<\?xml[^>]*\?>', '', clean_xml)
        try:
            root = ET.fromstring(clean_xml)
            items = root.findall(".//item") or root.findall(f".//{ATOM}entry")
            for item in items[:5]:
                title_elem = _first(item, "title", f"{ATOM}title")
                link_elem = _first(item, "link", f"{ATOM}link")
                date_elem = _first(item, "pubDate", f"{ATOM}updated", "date")
                author_elem = _first(item, "author", f"{ATOM}author/{ATOM}name", "creator", f"{DC}creator")

                title = title_elem.text.strip() if title_elem is not None and title_elem.text else "Untitled Issue"
                url = "https://developer.source"
                if link_elem is not None:
                    url = (link_elem.text or "").strip() or link_elem.attrib.get("href", url)
                raw_date = date_elem.text.strip() if date_elem is not None and date_elem.text else ""
                detected_at = self._normalize_datetime(raw_date)
                author = author_elem.text.strip() if author_elem is not None and author_elem.text else f"Contributor ({source_name})"

                desc = f"Developer friction point from {source_name}: {title}"
                self.db.save_pain_point(source_name, url, title, desc, author, "HIGH", detected_at)
                count += 1
        except ET.ParseError:
            titles = re.findall(r'<title>(.*?)</title>', raw_content, re.IGNORECASE)
            dates = re.findall(r'<(?:pubDate|updated|date)>(.*?)</(?:pubDate|updated|date)>', raw_content, re.IGNORECASE)
            authors = re.findall(r'<(?:author|creator|name)>(.*?)</(?:author|creator|name)>', raw_content, re.IGNORECASE)

            for i, t in enumerate(titles[:5]):
                clean_title = re.sub(r'<.*?>', '', t).strip()
                if clean_title and clean_title != "RSS Feed":
                    fallback_date = self._normalize_datetime(dates[i] if i < len(dates) else "")
                    fallback_author = authors[i] if i < len(authors) else f"Contributor ({source_name})"
                    clean_author = re.sub(r'<.*?>', '', fallback_author).strip()
                    self.db.save_pain_point(
                        source_name,
                        "https://fallback.source",
                        clean_title,
                        f"Extracted via fallback parser from {source_name}",
                        clean_author,
                        "HIGH",
                        fallback_date,
                    )
                    count += 1
        except Exception as e:
            logger.error(f"Unexpected error parsing feed [{source_name}]: {str(e)}")
        return count
