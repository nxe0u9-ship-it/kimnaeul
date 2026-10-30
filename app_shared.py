import base64
import json
import time
from datetime import datetime, timezone
from hashlib import sha256
from uuid import uuid4
from urllib.parse import unquote

import streamlit as st
import extra_streamlit_components as stx
from cryptography.fernet import Fernet, InvalidToken
from supabase import ClientOptions, create_client


REMEMBER_SECONDS = 7 * 24 * 60 * 60

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
            key,
            options=ClientOptions(auto_refresh_token=False)
        )

    return st.session_state.care_client


# 프로젝트별 로그인 쿠키 이름
def cookie_name():
    project = st.secrets["SUPABASE_URL"].strip().rstrip("/")
    suffix = sha256(project.encode()).hexdigest()[:12]
    return f"__Secure-care_login_{suffix}"


# 서버의 Secrets로 암호화 키 생성
def cookie_cipher():
    secret = str(
        st.secrets.get("LOGIN_COOKIE_SECRET", "")
    ).strip()

    if len(secret) < 32:
        st.error(
            "Streamlit Secrets에 LOGIN_COOKIE_SECRET을 설정해 주세요."
        )
        st.stop()

    key = base64.urlsafe_b64encode(
        sha256(secret.encode()).digest()
    )

    return Fernet(key)


# 세션 토큰 변경 여부 확인
def session_signature(session, until):
    value = json.dumps([
        session.access_token,
        session.refresh_token,
        until
    ])

    return sha256(value.encode()).hexdigest()


# 암호화된 로그인 유지 정보 저장 예약
def queue_cookie_save(session, until):
    payload = json.dumps(
        {
            "access": session.access_token,
            "refresh": session.refresh_token,
            "until": until
        },
        separators=(",", ":")
    )

    encrypted = (
        cookie_cipher()
        .encrypt(payload.encode())
        .decode()
    )

    if len(encrypted) > 3600:
        raise ValueError(
            "로그인 유지 정보가 쿠키에 저장하기에는 너무 커요."
        )

    st.session_state.care_cookie_job = {
        "id": uuid4().hex,
        "value": encrypted,
        "until": until,
        "signature": session_signature(session, until),
        "probe": 0
    }


# 로그인 유지 정보 삭제 예약
def queue_cookie_clear():
    st.session_state.care_cookie_job = {
        "id": uuid4().hex,
        "value": "",
        "until": 0,
        "signature": None,
        "probe": 0
    }


# 브라우저가 저장·삭제 결과를 응답한 후 다음 화면으로 이동
def finish_cookie_job():
    job = st.session_state.get("care_cookie_job")

    if not job:
        return

    manager = stx.CookieManager(
        key="care_cookie_manager"
    )

    expires = (
        datetime.fromtimestamp(
            job["until"],
            timezone.utc
        )
        if job["value"]
        else datetime(
            2000, 1, 1,
            tzinfo=timezone.utc
        )
    )

    manager.set(
        cookie_name(),
        job["value"],
        key=f"care_cookie_write_{job['id']}",
        path="/",
        expires_at=expires,
        secure=True,
        same_site="lax"
    )

    # 응답 전의 None과 실제 빈 쿠키 목록을 구분한다.
    browser_cookies = manager.cookie_manager(
        method="getAll",
        key=(
            f"care_cookie_verify_"
            f"{job['id']}_{job['probe']}"
        ),
        default=None
    )

    verified = False

    if isinstance(browser_cookies, dict):
        actual = browser_cookies.get(cookie_name())

        verified = (
            actual == job["value"]
            if job["value"]
            else (
                cookie_name() not in browser_cookies
                or actual == ""
            )
        )

    if verified:
        st.session_state.care_cookie_signature = (
            job["signature"]
        )
        st.session_state.pop(
            "care_cookie_job",
            None
        )
        st.rerun()

    st.info(
        "브라우저의 로그인 유지 정보를 처리하고 있어요."
    )
    st.caption(
        "계속 기다리는 화면이면 "
        "아래 버튼으로 다시 확인해 주세요."
    )

    if st.button(
        "브라우저 저장 상태 다시 확인",
        key="care_cookie_retry"
    ):
        job["probe"] += 1
        st.rerun()

    if job["value"] and st.button(
        "로그인 유지 없이 계속"
    ):
        st.session_state.care_remember = False
        queue_cookie_clear()
        st.rerun()

    st.stop()


# 현재 접속과 브라우저의 로그인 유지 정보 정리
def logout_here(client):
    try:
        client.auth.sign_out({"scope": "local"})
    except Exception:
        pass

    st.session_state.clear()

    # 현재 연결의 최초 쿠키로 다시 로그인되지 않게 한다.
    st.session_state.care_restore_checked = True
    st.session_state.care_auth_notice = "로그아웃했어요."

    queue_cookie_clear()
    st.rerun()


