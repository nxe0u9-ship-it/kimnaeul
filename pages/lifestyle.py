from datetime import date, datetime, time, timedelta
from hashlib import sha256
import json
import math

import pandas as pd
import streamlit as st

from app_shared import require_login, get_timezone_name, get_local_now
from sidebar_menu import show_sidebar_menu


TYPES = {
    "🍽️ 식사": "meal",
    "🏃 운동·산책": "activity",
    "😴 수면": "sleep",
    "📅 활동 없음 확인": "no_activity",
}

TYPE_LABELS = {
    "meal": "식사",
    "activity": "운동·산책",
    "sleep": "수면",
    "no_activity": "활동 없음",
}

UNITS = ["g", "mL", "개", "공기", "인분", "장", "컵"]
MEAL_SLOTS = ["아침", "점심", "저녁", "간식", "기타"]
INTENSITIES = ["가벼움", "보통", "높음"]


def show_error(message, error):
    st.error(message)
    st.caption(
        f"오류 종류: {type(error).__name__} / "
        f"오류 코드: {getattr(error, 'code', None) or '없음'}"
    )


def fingerprint(value):
    return sha256(
        json.dumps(value, sort_keys=True, default=str).encode()
    ).hexdigest()[:16]


def base_query(client, user_id, profile_id):
    return (
        client.table("lifestyle_records")
        .select("*")
        .eq("user_id", user_id)
        .eq("profile_id", profile_id)
    )


def check_activity_conflict(
    client, user_id, profile_id, record_date, record_type
):
    opposite = {
        "activity": "no_activity",
        "no_activity": "activity",
    }.get(record_type)

    if opposite is None:
        return

    existing = (
        base_query(client, user_id, profile_id)
        .eq("record_date", record_date)
        .eq("record_type", opposite)
        .limit(1)
        .execute()
        .data
    )

    if existing:
        if record_type == "activity":
            raise ValueError(
                "이 날짜에 ‘활동 없음’이 저장되어 있어요. "
                "아래 기록 목록에서 해당 확인 기록을 삭제한 뒤 "
                "활동을 입력해 주세요."
            )

        raise ValueError(
            "이 날짜에는 이미 활동 기록이 있어요. "
            "잘못 입력한 활동이라면 아래 목록에서 먼저 삭제해 주세요."
        )


def format_minutes(minutes):
    hours, remaining = divmod(int(minutes), 60)

    if hours and remaining:
        return f"{hours}시간 {remaining}분"
    if hours:
        return f"{hours}시간"
    return f"{remaining}분"


def display_records(rows, kind_filter="전체"):
    result = []
    icons = {
        "meal": "🍽️",
        "activity": "🏃",
        "sleep": "😴",
        "no_activity": "📅",
    }

    for row in rows:
        kind = row["record_type"]
        day = row["record_date"]
        clock = str(row.get("record_time") or "")[:5]
        name = row.get("item_name") or ""
        slot = row.get("meal_slot") or ""
        amount = row.get("amount")

        amount_text = (
            f"{float(amount):g} {row.get('amount_unit') or ''}".strip()
            if amount is not None else ""
        )

        duration = row.get("duration_minutes")
        duration_text = (
            format_minutes(duration)
            if duration is not None else ""
        )

        intensity = row.get("intensity") or ""
        memo = row.get("memo") or ""
        wake_day = ""
        wake_clock = ""

        if kind == "sleep" and duration is not None:
            try:
                started = datetime.combine(
                    date.fromisoformat(day),
                    time.fromisoformat(
                        row.get("record_time") or "00:00"
                    ),
                )
                ended = started + timedelta(minutes=int(duration))
                wake_day = ended.date().isoformat()
                wake_clock = ended.strftime("%H:%M")
            except (ValueError, TypeError, OverflowError):
                wake_day = "날짜·시간 확인 필요"

        if kind_filter == "식사":
            record = {
                "날짜": day,
                "섭취 시간": clock,
                "음식명·사료명": name,
                "식사 구분": slot,
                "섭취량": amount_text,
                "메모": memo,
            }

        elif kind_filter == "운동·산책":
            record = {
                "날짜": day,
                "시작 시간": clock,
                "활동명": name,
                "활동 시간": duration_text,
                "강도": intensity,
                "메모": memo,
            }

        elif kind_filter == "수면":
            record = {
                "잠든 날짜": day,
                "잠든 시간": clock,
                "일어난 날짜": wake_day,
                "일어난 시간": wake_clock,
                "총 수면 시간": duration_text,
                "메모": memo,
            }

        elif kind_filter == "활동 없음":
            record = {
                "날짜": day,
                "확인 내용": "활동 없음 확인",
                "메모": memo,
            }

        else:
            if kind == "meal":
                detail = " · ".join(
                    value for value in [slot, amount_text] if value
                )
            elif kind == "activity":
                detail = " · ".join(
                    value for value in [duration_text, intensity]
                    if value
                )
            elif kind == "sleep":
                detail = (
                    f"{duration_text} · 기상 {wake_day} {wake_clock}"
                ).strip()
            else:
                detail = (
                    "직접 확인한 기록"
                    if kind == "no_activity" else ""
                )

            record = {
                "날짜": day,
                "시간": clock or "—",
                "종류": (
                    f"{icons.get(kind, '')} "
                    f"{TYPE_LABELS.get(kind, kind)}"
                ).strip(),
                "기록 내용": name,
                "상세": detail,
                "메모": memo,
            }

        result.append(record)

    return pd.DataFrame(result)


def style_record_table(table, rows):
    colors = {
        "meal": "#FFF4E8",
        "activity": "#ECF7F0",
        "sleep": "#F2EEFC",
        "no_activity": "#F1F3F6",
    }

    row_colors = [
        colors.get(row["record_type"], "#FFFFFF")
        for row in rows
    ]

    return table.style.apply(
        lambda row: [
            f"background-color: {row_colors[row.name]}; "
            "color: #243247"
        ] * len(row),
        axis=1,
    )


