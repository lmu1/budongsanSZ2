import re
import time
from io import StringIO
import pandas as pd
import streamlit as st
import requests

# 🔥 [PRO] lmu1님의 실시간 GitHub 원본 주소 강제 호출
RAW_URL = "https://raw.githubusercontent.com/lmu1/budongsanSZ2/main/news_data.csv"

SIGNAL_COLOR = {"BULL": "red", "BEAR": "blue", "FLAT": "gray"}

def load_data_pro() -> pd.DataFrame:
    try:
        # Vercel 캐시를 100% 무시하는 강력한 방법: 직접 HTTP 요청
        res = requests.get(f"{RAW_URL}?nocache={int(time.time())}", timeout=5)
        if res.status_code == 200:
            return pd.read_csv(StringIO(res.text))
    except Exception:
        pass
    
    # 깃허브 URL 긁어오기 실패 시 최후의 보루 (로컬 읽기)
    try:
        return pd.read_csv("news_data.csv")
    except:
        return pd.DataFrame()

def parse_summary_pro(summary: str) -> pd.Series:
    # 데이터가 꼬이거나 AI가 이상한 대답을 해도 절대 터지지 않는 방어 코드
    if not isinstance(summary, str):
        return pd.Series({"region": "Unknown", "keyword": "Unknown", "display_summary": "내용 없음"})
    
    reg_m = re.search(r"Region:\s*([^\n]+)", summary, re.IGNORECASE)
    key_m = re.search(r"Keyword:\s*([^\n]+)", summary, re.IGNORECASE)
    
    region = reg_m.group(1).strip() if reg_m else "Unknown"
    keyword = key_m.group(1).strip() if key_m else "Unknown"
    
    # 본문에서 지저분한 영어 태그 완벽 삭제
    clean_summary = re.sub(r"(Region|Keyword|Signal).*(\n|$)", "", summary, flags=re.IGNORECASE).strip()
    # "요약:" 같은 불필요한 AI 말투 제거
    clean_summary = re.sub(r"^\*?\*(요약|분석)\*?\*:?\s*", "", clean_summary, flags=re.IGNORECASE).strip()
    
    return pd.Series({
        "region": region,
        "keyword": keyword,
        "display_summary": clean_summary
    })

def apply_filters(df: pd.DataFrame) -> pd.DataFrame:
    filtered = df.copy()
    for field in ["publisher", "region", "keyword", "signal"]:
        if field in filtered.columns:
            selected = st.session_state.get(f"selected_{field}", [])
            if selected:
                filtered = filtered[filtered[field].isin(selected)]
    return filtered

def main():
    st.set_page_config(page_title="부동산 시장 시그널 대시보드 PRO", layout="wide")
    st.title("🏠 AI 부동산 시장 시그널 대시보드 (PRO)")

    # 1. 무조건 최신 데이터 가져오기
    df = load_data_pro()

    if df.empty:
        st.error("데이터가 없습니다. GitHub Actions에서 main.py를 먼저 실행하세요.")
        return

    # 2. 데이터 완벽 분리
    parsed_df = df["summary"].apply(parse_summary_pro)
    df = pd.concat([df, parsed_df], axis=1)

    if "collected_at" in df.columns:
        df["collected_at"] = pd.to_datetime(df["collected_at"], errors="coerce")
        df = df.sort_values("collected_at", ascending=False).reset_index(drop=True)

    # 3. 사이드바 - 실시간 동기화 버튼
    st.sidebar.success(f"📌 최신 DB 업데이트:\n{df['collected_at'].iloc[0]}")
    st.sidebar.info(f"📚 누적된 기사: 총 {len(df)}개")
    if st.sidebar.button("🔄 즉시 새로고침", use_container_width=True):
        st.rerun()

    # 4. 필터 UI
    cols = st.columns([1, 1, 1, 1, 0.8])
    filter_fields = ["publisher", "region", "keyword", "signal"]

    for idx, field in enumerate(filter_fields):
        if field not in df.columns: df[field] = "Unknown"
        key = f"selected_{field}"
        if key not in st.session_state: st.session_state[key] = []
        options = sorted([str(v) for v in df[field].dropna().unique().tolist() if str(v).strip() and v != "Unknown"])
        cols[idx].multiselect(label=field.capitalize(), options=options, key=key)

    if cols[-1].button("필터 초기화", use_container_width=True):
        for field in filter_fields: st.session_state[f"selected_{field}"] = []
        st.rerun()

    filtered_df = apply_filters(df)
    st.caption(f"검색 결과: {len(filtered_df)} 건 (전체 {len(df)}건 중)")

    # 5. 깔끔한 결과 출력
    for _, row in filtered_df.iterrows():
        signal = row.get("signal", "FLAT")
        color = SIGNAL_COLOR.get(signal, "gray")
        
        with st.container():
            st.markdown(f"#### {row.get('title', '-')}")
            st.markdown(
                f"<span style='color:{color}; font-weight:700; border: 1px solid {color}; padding: 2px 6px; border-radius: 4px;'>{signal}</span> &nbsp;"
                f"**{row.get('publisher', 'Unknown')}** | 📍 {row.get('region', 'Unknown')} | 🔑 {row.get('keyword', 'Unknown')} | 🕒 {row.get('collected_at', '')}",
                unsafe_allow_html=True
            )
            st.write(row.get("display_summary", "내용을 불러올 수 없습니다."))
            st.markdown(f"[🔗 기사 원문 읽기]({row.get('link', '#')})")
            st.divider()

if __name__ == "__main__":
    main()
