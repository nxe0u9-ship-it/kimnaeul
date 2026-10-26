from datetime import datetime, timedelta
from uuid import uuid4
from zoneinfo import ZoneInfo

import pandas as pd
import streamlit as st

from app_shared import require_login, show_menu


st.set_page_config(
    page_title="당당케어",
    page_icon="🩸",
    layout="wide"
)

st.markdown("""
<style>
.stApp {
    background-color: #FFF9F9;
}
div.stButton > button {
    border-radius: 14px;
}
div[data-testid="stForm"] {
    padding: 22px;
    border-radius: 18px;
    background: white;
    border: 1px solid #EEEEEE;
}
</style>
""", unsafe_allow_html=True)

show_menu()
client, user = require_login()

st.title("🩸 나와 가족, 반려동물의 혈당 관리")
st.caption(
    "관리 대상을 선택해 혈당을 기록하고 이전 기록을 확인해요."
)

# 저장된 관리 대상 목록을 불러온다.
try:
    profiles = (
        client.table("care_profiles")
        .select("id,name,profile_type,animal_type")
        .eq("user_id", user.id)
        .order("created_at")
        .execute()
        .data
    )
except Exception:
    st.error(
        "관리 대상 목록을 불러오지 못했어요. "
        "연결 상태와 care_profiles 정책을 확인해 주세요."
    )
    st.stop()

# 관리 대상 추가
with st.expander("➕ 관리 대상 추가", expanded=not profiles):
    profile_type = st.radio(
        "대상 구분",
        ["사람", "반려동물"],
        horizontal=True
    )

    with st.form("add_profile", clear_on_submit=True):
        name = st.text_input(
            "이름 또는 별명",
            max_chars=50
        )

        animal_type = None

        if profile_type == "반려동물":
            animal_type = st.selectbox(
                "동물 종류",
                ["강아지", "고양이", "기타"]
            )

        added = st.form_submit_button(
            "관리 대상 등록",
            use_container_width=True
        )

    if added:
        if not name.strip():
            st.warning("이름 또는 별명을 입력해 주세요.")
        else:
            try:
                profile_id = str(uuid4())

                client.table("care_profiles").insert(
                    {
                        "id": profile_id,
                        "user_id": user.id,
                        "name": name.strip(),
                        "profile_type": profile_type,
                        "animal_type": animal_type
                    },
                    returning="minimal"
                ).execute()

            except Exception as error:
                st.error(
                    "관리 대상을 등록하지 못했어요. "
                    "잠시 후 다시 시도해 주세요."
                )

                # 개인정보 대신 오류 종류와 코드만 표시한다.
                error_code = getattr(error, "code", None)

                st.caption(
                    f"오류 종류: {type(error).__name__} / "
                    f"오류 코드: {error_code or '없음'}"
                )

            else:
                st.session_state.active_profile = profile_id
                st.rerun()

if not profiles:
    st.info(
        "먼저 위에서 관리 대상을 등록해 주세요. "
        "사람과 반려동물을 여러 명 등록할 수 있어요."
    )
    st.stop()

# 고유번호를 기준으로 관리 대상을 선택한다.
profile_map = {
    profile["id"]: profile
    for profile in profiles
}

if st.session_state.get("active_profile") not in profile_map:
    st.session_state.active_profile = profiles[0]["id"]


def profile_label(profile_id):
    profile = profile_map[profile_id]
    kind = profile.get("animal_type") or profile["profile_type"]

    return (
        f"{profile['name']} · "
        f"{kind} · {profile_id[:8]}"
    )


selected_id = st.selectbox(
    "관리 대상 선택",
    list(profile_map),
    format_func=profile_label,
    key="active_profile"
)

profile = profile_map[selected_id]

st.subheader(f"{profile['name']}의 혈당 관리")

record_tab, history_tab = st.tabs([
    "🩸 혈당 기록",
    "📈 기록·그래프"
])

now = datetime.now(ZoneInfo("Asia/Seoul"))

