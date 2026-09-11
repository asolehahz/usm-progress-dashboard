"""OT STAFF PTD / PIC — parse overtime rows and compute monthly hours + pay."""

from __future__ import annotations

import calendar
from datetime import date, datetime, timedelta

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


def jabatan_units(df: pd.DataFrame) -> list[str]:
    """Unique Jabatan/Unit values, sorted (blank labels omitted)."""
    if df is None or df.empty or "Jabatan/Unit" not in df.columns:
        return []
    return sorted(
        {str(v).strip() for v in df["Jabatan/Unit"] if str(v).strip()}
    )


def staff_months(df: pd.DataFrame) -> list[str]:
    """Month labels for a staff (or full) OT frame, newest first."""
    if df is None or df.empty or "Month" not in df.columns:
        return []
    work = df.copy()
    work["_month"] = work["Month"].astype(str).str.strip()
    work = work[work["_month"] != ""]
    if work.empty:
        return []
    if "Date_parsed" in work.columns:
        work = work.dropna(subset=["Date_parsed"])
        if not work.empty:
            work["_ym"] = work["Date_parsed"].map(
                lambda d: (d.year, d.month) if d is not None else (0, 0)
            )
            ordered = (
                work.sort_values("_ym", ascending=False)["_month"]
                .drop_duplicates()
                .tolist()
            )
            return ordered
    return list(dict.fromkeys(work["_month"].tolist()))


def filter_jabatan(df: pd.DataFrame, jabatan: str) -> pd.DataFrame:
    """Filter OT rows to one Jabatan/Unit, or return all if empty / All."""
    if df is None or df.empty:
        return pd.DataFrame(columns=df.columns if df is not None else OT_COLUMNS)
    label = str(jabatan or "").strip()
    if not label or label.lower() in {"all", "all jabatan/unit", "semua"}:
        return df.copy()
    return (
        df[df["Jabatan/Unit"].astype(str).str.strip() == label]
        .copy()
        .reset_index(drop=True)
    )


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


def filter_month(df: pd.DataFrame, month: str) -> pd.DataFrame:
    """Filter OT rows to one month label, or return all if month is empty / All."""
    if df is None or df.empty:
        return pd.DataFrame(columns=df.columns if df is not None else OT_COLUMNS)
    label = str(month or "").strip()
    if not label or label.lower() in {"all", "all months", "semua"}:
        return df.copy()
    return df[df["Month"].astype(str).str.strip() == label].copy().reset_index(drop=True)


def _ordinal(n: int) -> str:
    if 10 <= (n % 100) <= 20:
        suffix = "th"
    else:
        suffix = {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suffix}"


def _add_months(d: date, months: int) -> date:
    month_index = d.month - 1 + months
    year = d.year + month_index // 12
    month = month_index % 12 + 1
    day = min(d.day, calendar.monthrange(year, month)[1])
    return date(year, month, day)


def _fmt_dmy(d: date) -> str:
    return f"{d.day}/{d.month}/{d.year}"


def earliest_ot_date(*frames: pd.DataFrame) -> date | None:
    """Earliest parsed OT date across one or more frames."""
    earliest: date | None = None
    for df in frames:
        if df is None or df.empty or "Date_parsed" not in df.columns:
            continue
        for value in df["Date_parsed"].tolist():
            if value is None or (isinstance(value, float) and pd.isna(value)):
                continue
            if isinstance(value, datetime):
                d = value.date()
            elif isinstance(value, date):
                d = value
            else:
                continue
            if earliest is None or d < earliest:
                earliest = d
    return earliest


def payment_period_bounds(first_date: date, period_num: int) -> tuple[date, date]:
    """
    Payment cycles:
      1st: first recorded date → 25/8 (same year as first date)
      2nd: 26/8 → 25/9
      3rd: 26/9 → 25/10
      …
    """
    if period_num < 1:
        raise ValueError("period_num must be >= 1")
    p1_end = date(first_date.year, 8, 25)
    if period_num == 1:
        return first_date, p1_end
    end = _add_months(p1_end, period_num - 1)
    start = _add_months(p1_end, period_num - 2) + timedelta(days=1)
    return start, end


