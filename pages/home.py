from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import streamlit as st

from app_shared import require_login


def show_error(message, error):
    st.error(message)
    st.caption(
        f"오류 종류: {type(error).__name__} / "
        f"오류 코드: {getattr(error, 'code', None) or '없음'}"
    )


def count_today(
    client, user_id, profile_id,
    table, id_column, date_column, today
):
    result = (
        client.table(table)
        .select(id_column, count="exact")
        .eq("user_id", user_id)
        .eq("profile_id", profile_id)
        .eq(date_column, today.isoformat())
        .limit(1)
        .execute()
    )

    if result.count is None:
        raise ValueError("기록 건수를 확인하지 못했어요.")

    return result.count


def move_to_profile(profile_id, path):
    st.session_state.active_profile = profile_id
    st.switch_page(path)


st.set_page_config(
    page_title="우리집 케어 홈 | 당당케어",
    page_icon="🏠",
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

for path, label, icon in [
    ("pages/home.py", "우리집 케어 홈", "🏠"),
    ("pages/record.py", "혈당 기록하기", "🩸"),
    ("pages/history.py", "기록 확인·수정", "📈"),
    ("pages/lifestyle.py", "식사·활동 기록", "📝"),
    ("pages/meal.py", "냉장고 식단 추천", "🍽️"),
    ("pages/explore.py", "내 기록 탐구실", "🔍"),
    ("pages/visit.py", "진료 준비 노트", "🏥")
]:
    st.sidebar.page_link(
        path,
        label=label,
        icon=icon
    )

profile_menu = st.sidebar.container()

st.sidebar.page_link(
    "pages/chat.py",
    label="AI에게 물어보기",
    icon="💬"
)

client, user = require_login()

now = datetime.now(ZoneInfo("Asia/Seoul"))
today = now.date()

st.title("🏠 우리집 케어 홈")
st.caption(
    f"대한민국 기준 {today:%Y-%m-%d} · "
    "나와 가족, 반려동물의 기록을 한눈에 확인해요."
)


# 관리 대상 목록
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

if not profiles:
    st.info(
        "아직 등록된 관리 대상이 없어요. "
        "먼저 나와 가족, 반려동물을 등록해 주세요."
    )
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


# 왼쪽 관리 대상 선택
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
            key=f"home_profile_{user.id}_{item['id']}",
            type="primary" if active else "secondary",
            use_container_width=True
        ):
            st.session_state.active_profile = item["id"]
            st.rerun()


# 전체 현황
people_count = sum(
    item["profile_type"] == "사람"
    for item in profiles
)

pet_count = sum(
    item["profile_type"] == "반려동물"
    for item in profiles
)

c1, c2, c3 = st.columns(3)

c1.metric("전체 관리 대상", f"{len(profiles)}명·마리")
c2.metric("사람", f"{people_count}명")
c3.metric("반려동물", f"{pet_count}마리")

if st.button("🔄 최신 기록 다시 불러오기"):
    st.rerun()


# 대상별 기록 카드
st.subheader("🩸 대상별 최근 기록")

st.caption(
    "최근 혈당은 가장 최근 측정 날짜·시간의 기록이에요. "
    "아래 버튼을 누르면 해당 대상을 선택한 상태로 이동해요."
)

