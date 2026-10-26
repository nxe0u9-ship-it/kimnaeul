from datetime import date, datetime, time, timedelta
from hashlib import sha256
import json
from uuid import uuid4
from zoneinfo import ZoneInfo

import pandas as pd
import streamlit as st

from app_shared import require_login


MEALS = [
    "선택해 주세요", "공복", "식전",
    "식후 1시간", "식후 2시간", "취침 전", "기타"
]


def show_error(message, error):
    st.error(message)
    st.caption(
        f"오류 종류: {type(error).__name__} / "
        f"오류 코드: {getattr(error, 'code', None) or '없음'}"
    )


def change_record(
    client, user_id, profile_id, record_id, values=None
):
    # 계정·관리 대상·기록 번호가 일치하는 기록만 변경한다.
    table = client.table("blood_glucose")

    if values is None:
        query = table.delete(returning="representation")
    else:
        query = table.update(
            values,
            returning="representation"
        )

    result = (
        query.eq("user_id", user_id)
        .eq("profile_id", profile_id)
        .eq("record_id", record_id)
        .execute()
    )

    return bool(result.data)


def show_record_editor(
    client, user, profile_id, rows, display
):
    st.markdown("### ✏️ 표에서 기록 선택")
    st.caption(
        "표 왼쪽의 선택란을 누르면 "
        "아래에 수정·삭제 화면이 나와요."
    )

    # 목록의 내용이 바뀌면 선택을 초기화한다.
    table_revision = sha256(
        json.dumps(
            rows, sort_keys=True, default=str
        ).encode()
    ).hexdigest()[:16]

    event = st.dataframe(
        display,
        hide_index=True,
        use_container_width=True,
        on_select="rerun",
        selection_mode="single-row",
        key=f"record_table_{profile_id}_{table_revision}"
    )

    positions = event["selection"]["rows"]

    if not positions:
        st.info(
            "수정하거나 삭제할 기록 한 건을 "
            "표에서 선택해 주세요."
        )
        return

    # 표를 정렬해도 원본 데이터의 위치로 기록을 찾는다.
    position = positions[0]

    if not 0 <= position < len(rows):
        st.warning(
            "목록이 바뀌었어요. 기록을 다시 선택해 주세요."
        )
        return

    row = rows[position]
    target_id = row["record_id"]

    st.markdown("#### 선택한 기록")
    st.write(
        f"{row['measure_date']} "
        f"{str(row['measure_time'])[:5]} · "
        f"{row['glucose']} mg/dL · {row['meal']}"
    )

    # 다른 기록을 고르거나 저장 내용이 바뀌면 입력칸을 갱신한다.
    revision = sha256(
        json.dumps(
            row, sort_keys=True, default=str
        ).encode()
    ).hexdigest()[:12]

    prefix = f"{profile_id}_{target_id}_{revision}"
    original_meal = row.get("meal") or "기타"

    options = (
        MEALS
        if original_meal in MEALS
        else MEALS + [original_meal]
    )

    with st.form(f"edit_{prefix}"):
        c1, c2 = st.columns(2)

        edited_date = c1.date_input(
            "측정 날짜 수정",
            value=date.fromisoformat(row["measure_date"])
        )

        edited_time = c2.time_input(
            "측정 시간 수정",
            value=time.fromisoformat(row["measure_time"]),
            step=60
        )

        edited_glucose = st.number_input(
            "혈당 수치 수정 (mg/dL)",
            min_value=0,
            max_value=1000,
            value=int(row["glucose"]),
            step=1
        )

        edited_meal = st.selectbox(
            "측정 시점 수정",
            options,
            index=options.index(original_meal)
        )

        edited_insulin = st.number_input(
            "인슐린 투여량 수정 (단위)",
            min_value=0.0,
            value=float(row.get("insulin") or 0),
            step=0.5
        )

        edited_memo = st.text_area(
            "메모 수정",
            value=row.get("memo") or ""
        )

        submitted = st.form_submit_button(
            "💾 수정 내용 저장",
            use_container_width=True
        )

    if submitted:
        if edited_glucose <= 0:
            st.warning("혈당 수치를 입력해 주세요.")

        elif edited_meal == "선택해 주세요":
            st.warning("측정 시점을 선택해 주세요.")

        else:
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
                    target_id, values
                )

            except Exception as error:
                show_error(
                    "수정 결과를 확인하지 못했어요. "
                    "목록을 새로 확인해 주세요.",
                    error
                )

            else:
                if changed:
                    st.session_state.record_notice = (
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

    with st.form(f"delete_{prefix}"):
        st.warning(
            "선택한 기록 한 건을 삭제해요. "
            "삭제한 기록은 앱에서 복구할 수 없어요."
        )

        confirmed = st.checkbox(
            "위에서 선택한 기록을 삭제하는 데 동의해요."
        )

        delete_clicked = st.form_submit_button(
            "🗑️ 선택한 기록 삭제",
            use_container_width=True
        )

    if delete_clicked:
        if not confirmed:
            st.warning("삭제 확인란을 먼저 체크해 주세요.")

        else:
            try:
                changed = change_record(
                    client, user.id, profile_id, target_id
                )

            except Exception as error:
                show_error(
                    "삭제 결과를 확인하지 못했어요. "
                    "목록을 새로 확인해 주세요.",
                    error
                )

            else:
                if changed:
                    st.session_state.record_notice = (
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
    page_title="당당케어",
    page_icon="🩸",
    layout="wide"
)

st.markdown("""
<style>
.stApp { background-color: #FFF9F9; }
div.stButton > button { border-radius: 14px; }
div[data-testid="stForm"] {
    padding: 22px;
    border-radius: 18px;
    background: white;
    border: 1px solid #EEEEEE;
}
</style>
""", unsafe_allow_html=True)

st.sidebar.title("🩸 당당케어")
st.sidebar.page_link(
    "main.py", label="혈당 기록", icon="🩸"
)

profile_menu = st.sidebar.container()

st.sidebar.page_link(
    "pages/chat.py",
    label="AI에게 물어보기",
    icon="💬"
)

client, user = require_login()

st.title("🩸 나와 가족, 반려동물의 혈당 관리")
st.caption(
    "왼쪽에서 관리 대상을 선택해 "
    "혈당을 기록하고 이전 기록을 확인해요."
)

# 로그인한 계정의 관리 대상만 불러온다.
try:
    profiles = (
        client.table("care_profiles")
        .select("id,name,profile_type,animal_type")
        .eq("user_id", user.id)
        .order("created_at")
        .execute()
        .data
    )

except Exception as error:
    show_error(
        "관리 대상 목록을 불러오지 못했어요.",
        error
    )
    st.stop()

with st.expander("➕ 관리 대상 추가", expanded=not profiles):
    profile_type = st.radio(
        "대상 구분",
        ["사람", "반려동물"],
        horizontal=True
    )

    with st.form("add_profile", clear_on_submit=True):
        name = st.text_input(
            "이름 또는 별명", max_chars=50
        )

        animal_type = None

        if profile_type == "반려동물":
            animal_type = st.selectbox(
                "동물 종류",
                ["강아지", "고양이", "기타"]
            )

        added = st.form_submit_button(
            "관리 대상 등록",
            use_container_width=True
        )

    if added:
        if not name.strip():
            st.warning("이름 또는 별명을 입력해 주세요.")

        else:
            profile_id = str(uuid4())

            try:
                client.table("care_profiles").insert(
                    {
                        "id": profile_id,
                        "user_id": user.id,
                        "name": name.strip(),
                        "profile_type": profile_type,
                        "animal_type": animal_type
                    },
                    returning="minimal"
                ).execute()

            except Exception as error:
                show_error(
                    "관리 대상을 등록하지 못했어요. "
                    "잠시 후 다시 시도해 주세요.",
                    error
                )

            else:
                st.session_state.active_profile = profile_id
                st.rerun()

if not profiles:
    profile_menu.caption("등록된 관리 대상이 없어요.")
    st.info(
        "먼저 위에서 관리 대상을 등록해 주세요. "
        "사람과 반려동물을 여러 명 등록할 수 있어요."
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
        kind = item.get("animal_type") or item["profile_type"]
        icon = "👤" if item["profile_type"] == "사람" else "🐾"
        label = f"{icon} {item['name']} · {kind}"

        if sum(p["name"] == item["name"] for p in profiles) > 1:
            label += f" · {item['id'][:8]}"

        is_selected = (
            item["id"] == st.session_state.active_profile
        )

        if st.button(
            label,
            key=f"choose_profile_{item['id']}",
            type="primary" if is_selected else "secondary",
            use_container_width=True
        ):
            st.session_state.active_profile = item["id"]
            st.rerun()

selected_id = st.session_state.active_profile
profile = profile_map[selected_id]

st.subheader(f"{profile['name']}의 혈당 관리")

notice = st.session_state.pop("record_notice", None)

if notice and notice[:2] == (user.id, selected_id):
    st.success(notice[2])

record_tab, history_tab = st.tabs([
    "🩸 혈당 기록",
    "📈 기록·그래프·수정"
])

now = datetime.now(ZoneInfo("Asia/Seoul"))

# 새 혈당 기록 입력
with record_tab:
    with st.form(f"glucose_{selected_id}"):
        c1, c2 = st.columns(2)

        measure_date = c1.date_input(
            "📅 측정 날짜", value=now.date()
        )

        measure_time = c2.time_input(
            "🕐 측정 시간",
            value=now.time().replace(
                second=0, microsecond=0
            ),
            step=60
        )

        st.caption(
            "시간은 대한민국 기준이며, "
            "오후 1시는 13:00으로 저장돼요."
        )

        glucose = st.number_input(
            "🩸 혈당 수치 (mg/dL)",
            min_value=0,
            max_value=1000,
            value=0,
            step=1
        )

        meal = st.selectbox("🍽️ 측정 시점", MEALS)

        insulin = st.number_input(
            "💉 인슐린 투여량 (단위)",
            min_value=0.0,
            value=0.0,
            step=0.5
        )

        memo = st.text_area(
            "📝 메모",
            placeholder="식사, 활동량, 컨디션 등을 기록해 주세요."
        )

        saved = st.form_submit_button(
            "💾 혈당 기록 저장",
            use_container_width=True
        )

    if saved:
        if glucose <= 0:
            st.warning("혈당 수치를 입력해 주세요.")

        elif meal == "선택해 주세요":
            st.warning("측정 시점을 선택해 주세요.")

        else:
            try:
                client.table("blood_glucose").insert(
                    {
                        "user_id": user.id,
                        "profile_id": selected_id,
                        "name": profile["name"],
                        "measure_date": measure_date.isoformat(),
                        "measure_time": measure_time.strftime("%H:%M"),
                        "glucose": glucose,
                        "meal": meal,
                        "insulin": insulin,
                        "memo": memo
                    },
                    returning="minimal"
                ).execute()

            except Exception as error:
                show_error(
                    "기록을 저장하지 못했어요.",
                    error
                )

            else:
                st.success(
                    f"{profile['name']}의 혈당 "
                    f"{glucose} mg/dL 기록을 저장했어요!"
                )

# 조회 조건으로 기록을 좁힌 뒤 표에서 선택한다.
with history_tab:
    c1, c2 = st.columns(2)

    start = c1.date_input(
        "조회 시작일",
        value=now.date() - timedelta(days=90),
        key="history_start"
    )

    end = c2.date_input(
        "조회 종료일",
        value=now.date(),
        key="history_end"
    )

    meal_filter = st.selectbox(
        "측정 시점으로 찾기",
        ["전체"] + MEALS[1:],
        key=f"history_meal_{selected_id}"
    )

    if start > end:
        st.warning(
            "조회 시작일은 종료일보다 늦을 수 없어요."
        )

    else:
        try:
            query = (
                client.table("blood_glucose")
                .select(
                    "record_id,measure_date,measure_time,"
                    "glucose,meal,insulin,memo"
                )
                .eq("user_id", user.id)
                .eq("profile_id", selected_id)
                .gte("measure_date", start.isoformat())
                .lte("measure_date", end.isoformat())
            )

            if meal_filter != "전체":
                query = query.eq("meal", meal_filter)

            rows = (
                query.order("measure_date", desc=True)
                .order("measure_time", desc=True)
                .order("record_id")
                .limit(1000)
                .execute()
                .data
            )

        except Exception as error:
            show_error(
                "기록을 불러오지 못했어요. "
                "Supabase 설정 적용 여부와 연결 상태를 확인해 주세요.",
                error
            )
            rows = None

        if rows is not None:
            if not rows:
                st.info(
                    "선택한 기간과 측정 시점에 "
                    "해당하는 기록이 없어요."
                )

            else:
                df = pd.DataFrame(rows)

                df["glucose"] = pd.to_numeric(
                    df["glucose"], errors="coerce"
                )

                df["측정일시"] = pd.to_datetime(
                    df["measure_date"].astype(str)
                    + " "
                    + df["measure_time"].astype(str),
                    errors="coerce"
                )

                st.caption(
                    "선택한 기간의 최신 기록을 최대 1,000개 표시해요. "
                    "수정할 기록이 없으면 조회 기간을 바꿔 주세요."
                )

                c1, c2 = st.columns(2)

                c1.metric("표시된 기록", f"{len(df)}개")

                c2.metric(
                    "조회 결과의 최근 혈당",
                    f"{rows[0]['glucose']} mg/dL"
                )

                chart = (
                    df.dropna(
                        subset=["측정일시", "glucose"]
                    )
                    .sort_values("측정일시")
                )

                if not chart.empty:
                    st.line_chart(
                        chart.set_index("측정일시")[["glucose"]]
                        .rename(
                            columns={"glucose": "혈당 (mg/dL)"}
                        )
                    )

                display = df.drop(
                    columns=["측정일시", "record_id"]
                ).rename(
                    columns={
                        "measure_date": "측정 날짜",
                        "measure_time": "측정 시간",
                        "glucose": "혈당 (mg/dL)",
                        "meal": "측정 시점",
                        "insulin": "인슐린 (단위)",
                        "memo": "메모"
                    }
                )

                show_record_editor(
                    client, user, selected_id, rows, display
                )

                st.download_button(
                    "📥 표시된 기록 CSV 다운로드",
                    display.to_csv(index=False).encode("utf-8-sig"),
                    file_name="blood_glucose.csv",
                    mime="text/csv"
                )
