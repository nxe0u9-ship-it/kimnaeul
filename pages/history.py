import streamlit as st

from app_shared import require_login


st.set_page_config(
    page_title="기록 확인·수정 | 당당케어",
    page_icon="📈",
    layout="wide"
)

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
    "pages/chat.py",
    label="AI에게 물어보기",
    icon="💬"
)

client, user = require_login()

st.title("📈 기록 확인·수정")
st.caption(
    "나와 가족, 반려동물의 혈당 기록을 확인하고 관리해요."
)

st.info(
    "새 페이지를 준비하고 있어요. "
    "기존 기록 조회·그래프·검색·수정·삭제 기능은 "
    "아직 ‘혈당 기록하기’ 페이지에서 이용할 수 있어요."
)

st.page_link(
    "main.py",
    label="기존 혈당 기록 화면으로 이동",
    icon="🩸"
)
