import base64
import json
import time
from datetime import datetime, timezone
from hashlib import sha256
from uuid import uuid4
from urllib.parse import unquote
from zoneinfo import ZoneInfo, available_timezones

import streamlit as st
import extra_streamlit_components as stx
from cryptography.fernet import Fernet, InvalidToken
from supabase import ClientOptions, create_client


REMEMBER_SECONDS = 7 * 24 * 60 * 60

APP_URL = (
    "https://kimnaeul-nfmpatlk9u3uysxmtesvuq.streamlit.app/"
)


# 국가·지역별 기본 시간대
COUNTRIES = {
    "KR": ("대한민국", "Asia/Seoul"),
    "JP": ("일본", "Asia/Tokyo"),
    "CN": ("중국", "Asia/Shanghai"),
    "TW": ("대만", "Asia/Taipei"),
    "HK": ("홍콩", "Asia/Hong_Kong"),
    "SG": ("싱가포르", "Asia/Singapore"),
    "TH": ("태국", "Asia/Bangkok"),
    "VN": ("베트남", "Asia/Ho_Chi_Minh"),
    "PH": ("필리핀", "Asia/Manila"),
    "ID": ("인도네시아", "Asia/Jakarta"),
    "IN": ("인도", "Asia/Kolkata"),
    "US": ("미국", "America/New_York"),
    "CA": ("캐나다", "America/Toronto"),
    "MX": ("멕시코", "America/Mexico_City"),
    "BR": ("브라질", "America/Sao_Paulo"),
    "AR": (
        "아르헨티나",
        "America/Argentina/Buenos_Aires"
    ),
    "GB": ("영국", "Europe/London"),
    "FR": ("프랑스", "Europe/Paris"),
    "DE": ("독일", "Europe/Berlin"),
    "IT": ("이탈리아", "Europe/Rome"),
    "ES": ("스페인", "Europe/Madrid"),
    "PT": ("포르투갈", "Europe/Lisbon"),
    "NL": ("네덜란드", "Europe/Amsterdam"),
    "CH": ("스위스", "Europe/Zurich"),
    "SE": ("스웨덴", "Europe/Stockholm"),
    "TR": ("튀르키예", "Europe/Istanbul"),
    "RU": ("러시아", "Europe/Moscow"),
    "AE": ("아랍에미리트", "Asia/Dubai"),
    "ZA": (
        "남아프리카공화국",
        "Africa/Johannesburg"
    ),
    "AU": ("호주", "Australia/Sydney"),
    "NZ": ("뉴질랜드", "Pacific/Auckland"),
}


TIMEZONE_LABELS = {
    "Asia/Seoul": "서울",
    "Asia/Tokyo": "도쿄",
    "Asia/Shanghai": "상하이·베이징",
    "Asia/Taipei": "타이베이",
    "Asia/Hong_Kong": "홍콩",
    "Asia/Singapore": "싱가포르",
    "Asia/Bangkok": "방콕",
    "Asia/Ho_Chi_Minh": "호찌민",
    "Asia/Manila": "마닐라",
    "Asia/Jakarta": "자카르타",
    "Asia/Kolkata": "콜카타·뉴델리",
    "America/New_York": "뉴욕",
    "America/Chicago": "시카고",
    "America/Denver": "덴버",
    "America/Los_Angeles": "로스앤젤레스",
    "America/Phoenix": "피닉스",
    "America/Anchorage": "앵커리지",
    "Pacific/Honolulu": "호놀룰루",
    "America/Toronto": "토론토",
    "America/Vancouver": "밴쿠버",
    "America/Mexico_City": "멕시코시티",
    "America/Sao_Paulo": "상파울루",
    "America/Argentina/Buenos_Aires": "부에노스아이레스",
    "Europe/London": "런던",
    "Europe/Paris": "파리",
    "Europe/Berlin": "베를린",
    "Europe/Rome": "로마",
    "Europe/Madrid": "마드리드",
    "Europe/Lisbon": "리스본",
    "Europe/Amsterdam": "암스테르담",
    "Europe/Zurich": "취리히",
    "Europe/Stockholm": "스톡홀름",
    "Europe/Istanbul": "이스탄불",
    "Europe/Moscow": "모스크바",
    "Asia/Dubai": "두바이",
    "Africa/Johannesburg": "요하네스버그",
    "Australia/Sydney": "시드니",
    "Australia/Brisbane": "브리즈번",
    "Australia/Adelaide": "애들레이드",
    "Australia/Darwin": "다윈",
    "Australia/Perth": "퍼스",
    "Pacific/Auckland": "오클랜드",
    "UTC": "협정 세계시",
}