for item in profiles:
    profile_id = item["id"]
    kind = (
        item.get("animal_type")
        or item["profile_type"]
    )
    icon = (
        "👤"
        if item["profile_type"] == "사람"
        else "🐾"
    )

    with st.container(border=True):
        st.markdown(
            f"### {icon} {item['name']} · {kind}"
        )

        if profile_id == st.session_state.active_profile:
            st.caption("현재 선택한 관리 대상")

        try:
            latest_rows = (
                client.table("blood_glucose")
                .select(
                    "record_id,measure_date,"
                    "measure_time,glucose,meal"
                )
                .eq("user_id", user.id)
                .eq("profile_id", profile_id)
                .order("measure_date", desc=True)
                .order("measure_time", desc=True)
                .order("record_id")
                .limit(1)
                .execute()
                .data
            ) or []

            blood_count = count_today(
                client,
                user.id,
                profile_id,
                "blood_glucose",
                "record_id",
                "measure_date",
                today
            )

            lifestyle_count = count_today(
                client,
                user.id,
                profile_id,
                "lifestyle_records",
                "id",
                "record_date",
                today
            )

        except Exception as error:
            show_error(
                "이 대상의 기록 현황을 불러오지 못했어요.",
                error
            )

        else:
            c1, c2, c3 = st.columns(3)

            if latest_rows:
                latest = latest_rows[0]

                c1.metric(
                    "최근 혈당",
                    f"{latest['glucose']} mg/dL"
                )

                st.caption(
                    f"최근 측정: {latest['measure_date']} "
                    f"{str(latest['measure_time'])[:5]} · "
                    f"{latest.get('meal') or '측정 시점 미입력'}"
                )

            else:
                c1.metric("최근 혈당", "기록 없음")

            c2.metric(
                "오늘 날짜의 혈당 기록",
                f"{blood_count}건"
            )

            c3.metric(
                "오늘 날짜의 식사·활동 기록",
                f"{lifestyle_count}건"
            )

            if blood_count == 0:
                st.info(
                    "오늘 날짜로 저장된 혈당 기록이 없어요."
                )
            else:
                st.success(
                    "오늘 날짜의 혈당 기록이 저장되어 있어요."
                )

        c1, c2, c3 = st.columns(3)

        if c1.button(
            "🩸 혈당 기록",
            key=f"home_blood_{user.id}_{profile_id}",
            use_container_width=True
        ):
            move_to_profile(
                profile_id,
                "pages/record.py"
            )

        if c2.button(
            "📈 기록 확인",
            key=f"home_history_{user.id}_{profile_id}",
            use_container_width=True
        ):
            move_to_profile(
                profile_id,
                "pages/history.py"
            )

        if c3.button(
            "📝 식사·활동",
            key=f"home_lifestyle_{user.id}_{profile_id}",
            use_container_width=True
        ):
            move_to_profile(
                profile_id,
                "pages/lifestyle.py"
            )

st.caption(
    "식사·활동 건수는 저장된 행의 수예요. "
    "식사는 음식 한 종류당 한 건이며, "
    "수면은 잠든 날짜를 기준으로 집계해요. "
    "기록이 없다는 것은 식사·활동을 하지 않았다는 뜻이 아니에요."
)


# 다가오는 진료
st.divider()
st.subheader("🏥 앞으로 30일 안의 진료 예정")

try:
    visit_rows = (
        client.table("visit_notes")
        .select(
            "id,profile_id,title,visit_date,completed"
        )
        .eq("user_id", user.id)
        .eq("completed", False)
        .gte("visit_date", today.isoformat())
        .lte(
            "visit_date",
            (today + timedelta(days=30)).isoformat()
        )
        .order("visit_date")
        .order("id")
        .limit(21)
        .execute()
        .data
    ) or []

except Exception as error:
    show_error(
        "진료 예정 목록을 불러오지 못했어요.",
        error
    )

else:
    if not visit_rows:
        st.info(
            "앞으로 30일 안에 예정된 미완료 진료 노트가 없어요. "
            "진료 준비 노트에서 예정일을 저장하면 여기에 표시돼요."
        )

    for visit in visit_rows[:20]:
        target = profile_map.get(visit["profile_id"])

        if target is None:
            continue

        visit_day = date.fromisoformat(visit["visit_date"])
        remaining = (visit_day - today).days
        day_label = (
            "오늘"
            if remaining == 0
            else f"{remaining}일 후"
        )

        with st.container(border=True):
            st.markdown(
                f"**{visit['visit_date']} · {day_label}**"
            )
            st.write(
                f"{target['name']} · {visit['title']}"
            )

            if st.button(
                "🏥 이 진료 노트 열기",
                key=f"home_visit_{user.id}_{visit['id']}"
            ):
                target_id = visit["profile_id"]

                st.session_state.active_profile = target_id

                st.session_state[
                    f"visit_pending_{user.id}_{target_id}"
                ] = visit["id"]

                st.switch_page("pages/visit.py")

    if len(visit_rows) > 20:
        st.caption(
            "가까운 예정일부터 최대 20건 표시해요. "
            "나머지 노트는 진료 준비 페이지에서 확인해 주세요."
        )

st.page_link(
    "pages/visit.py",
    label="진료 준비 노트 작성·관리하기",
    icon="🏥"
)


# 자주 쓰는 기능
st.divider()
st.subheader("✨ 바로가기")

c1, c2 = st.columns(2)

with c1:
    st.page_link(
        "pages/meal.py",
        label="냉장고 재료·식사 조건 입력",
        icon="🍽️"
    )

with c2:
    st.page_link(
        "pages/explore.py",
        label="내 기록 비교·탐색",
        icon="🔍"
    )

st.caption(
    "홈 화면은 저장된 기록의 현황을 보여줘요. "
    "혈당의 정상 여부나 치료 방법을 자동 판단하지 않아요."
)
