import base64
import json

import streamlit as st
from supabase import create_client


APP_URL = "https://kimnaeul-nfmpatlk9u3uysxmtesvuq.streamlit.app/"


# 접속자별로 Supabase 연결을 보관한다.
def get_client():
    if "care_client" not in st.session_state:
        key = st.secrets["SUPABASE_KEY"].strip()
        role = None

        if key.count(".") == 2:
            try:
                part = key.split(".")[1]
                role = json.loads(
                    base64.urlsafe_b64decode(
                        part + "=" * (-len(part) % 4)
                    )
                ).get("role")
            except (ValueError, TypeError, UnicodeError):
                pass

        if key.startswith("sb_secret_") or role == "service_role":
            st.error(
                "Secrets의 SUPABASE_KEY에는 "
                "publishable 또는 anon 키를 넣어 주세요."
            )
            st.stop()

        st.session_state.care_client = create_client(
            st.secrets["SUPABASE_URL"].strip().rstrip("/"),
            key
        )

    return st.session_state.care_client


# 공통 왼쪽 메뉴
def show_menu():
    st.sidebar.title("🩸 당당케어")
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


# 첫 로그인 후 회원가입 완료 안내
def show_first_login_confirmation(client, user):
    metadata = user.user_metadata or {}

    if not user.email_confirmed_at:
        st.warning(
            "메일의 Confirm email address 링크로 "
            "이메일을 인증한 뒤 다시 로그인해 주세요."
        )
        st.stop()

    if metadata.get("care_welcome_seen") is True:
        return

    st.title("🎉 회원가입이 완료됐어요!")
    st.success("이메일 인증과 로그인을 모두 마쳤어요.")
    st.write(
        "당당케어에 오신 것을 환영해요. "
        "이제 나와 가족, 반려동물의 혈당을 관리할 수 있어요."
    )

    if st.button(
        "🩸 당당케어 시작하기",
        use_container_width=True
    ):
        try:
            client.auth.update_user({
                "data": {
                    **metadata,
                    "care_welcome_seen": True
                }
            })
        except Exception:
            st.error(
                "시작 설정을 저장하지 못했어요. "
                "잠시 후 버튼을 다시 눌러 주세요."
            )
        else:
            st.rerun()

    st.stop()


# 로그인 여부 확인 및 로그인·회원가입 화면
def require_login():
    client = get_client()

    try:
        session = client.auth.get_session()
        user = client.auth.get_user().user if session else None
    except Exception:
        st.error(
            "로그인 상태를 확인하지 못했어요. "
            "잠시 후 다시 시도해 주세요."
        )
        if st.button("로그인 화면으로 돌아가기"):
            st.session_state.clear()
            st.rerun()
        st.stop()

    if user:
        st.sidebar.caption(f"로그인: {user.email}")

        if st.sidebar.button(
            "로그아웃",
            use_container_width=True
        ):
            try:
                client.auth.sign_out({"scope": "local"})
            except Exception:
                pass

            st.session_state.clear()
            st.rerun()

        show_first_login_confirmation(client, user)
        return client, user

    st.title("🩸 당당케어")
    st.write(
        "로그인하고 나와 가족, "
        "반려동물의 혈당을 관리해요."
    )
    st.info(
        "처음 가입하셨나요? 메일에서 "
        "Confirm email address를 누른 뒤 "
        "이 화면에서 로그인해 주세요. "
        "첫 로그인 후 회원가입 완료 화면이 나와요."
    )

    login_tab, signup_tab = st.tabs(["로그인", "회원가입"])

    # 로그인
    with login_tab:
        with st.form("login_form", clear_on_submit=True):
            email = st.text_input("이메일", key="login_email")
            password = st.text_input(
                "비밀번호",
                type="password",
                key="login_password"
            )
            submitted = st.form_submit_button(
                "로그인",
                use_container_width=True
            )

        if submitted:
            if not email.strip() or not password:
                st.warning("이메일과 비밀번호를 입력해 주세요.")
            else:
                try:
                    result = client.auth.sign_in_with_password({
                        "email": email.strip(),
                        "password": password
                    })

                    if result.session:
                        st.rerun()
                    else:
                        st.error(
                            "로그인하지 못했어요. "
                            "이메일 인증 여부를 확인해 주세요."
                        )
                except Exception as error:
                    message = str(error).lower()

                    if "email not confirmed" in message:
                        st.error(
                            "가입 확인 메일의 인증 링크를 "
                            "먼저 눌러 주세요."
                        )
                    else:
                        st.error(
                            "로그인하지 못했어요. "
                            "이메일·비밀번호와 "
                            "연결 상태를 확인해 주세요."
                        )

    # 회원가입
    with signup_tab:
        st.caption(
            "가입 신청 → 메일의 Confirm email address 클릭 "
            "→ 앱에서 로그인 → 회원가입 완료 안내 순서예요."
        )
        st.info(
            "📬 인증 메일이 보이지 않으면 "
            "스팸메일함도 꼭 확인해 주세요. "
            "메일 도착까지 시간이 조금 걸릴 수 있어요."
        )

        with st.form("signup_form", clear_on_submit=True):
            new_email = st.text_input(
                "이메일",
                key="signup_email"
            )
            new_password = st.text_input(
                "비밀번호 (8자 이상)",
                type="password",
                key="signup_password"
            )
            confirm = st.text_input(
                "비밀번호 확인",
                type="password"
            )
            submitted = st.form_submit_button(
                "회원가입",
                use_container_width=True
            )

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
                        "options": {
                            "email_redirect_to": APP_URL
                        }
                    })

                    if result.session:
                        st.rerun()

                    # 인증된 기존 계정은 identities가
                    # 빈 목록으로 반환될 수 있다.
                    signup_user = getattr(result, "user", None)
                    identities = getattr(
                        signup_user, "identities", None
                    )

                    if signup_user is not None and identities == []:
                        st.warning(
                            "이미 가입된 이메일이에요. "
                            "위의 로그인 탭에서 로그인해 주세요."
                        )
                        st.stop()

                    st.success(
                        "📩 가입 요청을 처리했어요. "
                        "이메일 인증과 첫 로그인을 마치면 "
                        "회원가입 완료 화면이 나와요."
                    )
                    st.write(
                        "새 계정이거나 아직 인증하지 않았다면 "
                        "받은 메일에서 Confirm email address를 "
                        "누르고, 이 앱의 로그인 탭에서 "
                        "이메일과 비밀번호를 입력해 주세요."
                    )
                    st.warning(
                        "📬 메일이 안 보이나요? "
                        "받은편지함과 스팸메일함을 모두 확인해 주세요. "
                        "잠시 기다려도 없다면 입력한 "
                        "이메일 주소가 맞는지 확인해 주세요."
                    )
                    st.caption(
                        "이미 가입과 인증을 마쳤다면 "
                        "로그인 탭을 이용해 주세요."
                    )

                except Exception as error:
                    code = getattr(error, "code", None)
                    message = str(error).lower()

                    # 중복 가입 오류로 반환되는 경우도 처리한다.
                    if (
                        code in {"user_already_exists", "email_exists"}
                        or "user already registered" in message
                        or "user already exists" in message
                        or "email already exists" in message
                    ):
                        st.warning(
                            "이미 가입된 이메일이에요. "
                            "위의 로그인 탭에서 로그인해 주세요."
                        )
                    else:
                        st.error(
                            "가입 요청을 처리하지 못했어요. "
                            "이메일·비밀번호 조건을 확인하거나 "
                            "잠시 후 다시 시도해 주세요."
                        )

    st.stop()
