import streamlit as st


st.set_page_config(
    page_title="AI에게 물어보기 | 당당케어",
    page_icon="💬",
    layout="wide"
)

# 왼쪽 페이지 메뉴
st.sidebar.page_link(
    "main.py",
    label="혈당 기록",
    icon="🩸"
)
st.sidebar.page_link(
    "pages/chat.py",
    label="AI에게 물어보기",
    icon="💬"
)

st.title("🤖 AI 검사 수치 해석 도우미")
st.write("사람과 반려동물의 검사 결과를 이해하기 쉽게 설명해 드려요.")
