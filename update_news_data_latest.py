from __future__ import annotations

from pathlib import Path
import pandas as pd


OUTPUT_FILE = Path("news_data_latest.csv")
REQUIRED_COLUMNS = [
    "title",
    "link",
    "summary",
    "publisher",
    "reporter",
    "signal",
    "collected_at",
]


def find_source_files(root: Path) -> list[Path]:
    files = sorted(root.rglob("news_data*.csv"))
    return [f for f in files if f.name != OUTPUT_FILE.name]


def load_sources(files: list[Path]) -> pd.DataFrame:
    frames: list[pd.DataFrame] = []
    for file in files:
        df = pd.read_csv(file)
        missing = [c for c in REQUIRED_COLUMNS if c not in df.columns]
        if missing:
            raise ValueError(f"Missing columns in {file}: {missing}")

        frames.append(df[REQUIRED_COLUMNS].copy())

    if not frames:
        return pd.DataFrame(columns=REQUIRED_COLUMNS)

    return pd.concat(frames, ignore_index=True)


def build_latest(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df

    summary = df["summary"].astype(str).str.strip()
    df = df[summary.ne("") & summary.ne("nan") & summary.ne("None")].copy()

    df["__collected_at_dt"] = pd.to_datetime(df["collected_at"], errors="coerce")
    df = df.sort_values("__collected_at_dt")

    link = df["link"].astype(str).str.strip()
    has_link = link.ne("") & link.str.lower().ne("nan")

    with_link = df[has_link].drop_duplicates(subset=["link"], keep="last")
    without_link = df[~has_link].drop_duplicates(subset=["title", "summary"], keep="last")

    out = pd.concat([with_link, without_link], ignore_index=True)
    out = out.sort_values("__collected_at_dt")
    out = out.drop(columns=["__collected_at_dt"])

    return out[REQUIRED_COLUMNS]


def main() -> None:
    root = Path(".")
    source_files = find_source_files(root)

    merged = load_sources(source_files)
    latest = build_latest(merged)
    latest.to_csv(OUTPUT_FILE, index=False, encoding="utf-8-sig")

    print(f"source_files={len(source_files)}")
    for src in source_files:
        print(f" - {src}")
    print(f"rows_written={len(latest)}")


if __name__ == "__main__":
    main()
