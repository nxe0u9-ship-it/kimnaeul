import streamlit as st
from openai import (
    OpenAI,
    APIConnectionError,
    APIStatusError,
    APITimeoutError,
    AuthenticationError,
    RateLimitError
)

from app_shared import require_login
from record_context import show_record_context
from record_ai import show_record_analysis


MODEL = "gemini-3.5-flash-lite"

BASE_URL = (
    "https://generativelanguage.googleapis.com/v1beta/openai/"
)

SYSTEM_PROMPT = """
너는 당당케어의 일반 정보 학습 도우미다.
항상 이해하기 쉬운 한국어로 답한다.

역할:
- 혈당 측정 용어, 기록 방법, 식사와 활동에 관한 일반 정보를 설명한다.
- 모르는 내용은 모른다고 말하고 사실을 만들어내지 않는다.
- 이 일반 채팅에서는 사용자의 저장된 기록을 전달받지 않는다.
- 기록을 확인하거나 분석했다고 말하지 않는다.
- 저장 기록에 관한 질문이면 위의 '선택한 기록으로 질문하기'
  기능을 이용하도록 안내한다.
- 사람과 반려동물의 기준을 혼동하지 않는다.
- 설명에 대상 구분이 필요하지만 불명확하면 먼저 질문한다.

답변 범위:
- 개인의 상태를 진단하거나 치료 방침을 결정하지 않는다.
- 약물이나 인슐린 용량 변경을 지시하지 않는다.
- 개인 수치에 대한 의료 판단 대신 일반적인 설명과
  의료진 또는 수의사에게 확인할 질문을 안내한다.
- 긴급한 증상이 언급되면 채팅 답변을 기다리기보다
  즉시 전문적인 도움을 받도록 안내한다.
- 이름, 연락처, 실제 검사 결과 등 민감한 정보 입력을 요구하지 않는다.

답변은 질문에 필요한 내용을 중심으로 간결하게 작성한다.
"""


st.set_page_config(
    page_title="AI에게 물어보기 | 당당케어",
    page_icon="💬",
    layout="wide"
)

st.markdown("""
<style>
.stApp { background-color: #FFF9F9; }

div.stButton > button {
    border-radius: 14px;
}
</style>
""", unsafe_allow_html=True)


# 왼쪽 메뉴
st.sidebar.title("🩸 당당케어")

for path, label, icon in [
    ("pages/home.py", "우리집 케어 홈", "🏠"),
    ("pages/record.py", "혈당 기록하기", "🩸"),
    ("pages/history.py", "기록 확인·수정", "📈"),
    ("pages/lifestyle.py", "식사·활동 기록", "📝"),
    ("pages/meal.py", "냉장고 식단 추천", "🍽️"),
    ("pages/explore.py", "내 기록 탐구실", "🔍"),
    ("pages/visit.py", "진료 준비 노트", "🏥")
]:
    st.sidebar.page_link(
        path,
        label=label,
        icon=icon
    )

profile_menu = st.sidebar.container()

st.sidebar.page_link(
    "pages/chat.py",
    label="AI에게 물어보기",
    icon="💬"
)


# 로그인 확인
client, user = require_login()


# 관리 대상 불러오기
try:
    profiles = (
        client.table("care_profiles")
        .select("id,name,profile_type,animal_type")
        .eq("user_id", user.id)
        .order("created_at")
        .execute()
        .data
    ) or []

except Exception:
    st.error(
        "관리 대상 목록을 불러오지 못했어요. "
        "잠시 후 다시 시도해 주세요."
    )
    st.stop()


profile_map = {
    item["id"]: item
    for item in profiles
}

