import pytest
from fastapi.testclient import TestClient
from api import app
from db import DatabaseManager
from rss_scraper import FullyHardenedScraper

client = TestClient(app)

def test_health_check():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "healthy"

def test_asset_packaging_with_legal():
    payload = {
        "asset_name": "Async Redis Connection Pool",
        "category": "backend_module",
        "description": "High-throughput Redis connection pool manager for FastAPI serverless deployments.",
        "source_code": "class RedisPool: pass",
    }
    response = client.post("/v1/assets/package", json=payload)
    assert response.status_code == 201
    data = response.json()
    assert data["status"] == "packaged_ready"
    assert "privacy_policy" in data["legal_documents"]
    assert "terms_of_service" in data["legal_documents"]

def test_scraper_rss_normalization(tmp_path):
    db = DatabaseManager(str(tmp_path / "t.db"))
    scraper = FullyHardenedScraper(db)
    xml = """<?xml version="1.0"?><rss><channel><item><title>Test & Normalization</title><link>https://example.com</link><pubDate>Wed, 14 Oct 2026 12:00:00 GMT</pubDate><author>Hardened Author</author></item></channel></rss>"""
    assert scraper._parse_and_store_feed_hardened("Test Source", xml) == 1
    items = db.get_recent_pain_points(1)
    assert items[0]["author"] == "Hardened Author"
    assert items[0]["title"] == "Test & Normalization"
    assert items[0]["source_url"] == "https://example.com"
    assert "2026-10-14" in items[0]["detected_at"]

def test_scraper_atom_and_dedup(tmp_path):
    db = DatabaseManager(str(tmp_path / "t.db"))
    scraper = FullyHardenedScraper(db)
    xml = """<feed xmlns="http://www.w3.org/2005/Atom"><entry><title>Atom Item</title><link href="https://a.example/1"/><updated>2026-10-14T12:00:00Z</updated><author><name>Atom Author</name></author></entry></feed>"""
    scraper._parse_and_store_feed_hardened("Atom", xml)
    scraper._parse_and_store_feed_hardened("Atom", xml)
    items = db.get_recent_pain_points(10)
    assert len(items) == 1
    assert items[0]["author"] == "Atom Author"
    assert items[0]["source_url"] == "https://a.example/1"