@st.cache_data
def get_timezone_options():
    return sorted(available_timezones())


def timezone_label(name):
    city = TIMEZONE_LABELS.get(name)

    return (
        f"{city} · {name}"
        if city
        else name
    )


def validate_location(country_code, timezone_name):
    if country_code not in COUNTRIES:
        raise ValueError(
            "지원하는 국가를 선택해 주세요."
        )

    if timezone_name not in get_timezone_options():
        raise ValueError(
            "올바른 시간대를 선택해 주세요."
        )

    ZoneInfo(timezone_name)


def location_inputs(
    prefix,
    country_code="KR",
    timezone_name="Asia/Seoul"
):
    if country_code not in COUNTRIES:
        country_code = "KR"

    codes = list(COUNTRIES)

    selected_country = st.selectbox(
        "거주 국가·지역",
        codes,
        index=codes.index(country_code),
        format_func=lambda code: COUNTRIES[code][0],
        key=f"{prefix}_country"
    )

    default_zone = (
        timezone_name
        if selected_country == country_code
        else COUNTRIES[selected_country][1]
    )

    zones = get_timezone_options()

    if default_zone not in zones:
        default_zone = COUNTRIES[selected_country][1]

    # 기본값과 자주 쓰는 도시를 앞에 표시해요.
    # 그 외 시간대도 전체 목록에서 검색할 수 있어요.
    preferred = [default_zone] + [
        name
        for name in TIMEZONE_LABELS
        if name in zones
    ]

    options = list(
        dict.fromkeys(preferred + zones)
    )

    selected_timezone = st.selectbox(
        "날짜·시간 기준 시간대",
        options,
        index=options.index(default_zone),
        format_func=timezone_label,
        key=f"{prefix}_timezone_{selected_country}"
    )

    st.caption(
        "한 나라에도 여러 시간대가 있을 수 있어요. "
        "실제로 거주하는 도시의 시간대를 확인해 주세요. "
        "목록에서 도시의 영문 이름으로 검색할 수 있어요."
    )

    st.caption(
        "선택한 시간대를 기록의 날짜·시간, 오늘의 기록, "
        "냉장고 기한 상태를 표시하는 기준으로 사용해요. "
        "설정은 나중에 변경할 수 있어요."
    )

    preview = datetime.now(
        ZoneInfo(selected_timezone)
    )

    st.info(
        "선택한 시간대의 현재 시각: "
        f"{preview:%Y-%m-%d %H:%M} "
        f"({selected_timezone})"
    )

    return selected_country, selected_timezone


def remember_account_preferences(user_id, preferences):
    st.session_state.care_preferences_user_id = str(user_id)

    st.session_state.care_country_code = (
        preferences["country_code"]
    )

    st.session_state.care_timezone_name = (
        preferences["timezone"]
    )


