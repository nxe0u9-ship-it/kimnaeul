import streamlit as st

from openai import (
    OpenAI,
    APIConnectionError,
    APIStatusError,
    APITimeoutError,
    AuthenticationError,
    RateLimitError,
)

from app_shared import require_login
from sidebar_menu import show_sidebar_menu


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
- 사용자의 저장된 혈당·식사·활동·진료 기록을 전달받지 않는다.
- 저장 기록을 확인하거나 분석했다고 말하지 않는다.
- 기록을 불러오거나 전송하는 기능이 있다고 안내하지 않는다.
- 개인 기록이나 상세 증상·검사 결과를 추가로 보내도록 요구하지 않는다.
- 사람과 반려동물의 기준을 혼동하지 않는다.
- 설명에 대상 구분이 필요하면 사람인지 반려동물인지 먼저 질문한다.
- 이름, 연락처, 계정 정보 등은 요구하지 않는다.

답변 범위:
- 일반적인 용어와 기록 방법을 설명한다.
- 개인의 상태를 진단하거나 치료 방침을 결정하지 않는다.
- 개인 혈당 수치·검사 결과의 정상 여부나 위험도를 판단하지 않는다.
- 개인 증상 상담이나 개인별 처방을 요청하면
  의료진 또는 수의사에게 확인하도록 안내한다.
- 약물이나 인슐린의 투여량·투여 시각 변경을 지시하지 않는다.
- 치료를 목적으로 한 개인별 식단이나 운동 처방을 제공하지 않는다.
- 민감한 정보가 입력되면 답변에서 불필요하게 반복하지 않고,
  추가적인 개인정보나 건강기록을 보내지 않도록 안내한다.
- 긴급한 증상이 언급되면 채팅 답변을 기다리기보다
  즉시 전문적인 도움을 받도록 안내한다.

답변은 질문에 필요한 내용을 중심으로 간결하게 작성한다.
"""


st.set_page_config(
    page_title="AI에게 물어보기 | 당당케어",
    page_icon="💬",
    layout="wide",
)

st.markdown(
    """
<style>
.stApp {
    background-color: #FFF9F9;
}