def payment_period_label(first_date: date, period_num: int) -> str:
    start, end = payment_period_bounds(first_date, period_num)
    return (
        f"{_ordinal(period_num)} payment "
        f"({_fmt_dmy(start)} – {_fmt_dmy(end)})"
    )


def payment_period_number_for_date(d: date, first_date: date) -> int | None:
    """Which payment period a calendar date falls into (None if before period 1)."""
    if d < first_date:
        return None
    p1_end = date(first_date.year, 8, 25)
    if d <= p1_end:
        return 1
    # Months after Aug 25: period = 2 + months from Sep baseline
    # end of period n = Aug 25 + (n-1) months; find smallest n with d <= end
    n = 2
    while True:
        end = _add_months(p1_end, n - 1)
        if d <= end:
            return n
        n += 1
        if n > 240:  # safety
            return None


def attach_payment_periods(
    df: pd.DataFrame, first_date: date | None
) -> pd.DataFrame:
    """Add Payment # and Payment columns from Date_parsed."""
    if df is None:
        return pd.DataFrame(columns=OT_COLUMNS + ["Payment #", "Payment"])
    if df.empty:
        cols = list(df.columns)
        for extra in ("Payment #", "Payment"):
            if extra not in cols:
                cols.append(extra)
        return pd.DataFrame(columns=cols)
    out = df.copy()
    if first_date is None or "Date_parsed" not in out.columns:
        out["Payment #"] = pd.NA
        out["Payment"] = ""
        return out

    nums: list[int | None] = []
    labels: list[str] = []
    for value in out["Date_parsed"].tolist():
        if value is None or (isinstance(value, float) and pd.isna(value)):
            nums.append(None)
            labels.append("")
            continue
        d = value.date() if isinstance(value, datetime) else value
        if not isinstance(d, date):
            nums.append(None)
            labels.append("")
            continue
        num = payment_period_number_for_date(d, first_date)
        nums.append(num)
        labels.append(
            payment_period_label(first_date, num) if num is not None else ""
        )
    out["Payment #"] = nums
    out["Payment"] = labels
    return out


def payment_period_options(
    df: pd.DataFrame, first_date: date | None
) -> list[tuple[int, str]]:
    """(period_num, label) for periods present in df, ascending."""
    if first_date is None or df is None or df.empty:
        return []
    work = attach_payment_periods(df, first_date)
    nums = sorted(
        {
            int(n)
            for n in work["Payment #"].tolist()
            if n is not None and not (isinstance(n, float) and pd.isna(n))
        }
    )
    return [(n, payment_period_label(first_date, n)) for n in nums]


def filter_payment_period(
    df: pd.DataFrame, period: str | int, first_date: date | None
) -> pd.DataFrame:
    """Filter to one payment period, or all if empty / All."""
    if df is None or df.empty:
        return pd.DataFrame(columns=df.columns if df is not None else OT_COLUMNS)
    label = str(period or "").strip()
    if not label or label.lower() in {"all", "all payments", "semua"}:
        return attach_payment_periods(df, first_date)

    work = attach_payment_periods(df, first_date)
    if isinstance(period, int) or str(period).isdigit():
        num = int(period)
        return work[work["Payment #"] == num].copy().reset_index(drop=True)
    return (
        work[work["Payment"].astype(str) == label]
        .copy()
        .reset_index(drop=True)
    )