# 혈당 기록 입력
with record_tab:
    with st.form(f"glucose_{selected_id}"):
        c1, c2 = st.columns(2)

        measure_date = c1.date_input(
            "📅 측정 날짜",
            value=now.date()
        )

        measure_time = c2.time_input(
            "🕐 측정 시간",
            value=now.time().replace(
                second=0,
                microsecond=0
            ),
            step=60
        )

        st.caption(
            "시간은 대한민국 기준이며, "
            "오후 1시는 13:00으로 저장돼요."
        )

        glucose = st.number_input(
            "🩸 혈당 수치 (mg/dL)",
            min_value=0,
            max_value=1000,
            value=0,
            step=1
        )

        meal = st.selectbox(
            "🍽️ 측정 시점",
            [
                "선택해 주세요",
                "공복",
                "식전",
                "식후 1시간",
                "식후 2시간",
                "취침 전",
                "기타"
            ]
        )

        insulin = st.number_input(
            "💉 인슐린 투여량 (단위)",
            min_value=0.0,
            value=0.0,
            step=0.5
        )

        memo = st.text_area(
            "📝 메모",
            placeholder="식사, 활동량, 컨디션 등을 기록해 주세요."
        )

        saved = st.form_submit_button(
            "💾 혈당 기록 저장",
            use_container_width=True
        )

    if saved:
        if glucose <= 0:
            st.warning("혈당 수치를 입력해 주세요.")

        elif meal == "선택해 주세요":
            st.warning("측정 시점을 선택해 주세요.")

        else:
            try:
                # 계정과 관리 대상의 고유번호를 함께 저장한다.
                client.table("blood_glucose").insert(
                    {
                        "user_id": user.id,
                        "profile_id": selected_id,
                        "name": profile["name"],
                        "measure_date": measure_date.isoformat(),
                        "measure_time": measure_time.strftime("%H:%M"),
                        "glucose": glucose,
                        "meal": meal,
                        "insulin": insulin,
                        "memo": memo
                    },
                    returning="minimal"
                ).execute()

            except Exception:
                st.error(
                    "저장하지 못했어요. 연결 상태와 "
                    "blood_glucose의 열·저장 정책을 확인해 주세요."
                )

            else:
                st.success(
                    f"{profile['name']}의 혈당 "
                    f"{glucose} mg/dL 기록을 저장했어요!"
                )

# 이전 기록 조회 및 그래프
with history_tab:
    c1, c2 = st.columns(2)

    start = c1.date_input(
        "조회 시작일",
        value=now.date() - timedelta(days=90),
        key="history_start"
    )

    end = c2.date_input(
        "조회 종료일",
        value=now.date(),
        key="history_end"
    )

    if start > end:
        st.warning(
            "조회 시작일은 종료일보다 늦을 수 없어요."
        )

    else:
        try:
            rows = (
                client.table("blood_glucose")
                .select(
                    "measure_date,measure_time,"
                    "glucose,meal,insulin,memo"
                )
                .eq("user_id", user.id)
                .eq("profile_id", selected_id)
                .gte("measure_date", start.isoformat())
                .lte("measure_date", end.isoformat())
                .order("measure_date", desc=True)
                .order("measure_time", desc=True)
                .limit(1000)
                .execute()
                .data
            )

        except Exception:
            st.error(
                "기록을 불러오지 못했어요. "
                "연결 상태와 혈당 조회 정책을 확인해 주세요."
            )
            rows = None

        if rows is not None:
            if not rows:
                st.info(
                    "선택한 기간에 저장된 기록이 없어요."
                )

            else:
                df = pd.DataFrame(rows)

                df["glucose"] = pd.to_numeric(
                    df["glucose"],
                    errors="coerce"
                )

                df["측정일시"] = pd.to_datetime(
                    df["measure_date"].astype(str)
                    + " "
                    + df["measure_time"].astype(str),
                    errors="coerce"
                )

                st.caption(
                    "선택한 기간의 최신 기록을 최대 1,000개 표시해요. "
                    "더 오래된 기록은 조회 기간을 바꿔 확인해 주세요."
                )

                c1, c2 = st.columns(2)

                c1.metric(
                    "표시된 기록",
                    f"{len(df)}개"
                )

                c2.metric(
                    "가장 최근 혈당",
                    f"{rows[0]['glucose']} mg/dL"
                )

                chart = (
                    df.dropna(
                        subset=["측정일시", "glucose"]
                    )
                    .sort_values("측정일시")
                )

                if not chart.empty:
                    st.line_chart(
                        chart.set_index("측정일시")[["glucose"]]
                        .rename(
                            columns={
                                "glucose": "혈당 (mg/dL)"
                            }
                        )
                    )

                display = df.drop(
                    columns=["측정일시"]
                ).rename(
                    columns={
                        "measure_date": "측정 날짜",
                        "measure_time": "측정 시간",
                        "glucose": "혈당 (mg/dL)",
                        "meal": "측정 시점",
                        "insulin": "인슐린 (단위)",
                        "memo": "메모"
                    }
                )

                st.dataframe(
                    display,
                    hide_index=True,
                    use_container_width=True
                )

                st.download_button(
                    "📥 표시된 기록 CSV 다운로드",
                    display.to_csv(index=False).encode("utf-8-sig"),
                    file_name="blood_glucose.csv",
                    mime="text/csv"
                )
