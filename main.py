import html
import os
import re
import time
from datetime import datetime
from typing import Dict, List, Optional
import pandas as pd
import requests
from bs4 import BeautifulSoup

# 🔥 구글의 최신 라이브러리 사용
from google import genai

# --- 설정부 ---
QUERY = "부동산 전망"
TARGET_COUNT = 20 
CSV_PATH = "news_data.csv"

# 🛑 퀄리티 필터: 거르고 싶은 언론사나 기자 이름을 넣으세요.
EXCLUDE_PUBLISHERS = ["나쁜일보", "광고신문"] 
EXCLUDE_REPORTERS = ["홍길동", "아무개"]

# 🚀 우리가 뼈를 묻을 최종 모델
TARGET_MODEL = "gemini-2.5-flash-lite"

def get_env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise EnvironmentError(f"환경변수 {name}가 설정되지 않았습니다.")
    return value

def extract_article_metadata(link: str) -> Dict[str, str]:
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
            
        reporter_node = soup.select_one(".byline_s") or soup.select_one(".media_end_head_journalist_name")
        if reporter_node:
            metadata["reporter"] = reporter_node.get_text(" ", strip=True).split(' ')[0]
    except:
        pass
    return metadata

def main():
    client_id = get_env("NAVER_CLIENT_ID")
    client_secret = get_env("NAVER_CLIENT_SECRET")
    gemini_api_key = get_env("GEMINI_API_KEY")

    try:
        client = genai.Client(api_key=gemini_api_key)
        print(f"✅ 구글 AI 연결 성공! [{TARGET_MODEL}] 모델로 달립니다 🚗💨")
    except Exception as e:
        print(f"❌ 구글 AI 클라이언트 설정 실패: {e}")
        return

    print(f"🚀 '{QUERY}' 뉴스 수집 시작...")
    headers = {"X-Naver-Client-Id": client_id, "X-Naver-Client-Secret": client_secret}
    params = {"query": QUERY, "display": 100, "sort": "date"}
    res = requests.get("https://openapi.naver.com/v1/search/news.json", headers=headers, params=params)
    items = res.json().get("items", [])

    analyzed = []
    error_count = 0 

    for item in items:
        if len(analyzed) >= TARGET_COUNT or error_count > 10:
            break
        
        link = item.get("originallink") or item.get("link")
        meta = extract_article_metadata(link)
        
        # 필터링 작동
        if any(bad_pub in meta['publisher'] for bad_pub in EXCLUDE_PUBLISHERS): continue
        if any(bad_rep in meta['reporter'] for bad_rep in EXCLUDE_REPORTERS): continue

        prompt = f"""부동산 전문가로서 아래 기사를 분석해 줘.
[중요] 요약은 반드시 3문장(3줄) 이내로 끝내야 해.
부동산과 무관한 기사면 "Signal: INVALID"라고만 답해.

제목: {item['title']}
본문: {meta['content']}

마지막에 아래 형식 추가:
Region: 지역
Keyword: 키워드
Signal: (BULL/BEAR/FLAT)
"""

        try:
            # Lite 모델이라 한도 넉넉하지만 안전하게 10초 대기
            print(f"⏳ 10초 대기 중... (현재 {len(analyzed)}/30 완료)")
            time.sleep(10) 
            
            response = client.models.generate_content(
                model=TARGET_MODEL,
                contents=prompt
            )
            text = response.text
            
            if "INVALID" in text.upper():
                error_count = 0 
                continue

            signal = "FLAT"
            if "BULL" in text.upper(): signal = "BULL"
            elif "BEAR" in text.upper(): signal = "BEAR"

            analyzed.append({
                "title": re.sub(r"<[^>]+>", "", item['title']),
                "link": link,
                "summary": text.strip(),
                "publisher": meta['publisher'],
                "reporter": meta['reporter'],
                "signal": signal,
                "collected_at": datetime.now().strftime("%Y-%m-%d %H:%M")
            })
            print(f"✅ 요약 성공: {item['title'][:20]}...")
            error_count = 0 

        except Exception as e:
            print(f"⚠️ 오류 발생: {e}")
            if "429" in str(e) or "Quota" in str(e):
                print("🚨 할당량 초과. 내일 다시 실행하세요.")
                break
            error_count += 1
            time.sleep(15) 

    if analyzed:
        pd.DataFrame(analyzed).to_csv(CSV_PATH, index=False, encoding="utf-8-sig")
        print(f"🎉 총 {len(analyzed)}건 안전하게 저장 완료!")
    else:
        print("저장할 기사가 없습니다.")

if __name__ == "__main__":
    main()
