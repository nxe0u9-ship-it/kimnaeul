from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pandas as pd
import streamlit as st

from app_shared import require_login


MEALS = [
    "공복", "식전", "식후 1시간",
    "식후 2시간", "취침 전", "기타"
]

TIME_LABELS = [
    "새벽 (00~05시)",
    "오전 (06~11시)",
    "오후 (12~17시)",
    "저녁 (18~23시)"
]


def show_error(message, error):
    st.error(message)
    st.caption(
        f"오류 종류: {type(error).__name__} / "
        f"오류 코드: {getattr(error, 'code', None) or '없음'}"
    )


def activity_status(kinds):
    if "activity" in kinds and "no_activity" in kinds:
        return "기록 충돌"

    if "activity" in kinds:
        return "활동 기록 있음"

    if "no_activity" in kinds:
        return "활동 없음 확인"

    return "미입력"


def load_all_records(
    client, user_id, profile_id, table,
    fields, date_column, time_column,
    id_column, start, end
):
    # 일부 기록만으로 분석하지 않도록 나누어 불러온다.
    rows = []
    offset = 0

    while True:
        batch = (
            client.table(table)
            .select(fields)
            .eq("user_id", user_id)
            .eq("profile_id", profile_id)
            .gte(date_column, start.isoformat())
            .lte(date_column, end.isoformat())
            .order(date_column)
            .order(time_column)
            .order(id_column)
            .range(offset, offset + 499)
            .execute()
            .data
        ) or []

        if not batch:
            return rows

        rows.extend(batch)

        if len(rows) > 10000:
            raise ValueError(
                "조회 결과가 10,000건을 넘었어요. "
                "일부 기록만 분석하지 않도록 조회를 중단했어요. "
                "조회 기간을 줄여 주세요."
            )

        offset += len(batch)


def glucose_frame(rows):
    columns = [
        "record_id", "measure_date", "measure_time",
        "glucose", "meal", "memo"
    ]

    frame = pd.DataFrame(rows, columns=columns)

    frame["measured_at"] = pd.to_datetime(
        frame["measure_date"].astype(str)
        + " "
        + frame["measure_time"].astype(str),
        errors="coerce"
    )

    frame["glucose"] = pd.to_numeric(
        frame["glucose"],
        errors="coerce"
    )

    return frame.dropna(
        subset=["measured_at", "glucose"]
    ).copy()


def summarize(frame, group_column):
    return (
        frame.groupby(group_column)
        .agg(
            기록수=("glucose", "size"),
            측정일수=("measure_date", "nunique"),
            평균혈당=("glucose", "mean"),
            중앙값=("glucose", "median")
        )
        .rename(columns={
            "기록수": "기록 수",
            "측정일수": "측정한 날짜 수",
            "평균혈당": "평균 혈당 (mg/dL)",
            "중앙값": "중앙값 (mg/dL)"
        })
        .round(1)
    )


def timeline_frame(glucose_rows, lifestyle_rows, day):
    target_date = day.isoformat()
    events = []

    for row in glucose_rows:
        if row["measure_date"] != target_date:
            continue

        clock = str(row["measure_time"])[:5]

        events.append({
            "정렬": clock,
            "시간": clock,
            "종류": "🩸 혈당",
            "내용": (
                f"{row['glucose']} mg/dL · "
                f"{row.get('meal') or '측정 시점 미입력'}"
            ),
            "메모": row.get("memo") or ""
        })

    for row in lifestyle_rows:
        if row["record_date"] != target_date:
            continue

        kind = row["record_type"]
        clock = str(row.get("record_time") or "")[:5]
        name = row.get("item_name") or ""
        duration = row.get("duration_minutes")
        amount = row.get("amount")

        if kind == "meal":
            label = "🍽️ 식사"
            quantity = (
                f"{float(amount):g} "
                f"{row.get('amount_unit') or ''}"
                if amount is not None
                else "양 미입력"
            )
            detail = (
                f"{row.get('meal_slot') or '기타'} · "
                f"{name} · {quantity}"
            )

        elif kind == "activity":
            label = "🏃 운동·산책"
            detail = (
                f"{name} · {duration}분 · "
                f"강도 {row.get('intensity') or '미입력'}"
            )

        elif kind == "sleep":
            label = "😴 수면 시작"
            detail = f"{duration}분"

            if duration and row.get("record_time"):
                started = datetime.fromisoformat(
                    row["record_date"]
                    + "T"
                    + row["record_time"]
                )
                ended = started + timedelta(
                    minutes=int(duration)
                )
                detail += (
                    f" · 일어난 시각 "
                    f"{ended:%m/%d %H:%M}"
                )

        elif kind == "no_activity":
            label = "📅 활동 없음 확인"
            detail = "사용자가 해당 날짜의 활동 없음을 확인함"

        else:
            label = kind
            detail = name

        events.append({
            "정렬": clock or "99:99",
            "시간": clock or "하루 확인",
            "종류": label,
            "내용": detail,
            "메모": row.get("memo") or ""
        })

    if not events:
        return pd.DataFrame(
            columns=["시간", "종류", "내용", "메모"]
        )

    return (
        pd.DataFrame(events)
        .sort_values("정렬", kind="stable")
        .drop(columns=["정렬"])
        .reset_index(drop=True)
    )