if profiles:
    if st.session_state.get("active_profile") not in profile_map:
        st.session_state.active_profile = profiles[0]["id"]

    with profile_menu:
        st.caption("관리 대상")

        for item in profiles:
            icon = (
                "👤"
                if item["profile_type"] == "사람"
                else "🐾"
            )

            kind = (
                item.get("animal_type")
                or item["profile_type"]
            )

            label = f"{icon} {item['name']} · {kind}"

            if sum(
                p["name"] == item["name"]
                for p in profiles
            ) > 1:
                label += f" · {item['id'][:8]}"

            active = (
                item["id"]
                == st.session_state.active_profile
            )

            if st.button(
                label,
                key=f"chat_profile_{user.id}_{item['id']}",
                type="primary" if active else "secondary",
                use_container_width=True
            ):
                st.session_state.active_profile = item["id"]
                st.rerun()

else:
    profile_menu.caption("등록된 관리 대상이 없어요.")


# 페이지 안내
st.title("💬 AI에게 물어보기")
st.caption(
    "선택한 기간의 기록을 요약받거나, "
    "혈당 기록 방법과 식사·활동에 관한 일반 정보를 물어보세요."
)

if profiles:
    profile_id = st.session_state.active_profile
    profile = profile_map[profile_id]

    kind = (
        profile.get("animal_type")
        or profile["profile_type"]
    )

    st.info(
        f"현재 선택한 관리 대상: {profile['name']} · {kind}"
    )

else:
    profile_id = "general"


# 기록 미리보기와 기록 기반 질문
if profiles:
    with st.expander(
        "📋 내 기록 불러와 미리보기",
        expanded=True
    ):
        record_payload = show_record_context(
            client=client,
            user_id=user.id,
            profile_id=profile_id
        )

        st.caption(
            "기록을 불러오는 것만으로는 AI에 전송되지 않아요. "
            "아래에서 전송 내용을 확인하고 "
            "전송 버튼을 눌렀을 때만 요청해요."
        )

    show_record_analysis(
        user_id=user.id,
        profile_id=profile_id,
        payload=record_payload
    )

else:
    st.info(
        "관리 대상을 등록하면 저장된 기록을 불러와 "
        "기록 기반 질문 기능을 이용할 수 있어요."
    )

    st.page_link(
        "pages/record.py",
        label="관리 대상 등록하러 가기",
        icon="➕"
    )


# 일반 채팅 안내
st.divider()
st.subheader("💬 일반 정보 질문하기")

st.caption(
    "이 채팅에는 직접 입력한 질문과 최근 대화만 전송돼요. "
    "위에서 불러온 기록이나 기록 요약 답변은 "
    "일반 채팅에 자동으로 첨부되지 않아요."
)

st.caption(
    "일반 질문에는 실제 혈당·검사 결과나 개인정보를 입력하지 마세요. "
    "AI 답변은 의료진 또는 수의사의 진단·치료를 대신하지 않아요."
)


# 사용자·관리 대상별 일반 대화 보관
scope = f"{user.id}_{profile_id}"
messages_key = f"care_chat_messages_{scope}"

if messages_key not in st.session_state:
    st.session_state[messages_key] = []

if st.button(
    "🗑️ 일반 대화 지우기",
    key=f"clear_chat_{scope}"
):
    st.session_state[messages_key] = []
    st.rerun()

st.caption(
    "일반 대화는 현재 접속 세션에서만 보관해요. "
    "AI에는 최근 6번의 질문·답변을 함께 보내며, "
    "화면에는 최근 10번의 대화를 남겨요. "
    "대화 지우기는 앱 안의 일반 대화 목록을 비우는 기능이에요."
)


# API 키 확인
api_key = str(
    st.secrets.get("GEMINI_API_KEY", "")
).strip()

if not api_key:
    st.warning(
        "아직 Gemini API 키가 설정되지 않았어요. "
        "Streamlit Secrets에 GEMINI_API_KEY를 추가해 주세요."
    )
    st.stop()


# 일반 대화 표시
history = st.session_state[messages_key]

