import html
import os
import re
import time
from datetime import datetime
from email.utils import parsedate_to_datetime
from typing import Dict, List, Optional

import google.generativeai as genai
import pandas as pd
import requests
from bs4 import BeautifulSoup

EXCLUDE_PUBLISHERS: List[str] = []
EXCLUDE_REPORTERS: List[str] = []

SEARCH_QUERY = "부동산 전망"
TARGET_ARTICLE_COUNT = 30
DISPLAY_PER_REQUEST = 100
CSV_PATH = "news_data.csv"
NAVER_API_URL = "https://openapi.naver.com/v1/search/news.json"


def _clean_text(value: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(value or "")).strip()


def _strip_html(value: str) -> str:
    if not value:
        return ""
    soup = BeautifulSoup(value, "html.parser")
    return _clean_text(soup.get_text(" "))


def _parse_pub_date(value: str) -> str:
    try:
        dt = parsedate_to_datetime(value)
        return dt.isoformat()
    except Exception:
        return datetime.now().isoformat()


def fetch_news_page(start: int, display: int = DISPLAY_PER_REQUEST) -> List[Dict]:
    client_id = os.getenv("NAVER_CLIENT_ID")
    client_secret = os.getenv("NAVER_CLIENT_SECRET")
    if not client_id or not client_secret:
        raise EnvironmentError("NAVER_CLIENT_ID 또는 NAVER_CLIENT_SECRET 환경변수가 필요합니다.")

    headers = {
        "X-Naver-Client-Id": client_id,
        "X-Naver-Client-Secret": client_secret,
    }
    params = {
        "query": SEARCH_QUERY,
        "display": display,
        "start": start,
        "sort": "date",
    }

    response = requests.get(NAVER_API_URL, headers=headers, params=params, timeout=20)
    response.raise_for_status()
    data = response.json()
    return data.get("items", [])


def parse_article_info(url: str) -> Dict[str, str]:
    publisher = "미상"
    reporter = "미상"
    body = ""

    try:
        res = requests.get(url, timeout=20, headers={"User-Agent": "Mozilla/5.0"})
        res.raise_for_status()
        soup = BeautifulSoup(res.text, "html.parser")

        publisher_selectors = [
            "meta[property='og:site_name']",
            "meta[name='twitter:app:name:iphone']",
            ".media_end_head_top_logo img",
            ".press_logo img",
            ".logo img",
            "a[title*='신문']",
        ]
        for selector in publisher_selectors:
            node = soup.select_one(selector)
            if not node:
                continue
            if node.name == "meta":
                candidate = node.get("content", "")
            elif node.name == "img":
                candidate = node.get("alt", "")
            else:
                candidate = node.get_text(" ", strip=True)
            candidate = _clean_text(candidate)
            if candidate:
                publisher = candidate
                break

        body_candidates = [
            "#dic_area",
            "#newsct_article",
            "#articleBodyContents",
            ".article_view",
            ".article-body",
            "article",
        ]
        for selector in body_candidates:
            node = soup.select_one(selector)
            if node:
                body = _clean_text(node.get_text(" ", strip=True))
                if len(body) > 200:
                    break

        if not body:
            paragraphs = [p.get_text(" ", strip=True) for p in soup.select("p")]
            body = _clean_text(" ".join(paragraphs))

        reporter_patterns = [
            r"([가-힣]{2,4}\s?(?:기자|특파원))",
            r"([A-Za-z]{2,30}\s?(?:Reporter|기자))",
        ]
        text_for_reporter = " ".join([body, soup.get_text(" ", strip=True)])
        for pattern in reporter_patterns:
            match = re.search(pattern, text_for_reporter)
            if match:
                reporter = _clean_text(match.group(1))
                break

        if reporter == "미상":
            reporter_meta = soup.select_one("meta[name='author']")
            if reporter_meta and reporter_meta.get("content"):
                reporter = _clean_text(reporter_meta.get("content"))

    except Exception:
        pass

    return {
        "publisher": publisher or "미상",
        "reporter": reporter or "미상",
        "body": body or "본문을 불러오지 못했습니다.",
    }