st.set_page_config(
    page_title="내 기록 탐구실 | 당당케어",
    page_icon="🔍",
    layout="wide"
)

st.markdown("""
<style>
.stApp { background-color: #FFF9F9; }

div.stButton > button {
    border-radius: 14px;
}
</style>
""", unsafe_allow_html=True)


# 왼쪽 메뉴
st.sidebar.title("🩸 당당케어")

st.sidebar.page_link(
    "pages/home.py",
    label="우리 가족 케어",
    icon="🏠"
)

st.sidebar.page_link(
    "pages/record.py",
    label="혈당 기록하기",
    icon="🩸"
)

st.sidebar.page_link(
    "pages/history.py",
    label="기록 확인·수정",
    icon="📈"
)

st.sidebar.page_link(
    "pages/lifestyle.py",
    label="식사·활동 기록",
    icon="📝"
)

st.sidebar.page_link(
    "pages/meal.py",
    label="냉장고 식단 추천",
    icon="🍽️"
)

st.sidebar.page_link(
    "pages/explore.py",
    label="내 기록 탐구실",
    icon="🔍"
)

st.sidebar.page_link(
    "pages/visit.py",
    label="진료 준비 노트",
    icon="🏥"
)

profile_menu = st.sidebar.container()

st.sidebar.page_link(
    "pages/chat.py",
    label="AI에게 물어보기",
    icon="💬"
)

client, user = require_login()

st.title("🔍 내 기록 탐구실")
st.caption(
    "내가 저장한 혈당과 식사·활동 기록을 "
    "조건별로 살펴봐요."
)


# 관리 대상
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
    show_error(
        "관리 대상을 불러오지 못했어요.",
        error
    )
    st.stop()

if not profiles:
    st.info("먼저 관리 대상을 등록해 주세요.")
    st.page_link(
        "pages/record.py",
        label="관리 대상 등록하러 가기",
        icon="➕"
    )
    st.stop()

profile_map = {
    item["id"]: item
    for item in profiles
}

if st.session_state.get("active_profile") not in profile_map:
    st.session_state.active_profile = profiles[0]["id"]

with profile_menu:
    st.caption("관리 대상")

    for item in profiles:
        icon = (
            "👤"
            if item["profile_type"] == "사람"
            else "🐾"
        )
        kind = (
            item.get("animal_type")
            or item["profile_type"]
        )
        label = f"{icon} {item['name']} · {kind}"

        if sum(
            p["name"] == item["name"]
            for p in profiles
        ) > 1:
            label += f" · {item['id'][:8]}"

        active = (
            item["id"]
            == st.session_state.active_profile
        )

        if st.button(
            label,
            key=f"explore_profile_{user.id}_{item['id']}",
            type="primary" if active else "secondary",
            use_container_width=True
        ):
            st.session_state.active_profile = item["id"]
            st.rerun()


profile_id = st.session_state.active_profile
profile = profile_map[profile_id]
scope = f"{user.id}_{profile_id}"

st.subheader(f"{profile['name']}의 기록 탐색")

today = datetime.now(ZoneInfo("Asia/Seoul")).date()

c1, c2 = st.columns(2)

