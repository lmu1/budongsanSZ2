import os
import re
import time
from datetime import datetime
import pandas as pd
import requests
from bs4 import BeautifulSoup
from google import genai

# --- PRO 설정부 ---
QUERY = "부동산 전망"
TARGET_COUNT = 20  # 하루 한도 방어를 위한 20개 세팅
CSV_PATH = "news_data.csv"
TARGET_MODEL = "gemini-2.5-flash"  # 사용자님이 선택하신 2.5 버전 유지

def get_env(name: str) -> str:
    return os.getenv(name, "")

def extract_article_metadata(link: str) -> dict:
    metadata = {"publisher": "Unknown", "reporter": "Unknown", "content": ""}
    try:
        resp = requests.get(link, timeout=10, headers={"User-Agent": "Mozilla/5.0"})
        soup = BeautifulSoup(resp.text, "html.parser")
        content_node = soup.select_one("article#dic_area") or soup.select_one("#newsct_article") or soup.select_one("#articleBodyContents")
        if content_node:
            metadata["content"] = content_node.get_text(" ", strip=True)[:2500]
        pub_meta = soup.select_one("meta[property='og:site_name']")
        if pub_meta:
            metadata["publisher"] = pub_meta.get("content", "Unknown").strip()
    except:
        pass
    return metadata

def main():
    client_id = get_env("NAVER_CLIENT_ID")
    client_secret = get_env("NAVER_CLIENT_SECRET")
    api_key = get_env("GEMINI_API_KEY")

    if not api_key:
        print("❌ API 키가 없습니다.")
        return

    client = genai.Client(api_key=api_key)
    print(f"🚀 프로버전 수집기 가동: {TARGET_MODEL}")

    headers = {"X-Naver-Client-Id": client_id, "X-Naver-Client-Secret": client_secret}
    res = requests.get("https://openapi.naver.com/v1/search/news.json", headers=headers, params={"query": QUERY, "display": 100, "sort": "date"})
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
            time.sleep(10) # 2.5 버전 한도(RPM) 방어
            response = client.models.generate_content(model=TARGET_MODEL, contents=prompt)
            text = response.text
            
            if "INVALID" in text.upper(): continue

            signal = "FLAT"
            if "BULL" in text.upper(): signal = "BULL"
            elif "BEAR" in text.upper(): signal = "BEAR"

            new_analyzed.append({
                "title": re.sub(r"<[^>]+>", "", item['title']),
                "link": link,
                "summary": text.strip(),
                "publisher": meta['publisher'],
                "reporter": meta['reporter'],
                "signal": signal,
                "collected_at": datetime.now().strftime("%Y-%m-%d %H:%M")
            })
            print(f"✅ 완료: {item['title'][:15]}...")

        except Exception as e:
            print(f"⚠️ 오류: {e}")
            if "429" in str(e): break
            error_count += 1

    # 🔥 [PRO] 완벽한 데이터 누적 로직
    if new_analyzed:
        new_df = pd.DataFrame(new_analyzed)
        if os.path.exists(CSV_PATH):
            try:
                old_df = pd.read_csv(CSV_PATH)
                combined_df = pd.concat([old_df, new_df], ignore_index=True)
                # 링크(link)가 같은 중복 기사는 최신 수집본 하나만 남기고 삭제
                combined_df = combined_df.drop_duplicates(subset=['link'], keep='last')
            except:
                combined_df = new_df
        else:
            combined_df = new_df

        # 최신 기사가 위로 오도록 정렬 후 저장
        combined_df = combined_df.sort_values(by="collected_at", ascending=False)
        combined_df.to_csv(CSV_PATH, index=False, encoding="utf-8-sig")
        print(f"🎉 누적 저장 성공! 총 {len(combined_df)}건의 DB가 구축되었습니다.")
    else:
        print("저장할 신규 기사가 없습니다.")

if __name__ == "__main__":
    main()
