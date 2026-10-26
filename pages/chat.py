import streamlit as st

from app_shared import require_login


st.set_page_config(
    page_title="AI에게 물어보기 | 당당케어",
    page_icon="💬",
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

profile_menu = st.sidebar.container()

st.sidebar.page_link(
    "pages/chat.py",
    label="AI에게 물어보기",
    icon="💬"
)


# 로그인 확인
client, user = require_login()


# 관리 대상 불러오기
try:
    profiles = (
        client.table("care_profiles")
        .select("id,name,profile_type,animal_type")
        .eq("user_id", user.id)
        .order("created_at")
        .execute()
        .data
    ) or []

except Exception:
    st.error(
        "관리 대상 목록을 불러오지 못했어요. "
        "잠시 후 다시 시도해 주세요."
    )
    st.stop()


profile_map = {
    item["id"]: item
    for item in profiles
}

if profiles:
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
                key=f"chat_profile_{user.id}_{item['id']}",
                type="primary" if active else "secondary",
                use_container_width=True
            ):
                st.session_state.active_profile = item["id"]
                st.rerun()

else:
    profile_menu.caption("등록된 관리 대상이 없어요.")


# AI 화면
st.title("💬 AI에게 물어보기")
st.caption(
    "사람과 반려동물의 혈당과 검사 결과를 "
    "이해하기 위한 도우미예요."
)

if profiles:
    profile = profile_map[st.session_state.active_profile]
    kind = (
        profile.get("animal_type")
        or profile["profile_type"]
    )

    st.info(
        f"현재 선택한 관리 대상: "
        f"{profile['name']} · {kind}"
    )

st.info(
    "AI 답변 기능은 아직 연결 전이에요. "
    "혈당과 식사·활동 기록은 왼쪽 메뉴에서 이용해 주세요."
)

st.caption(
    "AI의 설명은 참고 정보이며 "
    "의료진 또는 수의사의 진단을 대신하지 않아요."
)