start = c1.date_input(
    "조회 시작일",
    value=today - timedelta(days=29),
    key=f"explore_start_{scope}"
)

end = c2.date_input(
    "조회 종료일",
    value=today,
    max_value=today,
    key=f"explore_end_{scope}"
)

if start > end:
    st.warning("조회 시작일은 종료일보다 늦을 수 없어요.")
    st.stop()

if (end - start).days > 365:
    st.warning("한 번에 조회하는 기간은 최대 366일이에요.")
    st.stop()


# 저장된 기록 조회
try:
    glucose_rows = load_all_records(
        client, user.id, profile_id,
        "blood_glucose",
        "record_id,measure_date,measure_time,glucose,meal,memo",
        "measure_date", "measure_time", "record_id",
        start, end
    )

    lifestyle_rows = load_all_records(
        client, user.id, profile_id,
        "lifestyle_records",
        (
            "id,record_date,record_time,record_type,"
            "item_name,meal_slot,amount,amount_unit,"
            "duration_minutes,intensity,memo"
        ),
        "record_date", "record_time", "id",
        start, end
    )

except ValueError as error:
    st.warning(str(error))
    st.stop()

except Exception as error:
    show_error(
        "탐구에 사용할 기록을 불러오지 못했어요.",
        error
    )
    st.stop()


blood = glucose_frame(glucose_rows)

c1, c2 = st.columns(2)

c1.metric(
    "조회한 혈당 기록",
    f"{len(glucose_rows)}건"
)

c2.metric(
    "조회한 식사·활동 기록",
    f"{len(lifestyle_rows)}건"
)

if len(blood) < len(glucose_rows):
    st.caption(
        "날짜·시간 또는 혈당값을 읽을 수 없는 기록은 "
        "혈당 통계에서 제외했어요."
    )

st.info(
    "아래 결과는 입력한 기록의 요약이에요. "
    "음식이나 운동이 혈당 변화의 원인이라고 "
    "판단하는 기능은 아니에요."
)

meal_filter = st.selectbox(
    "통계에서 비교할 측정 시점",
    MEALS,
    key=f"explore_meal_{scope}"
)

st.caption(
    f"시간대별·활동 기록별 통계는 "
    f"‘{meal_filter}’ 기록끼리만 비교해요. "
    "하루 타임라인에는 모든 측정 시점을 표시해요."
)

comparison = blood[
    blood["meal"] == meal_filter
].copy()

time_tab, activity_tab, timeline_tab = st.tabs([
    "🕐 시간대별 비교",
    "🏃 활동 기록별 비교",
    "📅 하루 타임라인"
])