def is_blacklisted(publisher: str, reporter: str) -> bool:
    publisher_hit = publisher in EXCLUDE_PUBLISHERS
    reporter_hit = reporter in EXCLUDE_REPORTERS
    return publisher_hit or reporter_hit


def run_gemini_summary(article: Dict, model) -> str:
    prompt = f"""
아래 기사 본문을 4~6문장으로 간결하게 요약해 주세요.
반드시 마지막 줄에 아래 태그를 정확한 포맷으로 붙여 주세요.
[언론사 | 기자명 | 지역 | 핵심단어 | 시그널]
- 시그널은 BULL, BEAR, FLAT 중 하나만 사용
- 지역은 기사 내용 기반으로 한글로 작성(불명확하면 전국)
- 핵심단어는 1~3개(쉼표로 구분)

언론사: {article['publisher']}
기자명: {article['reporter']}
제목: {article['title']}
본문:
{article['content'][:4000]}
"""
    try:
        response = model.generate_content(prompt)
        text = (response.text or "").strip()
        if not re.search(r"\[[^\]]+\|[^\]]+\|[^\]]+\|[^\]]+\|(BULL|BEAR|FLAT)\]", text):
            text += f"\n[{article['publisher']} | {article['reporter']} | 전국 | 부동산 | FLAT]"
        return text
    except Exception:
        return f"요약 생성에 실패했습니다.\n[{article['publisher']} | {article['reporter']} | 전국 | 부동산 | FLAT]"


def collect_filtered_articles() -> List[Dict]:
    filtered_articles: List[Dict] = []
    start = 1

    while len(filtered_articles) < TARGET_ARTICLE_COUNT and start <= 1000:
        items = fetch_news_page(start=start, display=DISPLAY_PER_REQUEST)
        if not items:
            break

        for item in items:
            link = item.get("originallink") or item.get("link")
            if not link:
                continue

            article_meta = parse_article_info(link)
            publisher = article_meta["publisher"]
            reporter = article_meta["reporter"]

            if is_blacklisted(publisher, reporter):
                continue

            filtered_articles.append(
                {
                    "title": _strip_html(item.get("title", "")),
                    "description": _strip_html(item.get("description", "")),
                    "link": link,
                    "pub_date": _parse_pub_date(item.get("pubDate", "")),
                    "publisher": publisher,
                    "reporter": reporter,
                    "content": article_meta["body"],
                }
            )

            if len(filtered_articles) >= TARGET_ARTICLE_COUNT:
                break

        start += DISPLAY_PER_REQUEST

    return filtered_articles[:TARGET_ARTICLE_COUNT]


def append_new_rows(df_new: pd.DataFrame, csv_path: str = CSV_PATH) -> int:
    if df_new.empty:
        return 0

    if os.path.exists(csv_path):
        df_existing = pd.read_csv(csv_path)
        existing_links = set(df_existing.get("link", pd.Series(dtype=str)).astype(str).tolist())
        df_to_append = df_new[~df_new["link"].astype(str).isin(existing_links)].copy()
        if df_to_append.empty:
            return 0
        df_to_append.to_csv(csv_path, mode="a", header=False, index=False)
        return len(df_to_append)

    df_new.to_csv(csv_path, index=False)
    return len(df_new)


def main() -> None:
    gemini_api_key = os.getenv("GEMINI_API_KEY")
    if not gemini_api_key:
        raise EnvironmentError("GEMINI_API_KEY 환경변수가 필요합니다.")

    genai.configure(api_key=gemini_api_key)
    model = genai.GenerativeModel("gemini-1.5-flash")

    articles = collect_filtered_articles()

    enriched_rows = []
    for article in articles:
        summary = run_gemini_summary(article, model)
        enriched = {
            **article,
            "ai_summary": summary,
            "collected_at": datetime.now().isoformat(),
        }
        enriched_rows.append(enriched)
        time.sleep(3)

    df_new = pd.DataFrame(enriched_rows)
    appended = append_new_rows(df_new, CSV_PATH)
    print(f"필터 통과 기사 수: {len(articles)}")
    print(f"CSV에 추가된 신규 기사 수: {appended}")


if __name__ == "__main__":
    main()
