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
        ]
        for candidate in publisher_candidates:
            if not candidate: continue
            value = candidate.get("content") or candidate.get("alt") or candidate.get_text(strip=True)
            if value:
                metadata["publisher"] = value.strip()
                break

        reporter_candidates = [
            soup.select_one("meta[name='byl']"),
            soup.select_one(".media_end_head_journalist_name"),
            soup.select_one(".byline_s"),
        ]
        for candidate in reporter_candidates:
            if not candidate: continue
            value = candidate.get("content") or candidate.get_text(" ", strip=True)
            if value:
                metadata["reporter"] = re.sub(r"기자.*$", "기자", value).strip()
                break

        content_node = soup.select_one("article#dic_area") or soup.select_one("#newsct_article") or soup.select_one("#articleBodyContents")
        if content_node:
            metadata["content"] = re.sub(r"\s+", " ", content_node.get_text(" ", strip=True))
    except Exception:
        pass
    return metadata

def fetch_naver_news(client_id: str, client_secret: str) -> List[Dict[str, str]]:
    headers = {"X-Naver-Client-Id": client_id, "X-Naver-Client-Secret": client_secret}
    collected = []
    seen_links = set()

    for start in range(1, 1000, 100):
        params = {"query": QUERY, "display": 100, "start": start, "sort": "date"}
        res = requests.get(NAVER_API_URL, headers=headers, params=params, timeout=10)
        res.raise_for_status()
        items = res.json().get("items", [])
        if not items: break

        for item in items:
            link = item.get("originallink") or item.get("link")
            if not link or link in seen_links: continue
            
            meta = extract_article_metadata(link)
            if meta["publisher"] in EXCLUDE_PUBLISHERS or meta["reporter"] in EXCLUDE_REPORTERS: continue
            
            seen_links.add(link)
            collected.append({
                "title": clean_html(item.get("title", "")),
                "description": clean_html(item.get("description", "")),
                "link": link,
                "pub_date": parse_pub_date(item.get("pubDate", "")),
                "publisher": meta["publisher"],
                "reporter": meta["reporter"],
                "content": meta["content"],
            })
            
            # 중간에 AI가 거를 것을 대비해 목표치보다 넉넉하게 기사를 모아둡니다.
            if len(collected) >= TARGET_COUNT * 2: 
                return collected
    return collected

def extract_tag_field(response_text: str, field_name: str, default_value: str) -> str:
    match = re.search(rf"{field_name}\s*:\s*([^\n\]]+)", response_text, flags=re.IGNORECASE)
    return match.group(1).strip() if match else default_value

def build_tag(publisher: str, reporter: str, region: str, keyword: str, signal: str) -> str:
    sig = signal.upper().strip() if signal.upper().strip() in {"BULL", "BEAR", "FLAT"} else "FLAT"
    return f"[{publisher} | {reporter} | {region} | {keyword} | {sig}]"

def summarize_with_gemini(api_key: str, article: Dict[str, str]) -> Optional[Dict[str, str]]:
    genai.configure(api_key=api_key)
    # 💡 1.5 Pro 모델 적용
    model = genai.GenerativeModel("gemini-1.5-flash")

    content = article.get("content") or article.get("description")
    
    # 🔥 AI 판단 필터: 문맥을 읽고 부동산과 무관하면 INVALID 반환
    prompt = f"""
너는 최고의 부동산 시장 애널리스트다.
아래 기사가 '부동산 시장 동향, 가격, 정책, 전망'과 직접적인 관련이 있는지 먼저 판단하라.
만약 부동산과 무관한 정치, 범죄, 단순 사회 기사라면 요약하지 말고 단 한 줄로 아래와 같이 출력하라:
Signal: INVALID

진짜 부동산 기사가 맞다면, 내용을 심층적으로 분석하여 2~4문장으로 핵심만 명확하게 요약하고 마지막에 다음 정보를 한 줄씩 출력하라:
Region: (한국 내 주요 지역 또는 전국)
Keyword: (핵심단어 1~3개)
Signal: (BULL, BEAR, FLAT 중 하나)

기사 제목: {article['title']}
기사 본문: {content[:3000]}
""".strip()

    try:
        response = model.generate_content(prompt)
        text = (response.text or "").strip()
    except Exception as exc:
        text = f"요약 생성 실패: {exc}\nRegion: 전국\nKeyword: 부동산\nSignal: FLAT"

    signal = extract_tag_field(text, "Signal", "FLAT").upper()
    
    # 무관한 기사로 판단되면 None을 반환해서 컷!
    if "INVALID" in signal:
        return None

    region = extract_tag_field(text, "Region", "전국")
    keyword = extract_tag_field(text, "Keyword", "부동산")

    try:
        summary_part = re.split(r"\n\s*Region\s*:", text, maxsplit=1, flags=re.IGNORECASE)[0].strip()
    except Exception:
        summary_part = text

    tag = build_tag(article["publisher"], article["reporter"], region, keyword, signal)

    return {
        **article,
        "summary": f"{summary_part}\n\n{tag}",
        "region": region,
        "keyword": keyword,
        "signal": signal if signal in {"BULL", "BEAR", "FLAT"} else "FLAT",
        "tag": tag,
        "collected_at": datetime.utcnow().isoformat(),
    }

def save_news_data(rows: List[Dict[str, str]]) -> None:
    if not rows:
        print("저장할 데이터가 없습니다.")
        return
    new_df = pd.DataFrame(rows)
    if os.path.exists(CSV_PATH):
        existing_df = pd.read_csv(CSV_PATH)
        existing_links = set(existing_df.get("link", pd.Series(dtype=str)).dropna().tolist())
        append_df = new_df[~new_df["link"].isin(existing_links)]
        if append_df.empty:
            print("새로 추가할 기사가 없습니다 (모두 중복).")
            return
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

    print(f"[{datetime.now()}] 네이버 뉴스 수집 시작...")
    articles = fetch_naver_news(client_id, client_secret)
    
    if not articles:
        print("수집된 기사가 없습니다.")
        return

    print(f"[{datetime.now()}] 수집된 기사 중 {TARGET_COUNT}건 엄선 요약 시작 (AI 문맥 필터 작동 중)")
    analyzed: List[Dict[str, str]] = []
    
    for article in articles:
        # 목표치(30건)를 채웠으면 즉시 종료
        if len(analyzed) >= TARGET_COUNT:
            break
            
        print(f"검토 중: {article['title'][:30]}...")
        summary_data = summarize_with_gemini(gemini_api_key, article)
        
        # AI가 무관하다고 판단(None 반환)하면 저장하지 않고 다음 기사로 넘어감
        if summary_data is None:
            print(" ➔ 🚫 [정치/무관 기사] AI가 걸러냄!")
            time.sleep(2)  
            continue
            
        analyzed.append(summary_data)
        print(f" ➔ ✅ [완료] (현재 {len(analyzed)}/{TARGET_COUNT}건 확정)")
        time.sleep(5)

    save_news_data(analyzed)
    print(f"[{datetime.now()}] 찐 부동산 뉴스만 수집 및 요약 완료!")

if __name__ == "__main__":
    main()