# 시간대별 비교
with time_tab:
    st.subheader("어느 시간대에 어떤 값이 기록됐을까?")

    if comparison.empty:
        st.info(
            f"선택한 기간에 ‘{meal_filter}’ 혈당 기록이 없어요. "
            "위에서 측정 시점이나 기간을 바꿔 주세요."
        )

    else:
        hourly = comparison.copy()

        hourly["시간대"] = hourly["measured_at"].dt.hour.map(
            lambda hour: TIME_LABELS[hour // 6]
        )

        summary = summarize(
            hourly,
            "시간대"
        ).reindex(TIME_LABELS)

        summary = summary.dropna(subset=["기록 수"])

        for column in ["기록 수", "측정한 날짜 수"]:
            summary[column] = summary[column].astype(int)

        st.dataframe(
            summary,
            use_container_width=True
        )

        st.bar_chart(
            summary[["평균 혈당 (mg/dL)"]]
        )

        st.caption(
            "평균과 함께 기록 수·측정한 날짜 수를 확인해 주세요. "
            "같은 측정 시점이어도 음식·약물·측정 조건은 "
            "서로 다를 수 있어요."
        )


# 날짜별 활동 상태
day_kinds = {}

for row in lifestyle_rows:
    day_kinds.setdefault(
        row["record_date"], set()
    ).add(row["record_type"])

day_status = {
    day: activity_status(kinds)
    for day, kinds in day_kinds.items()
}


# 활동 기록별 비교
with activity_tab:
    st.subheader("측정한 날짜의 활동 기록에 따라 비교하기")

    st.caption(
        "해당 날짜에 활동 기록이 있는지로 분류해요. "
        "혈당 측정 전·후에 활동했는지는 이 통계에서 구분하지 않아요."
    )

    if comparison.empty:
        st.info(
            f"선택한 기간에 ‘{meal_filter}’ 혈당 기록이 없어요."
        )

    else:
        activity_data = comparison.copy()

        activity_data["활동 상태"] = (
            activity_data["measure_date"]
            .map(day_status)
            .fillna("미입력")
        )

        counts = (
            activity_data.groupby("활동 상태")
            .size()
            .rename("해당 혈당 기록 수")
            .to_frame()
        )

        st.markdown("**기록 분류 현황**")
        st.dataframe(
            counts,
            use_container_width=True
        )

        usable = activity_data[
            activity_data["활동 상태"].isin([
                "활동 기록 있음",
                "활동 없음 확인"
            ])
        ].copy()

        if usable.empty:
            st.info(
                "비교할 활동 확인 기록이 아직 없어요. "
                "식사·활동 기록 페이지에서 활동을 입력하거나 "
                "활동이 없었던 날짜를 직접 확인해 주세요."
            )

        else:
            summary = summarize(
                usable,
                "활동 상태"
            )

            st.markdown("**활동 상태별 혈당 요약**")
            st.dataframe(
                summary,
                use_container_width=True
            )

            st.bar_chart(
                summary[["평균 혈당 (mg/dL)"]]
            )

            if len(summary) < 2:
                st.info(
                    "현재는 한쪽 조건의 기록만 있어요. "
                    "두 조건을 비교하려면 다른 조건의 기록도 필요해요."
                )

            elif (
                (summary["기록 수"] < 3).any()
                or (summary["측정한 날짜 수"] < 2).any()
            ):
                st.caption(
                    "한쪽 조건의 기록이 적거나 "
                    "한 날짜에 몰려 있어요. "
                    "표의 숫자는 현재 기록의 요약으로만 살펴봐 주세요."
                )

        if (activity_data["활동 상태"] == "기록 충돌").any():
            st.warning(
                "같은 날짜에 활동 기록과 ‘활동 없음’ 확인이 "
                "함께 있어요. 해당 날짜는 비교에서 제외했어요. "
                "식사·활동 기록 페이지에서 확인해 주세요."
            )

        st.caption(
            "‘미입력’은 활동을 하지 않았다는 뜻이 아니므로 "
            "활동 없음 그룹에 포함하지 않아요."
        )


# 하루 타임라인
with timeline_tab:
    st.subheader("하루의 기록을 시간순으로 보기")

    day = st.date_input(
        "살펴볼 날짜",
        value=end,
        min_value=start,
        max_value=end,
        key=f"explore_day_{scope}_{start}_{end}"
    )

    timeline = timeline_frame(
        glucose_rows,
        lifestyle_rows,
        day
    )

    if timeline.empty:
        st.info("이 날짜에는 저장된 기록이 없어요.")

    else:
        st.dataframe(
            timeline,
            hide_index=True,
            use_container_width=True
        )

        st.download_button(
            "📥 이 날짜의 타임라인 CSV 다운로드",
            data=timeline.to_csv(
                index=False
            ).encode("utf-8-sig"),
            file_name=f"care_timeline_{day.isoformat()}.csv",
            mime="text/csv",
            key=f"explore_csv_{scope}_{day}"
        )

    day_blood = blood[
        blood["measure_date"] == day.isoformat()
    ].sort_values("measured_at")

    if not day_blood.empty:
        st.markdown("**이 날짜의 혈당 흐름**")

        st.line_chart(
            day_blood.set_index("measured_at")[["glucose"]]
            .rename(columns={
                "glucose": "혈당 (mg/dL)"
            })
        )

    st.caption(
        "식사는 음식 한 종류당 한 행으로 표시해요. "
        "수면은 잠든 날짜에 표시하며, "
        "이 그래프에는 서로 다른 측정 시점의 혈당도 함께 나와요."
    )

    st.page_link(
        "pages/lifestyle.py",
        label="식사·활동 기록 입력하러 가기",
        icon="📝"
    )

    st.page_link(
        "pages/history.py",
        label="혈당 기록 확인·수정하러 가기",
        icon="📈"
    )