if not history:
    st.info(
        "예: ‘공복 혈당이라는 말은 무슨 뜻이야?’ "
        "또는 ‘식사 기록에는 어떤 내용을 적으면 좋아?’"
    )

for message in history:
    with st.chat_message(message["role"]):
        st.markdown(message["content"])


# 일반 질문 입력
user_input = st.chat_input(
    "일반적인 용어나 기록 방법을 물어보세요.",
    key=f"care_chat_input_{scope}"
)

if user_input:
    question = user_input.strip()

    if not question:
        st.warning("질문을 입력해 주세요.")
        st.stop()

    if len(question) > 3000:
        st.warning("질문은 3,000자 이내로 입력해 주세요.")
        st.stop()

    with st.chat_message("user"):
        st.markdown(question)

    # 기록 미리보기나 기록 분석 결과는 일반 채팅에 넣지 않는다.
    request_messages = [
        {
            "role": "system",
            "content": SYSTEM_PROMPT
        },
        *history[-12:],
        {
            "role": "user",
            "content": question
        }
    ]

    answer = ""
    error_message = None

    with st.chat_message("assistant"):
        answer_area = st.empty()

        try:
            with OpenAI(
                api_key=api_key,
                base_url=BASE_URL,
                timeout=45.0,
                max_retries=0
            ) as ai_client:
                with ai_client.chat.completions.create(
                    model=MODEL,
                    messages=request_messages,
                    stream=True,
                    max_tokens=1600
                ) as stream:

                    def text_chunks():
                        for chunk in stream:
                            if not chunk.choices:
                                continue

                            content = chunk.choices[0].delta.content

                            if content:
                                yield content

                    with answer_area.container():
                        answer = st.write_stream(text_chunks())

        except AuthenticationError:
            error_message = (
                "API 키를 확인하지 못했어요. "
                "Streamlit Secrets의 GEMINI_API_KEY를 확인해 주세요."
            )

        except RateLimitError:
            error_message = (
                "요청 한도에 도달했어요. 잠시 후 다시 시도하고, "
                "계속되면 AI Studio에서 사용 한도를 확인해 주세요."
            )

        except APITimeoutError:
            error_message = (
                "AI 응답 시간이 초과됐어요. "
                "잠시 후 질문을 다시 보내 주세요."
            )

        except APIConnectionError:
            error_message = (
                "Gemini 서버에 연결하지 못했어요. "
                "잠시 후 다시 시도해 주세요."
            )

        except APIStatusError as error:
            if error.status_code == 403:
                error_message = (
                    "현재 API 키나 프로젝트에서 요청이 허용되지 않았어요. "
                    "AI Studio의 접근 권한과 이용 가능 상태를 확인해 주세요."
                )

            elif error.status_code == 404:
                error_message = (
                    "현재 프로젝트에서 모델을 찾을 수 없어요. "
                    "AI Studio에서 gemini-3.5-flash-lite의 "
                    "사용 가능 여부를 확인해 주세요."
                )

            elif error.status_code == 400:
                error_message = (
                    "요청을 처리하지 못했어요. "
                    "질문을 짧게 바꿔 다시 보내 주세요."
                )

            else:
                error_message = (
                    "Gemini에서 정상 응답을 받지 못했어요. "
                    "잠시 후 다시 시도해 주세요."
                )

        except Exception:
            error_message = (
                "답변을 표시하는 중 문제가 생겼어요. "
                "잠시 후 다시 시도해 주세요."
            )

        if error_message:
            answer_area.empty()
            st.warning(error_message)

        elif not isinstance(answer, str) or not answer.strip():
            answer_area.empty()
            st.warning(
                "표시할 답변을 받지 못했어요. "
                "질문을 바꿔 다시 보내 주세요."
            )

        else:
            st.session_state[messages_key] = [
                *history,
                {
                    "role": "user",
                    "content": question
                },
                {
                    "role": "assistant",
                    "content": answer.strip()
                }
            ][-20:]