def show_record_summary(rows, start, end, kind_filter):
    st.markdown("### 📊 선택한 기간의 기록 요약")
    st.caption(
        f"{start:%Y-%m-%d} ~ {end:%Y-%m-%d} · "
        "아래 표에 표시된 기록 기준이에요."
    )

    period_days = (end - start).days + 1
    meal_days = {
        row["record_date"] for row in rows
        if row["record_type"] == "meal"
    }
    activities = [
        row for row in rows
        if row["record_type"] == "activity"
    ]
    sleeps = [
        row for row in rows
        if row["record_type"] == "sleep"
        and row.get("duration_minutes") is not None
        and float(row["duration_minutes"]) > 0
    ]
    confirmed_days = {
        row["record_date"] for row in rows
        if row["record_type"] == "no_activity"
    }

    metrics = []

    if kind_filter in ["전체", "식사"]:
        metrics.append((
            "🍽️ 식사 기록일",
            f"{len(meal_days)}일 / {period_days}일",
            "음식을 여러 개 입력한 날도 하루로 계산해요. "
            "식사 횟수나 섭취량의 합계는 아니에요.",
        ))

    if kind_filter in ["전체", "운동·산책"]:
        activity_minutes = sum(
            int(row.get("duration_minutes") or 0)
            for row in activities
        )
        metrics.append((
            "🏃 총 활동 시간",
            format_minutes(activity_minutes)
            if activities else "기록 없음",
            "저장된 운동·산책 시간의 합계예요. "
            "같은 시간대에 중복 저장한 기록도 각각 포함돼요.",
        ))

    if kind_filter in ["전체", "수면"]:
        if sleeps:
            average = int(
                sum(int(row["duration_minutes"]) for row in sleeps)
                / len(sleeps) + 0.5
            )
            sleep_value = format_minutes(average)
        else:
            sleep_value = "기록 없음"

        metrics.append((
            "😴 기록당 평균 수면",
            sleep_value,
            "잠든 날짜가 조회 기간에 포함된 수면 기록의 평균이에요. "
            "여러 번 나눠 잔 경우 각 기록을 따로 계산하며, "
            "분 단위로 반올림해요.",
        ))

    if kind_filter == "활동 없음":
        metrics.append((
            "📅 활동 없음 확인일",
            f"{len(confirmed_days)}일 / {period_days}일",
            "직접 ‘활동 없음’을 확인해 저장한 날짜 수예요.",
        ))

    columns = st.columns(len(metrics))

    for column, (label, value, help_text) in zip(columns, metrics):
        with column:
            with st.container(border=True):
                st.metric(label, value, help=help_text)

    if kind_filter in ["전체", "운동·산책"]:
        st.caption(
            f"운동·산책 기록 {len(activities)}건 · "
            f"활동 없음 확인 {len(confirmed_days)}일"
        )

    if kind_filter in ["전체", "수면"]:
        st.caption(
            f"평균 수면 계산에 포함한 수면 기록: {len(sleeps)}건"
        )

    if len(rows) >= 1000:
        st.warning(
            "조회 결과가 최대 표시 건수인 1,000건에 도달했어요. "
            "요약과 그래프도 표시된 기록만 사용해요. "
            "기간 전체를 확인하려면 조회 기간을 줄여 주세요."
        )

    st.caption(
        "기록이 없는 날짜를 식사·활동·수면이 없었던 날로 "
        "계산하지 않아요."
    )
    st.divider()


def show_meal_calendar(rows, start, end, ui_scope):
    meals = [
        row for row in rows
        if row["record_type"] == "meal"
    ]

    st.markdown("### 🍽️ 날짜별 식사 기록")

    if not meals:
        st.info("선택한 기간에 표시할 식사 기록이 없어요.")
        return

    months = sorted(
        {row["record_date"][:7] for row in meals},
        reverse=True,
    )
    selected_month = st.selectbox(
        "식사 기록을 볼 월",
        months,
        format_func=lambda value: (
            f"{value[:4]}년 {int(value[5:7])}월"
        ),
        key=f"meal_calendar_month_{ui_scope}_{start}_{end}",
    )

    first_day = date.fromisoformat(selected_month + "-01")
    next_month = (
        first_day.replace(day=28) + timedelta(days=4)
    ).replace(day=1)

    visible_start = max(start, first_day)
    visible_end = min(end, next_month - timedelta(days=1))
    grouped = {}

    for row in meals:
        slot = row.get("meal_slot") or "기타"
        if slot not in MEAL_SLOTS:
            slot = "기타"
        grouped.setdefault(
            (row["record_date"], slot), []
        ).append(row)

    weekdays = ["월", "화", "수", "목", "금", "토", "일"]
    chart_rows = []
    day_labels = []
    current_day = visible_start

    while current_day <= visible_end:
        label = (
            f"{current_day:%m/%d} "
            f"({weekdays[current_day.weekday()]})"
        )
        day_labels.append(label)

        for slot in MEAL_SLOTS:
            items = grouped.get(
                (current_day.isoformat(), slot), []
            )
            descriptions = []

            for item in items:
                name = item.get("item_name") or "이름 없는 음식"
                amount = item.get("amount")
                unit = item.get("amount_unit") or ""
                clock = str(item.get("record_time") or "")[:5]
                amount_text = (
                    f" {float(amount):g} {unit}"
                    if amount is not None else ""
                )
                descriptions.append(
                    f"{clock} {name}{amount_text}".strip()
                )

            chart_rows.append({
                "날짜": current_day.isoformat(),
                "날짜 표시": label,
                "식사 구분": slot,
                "상태": "기록 있음" if items else "기록 없음",
                "음식 기록 수": len(items),
                "음식 목록": (
                    " / ".join(descriptions)
                    if items else "저장된 기록이 없어요."
                ),
            })

        current_day += timedelta(days=1)

    st.caption(
        "주황색은 식사 기록이 있는 칸, 회색은 기록이 없는 칸이에요. "
        "칸에 커서를 올리면 음식·섭취량·입력 시각을 확인할 수 있어요."
    )

    st.vega_lite_chart(
        pd.DataFrame(chart_rows),
        {
            "mark": {
                "type": "rect",
                "cornerRadius": 5,
                "stroke": "white",
                "strokeWidth": 3,
            },
            "height": {"step": 25},
            "encoding": {
                "x": {
                    "field": "식사 구분",
                    "type": "ordinal",
                    "sort": MEAL_SLOTS,
                    "axis": {
                        "title": None,
                        "orient": "top",
                        "labelAngle": 0,
                        "labelFontSize": 13,
                    },
                },
                "y": {
                    "field": "날짜 표시",
                    "type": "ordinal",
                    "sort": day_labels,
                    "axis": {
                        "title": None,
                        "labelFontSize": 12,
                    },
                },
                "color": {
                    "field": "상태",
                    "type": "nominal",
                    "scale": {
                        "domain": ["기록 없음", "기록 있음"],
                        "range": ["#ECEFF3", "#F5A65B"],
                    },
                    "legend": {
                        "title": None,
                        "orient": "bottom",
                    },
                },
                "tooltip": [
                    {"field": "날짜", "type": "nominal"},
                    {"field": "식사 구분", "type": "nominal"},
                    {"field": "상태", "type": "nominal"},
                    {
                        "field": "음식 기록 수",
                        "type": "quantitative",
                        "format": "d",
                    },
                    {"field": "음식 목록", "type": "nominal"},
                ],
            },
            "config": {"view": {"stroke": None}},
        },
        use_container_width=True,
    )

    st.caption(
        "조회 기간 안에서 식사 기록이 있는 월만 선택 목록에 표시해요. "
        "음식 여러 개를 저장해도 같은 날짜·식사 구분은 한 칸으로 표시해요. "
        "회색은 식사를 거르거나 먹지 않았다는 뜻이 아니에요."
    )
    st.divider()


