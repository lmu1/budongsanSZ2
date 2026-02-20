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

# --- 설정부 ---
QUERY = "부동산 전망"
TARGET_COUNT = 30 # 30건을 다 채우려면 약 7~8분이 소요됩니다.
CSV_PATH = "news_data.csv"

def get_env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise EnvironmentError(f"환경변수 {name}가 설정되지 않았습니다.")
    return value

def clean_html(raw_text: str) -> str:
    return html.unescape(re.sub(r"<[^>]+>", "", raw_text or "")).strip()

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
    available_models = []
    try:
        for m in genai.list_models():
            if 'generateContent' in m.supported_generation_methods:
                clean_name = m.name.replace('models/', '')
                available_models.append(clean_name)
        # 최신 모델(2.5)부터 하위 모델까지 순차 탐색
        for pref in ["gemini-2.5-flash", "gemini-1.5-flash", "gemini-pro"]:
            if pref in available_models:
                print(f"✅ 사용 모델: {pref} (분당 5회 제한 모드 가동)")
                return genai.GenerativeModel(pref)
    except:
        pass
    return None

def main():
    client_id = get_env("NAVER_CLIENT_ID")
    client_secret = get_env("NAVER_CLIENT_SECRET")
    gemini_api_key = get_env("GEMINI_API_KEY")

    model = setup_gemini(gemini_api_key)
    if not model: return

    print(f"🚀 '{QUERY}' 수집 시작...")
    headers = {"X-Naver-Client-Id": client_id, "X-Naver-Client-Secret": client_secret}
    params = {"query": QUERY, "display": 100, "sort": "date"}
    res = requests.get("https://openapi.naver.com/v1/search/news.json", headers=headers, params=params)
    items = res.json().get("items", [])

    analyzed = []
    for item in items:
        if len(analyzed) >= TARGET_COUNT: break
        
        link = item.get("originallink") or item.get("link")
        meta = extract_article_metadata(link)
        
        prompt = f"부동산 전문가로서 아래 기사를 3문장 이내 요약해. 정치기사면 Signal: INVALID라고 답해.\n제목: {clean_html(item['title'])}\n본문: {meta['content']}\n형식:\nRegion: 지역\nKeyword: 키워드\nSignal: (BULL/BEAR/FLAT)"

        # 🔥 재시도 로직 추가 (429 에러 방어)
        success = False
        retries = 0
        while not success and retries < 3:
            try:
                response = model.generate_content(prompt)
                text = response.text
                
                if "INVALID" in text.upper():
                    print(f"🚫 무관한 기사 패스")
                    success = True # 처리는 성공한 것으로 간주
                    continue

                signal = "FLAT"
                if "BULL" in text.upper(): signal = "BULL"
                elif "BEAR" in text.upper(): signal = "BEAR"

                analyzed.append({
                    "title": clean_html(item['title']),
                    "link": link,
                    "summary": text.strip(),
                    "publisher": meta['publisher'],
                    "signal": signal,
                    "collected_at": datetime.now().strftime("%Y-%m-%d %H:%M")
                })
                print(f"✅ 요약 완료 ({len(analyzed)}/{TARGET_COUNT})")
                success = True
                # 무료 티어 5 RPM 제한을 지키기 위해 15초 대기
                time.sleep(15) 
                
            except Exception as e:
                if "429" in str(e):
                    print(f"⚠️ 속도 제한 감지! 40초간 휴식 후 다시 시도합니다... (시도 {retries+1}/3)")
                    time.sleep(40)
                    retries += 1
                else:
                    print(f"❌ 기타 오류: {e}")
                    break

    if analyzed:
        pd.DataFrame(analyzed).to_csv(CSV_PATH, index=False, encoding="utf-8-sig")
        print(f"🎉 저장 완료!")

if __name__ == "__main__":
    main()