def load_account_preferences(client, user):
    rows = (
        client.table("account_preferences")
        .select("country_code,timezone")
        .eq("user_id", user.id)
        .limit(1)
        .execute()
        .data
    ) or []

    if not rows:
        metadata = user.user_metadata or {}

        country = metadata.get(
            "care_country_code",
            "KR"
        )

        zone = metadata.get(
            "care_timezone",
            "Asia/Seoul"
        )

        try:
            validate_location(country, zone)

        except (ValueError, TypeError, KeyError):
            country = "KR"
            zone = "Asia/Seoul"

        # 이미 저장된 설정을 덮어쓰지 않도록 insert만 사용해요.
        try:
            client.table("account_preferences").insert({
                "user_id": user.id,
                "country_code": country,
                "timezone": zone
            }).execute()

        except Exception:
            # 다른 접속에서 먼저 생성했을 수도 있어 다시 조회해요.
            rows = (
                client.table("account_preferences")
                .select("country_code,timezone")
                .eq("user_id", user.id)
                .limit(1)
                .execute()
                .data
            ) or []

            if not rows:
                raise

        else:
            rows = [{
                "country_code": country,
                "timezone": zone
            }]

    preferences = rows[0]

    validate_location(
        preferences["country_code"],
        preferences["timezone"]
    )

    remember_account_preferences(
        user.id,
        preferences
    )

    return preferences


def get_timezone_name():
    return st.session_state.get(
        "care_timezone_name",
        "Asia/Seoul"
    )


def get_user_timezone():
    return ZoneInfo(get_timezone_name())


def get_local_now():
    return datetime.now(get_user_timezone())


@st.dialog("국가·시간대 설정")
def show_location_settings(client, user, preferences):
    country, zone = location_inputs(
        f"care_location_{user.id}",
        preferences["country_code"],
        preferences["timezone"]
    )

    st.caption(
        "이 설정은 같은 계정의 모든 관리 대상이 함께 사용해요. "
        "저장된 기록의 날짜·시간 값을 자동으로 바꾸지는 않아요."
    )

    if st.button(
        "💾 국가·시간대 저장",
        use_container_width=True
    ):
        try:
            validate_location(country, zone)

            result = (
                client.table("account_preferences")
                .upsert(
                    {
                        "user_id": user.id,
                        "country_code": country,
                        "timezone": zone
                    },
                    on_conflict="user_id",
                    returning="representation"
                )
                .execute()
            )

            if not result.data:
                raise ValueError(
                    "설정 저장 결과를 확인하지 못했어요."
                )

            remember_account_preferences(
                user.id,
                result.data[0]
            )

        except Exception:
            st.error(
                "국가·시간대를 저장하지 못했어요. "
                "잠시 후 다시 시도해 주세요."
            )

        else:
            st.session_state.care_location_notice = (
                "국가·시간대 설정을 저장했어요."
            )
            st.rerun()


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


def cookie_name():
    project = (
        st.secrets["SUPABASE_URL"]
        .strip()
        .rstrip("/")
    )

    suffix = sha256(
        project.encode()
    ).hexdigest()[:12]

    return f"__Secure-care_login_{suffix}"


def cookie_cipher():
    secret = str(
        st.secrets.get("LOGIN_COOKIE_SECRET", "")
    ).strip()

    if len(secret) < 32:
        st.error(
            "Streamlit Secrets에 "
            "LOGIN_COOKIE_SECRET을 설정해 주세요."
        )
        st.stop()

    key = base64.urlsafe_b64encode(
        sha256(secret.encode()).digest()
    )

    return Fernet(key)


def session_signature(session, until):
    value = json.dumps([
        session.access_token,
        session.refresh_token,
        until
    ])

    return sha256(
        value.encode()
    ).hexdigest()


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


def queue_cookie_clear():
    st.session_state.care_cookie_job = {
        "id": uuid4().hex,
        "value": "",
        "until": 0,
        "signature": None,
        "probe": 0
    }


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

    browser_cookies = manager.cookie_manager(
        method="getAll",
        key=(
            "care_cookie_verify_"
            f"{job['id']}_{job['probe']}"
        ),
        default=None
    )

    verified = False

    if isinstance(browser_cookies, dict):
        actual = browser_cookies.get(
            cookie_name()
        )

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


def logout_here(client):
    try:
        client.auth.sign_out({"scope": "local"})

    except Exception:
        pass

    st.session_state.clear()

    st.session_state.care_restore_checked = True
    st.session_state.care_auth_notice = "로그아웃했어요."

    queue_cookie_clear()
    st.rerun()