def show_activity_chart(rows, start, end, ui_scope):
    activity_rows = [
        row for row in rows
        if row["record_type"] in ["activity", "no_activity"]
    ]

    st.markdown("### 🏃 날짜별 운동·산책 시간")

    if not activity_rows:
        st.info(
            "선택한 기간에 표시할 운동·산책 또는 "
            "활동 없음 확인 기록이 없어요."
        )
        return

    months = sorted(
        {row["record_date"][:7] for row in activity_rows},
        reverse=True,
    )
    selected_month = st.selectbox(
        "활동 기록을 볼 월",
        months,
        format_func=lambda value: (
            f"{value[:4]}년 {int(value[5:7])}월"
        ),
        key=f"activity_chart_month_{ui_scope}_{start}_{end}",
    )

    first_day = date.fromisoformat(selected_month + "-01")
    next_month = (
        first_day.replace(day=28) + timedelta(days=4)
    ).replace(day=1)

    visible_start = max(start, first_day)
    visible_end = min(end, next_month - timedelta(days=1))
    grouped = {}
    confirmed_days = set()

    for row in activity_rows:
        day = date.fromisoformat(row["record_date"])

        if not visible_start <= day <= visible_end:
            continue

        if row["record_type"] == "no_activity":
            confirmed_days.add(day.isoformat())
            continue

        name = row.get("item_name") or "기타 활동"
        group_key = (day.isoformat(), name)
        total, count = grouped.get(group_key, (0, 0))
        grouped[group_key] = (
            total + int(row.get("duration_minutes") or 0),
            count + 1,
        )

    weekdays = ["월", "화", "수", "목", "금", "토", "일"]
    labels = {}
    current_day = visible_start

    while current_day <= visible_end:
        labels[current_day.isoformat()] = (
            f"{current_day:%m/%d} "
            f"({weekdays[current_day.weekday()]})"
        )
        current_day += timedelta(days=1)

    totals = {}
    for (day, name), (minutes, count) in grouped.items():
        totals[day] = totals.get(day, 0) + minutes

    chart_rows = []

    for (day, name), (minutes, count) in sorted(grouped.items()):
        chart_rows.append({
            "날짜": day,
            "날짜 표시": labels[day],
            "표시 종류": "활동",
            "활동 종류": name,
            "활동 시간(분)": minutes,
            "활동 시간": format_minutes(minutes),
            "날짜별 총 활동 시간": format_minutes(totals[day]),
            "기록 수": count,
            "상태": "활동 기록 있음",
        })

    for day, label in labels.items():
        chart_rows.append({
            "날짜": day,
            "날짜 표시": label,
            "표시 종류": "날짜 기준",
            "활동 종류": "",
            "활동 시간(분)": 0,
            "활동 시간": "",
            "날짜별 총 활동 시간": "",
            "기록 수": 0,
            "상태": (
                "활동 없음 확인"
                if day in confirmed_days else ""
            ),
        })

    st.caption(
        "막대 높이는 날짜별 총 활동 시간이에요. "
        "활동 종류마다 색을 나눠 표시하며, 커서를 올리면 "
        "종류별 시간과 기록 수를 확인할 수 있어요."
    )

    st.vega_lite_chart(
        pd.DataFrame(chart_rows),
        {
            "height": 320,
            "encoding": {
                "x": {
                    "field": "날짜 표시",
                    "type": "ordinal",
                    "sort": list(labels.values()),
                    "axis": {
                        "title": None,
                        "labelAngle": -45,
                        "labelOverlap": False,
                        "labelFontSize": 11,
                    },
                },
                "y": {
                    "field": "활동 시간(분)",
                    "type": "quantitative",
                    "scale": {"zero": True},
                    "axis": {"title": "활동 시간(분)"},
                },
            },
            "layer": [
                {
                    "transform": [{
                        "filter": "datum['표시 종류'] === '활동'"
                    }],
                    "mark": {"type": "bar", "tooltip": True},
                    "encoding": {
                        "y": {
                            "field": "활동 시간(분)",
                            "type": "quantitative",
                            "stack": "zero",
                        },
                        "color": {
                            "field": "활동 종류",
                            "type": "nominal",
                            "scale": {"scheme": "tableau10"},
                            "legend": {
                                "title": "활동 종류",
                                "orient": "bottom",
                            },
                        },
                        "order": {
                            "field": "활동 종류",
                            "type": "nominal",
                        },
                        "tooltip": [
                            {"field": "날짜", "type": "nominal"},
                            {"field": "활동 종류", "type": "nominal"},
                            {"field": "활동 시간", "type": "nominal"},
                            {
                                "field": "날짜별 총 활동 시간",
                                "type": "nominal",
                            },
                            {
                                "field": "기록 수",
                                "type": "quantitative",
                                "format": "d",
                            },
                        ],
                    },
                },
                {
                    "transform": [{
                        "filter": "datum['표시 종류'] === '날짜 기준'"
                    }],
                    "mark": {"type": "point", "opacity": 0},
                    "encoding": {
                        "tooltip": {"value": None},
                    },
                },
                {
                    "transform": [{
                        "filter": (
                            "datum['표시 종류'] === '날짜 기준' "
                            "&& datum['상태'] === '활동 없음 확인'"
                        )
                    }],
                    "mark": {
                        "type": "point",
                        "shape": "square",
                        "filled": True,
                        "size": 100,
                        "color": "#8893A5",
                        "clip": False,
                    },
                    "encoding": {
                        "tooltip": [
                            {"field": "날짜", "type": "nominal"},
                            {"field": "상태", "type": "nominal"},
                        ],
                    },
                },
            ],
            "config": {"view": {"stroke": None}},
        },
        use_container_width=True,
    )

    st.caption(
        "0분 위치의 회색 네모는 직접 저장한 ‘활동 없음 확인’이에요. "
        "막대와 네모가 모두 없는 날짜는 기록이 없는 날이며, "
        "활동 시간이 0분이었다는 뜻은 아니에요."
    )
    st.caption(
        "조회 기간 안에서 활동 또는 활동 없음 확인 기록이 있는 "
        "월만 선택할 수 있어요. "
        "같은 날짜·활동 종류의 시간은 합산하며, "
        "중복되거나 시간이 겹치는 기록도 각각 포함해요."
    )
    st.divider()


