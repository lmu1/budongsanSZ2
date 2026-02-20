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

NAVER_API_URL = "https://openapi.naver.com/v1/search/news.json"
QUERY = "부동산 전망"
TARGET_COUNT = 30
CSV_PATH = "news_data.csv"


def get_env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise EnvironmentError(f"환경변수 {name} 가 설정되어 있지 않습니다.")
    return value


def clean_html(raw_text: str) -> str:
    no_tag = re.sub(r"<[^>]+>", "", raw_text or "")
    return html.unescape(no_tag).strip()


def parse_pub_date(pub_date: str) -> str:
    try:
        dt = parsedate_to_datetime(pub_date)
        return dt.isoformat()
    except Exception:
        return datetime.utcnow().isoformat()


def extract_article_metadata(link: str) -> Dict[str, str]:
    metadata = {"publisher": "Unknown", "reporter": "Unknown", "content": ""}

    try:
        resp = requests.get(link, timeout=10, headers={"User-Agent": "Mozilla/5.0"})
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")

        publisher_candidates = [
            soup.select_one("meta[property='og:article:author']"),
            soup.select_one("meta[name='twitter:creator']"),
            soup.select_one("meta[property='og:site_name']"),
            soup.select_one("meta[name='newsct']"),
            soup.select_one("a.media_end_head_top_logo img"),
            soup.select_one("img.media_end_head_top_logo_img"),
            soup.select_one(".press_logo img"),
        ]

        for candidate in publisher_candidates:
            if not candidate:
                continue
            value = candidate.get("content") or candidate.get("alt") or candidate.get_text(strip=True)
            if value:
                metadata["publisher"] = value.strip()
                break

        reporter_candidates = [
            soup.select_one("meta[name='byl']"),
            soup.select_one("meta[property='article:author']"),
            soup.select_one(".media_end_head_journalist_name"),
            soup.select_one(".byline_s"),
            soup.select_one(".article_writer"),
            soup.select_one(".reporter"),
        ]

        for candidate in reporter_candidates:
            if not candidate:
                continue
            value = candidate.get("content") or candidate.get_text(" ", strip=True)
            if value:
                value = re.sub(r"기자.*$", "기자", value).strip()
                metadata["reporter"] = value
                break

        content_node = (
            soup.select_one("article#dic_area")
            or soup.select_one("#newsct_article")
            or soup.select_one("#articleBodyContents")
            or soup.select_one("article")
            or soup.body
        )
        if content_node:
            text = content_node.get_text(" ", strip=True)
            metadata["content"] = re.sub(r"\s+", " ", text)

    except Exception:
        pass

    return metadata


def fetch_naver_news(client_id: str, client_secret: str) -> List[Dict[str, str]]:
    headers = {
        "X-Naver-Client-Id": client_id,
        "X-Naver-Client-Secret": client_secret,
    }

    collected: List[Dict[str, str]] = []
    seen_links = set()

    for start in range(1, 1000, 100):
        params = {
            "query": QUERY,
            "display": 100,
            "start": start,
            "sort": "date",
        }
        res = requests.get(NAVER_API_URL, headers=headers, params=params, timeout=10)
        res.raise_for_status()
        items = res.json().get("items", [])

        if not items:
            break

        for item in items:
            link = item.get("originallink") or item.get("link")
            if not link or link in seen_links:
                continue

            meta = extract_article_metadata(link)
            publisher = meta.get("publisher", "Unknown")
            reporter = meta.get("reporter", "Unknown")

            if publisher in EXCLUDE_PUBLISHERS or reporter in EXCLUDE_REPORTERS:
                continue

            seen_links.add(link)
            collected.append(
                {
                    "title": clean_html(item.get("title", "")),
                    "description": clean_html(item.get("description", "")),
                    "link": link,
                    "pub_date": parse_pub_date(item.get("pubDate", "")),
                    "publisher": publisher,
                    "reporter": reporter,
                    "content": meta.get("content", ""),
                }
            )

            if len(collected) >= TARGET_COUNT:
                return collected

    return collected