def payment_period_ot_summary(df: pd.DataFrame, role: str) -> pd.DataFrame:
    """Per-payment-period OT hours + pay (df should already include Payment cols)."""
    rates = OT_RATES_RM_PER_HOUR.get(role.upper(), OT_RATES_RM_PER_HOUR["PIC"])
    empty_cols = [
        "Payment",
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
    if "Payment #" not in work.columns or "Payment" not in work.columns:
        return pd.DataFrame(columns=empty_cols)

    rows: list[dict[str, object]] = []
    ordered = (
        work.dropna(subset=["Payment #"])
        .sort_values("Payment #")["Payment #"]
        .drop_duplicates()
        .tolist()
    )
    for num in ordered:
        part = work[work["Payment #"] == num]
        label = ""
        if not part.empty:
            label = str(part["Payment"].iloc[0] or "")
        rows.append({"Payment": label, **_hours_pay_for_rows(part, rates)})
    return pd.DataFrame(rows)


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
        rows.append({"Month": month, **_hours_pay_for_rows(part, rates)})
    return pd.DataFrame(rows)


def _hours_pay_for_rows(part: pd.DataFrame, rates: dict[str, float]) -> dict[str, float]:
    h_biasa = float(part.loc[part["Jenis Hari"] == "Biasa", "Hours"].sum())
    h_week = float(part.loc[part["Jenis Hari"] == "Hujung Minggu", "Hours"].sum())
    h_hol = float(part.loc[part["Jenis Hari"] == "Cuti Umum", "Hours"].sum())
    p_biasa = h_biasa * rates["Biasa"]
    p_week = h_week * rates["Hujung Minggu"]
    p_hol = h_hol * rates["Cuti Umum"]
    return {
        "Hours Biasa": round(h_biasa, 2),
        "Hours Hujung Minggu": round(h_week, 2),
        "Hours Cuti Umum": round(h_hol, 2),
        "Total Hours": round(h_biasa + h_week + h_hol, 2),
        "Pay Biasa (RM)": round(p_biasa, 2),
        "Pay Hujung Minggu (RM)": round(p_week, 2),
        "Pay Cuti Umum (RM)": round(p_hol, 2),
        "Total Pay (RM)": round(p_biasa + p_week + p_hol, 2),
    }


def all_staff_ot_summary(df: pd.DataFrame, role: str) -> pd.DataFrame:
    """
    Per-staff OT hours + payment across the (already filtered) frame.

    Sorted by Total Pay descending.
    """
    rates = OT_RATES_RM_PER_HOUR.get(role.upper(), OT_RATES_RM_PER_HOUR["PIC"])
    empty_cols = [
        "Nama Staf",
        "Jabatan/Unit",
        "Hours Biasa",
        "Hours Hujung Minggu",
        "Hours Cuti Umum",
        "Total Hours",
        "Pay Biasa (RM)",
        "Pay Hujung Minggu (RM)",
        "Pay Cuti Umum (RM)",
        "Total Pay (RM)",
    ]
    if df is None or df.empty or "Nama Staf" not in df.columns:
        return pd.DataFrame(columns=empty_cols)

    rows: list[dict[str, object]] = []
    for staff in staff_names(df):
        part = df[df["Nama Staf"].astype(str).str.strip() == staff]
        units = sorted(
            {
                str(v).strip()
                for v in part.get("Jabatan/Unit", pd.Series(dtype=str))
                if str(v).strip()
            }
        )
        metrics = _hours_pay_for_rows(part, rates)
        rows.append(
            {
                "Nama Staf": staff,
                "Jabatan/Unit": ", ".join(units) if units else "",
                **metrics,
            }
        )
    if not rows:
        return pd.DataFrame(columns=empty_cols)
    out = pd.DataFrame(rows)
    return out.sort_values(
        by=["Total Pay (RM)", "Nama Staf"],
        ascending=[False, True],
    ).reset_index(drop=True)


def detail_table_for_display(df: pd.DataFrame) -> pd.DataFrame:
    """Columns shown in the staff OT detail table."""
    cols = [
        "No",
        "Tarikh",
        "Payment",
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
