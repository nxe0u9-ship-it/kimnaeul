from datetime import datetime
from uuid import uuid4
from zoneinfo import ZoneInfo

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


st.set_page_config(
    page_title="혈당 기록하기 | 당당케어",
    page_icon="🩸",
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
    "pages/home.py",
    label="우리집 케어 홈",
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


# 로그인 확인
client, user = require_login()

st.title("🩸 혈당 기록하기")
st.caption(
    "왼쪽에서 관리 대상을 선택해 혈당을 기록해요. "
    "이전 기록은 ‘기록 확인·수정’에서 확인할 수 있어요."
)


# 로그인한 계정의 관리 대상 불러오기
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
        "관리 대상 목록을 불러오지 못했어요.",
        error
    )
    st.stop()


# 관리 대상 등록
with st.expander(
    "➕ 관리 대상 추가",
    expanded=not profiles
):
    profile_type = st.radio(
        "대상 구분",
        ["사람", "반려동물"],
        horizontal=True
    )

    with st.form(
        "add_profile",
        clear_on_submit=True
    ):
        name = st.text_input(
            "이름 또는 별명",
            max_chars=50
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
            new_profile_id = str(uuid4())

            try:
                client.table("care_profiles").insert(
                    {
                        "id": new_profile_id,
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
                st.session_state.active_profile = new_profile_id
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


# 관리 대상 선택
with profile_menu:
    st.caption("관리 대상")

    for item in profiles:
        kind = (
            item.get("animal_type")
            or item["profile_type"]
        )
        icon = (
            "👤"
            if item["profile_type"] == "사람"
            else "🐾"
        )
        label = f"{icon} {item['name']} · {kind}"

        if sum(
            p["name"] == item["name"]
            for p in profiles
        ) > 1:
            label += f" · {item['id'][:8]}"

        is_selected = (
            item["id"]
            == st.session_state.active_profile
        )

        if st.button(
            label,
            key=f"choose_profile_{item['id']}",
            type=(
                "primary"
                if is_selected
                else "secondary"
            ),
            use_container_width=True
        ):
            st.session_state.active_profile = item["id"]
            st.rerun()


selected_id = st.session_state.active_profile
profile = profile_map[selected_id]

st.subheader(f"{profile['name']}의 혈당 관리")

now = datetime.now(ZoneInfo("Asia/Seoul"))


# 저장 완료 안내와 입력 양식 초기화 번호
scope = f"{user.id}_{selected_id}"
notice_key = f"glucose_notice_{scope}"
revision_key = f"glucose_revision_{scope}"
revision = st.session_state.get(revision_key, 0)

notice = st.session_state.pop(notice_key, None)

if notice:
    st.success(notice)

form_key = f"glucose_{scope}_{revision}"


# 혈당 입력
with st.form(form_key):
    c1, c2 = st.columns(2)

    measure_date = c1.date_input(
        "📅 측정 날짜",
        value=now.date(),
        max_value=now.date(),
        key=f"{form_key}_date"
    )

    measure_time = c2.time_input(
        "🕐 측정 시간",
        value=now.time().replace(
            second=0,
            microsecond=0
        ),
        step=60,
        key=f"{form_key}_time"
    )

    st.caption(
        "시간은 대한민국 기준이며, "
        "오후 1시는 13:00으로 저장돼요. "
        "현재보다 미래인 측정 시각은 저장할 수 없어요."
    )

    glucose = st.number_input(
        "🩸 혈당 수치 (mg/dL)",
        min_value=0,
        max_value=1000,
        value=0,
        step=1,
        key=f"{form_key}_glucose"
    )

    meal = st.selectbox(
        "🍽️ 측정 시점",
        MEALS,
        key=f"{form_key}_meal"
    )

    insulin = st.number_input(
        "💉 인슐린 투여량 (단위)",
        min_value=0.0,
        value=0.0,
        step=0.5,
        key=f"{form_key}_insulin"
    )

    memo = st.text_area(
        "📝 메모",
        placeholder="식사, 활동량, 컨디션 등을 기록해 주세요.",
        key=f"{form_key}_memo"
    )

    saved = st.form_submit_button(
        "💾 혈당 기록 저장",
        use_container_width=True
    )


# 혈당 저장
if saved:
    measured_at = datetime.combine(
        measure_date,
        measure_time
    ).replace(tzinfo=ZoneInfo("Asia/Seoul"))

    current_time = datetime.now(ZoneInfo("Asia/Seoul"))

    if measured_at > current_time:
        st.warning(
            "측정 시각이 현재보다 미래예요. "
            "실제로 측정한 날짜와 시간으로 바꿔 주세요."
        )

    elif glucose <= 0:
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
            st.session_state[notice_key] = (
                f"{profile['name']}의 혈당 "
                f"{glucose} mg/dL 기록을 저장했어요!"
            )
            st.session_state[revision_key] = revision + 1
            st.rerun()


# 선택한 대상의 최근 혈당 기록
st.divider()
st.subheader(f"📋 {profile['name']}의 최근 혈당 기록")
st.caption(
    "측정 날짜·시간이 최신인 순서로 최대 3건을 표시해요."
)

try:
    recent_rows = (
        client.table("blood_glucose")
        .select(
            "record_id,measure_date,measure_time,"
            "glucose,meal,insulin,memo"
        )
        .eq("user_id", user.id)
        .eq("profile_id", selected_id)
        .order("measure_date", desc=True)
        .order("measure_time", desc=True)
        .order("record_id")
        .limit(3)
        .execute()
        .data
    ) or []

except Exception as error:
    show_error(
        "최근 혈당 기록을 불러오지 못했어요.",
        error
    )

else:
    if recent_rows:
        recent_table = [
            {
                "측정 날짜": row["measure_date"],
                "측정 시간": str(row["measure_time"])[:5],
                "혈당 (mg/dL)": row["glucose"],
                "측정 시점": row.get("meal") or "미입력",
                "인슐린 (단위)": row.get("insulin"),
                "메모": row.get("memo") or ""
            }
            for row in recent_rows
        ]

        st.dataframe(
            recent_table,
            hide_index=True,
            use_container_width=True
        )

    else:
        st.info(
            "아직 저장된 혈당 기록이 없어요. "
            "위에서 첫 기록을 입력해 주세요."
        )


# 관련 페이지 이동
st.divider()

c1, c2, c3 = st.columns(3)

with c1:
    st.page_link(
        "pages/history.py",
        label="저장한 혈당 확인·수정하기",
        icon="📈"
    )

with c2:
    st.page_link(
        "pages/lifestyle.py",
        label="식사·활동 기록하기",
        icon="📝"
    )

with c3:
    st.page_link(
        "pages/meal.py",
        label="냉장고 재료·식사 조건 입력하기",
        icon="🍽️"
    )
