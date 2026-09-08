"""OT STAFF PTD / PIC — parse overtime rows and compute monthly hours + pay."""

from __future__ import annotations

from datetime import datetime

import pandas as pd

from app_config import OT_COLUMNS, OT_RATES_RM_PER_HOUR


def _normalize_day_type(value: str) -> str:
    text = str(value or "").strip().lower()
    if not text:
        return ""
    if "cuti" in text or "holiday" in text or "umum" in text:
        return "Cuti Umum"
    if "hujung" in text or "weekend" in text or "minggu" in text:
        return "Hujung Minggu"
    # Hari bekerja / hari biasa / Biasa
    if "biasa" in text or "bekerja" in text or "working" in text or "normal" in text:
        return "Biasa"
    return str(value).strip()


def _parse_hours(value) -> float | None:
    """Parse Jumlah like 4:00:00 / 4:00 / 4 into decimal hours."""
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    text = str(value).strip()
    if not text or text.upper() in {"N/A", "NA", "-"}:
        return None
    if ":" in text:
        parts = text.split(":")
        try:
            h = int(parts[0])
            m = int(parts[1]) if len(parts) > 1 else 0
            s = int(float(parts[2])) if len(parts) > 2 else 0
            return h + m / 60.0 + s / 3600.0
        except ValueError:
            return None
    try:
        return float(text.replace(",", ""))
    except ValueError:
        return None


def _parse_ot_date(value) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    for fmt in (
        "%A, %B %d, %Y",
        "%a, %B %d, %Y",
        "%d/%m/%Y",
        "%m/%d/%Y",
        "%Y-%m-%d",
        "%d-%m-%Y",
        "%d %B %Y",
        "%B %d, %Y",
    ):
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue
    return None


def parse_ot_sheet(raw: pd.DataFrame) -> pd.DataFrame:
    """Parse OT STAFF sheet into normalized rows with Hours and Month."""
    if raw is None or raw.empty:
        return pd.DataFrame(columns=OT_COLUMNS + ["Hours", "Month", "Date_parsed"])

    header_row_idx = None
    for i in range(min(8, len(raw))):
        row = [str(v).strip().lower() for v in raw.iloc[i].tolist()]
        if "nama staf" in row or ("tarikh" in row and "jumlah" in row):
            header_row_idx = i
            break
    if header_row_idx is None:
        return pd.DataFrame(columns=OT_COLUMNS + ["Hours", "Month", "Date_parsed"])

    header = [str(v).strip() for v in raw.iloc[header_row_idx].tolist()]
    col_map: dict[str, int] = {}
    for idx, name in enumerate(header):
        low = name.lower()
        if low == "no":
            col_map["No"] = idx
        elif low == "tarikh":
            col_map["Tarikh"] = idx
        elif low in {"nama staf", "nama staff", "staff"}:
            col_map["Nama Staf"] = idx
        elif "gred" in low or "jawatan" in low:
            col_map["Gred/Jawatan"] = idx
        elif "jabatan" in low or "unit" in low:
            col_map["Jabatan/Unit"] = idx
        elif "jenis" in low and "hari" in low:
            col_map["Jenis Hari"] = idx
        elif "mula" in low:
            col_map["Masa mula"] = idx
        elif "tamat" in low:
            col_map["Masa Tamat"] = idx
        elif low == "jumlah":
            col_map["Jumlah"] = idx
        elif low == "lokasi":
            col_map["Lokasi"] = idx
        elif "skop" in low:
            col_map["Skop kerja"] = idx

    rows: list[dict[str, object]] = []
    for r in range(header_row_idx + 1, len(raw)):
        row = raw.iloc[r]
        staff = (
            str(row.iloc[col_map["Nama Staf"]]).strip()
            if "Nama Staf" in col_map
            else ""
        )
        if not staff:
            continue
        tarikh = (
            str(row.iloc[col_map["Tarikh"]]).strip() if "Tarikh" in col_map else ""
        )
        day_type = _normalize_day_type(
            str(row.iloc[col_map["Jenis Hari"]]).strip()
            if "Jenis Hari" in col_map
            else ""
        )
        jumlah = (
            str(row.iloc[col_map["Jumlah"]]).strip() if "Jumlah" in col_map else ""
        )
        hours = _parse_hours(jumlah)
        parsed_date = _parse_ot_date(tarikh)
        month_label = parsed_date.strftime("%B %Y") if parsed_date else ""
        rows.append(
            {
                "No": (
                    str(row.iloc[col_map["No"]]).strip() if "No" in col_map else ""
                ),
                "Tarikh": tarikh,
                "Nama Staf": staff,
                "Gred/Jawatan": (
                    str(row.iloc[col_map["Gred/Jawatan"]]).strip()
                    if "Gred/Jawatan" in col_map
                    else ""
                ),
                "Jabatan/Unit": (
                    str(row.iloc[col_map["Jabatan/Unit"]]).strip()
                    if "Jabatan/Unit" in col_map
                    else ""
                ),
                "Jenis Hari": day_type,
                "Masa mula": (
                    str(row.iloc[col_map["Masa mula"]]).strip()
                    if "Masa mula" in col_map
                    else ""
                ),
                "Masa Tamat": (
                    str(row.iloc[col_map["Masa Tamat"]]).strip()
                    if "Masa Tamat" in col_map
                    else ""
                ),
                "Jumlah": jumlah,
                "Lokasi": (
                    str(row.iloc[col_map["Lokasi"]]).strip()
                    if "Lokasi" in col_map
                    else ""
                ),
                "Skop kerja": (
                    str(row.iloc[col_map["Skop kerja"]]).strip()
                    if "Skop kerja" in col_map
                    else ""
                ),
                "Hours": hours if hours is not None else 0.0,
                "Month": month_label,
                "Date_parsed": parsed_date,
            }
        )

    if not rows:
        return pd.DataFrame(columns=OT_COLUMNS + ["Hours", "Month", "Date_parsed"])
    return pd.DataFrame(rows)


