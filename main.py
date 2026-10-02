import streamlit as st
from supabase import create_client
import requests
from datetime import datetime
from zoneinfo import ZoneInfo


# =========================================================
# 1. 기본 설정
# =========================================================

st.set_page_config(
    page_title="당당케어",
    page_icon="🩸",
    layout="wide"
)


# =========================================================
# 2. Supabase 연결
# =========================================================

@st.cache_resource
def connect_supabase():
    """Supabase 데이터베이스에 연결하는 함수"""
    return create_client(
        st.secrets["SUPABASE_URL"],
        st.secrets["SUPABASE_KEY"]
    )


supabase = connect_supabase()
# ===== Supabase 연결 진단용 임시 코드 =====
if st.button("🔧 Supabase 저장 진단"):

    url = st.secrets["SUPABASE_URL"] + "/rest/v1/blood_glucose"
    key = st.secrets["SUPABASE_KEY"]

    headers = {
        "apikey": key,
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
        "Prefer": "return=minimal"
    }

    test_data = {
        "name": "연결테스트",
        "measure_date": "2026-10-02",
        "measure_time": "12:00",
        "glucose": 100,
        "meal": "공복",
        "insulin": 0,
        "memo": "Streamlit 연결 진단"
    }

    response = requests.post(
        url,
        headers=headers,
        json=test_data
    )

    st.write("상태 코드:", response.status_code)
    st.write("응답:", response.text)

# =========================================================
# 3. 세션 상태 초기화
# =========================================================

def initialize_session():
    """앱에서 사용할 세션 상태를 처음 한 번 생성"""
    
    if "page" not in st.session_state:
        st.session_state.page = "start"

    if "user_type" not in st.session_state:
        st.session_state.user_type = None

    if "profile_name" not in st.session_state:
        st.session_state.profile_name = ""


initialize_session()


# =========================================================
# 4. 공통 디자인
# =========================================================

st.markdown("""
<style>

/* 전체 배경 */
.stApp {
    background-color: #FFF9F9;
}

/* 메인 제목 */
.main-title {
    text-align: center;
    font-size: 46px;
    font-weight: 800;
    margin-top: 40px;
    margin-bottom: 5px;
}

/* 부제목 */
.main-subtitle {
    text-align: center;
    font-size: 18px;
    color: #777777;
    margin-bottom: 35px;
}

/* 카드 */
.card {
    background-color: white;
    padding: 25px;
    border-radius: 20px;
    border: 1px solid #EEEEEE;
    text-align: center;
    min-height: 150px;
}

/* 버튼 */
div.stButton > button {
    border-radius: 14px;
    height: 48px;
    font-weight: 700;
}

/* 폼 */
div[data-testid="stForm"] {
    background-color: white;
    padding: 25px;
    border-radius: 20px;
    border: 1px solid #EEEEEE;
}

</style>
""", unsafe_allow_html=True)


# =========================================================
# 5. 페이지 이동 함수
# =========================================================

def move_page(page_name):
    """원하는 화면으로 이동"""
    st.session_state.page = page_name
    st.rerun()


# =========================================================
# 화면 1 : 시작 화면
# =========================================================

def show_start_page():

    st.markdown(
        '<div class="main-title">🩸 당당케어</div>',
        unsafe_allow_html=True
    )

    st.markdown(
        '<div class="main-subtitle">'
        '사람과 반려동물의 혈당을 간편하게 기록하고 관리해요'
        '</div>',
        unsafe_allow_html=True
    )

    st.write("")
    st.subheader("누구의 혈당을 관리할까요?")

    human_col, pet_col = st.columns(2)

    # 사람 선택
    with human_col:

        st.markdown("""
        <div class="card">
            <div style="font-size:50px;">👤</div>
            <h3>사람</h3>
            <p>나 또는 가족의 혈당을 기록하고 관리해요.</p>
        </div>
        """, unsafe_allow_html=True)

        if st.button(
            "👤 사람으로 시작하기",
            use_container_width=True
        ):
            st.session_state.user_type = "사람"
            move_page("profile")

    # 반려동물 선택
    with pet_col:

        st.markdown("""
        <div class="card">
            <div style="font-size:50px;">🐾</div>
            <h3>반려동물</h3>
            <p>반려동물의 혈당을 기록하고 관리해요.</p>
        </div>
        """, unsafe_allow_html=True)

        if st.button(
            "🐾 반려동물로 시작하기",
            use_container_width=True
        ):
            st.session_state.user_type = "반려동물"
            move_page("profile")