div.stButton > button {
    border-radius: 14px;
}
</style>
""",
    unsafe_allow_html=True,
)


# 사이드바와 로그인
profile_menu = show_sidebar_menu("pages/chat.py")
client, user = require_login()


# 관리 대상 목록은 사이드바 표시와 대화 구분에만 사용
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
    if (
        st.session_state.get("active_profile")
        not in profile_map
    ):
        st.session_state.active_profile = (
            profiles[0]["id"]
        )

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

            label = (
                f"{icon} {item['name']} · {kind}"
            )

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
                key=(
                    f"chat_profile_{user.id}_"
                    f"{item['id']}"
                ),
                type=(
                    "primary"
                    if active
                    else "secondary"
                ),
                use_container_width=True,
            ):
                st.session_state.active_profile = (
                    item["id"]
                )
                st.rerun()

else:
    profile_menu.caption(
        "등록된 관리 대상이 없어요."
    )


# 페이지 안내
st.title("💬 AI에게 물어보기")

st.caption(
    "혈당 기록 용어와 기록 방법, "
    "식사·활동에 관한 일반 정보를 물어보세요."
)

if profiles:
    profile_id = st.session_state.active_profile
    profile = profile_map[profile_id]

    kind = (
        profile.get("animal_type")
        or profile["profile_type"]
    )

    st.info(
        f"현재 선택한 관리 대상: "
        f"{profile['name']} · {kind}"
    )

else:
    profile_id = "general"


st.divider()
st.subheader("💬 일반 정보 질문하기")

st.warning(
    "**개인정보나 건강기록을 입력하지 마세요.**\n\n"
    "이름·연락처·이메일, 본인이나 가족·반려동물의 실제 혈당 수치, "
    "검사 결과, 처방 내용, 상세 증상 등 민감한 정보는 보내지 마세요.\n\n"
    "**의학적 판단이 필요한 질문은 의료진 또는 수의사에게 확인해 주세요.**\n\n"
    "개인 수치 해석, 증상 진단, 치료 방법, "
    "약물·인슐린 용량 변경 등에 관한 상담은 이 채팅에서 받지 마세요."
)

st.caption(
    "직접 입력한 질문과 최근 대화는 답변 생성을 위해 "
    "Google Gemini로 전송돼요."
)

st.caption(
    "AI 답변에는 오류가 있을 수 있어요. "
    "일반적인 정보 학습에 활용하고, "
    "진단·치료 결정의 근거로 사용하지 마세요."
)


# 대화는 접속 세션의 관리 대상별 목록에 보관
scope = f"{user.id}_{profile_id}"
messages_key = f"care_general_chat_v2_{scope}"

if messages_key not in st.session_state:
    st.session_state[messages_key] = []

if st.button(
    "🗑️ 현재 대화 지우기",
    key=f"clear_general_chat_v2_{scope}",
):
    st.session_state[messages_key] = []
    st.rerun()

st.caption(
    "새로고침하거나 앱을 나갔다가 다시 접속하면 "
    "대화가 초기화될 수 있어요."
)

st.caption(
    "AI 사용량 제한이나 일시적인 서버 문제로 "
    "답변을 받지 못할 수 있어요. "
    "이 경우 잠시 후 다시 시도해 주세요."
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


# 대화 표시
history = st.session_state[messages_key]

if not history:
    st.info(
        "이런 질문을 할 수 있어요.\n\n"
        "• 공복 혈당이라는 말은 무슨 뜻인가요?\n"
        "• 식사 기록에는 어떤 항목을 적으면 좋나요?\n"
        "• 탄수화물과 식이섬유는 어떻게 다른가요?"
    )

for message in history:
    with st.chat_message(message["role"]):
        st.markdown(message["content"])


# 질문 입력
user_input = st.chat_input(
    "개인정보·건강기록 없이 일반적인 궁금증을 물어보세요.",
    key=f"care_general_chat_input_v2_{scope}",
)

if user_input:
    question = user_input.strip()

    if not question:
        st.warning(
            "질문을 입력해 주세요."
        )
        st.stop()

    if len(question) > 3000:
        st.warning(
            "질문은 3,000자 이내로 입력해 주세요."
        )
        st.stop()

    with st.chat_message("user"):
        st.markdown(question)

    # 직접 입력한 질문과 최근 대화만 전송
    request_messages = [
        {
            "role": "system",
            "content": SYSTEM_PROMPT,
        },
        *history[-12:],
        {
            "role": "user",
            "content": question,
        },
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
                max_retries=0,
            ) as ai_client:
                with ai_client.chat.completions.create(
                    model=MODEL,
                    messages=request_messages,
                    stream=True,
                    max_tokens=1600,
                ) as stream:

                    def text_chunks():
                        for chunk in stream:
                            if not chunk.choices:
                                continue

                            content = (
                                chunk.choices[0]
                                .delta.content
                            )

                            if content:
                                yield content

                    with answer_area.container():
                        answer = st.write_stream(
                            text_chunks()
                        )

        except AuthenticationError:
            error_message = (
                "API 키를 확인하지 못했어요. "
                "Streamlit Secrets의 GEMINI_API_KEY를 확인해 주세요."
            )

        except RateLimitError:
            error_message = (
                "요청 한도에 도달했어요. "
                "잠시 후 다시 시도하고, 계속되면 "
                "AI Studio에서 사용 한도를 확인해 주세요."
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
                    f"AI Studio에서 {MODEL}의 "
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

        elif (
            not isinstance(answer, str)
            or not answer.strip()
        ):
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
                    "content": question,
                },
                {
                    "role": "assistant",
                    "content": answer.strip(),
                },
            ][-20:]
