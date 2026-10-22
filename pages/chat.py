import streamlit as st
from app_shared import require_login, show_menu

st.set_page_config(page_title="AI에게 물어보기 | 당당케어", page_icon="💬", layout="wide")
show_menu()
client, user = require_login()

st.title("💬 AI에게 물어보기")
st.write("사람과 반려동물의 검사 결과를 이해하기 위한 도우미예요.")
st.info("AI 답변 기능은 아직 연결 전이에요. 혈당 기록과 조회는 왼쪽 ‘혈당 기록’에서 이용해 주세요.")
st.caption("AI의 설명은 참고 정보이며 의료진 또는 수의사의 진단을 대신하지 않아요.")