# 새로고침 후 저장된 로그인 복원
def restore_login(client):
    if st.session_state.get("care_restore_checked"):
        return

    encrypted = st.context.cookies.get(
        cookie_name()
    )

    if not encrypted:
        st.session_state.care_restore_checked = True
        return

    try:
        payload = json.loads(
            cookie_cipher().decrypt(
                unquote(encrypted).encode(),
                ttl=REMEMBER_SECONDS
            ).decode()
        )

        until = int(payload["until"])

        if until <= int(time.time()):
            raise ValueError("로그인 유지 기간 만료")

        if not payload["access"] or not payload["refresh"]:
            raise ValueError("로그인 유지 정보 누락")

    except (
        InvalidToken,
        ValueError,
        KeyError,
        TypeError,
        AttributeError
    ):
        st.session_state.care_restore_checked = True
        st.session_state.care_auth_notice = (
            "로그인 유지 기간이 끝났거나 "
            "정보를 확인할 수 없어요. 다시 로그인해 주세요."
        )

        queue_cookie_clear()
        st.rerun()

    try:
        result = client.auth.set_session(
            payload["access"],
            payload["refresh"]
        )

        if not result.session:
            raise ValueError("복원된 세션 없음")

    except Exception as error:
        status = str(
            getattr(error, "status", "")
        )

        if (
            status in {"400", "401", "403", "422"}
            or isinstance(error, ValueError)
        ):
            st.session_state.pop(
                "care_client",
                None
            )
            st.session_state.care_restore_checked = True
            st.session_state.care_auth_notice = (
                "이전 로그인이 만료됐어요. 다시 로그인해 주세요."
            )

            queue_cookie_clear()
            st.rerun()

        st.error(
            "로그인을 복원하지 못했어요. "
            "연결 상태를 확인해 주세요."
        )

        if st.button("로그인 복원 다시 시도"):
            st.rerun()

        if st.button(
            "저장된 로그인 지우고 다시 로그인"
        ):
            logout_here(client)

        st.stop()

    st.session_state.care_restore_checked = True
    st.session_state.care_remember = True
    st.session_state.care_remember_until = until


# 갱신된 토큰을 브라우저에도 반영
def sync_login_cookie(session):
    if not st.session_state.get("care_remember"):
        return

    until = st.session_state.get(
        "care_remember_until",
        0
    )

    if until <= int(time.time()):
        st.session_state.care_remember = False
        queue_cookie_clear()
        st.rerun()

    signature = session_signature(
        session,
        until
    )

    if signature == st.session_state.get(
        "care_cookie_signature"
    ):
        return

    try:
        queue_cookie_save(
            session,
            until
        )

    except ValueError:
        st.session_state.care_remember = False
        st.session_state.care_auth_notice = (
            "로그인 유지 정보를 저장할 수 없어 "
            "이번 접속에서만 로그인해요."
        )
        queue_cookie_clear()

    st.rerun()


# 공통 왼쪽 메뉴
def show_menu():
    st.sidebar.title("🩸 당당케어")

    for path, label, icon in [
        ("pages/home.py", "우리 가족 케어", "🏠"),
        ("pages/record.py", "혈당 기록하기", "🩸"),
        ("pages/history.py", "기록 확인·수정", "📈"),
        ("pages/lifestyle.py", "식사·활동 기록", "📝"),
        ("pages/meal.py", "냉장고 식단 추천", "🍽️"),
        ("pages/explore.py", "내 기록 탐구실", "🔍"),
        ("pages/visit.py", "진료 준비 노트", "🏥"),
        ("pages/chat.py", "AI에게 물어보기", "💬")
    ]:
        st.sidebar.page_link(
            path,
            label=label,
            icon=icon
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
    finish_cookie_job()
    cookie_cipher()

    client = get_client()
    restore_login(client)

    try:
        session = client.auth.get_session()
        user = (
            client.auth.get_user().user
            if session
            else None
        )

    except Exception:
        st.error(
            "로그인 상태를 확인하지 못했어요. "
            "잠시 후 다시 시도해 주세요."
        )

        if st.button("로그인 화면으로 돌아가기"):
            logout_here(client)

        st.stop()

    if user:
        sync_login_cookie(session)

        auth_notice = st.session_state.pop(
            "care_auth_notice",
            None
        )

        if auth_notice:
            st.info(auth_notice)

        st.sidebar.caption(
            f"로그인: {user.email}"
        )

        if st.sidebar.button(
            "로그아웃",
            use_container_width=True
        ):
            logout_here(client)

        show_first_login_confirmation(
            client,
            user
        )

        return client, user

    auth_notice = st.session_state.pop(
        "care_auth_notice",
        None
    )

    if auth_notice:
        st.info(auth_notice)

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

    login_tab, signup_tab = st.tabs([
        "로그인",
        "회원가입"
    ])

    # 로그인
    with login_tab:
        with st.form(
            "login_form",
            clear_on_submit=True
        ):
            email = st.text_input(
                "이메일",
                key="login_email"
            )

            password = st.text_input(
                "비밀번호",
                type="password",
                key="login_password"
            )

            remember = st.checkbox(
                "로그인 유지 (최대 7일)",
                value=False
            )

            st.caption(
                "개인 기기에서 선택해 주세요. "
                "비밀번호는 저장하지 않아요."
            )

            submitted = st.form_submit_button(
                "로그인",
                use_container_width=True
            )

        if submitted:
            if not email.strip() or not password:
                st.warning(
                    "이메일과 비밀번호를 입력해 주세요."
                )

            else:
                try:
                    result = client.auth.sign_in_with_password({
                        "email": email.strip(),
                        "password": password
                    })

                    if result.session:
                        st.session_state.care_restore_checked = True
                        st.session_state.care_remember = remember

                        if remember:
                            st.session_state.care_remember_until = (
                                int(time.time())
                                + REMEMBER_SECONDS
                            )

                        else:
                            queue_cookie_clear()

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

        with st.form(
            "signup_form",
            clear_on_submit=True
        ):
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
                st.warning(
                    "비밀번호는 8자 이상으로 입력해 주세요."
                )

            elif new_password != confirm:
                st.warning(
                    "두 비밀번호가 일치하지 않아요."
                )

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

                    signup_user = getattr(
                        result,
                        "user",
                        None
                    )

                    identities = getattr(
                        signup_user,
                        "identities",
                        None
                    )

                    if (
                        signup_user is not None
                        and identities == []
                    ):
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
                    code = getattr(
                        error,
                        "code",
                        None
                    )
                    message = str(error).lower()

                    if (
                        code in {
                            "user_already_exists",
                            "email_exists"
                        }
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
