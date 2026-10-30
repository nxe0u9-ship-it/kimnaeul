from datetime import datetime
from hashlib import sha256
from zoneinfo import ZoneInfo
import json
import math

import pandas as pd
import streamlit as st

from app_shared import require_login
from meal_ai import show_meal_recommendations
from sidebar_menu import show_sidebar_menu


UNITS = [
    "g", "kg", "mL", "L",
    "개", "장", "봉", "팩", "컵", "공기"
]

RESET_OPTIONS = {
    "냉장고 재료만 초기화": "ingredients",
    "식사 조건만 초기화": "conditions",
    "냉장고 재료·식사 조건 모두 초기화": "all"
}


def fingerprint(value):
    return sha256(
        json.dumps(
            value, sort_keys=True, default=str
        ).encode()
    ).hexdigest()[:16]


def show_error(message, error):
    st.error(message)
    st.caption(
        f"오류 종류: {type(error).__name__} / "
        f"오류 코드: {getattr(error, 'code', None) or '없음'}"
    )


def clean_ingredients(rows):
    result = []
    seen = set()

    for index, row in enumerate(rows, start=1):
        raw_name = row.get("재료명")
        name = (
            ""
            if raw_name is None
            else str(raw_name).strip()
        )

        raw_amount = row.get("보유량")
        amount = (
            None
            if raw_amount is None
            else float(raw_amount)
        )

        raw_unit = row.get("단위")
        unit = (
            ""
            if raw_unit is None
            else str(raw_unit).strip()
        )

        if not name and amount is None:
            continue

        if not name:
            raise ValueError(
                f"{index}행의 재료명을 입력해 주세요."
            )

        if amount is not None and (
            not math.isfinite(amount)
            or amount <= 0
        ):
            raise ValueError(
                f"{index}행의 보유량은 "
                "0보다 큰 숫자로 입력해 주세요."
            )

        if amount is not None and not unit:
            raise ValueError(
                f"{index}행의 단위를 선택해 주세요."
            )

        if name.casefold() in seen:
            raise ValueError(
                f"‘{name}’이 중복되어 있어요. "
                "한 행으로 합쳐 주세요."
            )

        seen.add(name.casefold())

        result.append({
            "name": name,
            "amount": amount,
            "unit": unit if amount is not None else ""
        })

    return result


def build_reset_values(reset_type):
    values = {}

    if reset_type in ["ingredients", "all"]:
        values["ingredients"] = []

    if reset_type in ["conditions", "all"]:
        values.update({
            "allergies": "",
            "excluded_foods": "",
            "dietary_guidance": "",
            "servings": 1,
            "max_cooking_minutes": 30
        })

    if not values:
        raise ValueError("초기화할 항목을 선택해 주세요.")

    values["updated_at"] = datetime.now(
        ZoneInfo("Asia/Seoul")
    ).isoformat()

    return values


st.set_page_config(
    page_title="냉장고 식단 추천 | 당당케어",
    page_icon="🍽️",
    layout="wide"
)