def show_sleep_chart(rows, start, end, ui_scope):
    st.markdown("### 😴 잠든 시각과 일어난 시각")

    sleeps = []
    invalid_count = 0

    for row in rows:
        if row["record_type"] != "sleep":
            continue

        try:
            started = datetime.combine(
                date.fromisoformat(row["record_date"]),
                time.fromisoformat(
                    row.get("record_time") or "00:00"
                ),
            )
            duration = int(row.get("duration_minutes") or 0)

            if duration <= 0:
                raise ValueError("수면 시간 없음")

            ended = started + timedelta(minutes=duration)

        except (ValueError, TypeError, OverflowError):
            invalid_count += 1
            continue

        sleeps.append((
            started, ended, duration, str(row["id"])
        ))

    if invalid_count:
        st.warning(
            "날짜·시간 또는 수면 시간이 올바르지 않은 "
            f"수면 기록 {invalid_count}건은 그래프에서 제외했어요. "
            "아래 상세 기록을 확인해 주세요."
        )

    if not sleeps:
        st.info(
            "선택한 기간에 그래프로 표시할 수면 기록이 없어요."
        )
        return

    months = sorted(
        {item[0].strftime("%Y-%m") for item in sleeps},
        reverse=True,
    )
    selected_month = st.selectbox(
        "수면 기록을 볼 월",
        months,
        format_func=lambda value: (
            f"{value[:4]}년 {int(value[5:7])}월"
        ),
        key=f"sleep_chart_month_{ui_scope}_{start}_{end}",
    )

    month_sleeps = sorted(
        [
            item for item in sleeps
            if item[0].strftime("%Y-%m") == selected_month
        ],
        key=lambda item: (item[0], item[3]),
    )

    page_size = 31
    page_count = max(
        1, math.ceil(len(month_sleeps) / page_size)
    )
    page = 1

    if page_count > 1:
        page = int(st.number_input(
            "수면 그래프 묶음",
            min_value=1,
            max_value=page_count,
            value=1,
            step=1,
            key=(
                f"sleep_chart_page_{ui_scope}_{start}_{end}_"
                f"{selected_month}_{fingerprint(month_sleeps)}"
            ),
            help="기록이 많으면 31건씩 나눠 표시해요.",
        ))

    offset = (page - 1) * page_size
    visible = month_sleeps[offset:offset + page_size]

    weekdays = ["월", "화", "수", "목", "금", "토", "일"]
    chart_rows = []
    labels = []

    for index, item in enumerate(visible, start=offset + 1):
        started, ended, duration, record_id = item
        label = (
            f"{started:%m/%d} "
            f"({weekdays[started.weekday()]}) · {index}번"
        )
        labels.append(label)

        midnight = datetime.combine(started.date(), time(0, 0))

        chart_rows.append({
            "수면 기록": label,
            "잠든 시각 위치": (
                (started - midnight).total_seconds() / 3600
            ),
            "일어난 시각 위치": (
                (ended - midnight).total_seconds() / 3600
            ),
            "잠든 날짜·시간": started.strftime("%Y-%m-%d %H:%M"),
            "일어난 날짜·시간": ended.strftime("%Y-%m-%d %H:%M"),
            "총 수면 시간": format_minutes(duration),
        })

    max_hour = max(
        item["일어난 시각 위치"] for item in chart_rows
    )
    tick_step = (
        6 if max_hour <= 48
        else max(24, math.ceil(max_hour / 8 / 24) * 24)
    )
    axis_end = max(
        24, math.ceil(max_hour / tick_step) * tick_step
    )

    label_expression = (
        "(floor(datum.value / 24) === 0 ? '' : "
        "floor(datum.value / 24) === 1 ? '다음 날 ' : "
        "'+' + floor(datum.value / 24) + '일 ') + "
        "format(datum.value % 24, '02d') + ':00'"
    )

    st.caption(
        "보라색 막대 하나가 수면 기록 한 건이에요. "
        "왼쪽은 잠든 시각, 오른쪽은 일어난 시각이며, "
        "같은 날 여러 번 잔 기록도 각각 표시해요."
    )

    st.vega_lite_chart(
        pd.DataFrame(chart_rows),
        {
            "height": {"step": 30},
            "mark": {
                "type": "bar",
                "color": "#9580D8",
                "cornerRadius": 6,
                "size": 17,
            },
            "encoding": {
                "y": {
                    "field": "수면 기록",
                    "type": "ordinal",
                    "sort": labels,
                    "axis": {
                        "title": "잠든 날짜 · 기록 번호",
                        "labelFontSize": 12,
                    },
                },
                "x": {
                    "field": "잠든 시각 위치",
                    "type": "quantitative",
                    "scale": {
                        "domain": [0, axis_end],
                        "nice": False,
                    },
                    "axis": {
                        "title": "잠든 날짜의 00:00 기준",
                        "values": list(
                            range(0, axis_end + 1, tick_step)
                        ),
                        "labelExpr": label_expression,
                        "labelOverlap": True,
                    },
                },
                "x2": {"field": "일어난 시각 위치"},
                "tooltip": [
                    {
                        "field": "잠든 날짜·시간",
                        "type": "nominal",
                    },
                    {
                        "field": "일어난 날짜·시간",
                        "type": "nominal",
                    },
                    {
                        "field": "총 수면 시간",
                        "type": "nominal",
                    },
                ],
            },
            "config": {"view": {"stroke": None}},
        },
        use_container_width=True,
    )

    st.caption(
        f"선택한 월의 수면 {len(month_sleeps)}건 중 "
        f"{offset + 1}~{offset + len(visible)}번 표시 · "
        "잠든 날짜가 조회 기간에 포함된 기록 기준이에요."
    )
    st.caption(
        "가로축의 ‘다음 날’은 각 기록에서 잠든 날짜의 "
        "다음 날을 뜻해요. "
        "예를 들어 23:00부터 다음 날 07:00까지의 수면은 "
        "자정을 지나 이어지는 막대로 표시해요. "
        "정확한 날짜·시간과 총 수면 시간은 막대에 커서를 "
        "올려 확인해 주세요."
    )
    st.divider()


