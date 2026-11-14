"""Article reader: URL -> clean article text, with free tools only (requests + BeautifulSoup).

Standalone: it does not import news_scraper. news_scraper uses it only when run with --read-articles.

    from article_reader import read_article
    r = read_article("https://...")      # r.status, r.text, r.final_url, r.title, r.published
"""
from .reader import ReadResult, read_article

__all__ = ["read_article", "ReadResult"]
