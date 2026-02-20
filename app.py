import re
from typing import Dict
import pandas as pd
import streamlit as st

CSV_PATH = "news_data.csv"

SIGNAL_COLOR = {
    "BULL": "red",
    "BEAR": "blue",
    "FLAT": "gray",
}

# 🔥 1. 핵심 해결: 캐시 수명을 0으로 설정해서 Vercel(Streamlit)이 항상 최신 데이터를 불러오게 만듭니다.
@st.cache_data(ttl=0)
def load_data() -> pd.DataFrame:
    try:
        return pd.read_csv(CSV_PATH)
    except FileNotFoundError:
        return pd.DataFrame()

# 🔥 2. AI가 출력한 새로운 형식(Region: 지역, Keyword: 키워드)을 읽어내는 파서
def parse_row(row: pd.Series) -> pd.Series:
    summary = str(row.get("summary", ""))
    
    # 예전 대괄호 태그 방식이 남아있을 경우를 대비한 방어 코드
    tag_match = re.search(r"\[\s*([^\|\]]+)\s*\|\s*([^\|\]]+)\s*\|\s*([^\|\]]+)\s*\|\s*([^\|\]]+)\s*\|\s*(BULL|BEAR|FLAT)\s*\]", summary, re.IGNORECASE)
    if tag_match:
        return pd.Series({
            "region": tag_match.group(3).strip(),
            "keyword": tag_match.group(4).strip(),
            "signal": tag_match.group(5).strip().upper(),
            "display_summary": summary.replace(tag_match.group(0), "").strip()
        })
    
    # 현재 사용 중인 줄바꿈 형식 추출
    reg_m = re.search(r"Region:\s*(.*)", summary, re.IGNORECASE)
    key_m = re.search(r"Keyword:\s*(.*)", summary, re.IGNORECASE)
    sig_m = re.search(r"Signal:\s*(BULL|BEAR|FLAT)", summary, re.IGNORECASE)
    
    # 깔끔한 화면을 위해 본문에서 태그 텍스트는 지워줍니다.
    clean_summary = re.sub(r"(Region|Keyword|Signal):.*", "", summary, flags=re.IGNORECASE).strip()
    
    return pd.Series({
        "region": reg_m.group(1).strip() if reg_m else "Unknown",
        "keyword": key_m.group(1).strip() if key_m else "Unknown",
        "signal": sig_m.group(1).strip().upper() if sig_m else "FLAT",
        "display_summary": clean_summary
    })

def apply_filters(df: pd.DataFrame) -> pd.DataFrame:
    filtered = df.copy()
    for field in ["publisher", "reporter", "region", "keyword", "signal"]:
        if field not in filtered.columns:
            continue
        selected = st.session_state.get(f"selected_{field}", [])
        if selected:
            filtered = filtered[filtered[field].isin(selected)]
    return filtered

def main() -> None:
    st.set_page_config(page_title="AI 부동산 시장 시그널 대시보드", layout="wide")
    st.title("🏠 AI 부동산 시장 시그널 대시보드")

    # 🔥 캐시가 풀린 상태로 데이터 로드
    df = load_data()

    if df.empty:
        st.info("표시할 데이터가 없습니다. 먼저 GitHub Actions가 실행되기를 기다려주세요.")
        return

    # 데이터 분석 및 컬럼 병합
    parsed_df = df.apply(parse_row, axis=1)
    for col in parsed_df.columns:
        df[col] = parsed_df[col]

    # 언론사/기자 컬럼이 없는 경우 기본값 세팅
    if "publisher" not in df.columns: df["publisher"] = "Unknown"
    if "reporter" not in df.columns: df["reporter"] = "Unknown"

    if "pub_date" in df.columns:
        df["pub_date"] = pd.to_datetime(df["pub_date"], errors="coerce")
        df = df.sort_values("pub_date", ascending=False, na_position="last").reset_index(drop=True)

    # 필터 UI 그리기
    cols = st.columns([1, 1, 1, 1, 1, 0.8])
    filter_fields = ["publisher", "reporter", "region", "keyword", "signal"]

    for idx, field in enumerate(filter_fields):
        key = f"selected_{field}"
        if key not in st.session_state:
            st.session_state[key] = []
        options = sorted([str(v) for v in df[field].dropna().unique().tolist() if v])
        cols[idx].multiselect(
            label=field.capitalize(),
            options=options,
            key=key,
            placeholder=f"{field} 선택",
        )

    if cols[-1].button("필터 초기화", use_container_width=True):
        for field in filter_fields:
            st.session_state[f"selected_{field}"] = []
        st.rerun()

    filtered_df = apply_filters(df)
    st.caption(f"총 {len(filtered_df)} / {len(df)} 건")

    # 기사 카드 출력
    for _, row in filtered_df.iterrows():
        signal = row.get("signal", "FLAT")
        color = SIGNAL_COLOR.get(signal, "gray")

        st.markdown(f"### {row.get('title', '-')}")
        st.markdown(
            f"<span style='color:{color}; font-weight:700;'>[{signal}]</span> "
            f"{row.get('publisher', 'Unknown')} | {row.get('reporter', 'Unknown')} | {row.get('region', 'Unknown')} | {row.get('keyword', 'Unknown')}",
            unsafe_allow_html=True,
        )
        st.write(row.get("display_summary", ""))
        st.markdown(f"🔗 [기사 링크]({row.get('link', '#')})")
        st.divider()

if __name__ == "__main__":
    main()
