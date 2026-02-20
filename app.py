import re
import time
from typing import Dict
import pandas as pd
import streamlit as st

# 🔥 사용자님의 아이디(lmu1)가 적용된 실시간 데이터 주소입니다.
RAW_URL = "https://raw.githubusercontent.com/lmu1/budongsanSZ2/main/news_data.csv"

SIGNAL_COLOR = {
    "BULL": "red",
    "BEAR": "blue",
    "FLAT": "gray",
}

def load_data() -> pd.DataFrame:
    try:
        # 💡 주소 뒤에 현재 시간을 붙여서 브라우저 캐시를 완전히 무력화합니다.
        # 이렇게 하면 새로고침할 때마다 GitHub에 있는 진짜 최신 파일을 가져옵니다.
        current_time = int(time.time())
        final_url = f"{RAW_URL}?t={current_time}"
        return pd.read_csv(final_url)
    except Exception as e:
        # URL 읽기에 실패할 경우를 대비한 백업용 로컬 로드
        try:
            return pd.read_csv("news_data.csv")
        except:
            return pd.DataFrame()

def parse_summary(summary: str) -> Dict[str, str]:
    if not isinstance(summary, str):
        return {"region": "Unknown", "keyword": "Unknown", "display_summary": ""}
    
    # 제미나이 출력 형식(Region/Keyword) 추출
    region_match = re.search(r"Region:\s*(.+)", summary, re.IGNORECASE)
    keyword_match = re.search(r"Keyword:\s*(.+)", summary, re.IGNORECASE)
    
    region = region_match.group(1).strip() if region_match else "Unknown"
    keyword = keyword_match.group(1).strip() if keyword_match else "Unknown"
    
    # 화면에 보여줄 본문에서 태그 텍스트 제거
    clean_summary = re.sub(r"(Region|Keyword|Signal):.*", "", summary, flags=re.IGNORECASE).strip()
    
    return {
        "region": region,
        "keyword": keyword,
        "display_summary": clean_summary
    }

def apply_filters(df: pd.DataFrame) -> pd.DataFrame:
    filtered = df.copy()
    for field in ["publisher", "reporter", "region", "keyword", "signal"]:
        if field in filtered.columns:
            selected = st.session_state.get(f"selected_{field}", [])
            if selected:
                filtered = filtered[filtered[field].isin(selected)]
    return filtered

def main() -> None:
    st.set_page_config(page_title="AI 부동산 시장 시그널 대시보드", layout="wide")
    st.title("🏠 AI 부동산 시장 시그널 대시보드")

    # 🔄 데이터 로드 (매번 GitHub Raw URL에서 새로 가져옴)
    df = load_data()

    if df.empty:
        st.warning("데이터를 불러올 수 없습니다. GitHub에 news_data.csv가 있는지 확인해 주세요.")
        return

    # 데이터 분석 및 컬럼 추가
    parsed_df = df["summary"].apply(lambda x: pd.Series(parse_summary(x)))
    df = pd.concat([df, parsed_df], axis=1)

    # 정렬 기준 설정
    if "collected_at" in df.columns:
        df["collected_at"] = pd.to_datetime(df["collected_at"], errors="coerce")
        df = df.sort_values("collected_at", ascending=False).reset_index(drop=True)

    # UI 상단 정보
    st.sidebar.info(f"최신 수집 시각: {df['collected_at'].iloc[0] if not df.empty else 'N/A'}")
    if st.sidebar.button("지금 당장 새로고침", use_container_width=True):
        st.rerun()
    st.sidebar.divider()

    # 필터 구성
    cols = st.columns([1, 1, 1, 1, 1, 0.8])
    filter_fields = ["publisher", "reporter", "region", "keyword", "signal"]

    for idx, field in enumerate(filter_fields):
        if field not in df.columns: df[field] = "Unknown"
        key = f"selected_{field}"
        if key not in st.session_state: st.session_state[key] = []
        options = sorted([str(v) for v in df[field].dropna().unique().tolist() if str(v).strip()])
        cols[idx].multiselect(label=field.capitalize(), options=options, key=key)

    if cols[-1].button("초기화", use_container_width=True):
        for field in filter_fields: st.session_state[f"selected_{field}"] = []
        st.rerun()

    filtered_df = apply_filters(df)
    st.caption(f"검색 결과: {len(filtered_df)} 건")

    # 결과 카드 출력
    for _, row in filtered_df.iterrows():
        signal = row.get("signal", "FLAT")
        color = SIGNAL_COLOR.get(signal, "gray")
        st.markdown(f"### {row.get('title', '-')}")
        st.markdown(
            f"<span style='color:{color}; font-weight:700;'>[{signal}]</span> "
            f"{row.get('publisher', 'Unknown')} | {row.get('region', 'Unknown')} | {row.get('keyword', 'Unknown')}",
            unsafe_allow_html=True
        )
        st.write(row.get("display_summary", row.get("summary", "")))
        st.markdown(f"🔗 [기사 본문]({row.get('link', '#')})")
        st.divider()

if __name__ == "__main__":
    main()