# 브라우저가 실제 쿠키 목록을 보낼 때까지 기다려요.
def restore_login(client):
    if st.session_state.get("care_restore_checked"):
        return

    manager = stx.CookieManager(
        key="care_restore_cookie_init"
    )

    attempt = st.session_state.get(
        "care_restore_cookie_attempt",
        0
    )

    browser_cookies = manager.cookie_manager(
        method="getAll",
        key=f"care_restore_cookie_read_{attempt}",
        default=None
    )

    if not isinstance(browser_cookies, dict):
        st.info(
            "저장된 로그인 정보를 확인하고 있어요."
        )

        if st.button("로그인 정보 다시 확인"):
            st.session_state.care_restore_cookie_attempt = (
                attempt + 1
            )
            st.rerun()

        st.stop()

    encrypted = browser_cookies.get(
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
            raise ValueError(
                "로그인 유지 기간 만료"
            )

        if not payload["access"] or not payload["refresh"]:
            raise ValueError(
                "로그인 유지 정보 누락"
            )

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
            raise ValueError(
                "복원된 세션 없음"
            )

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

    st.session_state.care_auth_notice = (
        "저장된 로그인 정보를 복원했어요."
    )


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
        queue_cookie_save(session, until)

    except ValueError:
        st.session_state.care_remember = False

        st.session_state.care_auth_notice = (
            "로그인 유지 정보를 저장할 수 없어 "
            "이번 접속에서만 로그인해요."
        )

        queue_cookie_clear()

    st.rerun()


def show_menu():
    st.sidebar.title("🩸 당당케어")

    for path, label, icon in [
        ("pages/home.py", "우리 가족 케어", "🏠"),
        ("pages/record.py", "혈당 기록하기", "🩸"),
        ("pages/history.py", "기록 확인·수정", "📈"),
        ("pages/lifestyle.py", "식사·활동 기록", "📝"),
        ("pages/meal.py", "냉장고 식단 추천", "🍽️"),
        ("pages/explore.py", "내 기록 탐구실", "🔍"),
        ("pages/visit.py", "진료 노트", "🏥"),
        ("pages/chat.py", "AI에게 물어보기", "💬")
    ]:
        st.sidebar.page_link(
            path,
            label=label,
            icon=icon
        )


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

    st.success(
        "이메일 인증과 로그인을 모두 마쳤어요."
    )

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


def delete_account_with_password(user, password):
    verifier = create_client(
        st.secrets["SUPABASE_URL"].strip().rstrip("/"),
        st.secrets["SUPABASE_KEY"].strip(),
        options=ClientOptions(auto_refresh_token=False)
    )

    try:
        try:
            result = verifier.auth.sign_in_with_password({
                "email": user.email,
                "password": password
            })

        except Exception:
            raise ValueError(
                "본인 확인에 실패했어요. "
                "현재 비밀번호와 연결 상태를 확인해 주세요."
            ) from None

        if (
            not result.session
            or not result.user
            or str(result.user.id) != str(user.id)
        ):
            raise ValueError(
                "로그인한 계정과 확인된 계정이 일치하지 않아요."
            )

        verifier.rpc(
            "delete_my_account",
            {"confirmation": "회원 탈퇴"}
        ).execute()

    finally:
        try:
            verifier.auth.sign_out({
                "scope": "local"
            })

        except Exception:
            pass


@st.dialog("회원 탈퇴")
def show_account_deletion(user):
    st.write(
        f"탈퇴할 계정: {user.email}"
    )

    st.warning(
        "이 계정에 등록한 모든 사람·반려동물의 관리 대상, "
        "혈당 기록, 식사·활동·수면 기록, "
        "냉장고 재료와 식사 조건, 진료 노트를 함께 삭제해요. "
        "삭제한 내용은 앱에서 복구할 수 없어요."
    )

    st.caption(
        "필요한 기록은 탈퇴 전에 "
        "각 기록 페이지에서 다운로드해 주세요."
    )

    with st.form(
        "care_delete_account_form",
        clear_on_submit=True
    ):
        password = st.text_input(
            "현재 비밀번호를 다시 입력해 주세요.",
            type="password"
        )

        confirmation = st.text_input(
            "확인을 위해 ‘회원 탈퇴’를 입력해 주세요."
        )

        confirmed = st.checkbox(
            "계정과 연결된 모든 기록이 삭제되는 것을 확인했어요."
        )

        submitted = st.form_submit_button(
            "계정과 모든 기록을 삭제하고 탈퇴",
            use_container_width=True
        )

    if not submitted:
        return

    if not password:
        st.warning(
            "현재 비밀번호를 입력해 주세요."
        )
        return

    if confirmation.strip() != "회원 탈퇴":
        st.warning(
            "확인 문구 ‘회원 탈퇴’를 정확하게 입력해 주세요."
        )
        return

    if not confirmed:
        st.warning(
            "삭제 확인란을 체크해 주세요."
        )
        return

    try:
        with st.spinner(
            "본인 확인 후 회원 탈퇴를 처리하고 있어요."
        ):
            delete_account_with_password(
                user,
                password
            )

    except ValueError as error:
        st.error(str(error))
        return

    except Exception:
        st.error(
            "회원 탈퇴 결과를 확인하지 못했어요. "
            "다시 로그인하여 계정 상태를 확인해 주세요. "
            "계정이 유지되어 있다면 "
            "Supabase 삭제 함수 설정도 확인해 주세요."
        )
        return

    st.session_state.clear()

    st.session_state.care_restore_checked = True

    st.session_state.care_auth_notice = (
        "회원 탈퇴가 완료됐어요. "
        "계정과 연결된 기록을 삭제했어요."
    )

    queue_cookie_clear()
    st.rerun()


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

        st.sidebar.caption(
            "로그인 유지 사용 중"
            if st.session_state.get("care_remember")
            else "이번 접속에서만 로그인 중"
        )

        if st.sidebar.button(
            "로그아웃",
            use_container_width=True
        ):
            logout_here(client)

        if st.sidebar.button(
            "회원 탈퇴",
            use_container_width=True
        ):
            show_account_deletion(user)

        show_first_login_confirmation(
            client,
            user
        )

        try:
            preferences = load_account_preferences(
                client,
                user
            )

        except Exception:
            st.error(
                "국가·시간대 설정을 불러오지 못했어요. "
                "account_preferences SQL 실행 여부와 "
                "연결 상태를 확인해 주세요."
            )

            if st.button(
                "국가·시간대 설정 다시 불러오기"
            ):
                st.rerun()

            st.stop()

        location_notice = st.session_state.pop(
            "care_location_notice",
            None
        )

        if location_notice:
            st.success(location_notice)

        st.sidebar.caption(
            "국가: "
            f"{COUNTRIES[preferences['country_code']][0]} · "
            f"시간대: {preferences['timezone']}"
        )

        if st.sidebar.button(
            "🌍 국가·시간대 설정",
            use_container_width=True
        ):
            show_location_settings(
                client,
                user,
                preferences
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
                    result = (
                        client.auth.sign_in_with_password({
                            "email": email.strip(),
                            "password": password
                        })
                    )

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

        # 국가 변경에 따라 시간대가 즉시 갱신되도록
        # 두 선택란은 회원가입 폼 밖에 배치해요.
        signup_country, signup_timezone = (
            location_inputs(
                "care_signup_location"
            )
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
                st.warning(
                    "이메일 주소를 입력해 주세요."
                )

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
                    validate_location(
                        signup_country,
                        signup_timezone
                    )

                    result = client.auth.sign_up({
                        "email": new_email.strip(),
                        "password": new_password,
                        "options": {
                            "email_redirect_to": APP_URL,
                            "data": {
                                "care_country_code": signup_country,
                                "care_timezone": signup_timezone
                            }
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