def extract_tag_field(response_text: str, field_name: str, default_value: str) -> str:
    match = re.search(rf"{field_name}\s*:\s*([^\n\]]+)", response_text, flags=re.IGNORECASE)
    if match:
        return match.group(1).strip()
    return default_value


def build_tag(publisher: str, reporter: str, region: str, keyword: str, signal: str) -> str:
    normalized_signal = signal.upper().strip()
    if normalized_signal not in {"BULL", "BEAR", "FLAT"}:
        normalized_signal = "FLAT"
    return f"[{publisher} | {reporter} | {region} | {keyword} | {normalized_signal}]"


def summarize_with_gemini(api_key: str, article: Dict[str, str]) -> Dict[str, str]:
    genai.configure(api_key=api_key)
    model = genai.GenerativeModel("gemini-1.5-flash")

    content = article.get("content") or article.get("description")
    prompt = f"""
너는 부동산 시장 애널리스트다.
아래 기사 내용을 2~4문장으로 핵심 요약하고, 마지막에 다음 정보를 각각 한 줄로 출력하라:
Region: (한국 내 주요 지역 또는 전국)
Keyword: (핵심단어 1~3개)
Signal: (BULL, BEAR, FLAT 중 하나)

기사 제목: {article['title']}
기사 본문: {content[:4000]}
""".strip()

    try:
        response = model.generate_content(prompt)
        text = (response.text or "").strip()
    except Exception as exc:
        text = f"요약 생성 실패: {exc}\nRegion: 전국\nKeyword: 부동산\nSignal: FLAT"

    region = extract_tag_field(text, "Region", "전국")
    keyword = extract_tag_field(text, "Keyword", "부동산")
    signal = extract_tag_field(text, "Signal", "FLAT")

    summary_part = re.split(r"\n\s*Region\s*:", text, maxsplit=1, flags=re.IGNORECASE)[0].strip()
    tag = build_tag(article["publisher"], article["reporter"], region, keyword, signal)

    return {
        **article,
        "summary": f"{summary_part}\n\n{tag}",
        "region": region,
        "keyword": keyword,
        "signal": signal.upper() if signal.upper() in {"BULL", "BEAR", "FLAT"} else "FLAT",
        "tag": tag,
        "collected_at": datetime.utcnow().isoformat(),
    }


def save_news_data(rows: List[Dict[str, str]]) -> None:
    new_df = pd.DataFrame(rows)

    if os.path.exists(CSV_PATH):
        existing_df = pd.read_csv(CSV_PATH)
        existing_links = set(existing_df.get("link", pd.Series(dtype=str)).dropna().tolist())
        append_df = new_df[~new_df["link"].isin(existing_links)]
        combined_df = pd.concat([existing_df, append_df], ignore_index=True)
        combined_df = combined_df.drop_duplicates(subset=["link"], keep="first")
        combined_df.to_csv(CSV_PATH, index=False, encoding="utf-8-sig")
        print(f"기존 {len(existing_df)}건 + 신규 {len(append_df)}건 저장 완료")
    else:
        new_df.to_csv(CSV_PATH, index=False, encoding="utf-8-sig")
        print(f"신규 {len(new_df)}건 저장 완료")


def main() -> None:
    client_id = get_env("NAVER_CLIENT_ID")
    client_secret = get_env("NAVER_CLIENT_SECRET")
    gemini_api_key = get_env("GEMINI_API_KEY")

    articles = fetch_naver_news(client_id, client_secret)
    if len(articles) < TARGET_COUNT:
        raise RuntimeError(f"필터 통과 기사가 {TARGET_COUNT}건 미만입니다. 현재 {len(articles)}건")

    analyzed: List[Dict[str, str]] = []
    for article in articles[:TARGET_COUNT]:
        analyzed.append(summarize_with_gemini(gemini_api_key, article))
        time.sleep(3)

    save_news_data(analyzed)


if __name__ == "__main__":
    main()