# =========================================================
# 화면 2 : 프로필 설정
# =========================================================

def show_profile_page():

    st.title("✨ 프로필 설정")

    if st.session_state.user_type == "사람":
        st.write("혈당을 기록할 사람의 기본 정보를 입력해 주세요.")
    else:
        st.write("혈당을 기록할 반려동물의 기본 정보를 입력해 주세요.")

    st.divider()

    with st.form("profile_form"):

        if st.session_state.user_type == "사람":

            profile_name = st.text_input(
                "이름 또는 별명",
                placeholder="예: 나을"
            )

        else:

            profile_name = st.text_input(
                "반려동물 이름",
                placeholder="예: 초코"
            )

            animal_type = st.selectbox(
                "동물 종류",
                [
                    "강아지",
                    "고양이",
                    "기타"
                ]
            )

        submitted = st.form_submit_button(
            "관리 시작하기 →",
            use_container_width=True
        )

    if submitted:

        # 예외 처리 1 : 이름 미입력
        if not profile_name.strip():

            st.warning("⚠️ 이름을 입력해 주세요.")

        else:

            st.session_state.profile_name = profile_name

            if st.session_state.user_type == "반려동물":
                st.session_state.animal_type = animal_type

            move_page("dashboard")

    if st.button("← 이전 화면"):
        move_page("start")


# =========================================================
# 화면 3 : 메인 대시보드
# =========================================================

def show_dashboard():

    name = st.session_state.profile_name
    user_type = st.session_state.user_type

    emoji = "👤" if user_type == "사람" else "🐾"

    st.title(f"{emoji} {name}의 혈당 관리")

    st.write(
        "혈당을 기록하거나 지금까지의 기록을 확인해 보세요."
    )

    st.divider()

    # -------------------------
    # 기능 카드
    # -------------------------

    col1, col2, col3 = st.columns(3)

    # 혈당 기록
    with col1:

        st.markdown("""
        <div class="card">
            <div style="font-size:45px;">🩸</div>
            <h3>혈당 기록</h3>
            <p>오늘의 혈당과 측정 상황을 기록해요.</p>
        </div>
        """, unsafe_allow_html=True)

        if st.button(
            "혈당 기록하기",
            use_container_width=True
        ):
            move_page("record")

    # 기록 분석
    with col2:

        st.markdown("""
        <div class="card">
            <div style="font-size:45px;">📈</div>
            <h3>기록 분석</h3>
            <p>저장한 혈당 변화와 기록을 확인해요.</p>
        </div>
        """, unsafe_allow_html=True)

        if st.button(
            "기록 확인하기",
            use_container_width=True
        ):
            move_page("analysis")

    # AI 해석
    with col3:

        st.markdown("""
        <div class="card">
            <div style="font-size:45px;">🤖</div>
            <h3>AI 검사 수치 해석</h3>
            <p>검사 수치를 입력하고 쉽게 설명받아요.</p>
        </div>
        """, unsafe_allow_html=True)

        if st.button(
            "AI에게 물어보기",
            use_container_width=True
        ):
            move_page("ai")

    st.write("")

    if st.button("🔄 관리 대상 변경"):
        st.session_state.user_type = None
        st.session_state.profile_name = ""
        move_page("start")


