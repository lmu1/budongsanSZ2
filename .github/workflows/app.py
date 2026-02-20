import re
from pathlib import Path

import pandas as pd
import streamlit as st

CSV_PATH = Path("news_data.csv")
TAG_PATTERN = re.compile(
    r"\[(?P<publisher>[^\]|]+)\|(?P<reporter>[^\]|]+)\|(?P<region>[^\]|]+)\|(?P<keyword>[^\]|]+)\|(?P<signal>BULL|BEAR|FLAT)\]"
)
SIGNAL_COLORS = {
    "BULL": "red",
    "BEAR": "blue",
    "FLAT": "gray",
}


def extract_tag_fields(summary: str):
    if not isinstance(summary, str):
        return {
            "tag_publisher": "미상",
            "tag_reporter": "미상",
            "tag_region": "전국",
            "tag_keyword": "부동산",
            "tag_signal": "FLAT",
        }

    match = TAG_PATTERN.search(summary.replace(" ", ""))
    if not match:
        return {
            "tag_publisher": "미상",
            "tag_reporter": "미상",
            "tag_region": "전국",
            "tag_keyword": "부동산",
            "tag_signal": "FLAT",
        }

    return {
        "tag_publisher": match.group("publisher").strip(),
        "tag_reporter": match.group("reporter").strip(),
        "tag_region": match.group("region").strip(),
        "tag_keyword": match.group("keyword").strip(),
        "tag_signal": match.group("signal").strip(),
    }


def initialize_state():
    defaults = {
        "publisher_filter": [],
        "reporter_filter": [],
        "region_filter": [],
        "keyword_filter": [],
        "signal_filter": [],
    }
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value


def and_filter(df: pd.DataFrame) -> pd.DataFrame:
    filtered = df.copy()

    if st.session_state.publisher_filter:
        filtered = filtered[filtered["tag_publisher"].isin(st.session_state.publisher_filter)]
    if st.session_state.reporter_filter:
        filtered = filtered[filtered["tag_reporter"].isin(st.session_state.reporter_filter)]
    if st.session_state.region_filter:
        filtered = filtered[filtered["tag_region"].isin(st.session_state.region_filter)]
    if st.session_state.keyword_filter:
        filtered = filtered[
            filtered["tag_keyword"].apply(
                lambda kw: all(sel in [k.strip() for k in str(kw).split(",")] for sel in st.session_state.keyword_filter)
            )
        ]
    if st.session_state.signal_filter:
        filtered = filtered[filtered["tag_signal"].isin(st.session_state.signal_filter)]

    return filtered


def load_data() -> pd.DataFrame:
    if not CSV_PATH.exists():
        return pd.DataFrame()

    df = pd.read_csv(CSV_PATH)
    if "pub_date" in df.columns:
        df["pub_date"] = pd.to_datetime(df["pub_date"], errors="coerce")
        df = df.sort_values("pub_date", ascending=False)

    tag_df = df["ai_summary"].apply(extract_tag_fields).apply(pd.Series)
    return pd.concat([df, tag_df], axis=1)


def main():
    st.set_page_config(page_title="AI 부동산 시장 시그널 대시보드", layout="wide")
    st.title("AI 부동산 시장 시그널 대시보드")
    initialize_state()

    df = load_data()
    if df.empty:
        st.warning("news_data.csv 파일이 없거나 데이터가 비어 있습니다.")
        return

    with st.sidebar:
        st.subheader("다중 교차 필터 (AND)")

        st.session_state.publisher_filter = st.multiselect(
            "언론사",
            options=sorted(df["tag_publisher"].dropna().unique().tolist()),
            default=st.session_state.publisher_filter,
        )
        st.session_state.reporter_filter = st.multiselect(
            "기자명",
            options=sorted(df["tag_reporter"].dropna().unique().tolist()),
            default=st.session_state.reporter_filter,
        )
        st.session_state.region_filter = st.multiselect(
            "지역",
            options=sorted(df["tag_region"].dropna().unique().tolist()),
            default=st.session_state.region_filter,
        )

        all_keywords = sorted(
            {
                keyword.strip()
                for raw in df["tag_keyword"].dropna().tolist()
                for keyword in str(raw).split(",")
                if keyword.strip()
            }
        )
        st.session_state.keyword_filter = st.multiselect(
            "핵심단어",
            options=all_keywords,
            default=st.session_state.keyword_filter,
        )
        st.session_state.signal_filter = st.multiselect(
            "시그널",
            options=["BULL", "BEAR", "FLAT"],
            default=st.session_state.signal_filter,
        )

        if st.button("필터 초기화"):
            for key in [
                "publisher_filter",
                "reporter_filter",
                "region_filter",
                "keyword_filter",
                "signal_filter",
            ]:
                st.session_state[key] = []
            st.rerun()

    filtered = and_filter(df)
    st.caption(f"전체 {len(df)}건 / 필터 결과 {len(filtered)}건")

    for _, row in filtered.iterrows():
        signal = str(row.get("tag_signal", "FLAT")).upper()
        color = SIGNAL_COLORS.get(signal, "gray")

        st.markdown(f"### {row.get('title', '(제목 없음)')}")
        st.markdown(
            f"- 날짜: {row.get('pub_date', '')}  \\n- 언론사: {row.get('tag_publisher', '미상')}  \\n- 기자: {row.get('tag_reporter', '미상')}  \\n- 지역: {row.get('tag_region', '전국')}"
        )
        st.markdown(f"<span style='color:{color};font-weight:700'>시그널: {signal}</span>", unsafe_allow_html=True)
        st.markdown(row.get("ai_summary", ""))
        st.markdown(f"[원문 링크]({row.get('link', '#')})")
        st.divider()


if __name__ == "__main__":
    main()
