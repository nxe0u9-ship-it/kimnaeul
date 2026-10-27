from datetime import date, datetime, time, timedelta
from hashlib import sha256
from html import escape
from zoneinfo import ZoneInfo
import json

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from app_shared import require_login


MEALS = [
    "공복", "식전", "식후 1시간",
    "식후 2시간", "취침 전", "기타"
]

COLUMN_NAMES = {
    "measure_date": "측정 날짜",
    "measure_time": "측정 시간",
    "glucose": "혈당 (mg/dL)",
    "meal": "측정 시점",
    "insulin": "인슐린 (단위)",
    "memo": "메모"
}


def fingerprint(value):
    return sha256(
        json.dumps(
            value, sort_keys=True, default=str
        ).encode()
    ).hexdigest()[:16]


def show_error(message, error):
    st.error(message)
    st.caption(
        f"오류 종류: {type(error).__name__} / "
        f"오류 코드: {getattr(error, 'code', None) or '없음'}"
    )


def display_records(rows):
    return (
        pd.DataFrame(rows)
        .drop(columns=["record_id"])
        .rename(columns=COLUMN_NAMES)
    )


def load_records(
    client, user_id, profile_id, start, end,
    meal, search_date=None, time_range=None, memo=""
):
    query = (
        client.table("blood_glucose")
        .select(
            "record_id,measure_date,measure_time,"
            "glucose,meal,insulin,memo"
        )
        .eq("user_id", user_id)
        .eq("profile_id", profile_id)
        .gte("measure_date", start.isoformat())
        .lte("measure_date", end.isoformat())
    )

    if meal != "전체":
        query = query.eq("meal", meal)

    if search_date is not None:
        query = query.eq(
            "measure_date", search_date.isoformat()
        )

    if time_range is not None:
        query = query.gte(
            "measure_time",
            time_range[0].strftime("%H:%M:%S")
        ).lte(
            "measure_time",
            time_range[1].replace(
                second=59, microsecond=999999
            ).isoformat()
        )

    if memo.strip():
        keyword = (
            memo.strip()
            .replace("\\", "\\\\")
            .replace("%", "\\%")
            .replace("_", "\\_")
        )
        query = query.ilike("memo", f"%{keyword}%")

    return (
        query.order("measure_date", desc=True)
        .order("measure_time", desc=True)
        .order("record_id")
        .limit(1000)
        .execute()
        .data
    ) or []


def change_record(
    client, user_id, profile_id, record_id, values=None
):
    table = client.table("blood_glucose")

    if values is None:
        query = table.delete(returning="representation")
    else:
        query = table.update(
            values, returning="representation"
        )

    result = (
        query.eq("user_id", user_id)
        .eq("profile_id", profile_id)
        .eq("record_id", record_id)
        .execute()
    )

    return bool(result.data)


def select_from_table(rows, scope):
    event = st.dataframe(
        display_records(rows),
        hide_index=True,
        use_container_width=True,
        on_select="rerun",
        selection_mode="single-row",
        key=f"history_table_{scope}_{fingerprint(rows)}"
    )

    positions = event["selection"]["rows"]

    if positions and 0 <= positions[0] < len(rows):
        return rows[positions[0]]

    st.info("표 왼쪽 선택란에서 기록 한 건을 선택해 주세요.")
    return None