def staff_names(df: pd.DataFrame) -> list[str]:
    if df is None or df.empty or "Nama Staf" not in df.columns:
        return []
    return sorted({str(v).strip() for v in df["Nama Staf"] if str(v).strip()})


def filter_staff(df: pd.DataFrame, staff: str) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame(columns=df.columns if df is not None else OT_COLUMNS)
    out = df[df["Nama Staf"].astype(str).str.strip() == str(staff).strip()].copy()
    if "Date_parsed" in out.columns:
        out = out.sort_values(
            by=["Date_parsed", "No"],
            ascending=[True, True],
            na_position="last",
        ).reset_index(drop=True)
    return out


def monthly_ot_summary(df: pd.DataFrame, role: str) -> pd.DataFrame:
    """
    Per-month OT hours + payment for one staff (already filtered).

    Payment uses OT_RATES_RM_PER_HOUR[role] for Biasa / Hujung Minggu / Cuti Umum.
    """
    rates = OT_RATES_RM_PER_HOUR.get(role.upper(), OT_RATES_RM_PER_HOUR["PIC"])
    empty_cols = [
        "Month",
        "Hours Biasa",
        "Hours Hujung Minggu",
        "Hours Cuti Umum",
        "Total Hours",
        "Pay Biasa (RM)",
        "Pay Hujung Minggu (RM)",
        "Pay Cuti Umum (RM)",
        "Total Pay (RM)",
    ]
    if df is None or df.empty:
        return pd.DataFrame(columns=empty_cols)

    work = df.copy()
    if "Month" not in work.columns or work["Month"].astype(str).str.strip().eq("").all():
        return pd.DataFrame(columns=empty_cols)

    rows: list[dict[str, object]] = []
    months = []
    for m in work["Month"].tolist():
        label = str(m or "").strip()
        if label and label not in months:
            months.append(label)

    for month in months:
        part = work[work["Month"].astype(str) == month]
        h_biasa = float(
            part.loc[part["Jenis Hari"] == "Biasa", "Hours"].sum()
        )
        h_week = float(
            part.loc[part["Jenis Hari"] == "Hujung Minggu", "Hours"].sum()
        )
        h_hol = float(
            part.loc[part["Jenis Hari"] == "Cuti Umum", "Hours"].sum()
        )
        p_biasa = h_biasa * rates["Biasa"]
        p_week = h_week * rates["Hujung Minggu"]
        p_hol = h_hol * rates["Cuti Umum"]
        rows.append(
            {
                "Month": month,
                "Hours Biasa": round(h_biasa, 2),
                "Hours Hujung Minggu": round(h_week, 2),
                "Hours Cuti Umum": round(h_hol, 2),
                "Total Hours": round(h_biasa + h_week + h_hol, 2),
                "Pay Biasa (RM)": round(p_biasa, 2),
                "Pay Hujung Minggu (RM)": round(p_week, 2),
                "Pay Cuti Umum (RM)": round(p_hol, 2),
                "Total Pay (RM)": round(p_biasa + p_week + p_hol, 2),
            }
        )
    return pd.DataFrame(rows)


def detail_table_for_display(df: pd.DataFrame) -> pd.DataFrame:
    """Columns shown in the staff OT detail table."""
    cols = [
        "No",
        "Tarikh",
        "Jenis Hari",
        "Masa mula",
        "Masa Tamat",
        "Jumlah",
        "Hours",
        "Lokasi",
        "Skop kerja",
        "Gred/Jawatan",
        "Jabatan/Unit",
    ]
    if df is None or df.empty:
        return pd.DataFrame(columns=cols)
    out = df.copy()
    keep = [c for c in cols if c in out.columns]
    return out[keep]
