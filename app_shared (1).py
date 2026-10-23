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


def show_signup_confirmation():
    """실제 이메일 인증에 성공한 경우에만 가입 완료 화면을 표시한다."""
    if "token_hash" in st.query_params:
        token_hash = st.query_params.get("token_hash", "")
        verification_type = st.query_params.get("type", "")
        # 인증 토큰을 화면이나 오류 메시지에 출력하지 않는다.
        del st.query_params["token_hash"]
        if "type" in st.query_params:
            del st.query_params["type"]
        verification_client = None
        try:
            if not token_hash or verification_type != "email":
                raise ValueError("Invalid verification request")
            # 기존 로그인과 분리된 클라이언트로 인증한다.
            verification_client = create_client(
                st.secrets["SUPABASE_URL"].strip().rstrip("/"),
                st.secrets["SUPABASE_KEY"].strip()
            )
            with st.spinner("이메일을 인증하고 있어요..."):
                result = verification_client.auth.verify_otp({
                    "token_hash": token_hash,
                    "type": "email"
                })
            if not result.user or not result.user.email_confirmed_at:
                raise ValueError("Email was not confirmed")
            st.session_state.signup_confirmation = "success"
        except Exception:
            st.session_state.signup_confirmation = "error"
        finally:
            if verification_client is not None:
                try:
                    verification_client.auth.sign_out({"scope": "local"})
                except Exception:
                    pass
        st.rerun()

    status = st.session_state.get("signup_confirmation")
    if status:
        if status == "success":
            st.title("🎉 회원가입이 완료됐어요!")
            st.success("이메일 인증이 완료됐어요. 당당케어에 오신 것을 환영해요.")
            st.write("아래 버튼을 누르고 가입한 이메일과 비밀번호로 로그인해 주세요.")
        else:
            st.title("이메일 인증을 확인해 주세요")
            st.warning("인증을 완료하지 못했어요. 이미 사용했거나 만료된 링크일 수 있고, 연결 문제일 수도 있어요.")
            st.write("이미 인증했다면 로그인해 주세요. 인증 전이라면 로그인 화면의 ‘인증 메일 다시 받기’를 이용해 주세요.")
        if st.button("로그인 화면으로 이동", use_container_width=True):
            del st.session_state["signup_confirmation"]
            st.rerun()
        st.stop()


def require_login():
    client = get_client()
    show_signup_confirmation()
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
        st.caption("가입 신청 → 메일의 가입 완료 버튼 → 회원가입 완료 안내 → 로그인 순서로 진행해 주세요.")
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
                    st.success("📩 가입 요청을 보냈어요. 새 계정이면 메일의 ‘이메일 인증하고 가입 완료하기’를 눌러 가입을 마무리해 주세요.")
                    st.caption("메일이 없다면 스팸함을 확인해 주세요. 이미 가입했다면 로그인 탭을 이용해 주세요.")
                except Exception:
                    st.error("가입 요청을 처리하지 못했어요. 이메일·비밀번호 조건을 확인하거나 잠시 후 다시 시도해 주세요.")
    with st.expander("인증 메일 다시 받기"):
        with st.form("resend_confirmation", clear_on_submit=True):
            resend_email = st.text_input("가입한 이메일", key="resend_email")
            resend = st.form_submit_button("인증 메일 다시 보내기")
        if resend:
            if not resend_email.strip() or "@" not in resend_email:
                st.warning("가입한 이메일 주소를 입력해 주세요.")
            else:
                try:
                    client.auth.resend({
                        "type": "signup", "email": resend_email.strip(),
                        "options": {"email_redirect_to": APP_URL}
                    })
                    st.success("재발송 요청을 보냈어요. 인증 전 계정이면 메일함에서 가장 최근 메일을 확인해 주세요.")
                except Exception:
                    st.error("지금은 재발송하지 못했어요. 잠시 후 다시 시도해 주세요.")
    st.stop()
