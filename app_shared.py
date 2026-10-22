import base64
import json

import streamlit as st
from supabase import create_client

APP_URL = "https://kimnaeul-nfmpatlk9u3uysxmtesvuq.streamlit.app/"


def get_client():
    # 로그인 세션은 접속자마다 따로 유지한다. 공용 캐시를 사용하지 않는다.
    if "care_client" not in st.session_state:
        key = st.secrets["SUPABASE_KEY"].strip()
        role = None
        if key.count(".") == 2:
            try:
                part = key.split(".")[1]
                role = json.loads(base64.urlsafe_b64decode(
                    part + "=" * (-len(part) % 4)
                )).get("role")
            except (ValueError, TypeError, UnicodeError):
                pass
        if key.startswith("sb_secret_") or role == "service_role":
            st.error("Secrets의 SUPABASE_KEY에는 publishable 또는 anon 키를 넣어 주세요.")
            st.stop()
        st.session_state.care_client = create_client(
            st.secrets["SUPABASE_URL"].strip().rstrip("/"), key
        )
    return st.session_state.care_client


def show_menu():
    st.sidebar.title("🩸 당당케어")
    st.sidebar.page_link("main.py", label="혈당 기록", icon="🩸")
    st.sidebar.page_link("pages/chat.py", label="AI에게 물어보기", icon="💬")


def require_login():
    client = get_client()
    try:
        session = client.auth.get_session()
        user = client.auth.get_user().user if session else None
    except Exception:
        st.error("로그인 상태를 확인하지 못했어요. 잠시 후 다시 시도해 주세요.")
        if st.button("로그인 화면으로 돌아가기"):
            st.session_state.clear()
            st.rerun()
        st.stop()

    if user:
        st.sidebar.caption(f"로그인: {user.email}")
        if st.sidebar.button("로그아웃", use_container_width=True):
            try:
                client.auth.sign_out({"scope": "local"})
            except Exception:
                pass
            st.session_state.clear()
            st.rerun()
        return client, user

    st.title("🩸 당당케어")
    st.write("로그인하고 나와 가족, 반려동물의 혈당을 관리해요.")
    login_tab, signup_tab = st.tabs(["로그인", "회원가입"])

    with login_tab:
        with st.form("login_form", clear_on_submit=True):
            email = st.text_input("이메일", key="login_email")
            password = st.text_input("비밀번호", type="password", key="login_password")
            submitted = st.form_submit_button("로그인", use_container_width=True)
        if submitted:
            if not email.strip() or not password:
                st.warning("이메일과 비밀번호를 입력해 주세요.")
            else:
                try:
                    result = client.auth.sign_in_with_password({
                        "email": email.strip(), "password": password
                    })
                    if result.session:
                        st.rerun()
                    else:
                        st.error("로그인하지 못했어요. 이메일 인증 여부를 확인해 주세요.")
                except Exception as error:
                    message = str(error).lower()
                    if "email not confirmed" in message:
                        st.error("가입 확인 메일의 인증 링크를 먼저 눌러 주세요.")
                    else:
                        st.error("로그인하지 못했어요. 이메일·비밀번호와 연결 상태를 확인해 주세요.")

    with signup_tab:
        st.caption("가입 후 이메일로 받은 인증 링크를 누르고, 이 앱에서 로그인해 주세요.")
        with st.form("signup_form", clear_on_submit=True):
            new_email = st.text_input("이메일", key="signup_email")
            new_password = st.text_input("비밀번호 (8자 이상)", type="password", key="signup_password")
            confirm = st.text_input("비밀번호 확인", type="password")
            submitted = st.form_submit_button("회원가입", use_container_width=True)
        if submitted:
            if not new_email.strip() or "@" not in new_email:
                st.warning("이메일 주소를 입력해 주세요.")
            elif len(new_password) < 8:
                st.warning("비밀번호는 8자 이상으로 입력해 주세요.")
            elif new_password != confirm:
                st.warning("두 비밀번호가 일치하지 않아요.")
            else:
                try:
                    result = client.auth.sign_up({
                        "email": new_email.strip(),
                        "password": new_password,
                        "options": {"email_redirect_to": APP_URL}
                    })
                    if result.session:
                        st.rerun()
                    st.success("가입 요청을 보냈어요. 새 계정이면 확인 메일을 인증한 뒤 로그인해 주세요.")
                    st.caption("메일이 없다면 스팸함을 확인해 주세요. 이미 가입했다면 로그인 탭을 이용해 주세요.")
                except Exception:
                    st.error("가입 요청을 처리하지 못했어요. 이메일·비밀번호 조건을 확인하거나 잠시 후 다시 시도해 주세요.")
    st.stop()
