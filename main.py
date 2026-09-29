import streamlit as st
from supabase import create_client

st.title("🔌 Supabase 연결 테스트")

try:
    supabase = create_client(
        st.secrets["SUPABASE_URL"],
        st.secrets["SUPABASE_KEY"]
    )

    response = (
        supabase
        .table("blood_glucose")
        .select("*")
        .limit(1)
        .execute()
    )

    st.success("✅ Supabase 연결 성공!")
    st.write("blood_glucose 테이블도 정상적으로 연결됐어요.")

except Exception as e:
    st.error("❌ Supabase 연결 실패")
    st.code(str(e))