def build_edit_values(kind, form, now):
    now = now.replace(tzinfo=None)
    day = form["date"]

    if kind not in TYPE_LABELS:
        raise ValueError("수정할 수 없는 기록 종류예요.")

    values = {
        "record_date": day.isoformat(),
        "record_time": None,
        "item_name": None,
        "meal_slot": None,
        "amount": None,
        "amount_unit": None,
        "duration_minutes": None,
        "intensity": None,
        "memo": form.get("memo", "").strip(),
    }

    if kind == "no_activity":
        if day >= now.date():
            raise ValueError(
                "활동 없음은 하루가 끝난 날짜에만 기록해 주세요."
            )
        if not form.get("confirmed"):
            raise ValueError("활동 없음 확인란을 체크해 주세요.")

        values["item_name"] = "활동 없음 확인"
        return values

    clock = form["time"].replace(
        second=0, microsecond=0, tzinfo=None
    )
    started = datetime.combine(day, clock)

    if started > now:
        raise ValueError(
            "아직 지나지 않은 시각으로 수정할 수 없어요."
        )

    values["record_time"] = clock.strftime("%H:%M")

    if kind == "meal":
        name = form.get("name", "").strip()
        amount = float(form.get("amount", 0))
        unit = form.get("unit", "").strip()
        slot = form.get("meal_slot")

        if not name:
            raise ValueError("음식명·사료명을 입력해 주세요.")
        if not math.isfinite(amount) or amount <= 0:
            raise ValueError(
                "섭취량은 0보다 큰 숫자로 입력해 주세요."
            )
        if not unit or slot not in MEAL_SLOTS:
            raise ValueError(
                "섭취량 단위와 식사 구분을 확인해 주세요."
            )

        values.update(
            item_name=name,
            amount=amount,
            amount_unit=unit,
            meal_slot=slot,
        )

    elif kind == "activity":
        name = form.get("name", "").strip()
        duration = int(form.get("duration", 0))
        intensity = form.get("intensity")

        if not name:
            raise ValueError("활동명을 입력해 주세요.")
        if not 1 <= duration <= 1440 or intensity not in INTENSITIES:
            raise ValueError("활동 시간과 강도를 확인해 주세요.")

        ended = started + timedelta(minutes=duration)

        if ended > now:
            raise ValueError(
                "활동이 끝난 뒤 실제 활동 시간을 기록해 주세요."
            )

        next_midnight = datetime.combine(
            day + timedelta(days=1), time(0, 0)
        )
        if ended > next_midnight:
            raise ValueError(
                "자정을 넘긴 활동은 날짜별로 나눠 기록해 주세요."
            )

        values.update(
            item_name=name,
            duration_minutes=duration,
            intensity=intensity,
        )

    elif kind == "sleep":
        wake_clock = form["wake_time"].replace(
            second=0, microsecond=0, tzinfo=None
        )
        ended = datetime.combine(form["wake_date"], wake_clock)
        duration = int((ended - started).total_seconds() // 60)

        if duration <= 0:
            raise ValueError(
                "일어난 시각은 잠든 시각보다 늦어야 해요."
            )
        if ended > now:
            raise ValueError(
                "일어난 시각은 현재보다 늦을 수 없어요."
            )

        values.update(
            item_name="수면",
            duration_minutes=duration,
        )

    return values


def show_lifestyle_editor(client, user_id, profile_id, row):
    kind = row["record_type"]

    if kind not in TYPE_LABELS:
        st.info("이 종류의 기록은 수정 화면을 지원하지 않아요.")
        return

    scope = f"{user_id}_{profile_id}"
    timezone_name = get_timezone_name()
    prefix = (
        f"lifestyle_edit_{scope}_{row['id']}_"
        f"{fingerprint(row)}_{timezone_name}"
    )

    now = get_local_now()
    original_day = date.fromisoformat(row["record_date"])
    original_clock = time.fromisoformat(
        row.get("record_time") or "00:00"
    )
    latest_day = (
        now.date() - timedelta(days=1)
        if kind == "no_activity" else now.date()
    )

    st.markdown("### ✏️ 선택한 기록 수정")
    st.caption(
        f"기록 종류: {TYPE_LABELS[kind]} · "
        "종류는 유지하고 내용을 수정해요."
    )
    st.caption(f"수정 날짜·시간 기준: {timezone_name}")

    if kind == "sleep":
        st.info(
            "밤 12시(자정)는 24:00이 아니라 "
            "다음 날 00:00으로 입력해 주세요. "
            "예를 들어 11월 5일 밤 12시에 잠들었다면 "
            "잠든 날짜는 11월 6일, 잠든 시간은 00:00으로 "
            "선택해 주세요. "
            "일어난 시각이 자정인 경우에도 같은 기준으로 "
            "날짜와 시간을 선택해 주세요."
        )

    form = {}

    with st.form(prefix):
        form["date"] = st.date_input(
            "잠든 날짜 수정"
            if kind == "sleep" else "기록 날짜 수정",
            value=original_day,
            max_value=max(original_day, latest_day),
        )

        if kind != "no_activity":
            form["time"] = st.time_input(
                "잠든 시간 수정"
                if kind == "sleep" else "시작·섭취 시간 수정",
                value=original_clock,
                step=60,
            )

        if kind == "meal":
            form["name"] = st.text_input(
                "음식명·사료명 수정",
                value=row.get("item_name") or "",
            )
            slot = row.get("meal_slot") or "기타"

            form["meal_slot"] = st.selectbox(
                "식사 구분 수정",
                MEAL_SLOTS,
                index=(
                    MEAL_SLOTS.index(slot)
                    if slot in MEAL_SLOTS else 4
                ),
            )
            form["amount"] = st.number_input(
                "먹은 양 수정",
                min_value=0.0,
                value=float(row.get("amount") or 0),
                step=0.5,
            )

            original_unit = row.get("amount_unit") or "g"
            units = (
                UNITS if original_unit in UNITS
                else UNITS + [original_unit]
            )
            form["unit"] = st.selectbox(
                "단위 수정",
                units,
                index=units.index(original_unit),
            )

        elif kind == "activity":
            form["name"] = st.text_input(
                "활동명 수정",
                value=row.get("item_name") or "",
            )
            original_duration = max(
                1, int(row.get("duration_minutes") or 1)
            )
            form["duration"] = st.number_input(
                "활동 시간 수정(분)",
                min_value=1,
                max_value=max(1440, original_duration),
                value=original_duration,
                step=1,
            )

            intensity = row.get("intensity") or "보통"
            form["intensity"] = st.selectbox(
                "활동 강도 수정",
                INTENSITIES,
                index=(
                    INTENSITIES.index(intensity)
                    if intensity in INTENSITIES else 1
                ),
            )

        elif kind == "sleep":
            original_end = datetime.combine(
                original_day, original_clock
            ) + timedelta(
                minutes=int(row.get("duration_minutes") or 1)
            )

            form["wake_date"] = st.date_input(
                "일어난 날짜 수정",
                value=original_end.date(),
                max_value=max(original_end.date(), now.date()),
            )
            form["wake_time"] = st.time_input(
                "일어난 시간 수정",
                value=original_end.time(),
                step=60,
            )

        else:
            form["confirmed"] = st.checkbox(
                "수정한 날짜에 따로 기록할 운동·산책 활동이 "
                "없었음을 확인했어요."
            )

        form["memo"] = st.text_area(
            "보충 메모 수정",
            value=row.get("memo") or "",
        )
        save = st.form_submit_button(
            "💾 수정 내용 저장",
            use_container_width=True,
        )

    if not save:
        return

    try:
        values = build_edit_values(kind, form, get_local_now())
        check_activity_conflict(
            client, user_id, profile_id,
            values["record_date"], kind,
        )

        result = (
            client.table("lifestyle_records")
            .update(values, returning="representation")
            .eq("user_id", user_id)
            .eq("profile_id", profile_id)
            .eq("id", row["id"])
            .eq("record_type", kind)
            .execute()
        )

        if not result.data:
            raise ValueError(
                "변경된 기록이 없어요. 목록을 다시 불러와 주세요."
            )

    except ValueError as error:
        st.warning(str(error))

    except Exception as error:
        if getattr(error, "code", None) == "23505":
            st.warning(
                "이 날짜에는 이미 활동 없음 확인이 있어요. "
                "날짜를 확인해 주세요."
            )
        else:
            show_error(
                "수정 결과를 확인하지 못했어요. "
                "목록을 다시 불러와 주세요.",
                error,
            )

    else:
        st.session_state.pop(
            f"care_record_context_{scope}", None
        )
        st.session_state.pop(
            f"record_ai_result_{scope}", None
        )
        st.session_state.lifestyle_notice = (
            user_id, profile_id,
            "선택한 기록을 수정했어요.",
        )
        st.rerun()


st.set_page_config(
    page_title="식사·활동 기록 | 당당케어",
    page_icon="📝",
    layout="wide",
)

st.markdown(
    """
<style>
.stApp {
    background-color: #FFF9F9;
}

div.stButton > button {
    border-radius: 14px;
}

div[data-testid="stForm"] {
    padding: 22px;
    border-radius: 18px;
    background: white;
    border: 1px solid #EEEEEE;
}
</style>
""",
    unsafe_allow_html=True,
)

profile_menu = show_sidebar_menu("pages/lifestyle.py")
client, user = require_login()
timezone_name = get_timezone_name()

try:
    profiles = (
        client.table("care_profiles")
        .select("id,name,profile_type,animal_type")
        .eq("user_id", user.id)
        .order("created_at")
        .execute()
        .data
    ) or []

except Exception as error:
    show_error("관리 대상을 불러오지 못했어요.", error)
    st.stop()

if not profiles:
    st.info("먼저 혈당 기록하기에서 관리 대상을 등록해 주세요.")
    st.page_link(
        "pages/record.py",
        label="관리 대상 등록하러 가기",
        icon="➕",
    )
    st.stop()

profile_map = {
    item["id"]: item for item in profiles
}

if st.session_state.get("active_profile") not in profile_map:
    st.session_state.active_profile = profiles[0]["id"]

with profile_menu:
    st.caption("관리 대상")

    for item in profiles:
        icon = "👤" if item["profile_type"] == "사람" else "🐾"
        kind = item.get("animal_type") or item["profile_type"]
        label = f"{icon} {item['name']} · {kind}"

        if sum(p["name"] == item["name"] for p in profiles) > 1:
            label += f" · {item['id'][:8]}"

        active = item["id"] == st.session_state.active_profile

        if st.button(
            label,
            key=f"lifestyle_profile_{user.id}_{item['id']}",
            type="primary" if active else "secondary",
            use_container_width=True,
        ):
            st.session_state.active_profile = item["id"]
            st.rerun()

profile_id = st.session_state.active_profile
profile = profile_map[profile_id]
scope = f"{user.id}_{profile_id}"
ui_scope = f"{scope}_{timezone_name}"

now = get_local_now()
today = now.date()
clock = now.time().replace(second=0, microsecond=0)

st.title("📝 식사·활동 기록")
st.caption(
    "실제로 먹은 음식과 활동을 날짜·시간·양으로 기록해요. "
    "입력하지 않은 항목은 ‘없음’으로 판단하지 않아요."
)
st.caption(
    f"날짜·시간 기준: {timezone_name} · "
    f"현재 시각 {now:%Y-%m-%d %H:%M}"
)
st.subheader(f"{profile['name']}의 식사·활동")

notice = st.session_state.pop("lifestyle_notice", None)

if notice and notice[:2] == (user.id, profile_id):
    st.success(notice[2])

selected_type = st.radio(
    "무엇을 기록할까요?",
    list(TYPES),
    horizontal=True,
    key=f"lifestyle_type_{ui_scope}",
)

record_type = TYPES[selected_type]
is_pet = profile["profile_type"] == "반려동물"
revision_key = f"lifestyle_form_revision_{scope}"
revision = st.session_state.get(revision_key, 0)

food_count = 1
activity_name = None
custom_activity = ""

if record_type == "meal":
    st.caption(
        "같은 식사에서 먹은 음식을 음식별로 입력해요. "
        "섭취량은 실제 먹은 양을 적어 주세요."
    )
    food_count = st.number_input(
        "입력할 음식 개수",
        min_value=1,
        max_value=10,
        value=1,
        step=1,
        key=f"food_count_{ui_scope}",
    )

elif record_type == "activity":
    activities = (
        ["산책", "실내 놀이", "달리기", "기타"]
        if is_pet
        else ["걷기", "달리기", "자전거", "근력 운동", "수영", "기타"]
    )
    activity_name = st.selectbox(
        "활동 종류",
        activities,
        key=f"activity_kind_{ui_scope}",
    )

    if activity_name == "기타":
        custom_activity = st.text_input(
            "기타 활동 입력",
            placeholder="예: 계단 오르기, 배드민턴, 공놀이",
            max_chars=100,
            key=f"custom_activity_{ui_scope}_{revision}",
        )
        st.caption(
            "실제로 한 활동을 입력해 주세요. 입력한 이름으로 저장돼요."
        )

    st.caption(
        "시작 시각과 지속 시간을 입력해요. "
        "자정을 넘긴 활동은 날짜별로 나눠 기록해 주세요."
    )

elif record_type == "sleep":
    st.caption(
        "잠든 날짜·시간과 일어난 날짜·시간을 입력해요. "
        "기록 날짜는 잠들기 시작한 날짜로 저장돼요."
    )
    st.info(
        "밤 12시(자정)는 24:00이 아니라 "
        "다음 날 00:00으로 입력해 주세요. "
        "예를 들어 11월 5일 밤 12시에 잠들었다면 "
        "잠든 날짜는 11월 6일, 잠든 시간은 00:00으로 "
        "선택해 주세요. "
        "일어난 시각이 자정인 경우에도 같은 기준으로 "
        "날짜와 시간을 선택해 주세요."
    )

else:
    st.info(
        "운동·산책 등 따로 기록할 활동이 없었던 날을 확인해요. "
        "하루가 끝난 어제 이전 날짜만 선택할 수 있어요."
    )

form_key = (
    f"lifestyle_form_{ui_scope}_{record_type}_{revision}"
)

with st.form(form_key):
    default_date = (
        today - timedelta(days=1)
        if record_type in ["sleep", "no_activity"] else today
    )
    latest_date = (
        today - timedelta(days=1)
        if record_type == "no_activity" else today
    )

    record_date = st.date_input(
        "잠든 날짜" if record_type == "sleep" else "기록 날짜",
        value=default_date,
        max_value=latest_date,
    )

    record_time = None

    if record_type != "no_activity":
        record_time = st.time_input(
            "잠든 시간"
            if record_type == "sleep" else "시작·섭취 시간",
            value=time(23, 0) if record_type == "sleep" else clock,
            step=60,
        )

    foods = []
    meal_slot = None
    duration = None
    intensity = None
    wake_date = None
    wake_time = None
    confirmed = False

    if record_type == "meal":
        meal_slot = st.selectbox("식사 구분", MEAL_SLOTS)

        for index in range(int(food_count)):
            st.markdown(f"**음식 {index + 1}**")
            c1, c2, c3 = st.columns([2, 1, 1])

            food_name = c1.text_input(
                "음식명·사료명",
                key=f"{form_key}_food_{index}",
                placeholder="예: 현미밥 또는 사료 제품명",
            )
            amount = c2.number_input(
                "먹은 양",
                min_value=0.0,
                value=0.0,
                step=0.5,
                key=f"{form_key}_amount_{index}",
            )
            unit = c3.selectbox(
                "단위",
                UNITS,
                key=f"{form_key}_unit_{index}",
            )
            foods.append((food_name, amount, unit))

        st.caption(
            "같은 ‘컵·공기·개’라도 실제 양은 다를 수 있어요. "
            "무게를 잴 수 있으면 g으로 기록해 주세요."
        )

    elif record_type == "activity":
        duration = st.number_input(
            "활동 시간(분)",
            min_value=1,
            max_value=1440,
            value=20,
            step=1,
        )
        intensity = st.selectbox(
            "느낀 활동 강도", INTENSITIES
        )

    elif record_type == "sleep":
        wake_date = st.date_input(
            "일어난 날짜",
            value=today,
            max_value=today,
        )
        wake_time = st.time_input(
            "일어난 시간",
            value=time(7, 0),
            step=60,
        )

    else:
        confirmed = st.checkbox(
            "이 날짜에 따로 기록할 운동·산책 활동이 "
            "없었음을 확인했어요."
        )

    memo = st.text_area(
        "보충 메모(선택)",
        placeholder="추가로 남길 내용이 있을 때만 입력해 주세요.",
    )
    submitted = st.form_submit_button(
        "💾 기록 저장",
        use_container_width=True,
    )

    save_notice = st.session_state.pop(
        f"lifestyle_save_notice_{scope}", None
    )

    if save_notice:
        st.success(save_notice)

if submitted:
    now = get_local_now()
    today = now.date()

    try:
        values = {
            "user_id": user.id,
            "profile_id": profile_id,
            "record_type": record_type,
            "record_date": record_date.isoformat(),
            "record_time": (
                record_time.strftime("%H:%M")
                if record_time is not None else None
            ),
            "memo": memo.strip(),
        }

        started = None

        if record_time is not None:
            started = datetime.combine(record_date, record_time)
            if started > now.replace(tzinfo=None):
                raise ValueError(
                    "아직 지나지 않은 시각은 기록할 수 없어요."
                )

        if record_type == "meal":
            if any(
                not name.strip() or amount <= 0
                for name, amount, unit in foods
            ):
                raise ValueError(
                    "모든 음식의 이름과 0보다 큰 섭취량을 입력해 주세요."
                )

            payload = [
                {
                    **values,
                    "item_name": name.strip(),
                    "meal_slot": meal_slot,
                    "amount": amount,
                    "amount_unit": unit,
                }
                for name, amount, unit in foods
            ]

        elif record_type == "activity":
            name = (
                custom_activity.strip()
                if activity_name == "기타" else activity_name
            )

            if not name:
                raise ValueError(
                    "‘기타 활동 입력’ 칸에 실제 활동명을 입력해 주세요."
                )

            ended = started + timedelta(minutes=int(duration))

            if ended > now.replace(tzinfo=None):
                raise ValueError(
                    "활동이 끝난 뒤 실제 활동 시간을 기록해 주세요."
                )

            next_midnight = datetime.combine(
                record_date + timedelta(days=1), time(0, 0)
            )
            if ended > next_midnight:
                raise ValueError(
                    "자정을 넘긴 활동은 날짜별로 나눠 기록해 주세요."
                )

            payload = [{
                **values,
                "item_name": name,
                "duration_minutes": int(duration),
                "intensity": intensity,
            }]

        elif record_type == "sleep":
            ended = datetime.combine(wake_date, wake_time)
            minutes = int(
                (ended - started).total_seconds() // 60
            )

            if minutes <= 0:
                raise ValueError(
                    "일어난 시각은 잠든 시각보다 늦어야 해요."
                )
            if ended > now.replace(tzinfo=None):
                raise ValueError(
                    "일어난 시각이 현재보다 늦게 입력되어 있어요."
                )

            payload = [{
                **values,
                "item_name": "수면",
                "duration_minutes": minutes,
            }]

        else:
            if not confirmed:
                raise ValueError(
                    "활동 없음 확인란을 체크해 주세요."
                )
            if record_date >= today:
                raise ValueError(
                    "활동 없음은 하루가 끝난 날짜에만 기록해 주세요."
                )

            payload = [{
                **values,
                "item_name": "활동 없음 확인",
            }]

        check_activity_conflict(
            client, user.id, profile_id,
            record_date.isoformat(), record_type,
        )

        (
            client.table("lifestyle_records")
            .insert(payload, returning="minimal")
            .execute()
        )

    except ValueError as error:
        st.warning(str(error))

    except Exception as error:
        if getattr(error, "code", None) == "23505":
            st.warning(
                "이미 같은 날짜의 활동 없음 확인이 저장되어 있어요. "
                "아래 목록을 확인해 주세요."
            )
        else:
            show_error(
                "저장 결과를 확인하지 못했어요. "
                "중복 저장 전에 아래 기록 목록을 확인해 주세요.",
                error,
            )

    else:
        st.session_state[revision_key] = revision + 1
        st.session_state[f"lifestyle_save_notice_{scope}"] = (
            f"{len(payload)}건의 기록을 저장했어요."
        )
        st.rerun()

st.divider()
st.subheader("📋 저장한 식사·활동 기록")

c1, c2 = st.columns(2)

start = c1.date_input(
    "조회 시작일",
    value=today - timedelta(days=6),
    key=f"lifestyle_start_{ui_scope}",
)
end = c2.date_input(
    "조회 종료일",
    value=today,
    key=f"lifestyle_end_{ui_scope}",
)

kind_filter = st.selectbox(
    "기록 종류",
    ["전체"] + list(TYPE_LABELS.values()),
    key=f"lifestyle_filter_{ui_scope}",
)

if start > end:
    st.warning("조회 시작일은 종료일보다 늦을 수 없어요.")
    st.stop()

try:
    query = (
        base_query(client, user.id, profile_id)
        .gte("record_date", start.isoformat())
        .lte("record_date", end.isoformat())
    )

    if kind_filter != "전체":
        filter_code = next(
            code for code, label in TYPE_LABELS.items()
            if label == kind_filter
        )
        query = query.eq("record_type", filter_code)

    rows = (
        query.order("record_date", desc=True)
        .order("record_time", desc=True)
        .order("id")
        .limit(1000)
        .execute()
        .data
    ) or []

except Exception as error:
    show_error("기록을 불러오지 못했어요.", error)
    st.stop()

if not rows:
    st.info(
        "선택한 조건에 해당하는 기록이 없어요. "
        "기록이 없다는 것은 활동이나 식사가 없었다는 뜻은 아니에요."
    )
    st.stop()

show_record_summary(rows, start, end, kind_filter)

if kind_filter in ["전체", "식사"]:
    show_meal_calendar(rows, start, end, ui_scope)

if kind_filter in ["전체", "운동·산책", "활동 없음"]:
    show_activity_chart(rows, start, end, ui_scope)

if kind_filter in ["전체", "수면"]:
    show_sleep_chart(rows, start, end, ui_scope)

st.markdown("### 📋 상세 기록 확인·수정")
st.caption(
    f"최신 기록 {len(rows)}건 표시 · 최대 1,000건. "
    "식사는 음식 한 종류당 한 행으로 표시해요. "
    "수정하거나 삭제할 기록은 표 맨 왼쪽, 날짜 앞에 있는 "
    "네모 선택 칸을 눌러 체크해 주세요. "
    "체크하면 표 아래에 해당 기록의 전체 메모와 "
    "수정·삭제 화면이 나타나요."
)

table = display_records(rows, kind_filter)

st.caption(
    "행 색상: 🍽️ 식사 — 연한 주황 · "
    "🏃 운동·산책 — 연한 초록 · "
    "😴 수면 — 연한 보라 · "
    "📅 활동 없음 — 연한 회색"
)

event = st.dataframe(
    style_record_table(table, rows),
    hide_index=True,
    use_container_width=True,
    column_config={
        "메모": st.column_config.TextColumn(
            "메모", width="medium"
        ),
        "상세": st.column_config.TextColumn(
            "상세", width="large"
        ),
    },
    on_select="rerun",
    selection_mode="single-row",
    key=f"lifestyle_table_{ui_scope}_{fingerprint(rows)}",
)

st.download_button(
    "📥 표시된 기록 CSV 다운로드",
    data=table.to_csv(index=False).encode("utf-8-sig"),
    file_name="lifestyle_records.csv",
    mime="text/csv",
    key=f"lifestyle_csv_{ui_scope}",
)

positions = event["selection"]["rows"]

if positions and 0 <= positions[0] < len(rows):
    row = rows[positions[0]]

    st.markdown("### 선택한 기록")
    st.write(
        f"{row['record_date']} "
        f"{str(row.get('record_time') or '')[:5]} · "
        f"{TYPE_LABELS.get(row['record_type'], row['record_type'])} · "
        f"{row.get('item_name') or ''}"
    )

    with st.container(border=True):
        st.markdown("**📝 선택한 기록의 전체 메모**")
        if row.get("memo"):
            st.text(row["memo"])
        else:
            st.caption("저장한 메모가 없어요.")

    show_lifestyle_editor(
        client=client,
        user_id=user.id,
        profile_id=profile_id,
        row=row,
    )

    with st.form(
        f"lifestyle_delete_{ui_scope}_{row['id']}_{fingerprint(row)}"
    ):
        st.warning(
            "선택한 한 행을 삭제해요. "
            "삭제한 기록은 앱에서 복구할 수 없어요."
        )
        confirm_delete = st.checkbox(
            "선택한 기록의 삭제를 확인했어요."
        )
        delete_clicked = st.form_submit_button(
            "🗑️ 선택한 기록 삭제"
        )

    if delete_clicked:
        if not confirm_delete:
            st.warning("삭제 확인란을 먼저 체크해 주세요.")

        else:
            try:
                result = (
                    client.table("lifestyle_records")
                    .delete(returning="representation")
                    .eq("user_id", user.id)
                    .eq("profile_id", profile_id)
                    .eq("id", row["id"])
                    .execute()
                )

            except Exception as error:
                show_error(
                    "삭제 결과를 확인하지 못했어요. "
                    "목록을 새로 확인해 주세요.",
                    error,
                )

            else:
                if result.data:
                    st.session_state.lifestyle_notice = (
                        user.id, profile_id,
                        "선택한 기록을 삭제했어요.",
                    )
                    st.rerun()
                else:
                    st.warning(
                        "삭제된 기록이 없어요. "
                        "목록을 새로 확인해 주세요."
                    )
