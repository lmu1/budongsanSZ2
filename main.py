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
TARGET_COUNT = 30
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
        # 본문 및 언론사 추출 (네이버 뉴스 위주)
        content_node = soup.select_one("article#dic_area") or soup.select_one("#newsct_article") or soup.select_one("#articleBodyContents")
        if content_node:
            metadata["content"] = content_node.get_text(" ", strip=True)[:2500]
        pub_meta = soup.select_one("meta[property='og:site_name']")
        if pub_meta:
            metadata["publisher"] = pub_meta.get("content", "Unknown")
    except:
        pass
    return metadata

# 🔥 [핵심] 사용 가능한 모델을 서버에서 직접 목록 받아와서 고르기
def setup_gemini(api_key: str):
    genai.configure(api_key=api_key)
    print("🔎 사용 가능한 모델 목록 조회 중...")
    
    available_models = []
    try:
        for m in genai.list_models():
            if 'generateContent' in m.supported_generation_methods:
                # 'models/' 접두사를 제거하고 순수 이름만 보관
                clean_name = m.name.replace('models/', '')
                available_models.append(clean_name)
                print(f" - 발견된 모델: {clean_name}")
    except Exception as e:
        print(f"❌ 모델 목록 조회 실패: {e}")
        return None

    # 선호 순위: flash -> pro -> 그 외 첫 번째
    for pref in ["gemini-1.5-flash", "gemini-1.5-pro", "gemini-pro"]:
        if pref in available_models:
            print(f"✅ 최종 선택된 모델: {pref}")
            return genai.GenerativeModel(pref)
    
    if available_models:
        print(f"⚠️ 선호 모델이 없어 첫 번째 모델({available_models[0]})을 선택합니다.")
        return genai.GenerativeModel(available_models[0])
    return None

def main():
    client_id = get_env("NAVER_CLIENT_ID")
    client_secret = get_env("NAVER_CLIENT_SECRET")
    gemini_api_key = get_env("GEMINI_API_KEY")

    # 모델 설정
    model = setup_gemini(gemini_api_key)
    if not model:
        print("❌ 사용할 수 있는 AI 모델이 없습니다. API 키를 확인하세요.")
        return

    # 네이버 뉴스 검색
    print(f"🚀 '{QUERY}' 검색 시작...")
    headers = {"X-Naver-Client-Id": client_id, "X-Naver-Client-Secret": client_secret}
    params = {"query": QUERY, "display": 50, "sort": "date"}
    res = requests.get("https://openapi.naver.com/v1/search/news.json", headers=headers, params=params)
    items = res.json().get("items", [])

    analyzed = []
    for item in items:
        if len(analyzed) >= TARGET_COUNT: break
        
        link = item.get("originallink") or item.get("link")
        meta = extract_article_metadata(link)
        
        prompt = f"""
부동산 애널리스트로서 아래 기사를 3문장 이내로 요약해.
정치/사회/사건사고 기사면 "Signal: INVALID"라고만 답해.

제목: {clean_html(item['title'])}
본문: {meta['content']}

마지막에 아래 형식 추가:
Region: 지역명
Keyword: 키워드
Signal: (BULL, BEAR, FLAT 중 하나)
"""
        try:
            response = model.generate_content(prompt)
            text = response.text
            
            if "INVALID" in text.upper():
                print(f"🚫 건너뜀 (무관한 기사): {item['title'][:20]}...")
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
            print(f"✅ 요약 성공: {item['title'][:20]}...")
            time.sleep(4) # 무료 할당량 보호
        except Exception as e:
            print(f"❌ 요약 중 오류 발생: {e}")

    if analyzed:
        pd.DataFrame(analyzed).to_csv(CSV_PATH, index=False, encoding="utf-8-sig")
        print(f"🎉 총 {len(analyzed)}건 저장 완료!")

if __name__ == "__main__":
    main()