def show_graph(rows, scope, selectable):
    chart = pd.DataFrame(rows)

    chart["measured_at"] = pd.to_datetime(
        chart["measure_date"].astype(str)
        + " "
        + chart["measure_time"].astype(str),
        errors="coerce"
    )

    chart["glucose"] = pd.to_numeric(
        chart["glucose"], errors="coerce"
    )

    chart = (
        chart.dropna(subset=["measured_at", "glucose"])
        .sort_values(
            ["measured_at", "record_id"],
            kind="stable"
        )
        .reset_index(drop=True)
    )

    if chart.empty:
        st.info("그래프에 표시할 기록이 없어요.")
        return None

    label_mode = st.radio(
        "그래프 수치 표시",
        ["자동", "모두 표시", "숨기기"],
        horizontal=True,
        key=f"history_labels_{scope}"
    )

    count = len(chart)
    label_step = max(1, (count + 19) // 20)

    labels = []

    for i, value in enumerate(chart["glucose"]):
        visible = (
            label_mode == "모두 표시"
            or (
                label_mode == "자동"
                and (i % label_step == 0 or i == count - 1)
            )
        )
        labels.append(f"{value:g}" if visible else "")

    # 날짜·시간 눈금은 최대 약 8개만 표시한다.
    unique_times = (
        chart["measured_at"].drop_duplicates().tolist()
    )
    tick_step = max(1, (len(unique_times) + 7) // 8)
    ticks = unique_times[::tick_step]

    if ticks[-1] != unique_times[-1]:
        ticks.append(unique_times[-1])

    graph_key = (
        f"history_graph_{scope}_{selectable}_"
        f"{fingerprint(rows)}"
    )

    # 이전 선택을 읽어 선택한 점을 강조한다.
    previous = st.session_state.get(graph_key, {})
    previous_points = previous.get(
        "selection", {}
    ).get("points", [])

    selected_ids = set()

    if selectable:
        for point in previous_points:
            custom = point.get("customdata")

            if isinstance(custom, (list, tuple)) and custom:
                selected_ids.add(str(custom[0]))

    selected_positions = [
        i for i, record_id in enumerate(chart["record_id"])
        if str(record_id) in selected_ids
    ]

    fig = go.Figure(
        go.Scatter(
            x=chart["measured_at"],
            y=chart["glucose"],
            mode="lines+markers+text",
            text=labels,
            textposition="top center",
            textfont={"size": 13},
            cliponaxis=False,
            marker={"size": 10, "color": "#DC617E"},
            line={"width": 2, "color": "#DC617E"},
            customdata=chart[["record_id"]].values.tolist(),
            hovertext=[
                escape(
                    f"{row['meal']} · "
                    f"{row.get('memo') or '메모 없음'}"
                )
                for row in chart.to_dict("records")
            ],
            hovertemplate=(
                "%{x|%Y-%m-%d %H:%M}<br>"
                "혈당 %{y} mg/dL<br>"
                "%{hovertext}<extra></extra>"
            ),
            selectedpoints=selected_positions or None,
            selected={
                "marker": {
                    "size": 17,
                    "color": "#6D48C5"
                }
            },
            unselected={"marker": {"opacity": 0.65}}
        )
    )

    fig.update_layout(
        height=440,
        margin={"l": 35, "r": 35, "t": 45, "b": 85},
        xaxis={
            "title": "측정 날짜 · 시간",
            "type": "date",
            "tickmode": "array",
            "tickvals": ticks,
            "ticktext": [
                item.strftime("%m/%d<br>%H:%M")
                for item in ticks
            ],
            "showgrid": False
        },
        yaxis={
            "title": "혈당 (mg/dL)",
            "gridcolor": "#EEEEEE",
            "rangemode": "tozero"
        },
        plot_bgcolor="white",
        paper_bgcolor="white",
        clickmode="event+select",
        dragmode="pan",
        showlegend=False,
        uirevision=f"history_{scope}_{fingerprint(rows)}"
    )

    if label_mode == "자동":
        st.caption(
            "기록이 많으면 일부 점에만 수치를 표시해요. "
            "모든 값은 아래 표에서도 확인할 수 있어요."
        )

    elif label_mode == "모두 표시":
        st.caption(
            "수치가 겹치면 조회 기간을 줄이거나 "
            "그래프 오른쪽 위 도구로 확대해 주세요."
        )

    if not selectable:
        st.plotly_chart(
            fig,
            use_container_width=True,
            key=graph_key
        )
        return None

    st.caption(
        "수정할 점을 한 개 눌러 주세요. "
        "겹친 점은 검색이나 표에서 선택할 수 있어요."
    )

    event = st.plotly_chart(
        fig,
        use_container_width=True,
        key=graph_key,
        on_select="rerun",
        selection_mode="points"
    )

    points = event["selection"]["points"]

    if len(points) != 1:
        st.info("수정할 점을 한 개만 선택해 주세요.")
        return None

    custom = points[0].get("customdata")

    if not isinstance(custom, (list, tuple)) or not custom:
        return None

    return next(
        (
            row for row in rows
            if str(row["record_id"]) == str(custom[0])
        ),
        None
    )


def edit_record(client, user, profile_id, row):
    st.markdown("### ✏️ 선택한 기록 수정·삭제")

    st.info(
        f"📅 {row['measure_date']} "
        f"{str(row['measure_time'])[:5]}  |  "
        f"🩸 {row['glucose']} mg/dL  |  "
        f"🍽️ {row['meal']}"
    )

    prefix = (
        f"history_edit_{user.id}_{profile_id}_"
        f"{row['record_id']}_{fingerprint(row)}"
    )

    original_meal = row.get("meal") or "기타"
    options = (
        MEALS if original_meal in MEALS
        else MEALS + [original_meal]
    )

    with st.form(prefix):
        c1, c2 = st.columns(2)

        edited_date = c1.date_input(
            "측정 날짜",
            value=date.fromisoformat(row["measure_date"])
        )

        edited_time = c2.time_input(
            "측정 시간",
            value=time.fromisoformat(row["measure_time"]),
            step=60
        )

        edited_glucose = st.number_input(
            "혈당 수치 (mg/dL)",
            min_value=1,
            max_value=1000,
            value=int(row["glucose"]),
            step=1
        )

        edited_meal = st.selectbox(
            "측정 시점",
            options,
            index=options.index(original_meal)
        )

        edited_insulin = st.number_input(
            "인슐린 투여량 (단위)",
            min_value=0.0,
            value=float(row.get("insulin") or 0),
            step=0.5
        )

        edited_memo = st.text_area(
            "메모",
            value=row.get("memo") or ""
        )

        save = st.form_submit_button(
            "💾 수정 내용 저장",
            use_container_width=True
        )

    if save:
        values = {
            "measure_date": edited_date.isoformat(),
            "measure_time": edited_time.strftime("%H:%M"),
            "glucose": edited_glucose,
            "meal": edited_meal,
            "insulin": edited_insulin,
            "memo": edited_memo
        }

        try:
            changed = change_record(
                client, user.id, profile_id,
                row["record_id"], values
            )

        except Exception as error:
            show_error(
                "수정 결과를 확인하지 못했어요. "
                "목록을 새로 확인해 주세요.",
                error
            )

        else:
            if changed:
                st.session_state.history_notice = (
                    user.id,
                    profile_id,
                    "혈당 기록을 수정했어요."
                )
                st.rerun()

            else:
                st.warning(
                    "변경된 기록이 없어요. "
                    "기록 존재 여부와 수정 정책을 확인해 주세요."
                )

    with st.form(f"{prefix}_delete"):
        st.warning(
            "선택한 기록 한 건을 삭제해요. "
            "삭제한 기록은 앱에서 복구할 수 없어요."
        )

        confirmed = st.checkbox(
            "위에서 선택한 기록의 삭제를 확인했어요."
        )

        delete = st.form_submit_button(
            "🗑️ 선택한 기록 삭제",
            use_container_width=True
        )

    if delete:
        if not confirmed:
            st.warning("삭제 확인란을 먼저 체크해 주세요.")

        else:
            try:
                changed = change_record(
                    client, user.id, profile_id,
                    row["record_id"]
                )

            except Exception as error:
                show_error(
                    "삭제 결과를 확인하지 못했어요. "
                    "목록을 새로 확인해 주세요.",
                    error
                )

            else:
                if changed:
                    st.session_state.history_notice = (
                        user.id,
                        profile_id,
                        "혈당 기록을 삭제했어요."
                    )
                    st.rerun()

                else:
                    st.warning(
                        "삭제된 기록이 없어요. "
                        "기록 존재 여부와 삭제 정책을 확인해 주세요."
                    )


st.set_page_config(
    page_title="기록 확인·수정 | 당당케어",
    page_icon="📈",
    layout="wide"
)

st.markdown("""
<style>
.stApp { background-color: #FFF9F9; }

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
""", unsafe_allow_html=True)


# 왼쪽 메뉴
st.sidebar.title("🩸 당당케어")

st.sidebar.page_link(
    "main.py",
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

profile_menu = st.sidebar.container()

st.sidebar.page_link(
    "pages/chat.py",
    label="AI에게 물어보기",
    icon="💬"
)


# 로그인 확인
client, user = require_login()

st.title("📈 기록 확인·수정")
st.caption(
    "관리 대상별 혈당 기록을 조회하고, "
    "원하는 기록을 찾아 수정하거나 삭제해요."
)


# 관리 대상 조회
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
    st.info(
        "먼저 혈당 기록하기 페이지에서 "
        "관리 대상을 등록해 주세요."
    )
    st.page_link(
        "main.py",
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


# 관리 대상 선택
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
            item["id"] == st.session_state.active_profile
        )

        if st.button(
            label,
            key=f"history_profile_{user.id}_{item['id']}",
            type="primary" if active else "secondary",
            use_container_width=True
        ):
            st.session_state.active_profile = item["id"]
            st.rerun()

profile_id = st.session_state.active_profile
profile = profile_map[profile_id]
scope = f"{user.id}_{profile_id}"

st.subheader(f"{profile['name']}의 혈당 기록")

notice = st.session_state.pop("history_notice", None)

if notice and notice[:2] == (user.id, profile_id):
    st.success(notice[2])

today = datetime.now(ZoneInfo("Asia/Seoul")).date()


# 조회 기간 선택
period = st.radio(
    "조회 기간",
    ["오늘", "최근 7일", "최근 30일", "직접 설정"],
    index=1,
    horizontal=True,
    key=f"history_period_{scope}"
)

if period == "직접 설정":
    c1, c2 = st.columns(2)

    start = c1.date_input(
        "조회 시작일",
        value=today - timedelta(days=90),
        key=f"history_start_{scope}"
    )

    end = c2.date_input(
        "조회 종료일",
        value=today,
        key=f"history_end_{scope}"
    )

else:
    days = {
        "오늘": 1,
        "최근 7일": 7,
        "최근 30일": 30
    }[period]

    start = today - timedelta(days=days - 1)
    end = today

    st.caption(
        f"📅 {start:%Y-%m-%d} ~ {end:%Y-%m-%d}"
    )

if start > end:
    st.warning("조회 시작일은 종료일보다 늦을 수 없어요.")
    st.stop()

meal = st.selectbox(
    "측정 시점으로 찾기",
    ["전체"] + MEALS,
    key=f"history_meal_filter_{scope}"
)


# 기록 수정·삭제 모드
editing = st.toggle(
    "✏️ 기록 수정·삭제",
    key=f"history_editing_{scope}"
)

method = None
search_date = None
time_range = None
memo = ""

if editing:
    method = st.radio(
        "기록을 찾는 방법",
        [
            "그래프에서 선택",
            "검색해서 찾기",
            "표에서 선택"
        ],
        horizontal=True,
        key=f"history_method_{scope}"
    )


# 검색 조건
if method == "검색해서 찾기":
    st.caption(
        "위의 조회 기간·측정 시점 안에서 검색해요. "
        "여러 조건을 쓰면 모두 일치하는 기록을 찾아요."
    )

    use_date = st.checkbox(
        "특정 날짜로 찾기",
        key=f"history_use_date_{scope}"
    )

    picked_date = st.date_input(
        "찾을 날짜",
        value=end,
        disabled=not use_date,
        key=f"history_search_date_{scope}"
    )

    use_time = st.checkbox(
        "시간대로 찾기",
        key=f"history_use_time_{scope}"
    )

    c1, c2 = st.columns(2)

    from_time = c1.time_input(
        "시작 시간",
        value=time(0, 0),
        step=60,
        disabled=not use_time,
        key=f"history_from_time_{scope}"
    )

    to_time = c2.time_input(
        "종료 시간",
        value=time(23, 59),
        step=60,
        disabled=not use_time,
        key=f"history_to_time_{scope}"
    )

    memo = st.text_input(
        "메모에 포함된 단어",
        placeholder="예: 산책, 아침, 간식",
        key=f"history_memo_search_{scope}"
    )

    if not (use_date or use_time or memo.strip()):
        st.info(
            "날짜·시간대·메모 중 "
            "검색 조건을 하나 이상 입력해 주세요."
        )
        st.stop()

    if use_date:
        if not start <= picked_date <= end:
            st.warning(
                "찾을 날짜가 조회 기간 밖에 있어요. "
                "조회 기간을 바꿔 주세요."
            )
            st.stop()

        search_date = picked_date

    if use_time:
        if from_time > to_time:
            st.warning(
                "시작 시간은 종료 시간보다 늦을 수 없어요."
            )
            st.stop()

        time_range = (from_time, to_time)


# 기록 불러오기
try:
    rows = load_records(
        client,
        user.id,
        profile_id,
        start,
        end,
        meal,
        search_date,
        time_range,
        memo
    )

except Exception as error:
    show_error("기록을 불러오지 못했어요.", error)
    st.stop()

if not rows:
    st.info(
        "조건에 맞는 기록이 없어요. "
        "조회 기간이나 검색 조건을 바꿔 주세요."
    )
    st.stop()

st.caption(
    "조건에 맞는 최신 기록을 최대 1,000건 표시해요. "
    "더 오래된 기록은 조회 기간을 좁혀 찾아 주세요."
)


# 기록 요약
c1, c2 = st.columns(2)

c1.metric(
    "표시된 기록",
    f"{len(rows)}개"
)

c2.metric(
    "조회 결과의 최근 혈당",
    f"{rows[0]['glucose']} mg/dL"
)


# 그래프
selected = show_graph(
    rows,
    scope,
    selectable=(
        editing
        and method == "그래프에서 선택"
    )
)


# 표 또는 검색 결과에서 선택
if editing and method in ["검색해서 찾기", "표에서 선택"]:
    st.markdown(
        "### 🔎 검색 결과"
        if method == "검색해서 찾기"
        else "### 📋 표에서 기록 선택"
    )
    selected = select_from_table(rows, scope)

else:
    st.markdown("### 📋 기록 목록")
    st.dataframe(
        display_records(rows),
        hide_index=True,
        use_container_width=True
    )


# 선택한 기록 수정·삭제
if editing and selected is not None:
    edit_record(
        client,
        user,
        profile_id,
        selected
    )


# CSV 다운로드
st.download_button(
    "📥 표시된 기록 CSV 다운로드",
    data=display_records(rows).to_csv(
        index=False
    ).encode("utf-8-sig"),
    file_name="blood_glucose.csv",
    mime="text/csv",
    key=f"history_download_{scope}"
)
