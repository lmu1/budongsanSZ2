import html
import os
import re
import time
from datetime import datetime
from typing import Dict, List, Optional
import google.generativeai as genai
import pandas as pd
import requests
from bs4 import BeautifulSoup

# --- 설정부 ---
QUERY = "부동산 전망"
TARGET_COUNT = 5 
CSV_PATH = "news_data.csv"

def get_env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise EnvironmentError(f"환경변수 {name}가 설정되지 않았습니다.")
    return value

def extract_article_metadata(link: str) -> Dict[str, str]:
    metadata = {"publisher": "Unknown", "content": ""}
    try:
        resp = requests.get(link, timeout=10, headers={"User-Agent": "Mozilla/5.0"})
        soup = BeautifulSoup(resp.text, "html.parser")
        content_node = soup.select_one("article#dic_area") or soup.select_one("#newsct_article") or soup.select_one("#articleBodyContents")
        if content_node:
            metadata["content"] = content_node.get_text(" ", strip=True)[:2500]
        pub_meta = soup.select_one("meta[property='og:site_name']")
        if pub_meta:
            metadata["publisher"] = pub_meta.get("content", "Unknown")
    except:
        pass
    return metadata

def setup_gemini(api_key: str):
    genai.configure(api_key=api_key)
    try:
        available_models = [m.name.replace('models/', '') for m in genai.list_models() if 'generateContent' in m.supported_generation_methods]
        for pref in ["gemini-2.5-flash", "gemini-1.5-flash", "gemini-pro"]:
            if pref in available_models:
                print(f"✅ 사용 모델: {pref} (안전빵 20초 대기 모드)")
                return genai.GenerativeModel(pref)
    except Exception as e:
        print(f"모델 탐색 실패: {e}")
    return None

def main():
    client_id = get_env("NAVER_CLIENT_ID")
    client_secret = get_env("NAVER_CLIENT_SECRET")
    gemini_api_key = get_env("GEMINI_API_KEY")

    model = setup_gemini(gemini_api_key)
    if not model: 
        print("❌ 모델 설정 실패")
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
        
        # 🔥 요약 길이를 완벽하게 통제하는 강력한 프롬프트
        prompt = f"""부동산 전문가로서 아래 기사를 분석해 줘.
[중요] 요약은 반드시 3문장(3줄) 이내로 끝내야 해. 절대 3문장을 초과하지 마.
부동산과 무관한 정치/단순사회/사건사고 기사면 요약하지 말고 "Signal: INVALID"라고만 답해.

제목: {item['title']}
본문: {meta['content']}

마지막에 아래 형식 추가:
Region: 지역
Keyword: 키워드
Signal: (BULL/BEAR/FLAT)
"""

        try:
            print(f"⏳ 구글 API 제한 방어 중: 20초 대기... (현재 {len(analyzed)}/30 완료)")
            time.sleep(20) 
            
            response = model.generate_content(prompt)
            text = response.text
            
            if "INVALID" in text.upper():
                print(f"🚫 무관한 기사 패스 (정치/사회)")
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
                "signal": signal,
                "collected_at": datetime.now().strftime("%Y-%m-%d %H:%M")
            })
            print(f"✅ 요약 완료: {item['title'][:20]}...")
            error_count = 0 

        except Exception as e:
            print(f"⚠️ 오류 발생: {e}")
            error_count += 1
            time.sleep(30) 

    if analyzed:
        pd.DataFrame(analyzed).to_csv(CSV_PATH, index=False, encoding="utf-8-sig")
        print(f"🎉 총 {len(analyzed)}건 안전하게 저장 완료 후 종료합니다.")
    else:
        print("저장할 기사가 없습니다.")

if __name__ == "__main__":
    main()
