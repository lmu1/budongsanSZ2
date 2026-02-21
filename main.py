import os
import re
import time
from datetime import datetime
from pathlib import Path

import pandas as pd
import requests
from bs4 import BeautifulSoup
from google import genai

# --- PRO 설정부 ---
QUERY = "부동산 전망"
TARGET_COUNT = 20  # 하루 한도 방어를 위한 20개 세팅
TARGET_MODEL = "gemini-2.5-flash-lite"  # 사용자님이 선택하신 2.5 버전 유지
OUTPUT_FILES = ["news_data.csv", "news_data_latest.csv"]
CANONICAL_FILE = "news_data_latest.csv"
REQUIRED_COLUMNS = [
    "title",
    "link",
    "summary",
    "publisher",
    "reporter",
    "signal",
    "collected_at",
]

def get_env(name: str) -> str:
    return os.getenv(name, "")

def extract_article_metadata(link: str) -> dict:
    metadata = {"publisher": "Unknown", "reporter": "Unknown", "content": ""}
    try:
        resp = requests.get(link, timeout=10, headers={"User-Agent": "Mozilla/5.0"})
        soup = BeautifulSoup(resp.text, "html.parser")
        
        # 1. 본문 추출
        content_node = (
            soup.select_one("article#dic_area")
            or soup.select_one("#newsct_article")
            or soup.select_one("#articleBodyContents")
        )
        if content_node:
            metadata["content"] = content_node.get_text(" ", strip=True)[:2500]
            
        # 2. 언론사 추출
        pub_meta = soup.select_one("meta[property='og:site_name']")
        if pub_meta:
            metadata["publisher"] = pub_meta.get("content", "Unknown").strip()
            
        # 💡 3. 기자 이름 추출 (새로 추가된 로직)
        reporter_node = (
            soup.select_one(".media_end_head_journalist_name") 
            or soup.select_one(".byline_s") 
            or soup.select_one(".b_text")
        )
        if reporter_node:
            metadata["reporter"] = reporter_node.get_text(strip=True)
            
    except Exception:
        pass
    return metadata

def find_all_news_csv() -> list[Path]:
    files = sorted(Path(".").glob("news_data*.csv"))
    return [f for f in files if f.name != CANONICAL_FILE]

def load_all_existing_news() -> pd.DataFrame:
    source_files = find_all_news_csv()
    frames: list[pd.DataFrame] = []

    for file in source_files:
        try:
            # 💡 한글 깨짐 및 로딩 에러 방지를 위해 encoding 추가
            df = pd.read_csv(file, encoding="utf-8-sig")
            missing = [c for c in REQUIRED_COLUMNS if c not in df.columns]
            if missing:
                print(f"⚠️ 스킵: {file} (필수 컬럼 누락: {missing})")
                continue
            frames.append(df[REQUIRED_COLUMNS].copy())
        except Exception as err:
            print(f"⚠️ 스킵: {file} 로딩 실패 ({err})")

    if frames:
        merged = pd.concat(frames, ignore_index=True)
        print(f"📚 기존 CSV 병합 완료: {len(source_files)}개 파일 / {len(merged)}건")
        return merged

    return pd.DataFrame(columns=REQUIRED_COLUMNS)

def build_canonical_dataset(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df

    summary = df["summary"].astype(str).str.strip()
    valid = summary.ne("") & summary.ne("nan") & summary.ne("None")
    df = df[valid].copy()

    df["__collected_at_dt"] = pd.to_datetime(df["collected_at"], errors="coerce")
    df = df.sort_values("__collected_at_dt")

    link = df["link"].astype(str).str.strip()
    has_link = link.ne("") & link.str.lower().ne("nan")

    with_link = df[has_link].drop_duplicates(subset=["link"], keep="last")
    without_link = df[~has_link].drop_duplicates(subset=["title", "summary"], keep="last")

    canonical = pd.concat([with_link, without_link], ignore_index=True)
    canonical = canonical.sort_values("__collected_at_dt", ascending=False)
    canonical = canonical.drop(columns=["__collected_at_dt"])
    return canonical[REQUIRED_COLUMNS]

def save_canonical(df: pd.DataFrame) -> None:
    for path in OUTPUT_FILES:
        df.to_csv(path, index=False, encoding="utf-8-sig")
    print(f"🎉 누적 저장 성공! 총 {len(df)}건의 DB가 구축되었습니다.")

def main() -> None:
    client_id = get_env("NAVER_CLIENT_ID")
    client_secret = get_env("NAVER_CLIENT_SECRET")
    api_key = get_env("GEMINI_API_KEY")

    if not api_key:
        print("❌ API 키가 없습니다.")
        return

    client = genai.Client(api_key=api_key)
    print(f"🚀 프로버전 수집기 가동: {TARGET_MODEL}")

    headers = {"X-Naver-Client-Id": client_id, "X-Naver-Client-Secret": client_secret}
    res = requests.get(
        "https://openapi.naver.com/v1/search/news.json",
        headers=headers,
        params={"query": QUERY, "display": 100, "sort": "date"},
    )
    items = res.json().get("items", [])

    new_analyzed = []
    error_count = 0

    for item in items:
        if len(new_analyzed) >= TARGET_COUNT or error_count > 5:
            break

        link = item.get("originallink") or item.get("link")
        meta = extract_article_metadata(link)

        prompt = f"""부동산 전문가로서 아래 기사를 3문장 이내로 요약해. 정치/사건 기사면 "Signal: INVALID"라고 답해.
제목: {item['title']}
본문: {meta['content']}

[필수형식]
Region: 지역명
Keyword: 핵심키워드
Signal: (BULL/BEAR/FLAT)"""

        try:
            print(f"⏳ AI 분석 중... ({len(new_analyzed)+1}/{TARGET_COUNT})")
            time.sleep(30)  # 2.5 버전 한도(RPM) 방어
            response = client.models.generate_content(model=TARGET_MODEL, contents=prompt)
            text = response.text

            if "INVALID" in text.upper():
                continue

            signal = "FLAT"
            if "BULL" in text.upper():
                signal = "BULL"
            elif "BEAR" in text.upper():
                signal = "BEAR"

            new_analyzed.append(
                {
                    "title": re.sub(r"<[^>]+>", "", item["title"]),
                    "link": link,
                    "summary": text.strip(),
                    "publisher": meta["publisher"],
                    "reporter": meta["reporter"],
                    "signal": signal,
                    "collected_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
                }
            )
            print(f"✅ 완료: {item['title'][:15]}...")

        except Exception as err:
            print(f"⚠️ 오류: {err}")
            if "429" in str(err):
                break
            error_count += 1

    existing_df = load_all_existing_news()

    if new_analyzed:
        new_df = pd.DataFrame(new_analyzed)
        combined_df = pd.concat([existing_df, new_df], ignore_index=True)
    else:
        combined_df = existing_df
        print("ℹ️ 신규 분석 기사가 없어 기존 누적본만 정리합니다.")

    canonical_df = build_canonical_dataset(combined_df)
    save_canonical(canonical_df)

if __name__ == "__main__":
    main()
