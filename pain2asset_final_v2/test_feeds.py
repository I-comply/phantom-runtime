from db import DatabaseManager
from rss_scraper import FullyHardenedScraper

SO_ATOM = (
    '<?xml version="1.0" encoding="utf-8"?>'
    '<feed xmlns="http://www.w3.org/2005/Atom"><entry>'
    "<id>https://stackoverflow.com/q/1</id>"
    '<title type="text">Docker build fails &amp; hangs</title>'
    "<author><name>asker</name></author>"
    '<link rel="alternate" href="https://stackoverflow.com/questions/1"/>'
    "<updated>2026-10-14T11:00:00Z</updated>"
    "</entry></feed>"
)


def test_feed_registry_valid():
    feeds = FullyHardenedScraper.FEEDS
    assert "GitHub Issues" not in feeds
    assert all(u.startswith("https://") for u in feeds.values())
    assert len(set(feeds.values())) == len(feeds)


def test_stackoverflow_atom_sample(tmp_path):
    db = DatabaseManager(str(tmp_path / "t.db"))
    scraper = FullyHardenedScraper(db)
    assert scraper._parse_and_store_feed_hardened("StackOverflow DevOps", SO_ATOM) == 1
    row = db.get_recent_pain_points(1)[0]
    assert row["title"] == "Docker build fails & hangs"
    assert row["author"] == "asker"
    assert row["source_url"] == "https://stackoverflow.com/questions/1"
