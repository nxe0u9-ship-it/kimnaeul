import streamlit as st


MENU_ITEMS = [
    ("pages/home.py", "우리 가족 케어", "🏠"),
    ("pages/record.py", "혈당 기록하기", "🩸"),
    ("pages/history.py", "기록 확인·수정", "📈"),
    ("pages/lifestyle.py", "식사·활동 기록", "📝"),
    ("pages/meal.py", "냉장고 식단 추천", "🍽️"),
    ("pages/explore.py", "내 기록 탐구실", "🔍"),
    ("pages/visit.py", "진료 준비 노트", "🏥"),
    ("pages/chat.py", "AI에게 물어보기", "💬")
]


def show_sidebar_menu(current_page):
    """
    현재 페이지 메뉴 바로 아래에 관리 대상 표시 공간을 만든다.

    반환된 컨테이너 안에 각 페이지의 관리 대상 선택 버튼을 표시한다.
    """
    valid_paths = {
        path
        for path, label, icon in MENU_ITEMS
    }

    if current_page not in valid_paths:
        raise ValueError(
            f"등록되지 않은 페이지 경로예요: {current_page}"
        )

    st.sidebar.title("🩸 당당케어")

    profile_menu = None

    for path, label, icon in MENU_ITEMS:
        st.sidebar.page_link(
            path,
            label=label,
            icon=icon
        )

        if path == current_page:
            profile_menu = st.sidebar.container()

    return profile_menu
