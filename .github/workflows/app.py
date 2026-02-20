import re
from typing import Dict

import pandas as pd
import streamlit as st

CSV_PATH = "news_data.csv"
TAG_PATTERN = re.compile(
    r"\[\s*(?P<publisher>[^\|\]]+)\s*\|\s*(?P<reporter>[^\|\]]+)\s*\|\s*(?P<region>[^\|\]]+)\s*\|\s*(?P<keyword>[^\|\]]+)\s*\|\s*(?P<signal>BULL|BEAR|FLAT)\s*\]",
    re.IGNORECASE,
)

SIGNAL_COLOR = {
    "BULL": "red",
    "BEAR": "blue",
    "FLAT": "gray",
}


def parse_tag(summary: str) -> Dict[str, str]:
    if not isinstance(summary, str):
        return {
            "publisher": "Unknown",
            "reporter": "Unknown",
            "region": "Unknown",
            "keyword": "Unknown",
            "signal": "FLAT",
        }

    match = TAG_PATTERN.search(summary)
    if not match:
        return {
            "publisher": "Unknown",
            "reporter": "Unknown",
            "region": "Unknown",
            "keyword": "Unknown",
            "signal": "FLAT",
        }

    parsed = {k: v.strip() for k, v in match.groupdict().items()}
    parsed["signal"] = parsed["signal"].upper()
    return parsed


def apply_filters(df: pd.DataFrame) -> pd.DataFrame:
    filtered = df.copy()

    for field in ["publisher", "reporter", "region", "keyword", "signal"]:
        selected = st.session_state.get(f"selected_{field}", [])
        if selected:
            filtered = filtered[filtered[field].isin(selected)]

    return filtered


def main() -> None:
    st.set_page_config(page_title="AI 부동산 시장 시그널 대시보드", layout="wide")
    st.title("🏠 AI 부동산 시장 시그널 대시보드")

    try:
        df = pd.read_csv(CSV_PATH)
    except FileNotFoundError:
        st.warning("news_data.csv 파일이 없습니다. 먼저 main.py를 실행하세요.")
        return

    if df.empty:
        st.info("표시할 데이터가 없습니다.")
        return

    parsed_df = df["summary"].apply(parse_tag).apply(pd.Series)
    df = pd.concat([df, parsed_df], axis=1)
    df["pub_date"] = pd.to_datetime(df["pub_date"], errors="coerce")
    df = df.sort_values("pub_date", ascending=False, na_position="last").reset_index(drop=True)

    cols = st.columns([1, 1, 1, 1, 1, 0.8])
    filter_fields = ["publisher", "reporter", "region", "keyword", "signal"]

    for idx, field in enumerate(filter_fields):
        key = f"selected_{field}"
        if key not in st.session_state:
            st.session_state[key] = []
        options = sorted([v for v in df[field].dropna().unique().tolist() if v])
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

    for _, row in filtered_df.iterrows():
        signal = row.get("signal", "FLAT")
        color = SIGNAL_COLOR.get(signal, "gray")

        st.markdown(f"### {row.get('title', '-')}")
        st.markdown(
            f"<span style='color:{color}; font-weight:700;'>[{signal}]</span> "
            f"{row.get('publisher', 'Unknown')} | {row.get('reporter', 'Unknown')} | {row.get('region', 'Unknown')} | {row.get('keyword', 'Unknown')}",
            unsafe_allow_html=True,
        )
        st.write(row.get("summary", ""))
        st.markdown(f"🔗 [기사 링크]({row.get('link', '#')})")
        st.divider()


if __name__ == "__main__":
    main()