# =========================================================
# 화면 4 : 혈당 기록
# =========================================================
def show_record_page():

    st.title("🩸 혈당 기록")

    st.caption(
        f"{st.session_state.profile_name}의 새로운 혈당 기록을 입력해 주세요."
    )

    st.divider()

    # 대한민국 표준시(KST) 기준 현재 날짜와 시간
    korea_now = datetime.now(ZoneInfo("Asia/Seoul"))

    with st.form("glucose_form"):

        col1, col2 = st.columns(2)

        with col1:
            measure_date = st.date_input(
                "📅 측정 날짜",
                value=korea_now.date()
            )

        with col2:
            measure_time = st.time_input(
                "🕐 측정 시간",
                value=korea_now.time().replace(
                    second=0,
                    microsecond=0
                ),
                step=60
            )

            # 오전/오후를 쉽게 구분할 수 있도록 24시간제로 표시
            st.caption(
                f"선택한 시간: {measure_time.strftime('%H:%M')}"
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
            placeholder="식사, 활동량, 컨디션 등을 자유롭게 기록해 주세요."
        )

        save_button = st.form_submit_button(
            "💾 혈당 기록 저장하기",
            use_container_width=True
        )

    # 혈당 기록 저장
    if save_button:

        # 예외 처리 1 : 혈당 미입력
        if glucose <= 0:

            st.warning(
                "⚠️ 혈당 수치를 입력해 주세요."
            )

        # 예외 처리 2 : 측정 시점 미선택
        elif meal == "선택해 주세요":

            st.warning(
                "⚠️ 혈당을 언제 측정했는지 선택해 주세요."
            )

        else:

            try:

                record_data = {
                    "name": st.session_state.profile_name,
                    "measure_date": str(measure_date),

                    # 24시간제(HH:MM)로 저장
                    "measure_time": measure_time.strftime("%H:%M"),

                    "glucose": glucose,
                    "meal": meal,
                    "insulin": insulin,
                    "memo": memo
                }

                supabase.table(
                    "blood_glucose"
                ).insert(
                    record_data
                ).execute()

                st.success(
                    f"🎉 혈당 {glucose} mg/dL 기록을 저장했어요!"
                )

            # 예외 처리 3 : 데이터베이스 저장 오류
            except Exception as error:

                st.error(
                    "❌ 기록을 저장하는 중 문제가 발생했어요."
                )

                with st.expander("오류 내용 확인"):
                    st.code(str(error))

    st.write("")

    if st.button("← 메인 화면으로"):
        move_page("dashboard")


# =========================================================
# 화면 5 : 기록 분석
# =========================================================

def show_analysis_page():

    st.title("📈 혈당 기록 분석")

    st.info(
        "다음 단계에서 Supabase에 저장된 혈당 기록과 "
        "혈당 변화 그래프를 이 화면에 추가할 예정이에요."
    )

    if st.button("← 메인 화면으로"):
        move_page("dashboard")


# =========================================================
# 화면 6 : AI 검사 수치 해석
# =========================================================

def show_ai_page():

    st.title("🤖 AI 검사 수치 해석")

    st.warning(
        "AI의 설명은 검사 수치를 이해하기 위한 참고 정보이며 "
        "의료진 또는 수의사의 진단을 대신하지 않아요."
    )

    st.info(
        "다음 단계에서 검사 수치를 입력하고 "
        "AI에게 설명을 요청하는 기능을 연결할 예정이에요."
    )

    if st.button("← 메인 화면으로"):
        move_page("dashboard")


# =========================================================
# 6. 현재 페이지 표시
# =========================================================

current_page = st.session_state.page


if current_page == "start":
    show_start_page()

elif current_page == "profile":
    show_profile_page()

elif current_page == "dashboard":
    show_dashboard()

elif current_page == "record":
    show_record_page()

elif current_page == "analysis":
    show_analysis_page()

elif current_page == "ai":
    show_ai_page()

else:
    move_page("start")