st.markdown("""
<style>
.stApp { background-color: #FFF9F9; }

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


# 현재 페이지 메뉴 바로 아래에 관리 대상 선택 영역 배치
profile_menu = show_sidebar_menu("pages/meal.py")


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

except Exception as error:
    show_error(
        "관리 대상 목록을 불러오지 못했어요.",
        error
    )
    st.stop()


st.title("🍽️ 냉장고 식단 추천")
st.caption(
    "가지고 있는 재료와 식사 조건을 저장하고, "
    "AI에게 아침·점심·저녁 메뉴를 추천받아요."
)

if not profiles:
    st.info(
        "먼저 혈당 기록하기 페이지에서 "
        "관리 대상을 등록해 주세요."
    )
    st.page_link(
        "pages/record.py",
        label="관리 대상 등록하러 가기",
        icon="➕"
    )
    st.stop()


profile_map = {
    item["id"]: item
    for item in profiles
}

if st.session_state.get("active_profile") not in profile_map:
    st.session_state.active_profile = profiles[0]["id"]


# 관리 대상 선택
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
            key=f"meal_profile_{user.id}_{item['id']}",
            type="primary" if active else "secondary",
            use_container_width=True
        ):
            st.session_state.active_profile = item["id"]
            st.rerun()


profile_id = st.session_state.active_profile
profile = profile_map[profile_id]
scope = f"{user.id}_{profile_id}"


# 사람 대상 식단 페이지
if profile["profile_type"] != "사람":
    st.info(
        "냉장고 식단 추천은 현재 사람 대상 기능이에요. "
        "왼쪽에서 사람 관리 대상을 선택해 주세요."
    )
    st.page_link(
        "pages/lifestyle.py",
        label="반려동물의 사료·간식 섭취 기록하기",
        icon="📝"
    )
    st.stop()


st.subheader(f"{profile['name']}의 냉장고와 식사 조건")


# 기존 저장 내용 불러오기
try:
    saved_rows = (
        client.table("meal_settings")
        .select(
            "ingredients,allergies,excluded_foods,"
            "dietary_guidance,servings,"
            "max_cooking_minutes,updated_at"
        )
        .eq("user_id", user.id)
        .eq("profile_id", profile_id)
        .limit(1)
        .execute()
        .data
    ) or []

except Exception as error:
    show_error(
        "저장된 식사 조건을 불러오지 못했어요.",
        error
    )
    st.stop()

settings = saved_rows[0] if saved_rows else {}

notice = st.session_state.pop("meal_notice", None)

if notice and notice[:2] == (user.id, profile_id):
    st.success(notice[2])


# 재료 입력 표 초기값
ingredient_rows = [
    {
        "재료명": item.get("name") or "",
        "보유량": item.get("amount"),
        "단위": item.get("unit") or None
    }
    for item in (settings.get("ingredients") or [])
]

if not ingredient_rows:
    ingredient_rows = [{
        "재료명": "",
        "보유량": None,
        "단위": "g"
    }]

ingredient_df = pd.DataFrame(
    ingredient_rows,
    columns=["재료명", "보유량", "단위"]
)

ingredient_df["재료명"] = (
    ingredient_df["재료명"].astype("string")
)

ingredient_df["보유량"] = pd.to_numeric(
    ingredient_df["보유량"],
    errors="coerce"
).astype(float)

ingredient_df["단위"] = (
    ingredient_df["단위"].astype("string")
)

revision = fingerprint(settings)
form_key = f"meal_settings_form_{scope}_{revision}"


# 재료와 조건 입력
with st.form(form_key):
    st.markdown("### 🧊 냉장고에 있는 재료")

    st.caption(
        "표의 칸을 눌러 입력해요. "
        "맨 아래 빈 행에서 재료를 추가하고, "
        "왼쪽 행 선택란에서 행을 선택해 삭제할 수 있어요."
    )

    edited_ingredients = st.data_editor(
        ingredient_df,
        hide_index=True,
        num_rows="dynamic",
        use_container_width=True,
        column_config={
            "재료명": st.column_config.TextColumn(
                "재료명",
                help="예: 달걀, 두부, 양배추",
                max_chars=80
            ),
            "보유량": st.column_config.NumberColumn(
                "보유량",
                help="양을 모르면 비워 두세요.",
                min_value=0.0,
                step=0.5
            ),
            "단위": st.column_config.SelectboxColumn(
                "단위",
                options=UNITS,
                default="g"
            )
        },
        key=f"meal_editor_{scope}_{revision}"
    )

    st.caption(
        "보유량은 선택 사항이에요. "
        "양을 입력할 때는 단위도 선택해 주세요."
    )

    st.markdown("### ⚙️ 식사 조건")

    allergies = st.text_area(
        "알레르기",
        value=settings.get("allergies") or "",
        placeholder=(
            "예: 우유, 땅콩. "
            "확인된 알레르기가 없다면 ‘없음’이라고 입력해 주세요."
        ),
        max_chars=1000
    )

    st.caption(
        "알레르기 항목은 보관용이며, "
        "이번 AI 메뉴 추천에 전송되거나 자동 반영되지 않아요."
    )

    excluded_foods = st.text_area(
        "제외하고 싶은 음식·재료",
        value=settings.get("excluded_foods") or "",
        placeholder="예: 버섯, 고수 — 음식·재료 이름만 입력",
        max_chars=1000
    )

    dietary_guidance = st.text_area(
        "의료진에게 받은 식사 지침(선택)",
        value=settings.get("dietary_guidance") or "",
        placeholder=(
            "의료진에게 안내받은 내용이 있으면 입력해 주세요. "
            "없으면 비워 두어도 돼요."
        ),
        max_chars=3000
    )

    st.caption(
        "의료진 지침은 보관용이며, "
        "이번 AI 메뉴 추천에 전송되거나 자동 반영되지 않아요."
    )

    c1, c2 = st.columns(2)

    servings = c1.number_input(
        "한 끼 기준 인분 수",
        min_value=1,
        max_value=20,
        value=int(settings.get("servings", 1)),
        step=1
    )

    cooking_minutes = c2.number_input(
        "한 끼 최대 조리 시간(분)",
        min_value=5,
        max_value=240,
        value=int(
            settings.get("max_cooking_minutes", 30)
        ),
        step=5
    )

    save_clicked = st.form_submit_button(
        "💾 재료·식사 조건 저장",
        use_container_width=True
    )


# 입력 검증과 저장
if save_clicked:
    try:
        clean_df = edited_ingredients.astype(object).where(
            pd.notna(edited_ingredients),
            None
        )

        ingredients = clean_ingredients(
            clean_df.to_dict("records")
        )

        payload = {
            "profile_id": profile_id,
            "user_id": user.id,
            "ingredients": ingredients,
            "allergies": allergies.strip(),
            "excluded_foods": excluded_foods.strip(),
            "dietary_guidance": dietary_guidance.strip(),
            "servings": int(servings),
            "max_cooking_minutes": int(cooking_minutes),
            "updated_at": datetime.now(
                ZoneInfo("Asia/Seoul")
            ).isoformat()
        }

        client.table("meal_settings").upsert(
            payload,
            on_conflict="profile_id",
            returning="minimal"
        ).execute()

    except ValueError as error:
        st.warning(str(error))

    except Exception as error:
        show_error(
            "저장 결과를 확인하지 못했어요. "
            "페이지를 다시 열어 저장 내용을 확인해 주세요.",
            error
        )

    else:
        st.session_state.meal_notice = (
            user.id,
            profile_id,
            "재료와 식사 조건을 저장했어요."
        )
        st.rerun()


# 저장 상태 확인
st.divider()
st.markdown("### 📋 현재 저장된 내용")

saved_ingredients = settings.get("ingredients") or []

if not settings:
    st.info(
        "아직 저장한 내용이 없어요. "
        "위에서 입력한 뒤 저장 버튼을 눌러 주세요."
    )

else:
    c1, c2, c3 = st.columns(3)

    c1.metric(
        "저장한 재료",
        f"{len(saved_ingredients)}종류"
    )

    c2.metric(
        "한 끼 인분 수",
        f"{settings['servings']}인분"
    )

    c3.metric(
        "한 끼 최대 조리 시간",
        f"{settings['max_cooking_minutes']}분"
    )

    if saved_ingredients:
        summary = []

        for item in saved_ingredients:
            amount = item.get("amount")

            summary.append({
                "재료명": item["name"],
                "보유량": (
                    f"{float(amount):g} {item.get('unit') or ''}"
                    if amount is not None
                    else "미입력"
                )
            })

        st.dataframe(
            pd.DataFrame(summary),
            hide_index=True,
            use_container_width=True
        )

    else:
        st.caption("저장된 재료가 없어요.")

    with st.expander("저장한 식사 조건 보기"):
        st.markdown("**알레르기**")
        st.write(
            settings.get("allergies") or "미입력"
        )

        st.markdown("**제외할 음식·재료**")
        st.write(
            settings.get("excluded_foods") or "미입력"
        )

        st.markdown("**의료진에게 받은 식사 지침**")
        st.write(
            settings.get("dietary_guidance") or "미입력"
        )

    st.caption(
        "입력란을 수정해도 저장 버튼을 누르기 전에는 "
        "위의 저장 내용이 바뀌지 않아요."
    )


# 냉장고·식사 조건 선택 초기화
with st.expander("🗑️ 냉장고·식사 조건 초기화"):
    st.write(f"초기화할 관리 대상: **{profile['name']}**")

    reset_label = st.radio(
        "초기화할 항목 옆의 선택 칸을 눌러 주세요.",
        list(RESET_OPTIONS),
        index=None,
        key=f"meal_reset_choice_{scope}_{revision}"
    )

    reset_type = RESET_OPTIONS.get(reset_label)

    if reset_type == "ingredients":
        st.warning(
            f"저장된 냉장고 재료 "
            f"{len(saved_ingredients)}종류를 모두 비워요."
        )

        st.caption(
            "알레르기, 제외할 음식, 의료진 지침, "
            "인분 수와 조리 시간은 유지돼요."
        )

    elif reset_type == "conditions":
        st.warning(
            "알레르기, 제외할 음식·재료, "
            "의료진에게 받은 식사 지침을 모두 비워요. "
            "인분 수는 1인분, 최대 조리 시간은 30분으로 돌아가요."
        )

        st.caption("저장된 냉장고 재료는 유지돼요.")

    elif reset_type == "all":
        st.warning(
            "냉장고 재료와 식사 조건을 모두 초기화해요. "
            "알레르기, 제외할 음식·재료, 의료진 지침을 비우고, "
            "인분 수는 1인분, 최대 조리 시간은 30분으로 돌아가요."
        )

    else:
        st.info("위에서 초기화할 항목을 하나 선택해 주세요.")

    st.caption(
        "초기화한 내용은 앱에서 복구할 수 없어요. "
        "선택한 대상의 냉장고·식사 조건에만 적용되며, "
        "혈당 기록과 식사·활동 기록은 유지돼요."
    )

    if not settings:
        st.caption("아직 저장한 재료·식사 조건이 없어요.")

    reset_has_data = (
        bool(saved_ingredients)
        if reset_type == "ingredients"
        else bool(settings)
    )

    if (
        reset_type == "ingredients"
        and settings
        and not saved_ingredients
    ):
        st.caption("초기화할 냉장고 재료가 없어요.")

    reset_form_key = (
        f"meal_reset_form_{scope}_{revision}_{reset_type}"
    )

    with st.form(reset_form_key):
        confirm_reset = st.checkbox(
            "선택한 항목이 초기화되는 것을 확인했어요."
        )

        reset_name = st.text_input(
            "확인을 위해 현재 관리 대상 이름을 그대로 입력해 주세요.",
            help=f"입력할 이름: {profile['name']}"
        )

        reset_clicked = st.form_submit_button(
            "🗑️ 선택한 항목 초기화",
            use_container_width=True,
            disabled=(
                reset_type is None
                or not reset_has_data
            )
        )

    if reset_clicked:
        if reset_type is None:
            st.warning("초기화할 항목을 먼저 선택해 주세요.")

        elif not confirm_reset:
            st.warning("초기화 확인란을 먼저 체크해 주세요.")

        elif reset_name.strip() != profile["name"]:
            st.warning("현재 관리 대상 이름을 정확히 입력해 주세요.")

        else:
            try:
                reset_values = build_reset_values(reset_type)

                result = (
                    client.table("meal_settings")
                    .update(
                        reset_values,
                        returning="representation"
                    )
                    .eq("user_id", user.id)
                    .eq("profile_id", profile_id)
                    .execute()
                )

                if not result.data:
                    raise ValueError(
                        "초기화된 설정이 없어요. "
                        "페이지를 다시 열어 확인해 주세요."
                    )

            except Exception as error:
                show_error(
                    "초기화 결과를 확인하지 못했어요. "
                    "페이지를 다시 열어 저장 내용을 확인해 주세요.",
                    error
                )

            else:
                result_messages = {
                    "ingredients": (
                        f"{profile['name']}의 냉장고 재료를 "
                        "초기화했어요."
                    ),
                    "conditions": (
                        f"{profile['name']}의 식사 조건을 "
                        "초기화했어요."
                    ),
                    "all": (
                        f"{profile['name']}의 냉장고 재료와 "
                        "식사 조건을 모두 초기화했어요."
                    )
                }

                st.session_state.meal_notice = (
                    user.id,
                    profile_id,
                    result_messages[reset_type]
                )
                st.rerun()


# Gemini 식단 추천 화면 연결
show_meal_recommendations(
    user_id=user.id,
    profile_id=profile_id,
    settings=settings
)
