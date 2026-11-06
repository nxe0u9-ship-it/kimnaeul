from datetime import date, datetime
from hashlib import sha256
from uuid import uuid4
import json
import math

import pandas as pd
import streamlit as st

from app_shared import (
    require_login,
    get_timezone_name,
    get_local_now,
)
from meal_ai import show_meal_recommendations
from sidebar_menu import show_sidebar_menu


UNITS = [
    "g", "kg", "mL", "L",
    "개", "장", "봉", "팩", "컵", "공기",
]

RESET_OPTIONS = {
    "선택한 냉장고 재료만 초기화": "ingredients",
    "현재 대상의 식사 조건만 초기화": "conditions",
    "선택한 냉장고·현재 대상의 식사 조건 초기화": "all",
}


def fingerprint(value):
    return sha256(
        json.dumps(
            value,
            sort_keys=True,
            default=str,
        ).encode()
    ).hexdigest()[:16]


def show_error(message, error):
    st.error(message)
    st.caption(
        f"오류 종류: {type(error).__name__} / "
        f"오류 코드: {getattr(error, 'code', None) or '없음'}"
    )


def parse_expiry(value):
    if value is None or value == "" or pd.isna(value):
        return None

    if isinstance(value, datetime):
        return value.date()

    if isinstance(value, date):
        return value

    return date.fromisoformat(
        str(value).strip()
    )


def expiry_info(item, today):
    try:
        expiry = parse_expiry(
            item.get("expiry_date")
        )
    except (ValueError, TypeError):
        return None, "⚠️ 날짜 확인 필요", False

    if expiry is None:
        return None, "기한 미입력", True

    remaining = (expiry - today).days

    if remaining < 0:
        return (
            expiry,
            f"🔴 유통기한이 지났어요 · {-remaining}일 경과",
            False,
        )

    if remaining == 0:
        return expiry, "🟠 오늘까지", True

    return (
        expiry,
        f"기한까지 {remaining}일",
        True,
    )


def expiry_for_editor(item):
    try:
        return parse_expiry(
            item.get("expiry_date")
        )
    except (ValueError, TypeError):
        return None


def clean_ingredients(rows):
    result = []
    seen = set()

    for index, row in enumerate(rows, start=1):
        name = str(
            row.get("재료명") or ""
        ).strip()

        raw_amount = row.get("보유량")

        amount = (
            None
            if raw_amount is None
            else float(raw_amount)
        )

        unit = str(
            row.get("단위") or ""
        ).strip()

        try:
            expiry = parse_expiry(
                row.get("유통·소비기한")
            )
        except (ValueError, TypeError):
            raise ValueError(
                f"{index}행의 유통·소비기한을 확인해 주세요."
            )

        if not name and amount is None and expiry is None:
            continue

        if not name:
            raise ValueError(
                "재료명을 입력해 주세요."
            )

        if amount is not None and (
            not math.isfinite(amount)
            or amount <= 0
        ):
            raise ValueError(
                "보유량은 0보다 큰 숫자로 입력해 주세요."
            )

        if amount is not None and unit not in UNITS:
            raise ValueError(
                "보유량 단위를 선택해 주세요."
            )

        if name.casefold() in seen:
            raise ValueError(
                f"‘{name}’이 중복되어 있어요."
            )

        seen.add(name.casefold())

        result.append({
            "name": name,
            "amount": amount,
            "unit": (
                unit
                if amount is not None
                else ""
            ),
            "expiry_date": (
                expiry.isoformat()
                if expiry
                else None
            ),
        })

    return result


def read_fridge(client, user_id, fridge_id):
    rows = (
        client.table("family_refrigerators")
        .select("id,name,ingredients")
        .eq("user_id", user_id)
        .eq("id", fridge_id)
        .limit(1)
        .execute()
        .data
    ) or []

    return rows[0] if rows else None


def make_ingredient(
    name,
    has_amount,
    amount,
    unit,
    has_expiry,
    expiry_date,
):
    name = name.strip()

    if not name:
        raise ValueError(
            "재료명을 입력해 주세요."
        )

    values = clean_ingredients([{
        "재료명": name,
        "보유량": (
            float(amount)
            if has_amount
            else None
        ),
        "단위": (
            unit
            if has_amount
            else ""
        ),
        "유통·소비기한": (
            expiry_date
            if has_expiry
            else None
        ),
    }])

    return values[0]


def check_ingredient_name(
    items,
    name,
    skip_index=None,
):
    normalized = name.strip().casefold()

    for index, item in enumerate(items):
        existing_name = str(
            item.get("name") or ""
        ).strip().casefold()

        if (
            index != skip_index
            and existing_name == normalized
        ):
            raise ValueError(
                f"‘{name}’이 이미 있어요. "
                "기존 재료를 선택해 수정해 주세요."
            )


def update_fridge_ingredients(
    client,
    user_id,
    fridge_id,
    expected_revision,
    ingredients,
):
    current = read_fridge(
        client,
        user_id,
        fridge_id,
    )

    if (
        current is None
        or fingerprint(current) != expected_revision
    ):
        raise ValueError(
            "냉장고 내용이 바뀌었어요. "
            "위의 새로 불러오기 버튼을 누른 뒤 "
            "다시 수정해 주세요."
        )

    result = (
        client.table("family_refrigerators")
        .update(
            {"ingredients": ingredients},
            returning="representation",
        )
        .eq("user_id", user_id)
        .eq("id", fridge_id)
        .execute()
    )

    if (
        not result.data
        or result.data[0].get("ingredients") != ingredients
    ):
        raise ValueError(
            "저장 결과를 확인하지 못했어요. "
            "위의 새로 불러오기 버튼을 눌러 "
            "저장된 내용을 확인해 주세요."
        )


def show_fridge_picker(client, user_id):
    st.subheader("🧊 사용할 냉장고 선택")

    st.caption(
        "같은 계정에서도 집·기숙사처럼 냉장고를 나눠 "
        "사용할 수 있어요. 재료와 기한은 냉장고별로 저장돼요."
    )

    try:
        fridges = (
            client.table("family_refrigerators")
            .select("id,name,ingredients")
            .eq("user_id", user_id)
            .order("created_at")
            .order("id")
            .execute()
            .data
        ) or []

    except Exception as error:
        show_error(
            "냉장고 목록을 불러오지 못했어요. "
            "여러 냉장고용 SQL 실행 여부를 확인해 주세요.",
            error,
        )
        st.stop()

    with st.expander(
        "➕ 새 냉장고 만들기",
        expanded=not fridges,
    ):
        with st.form(
            f"fridge_create_{user_id}",
            clear_on_submit=True,
        ):
            new_name = st.text_input(
                "새 냉장고 이름",
                max_chars=50,
                placeholder=(
                    "예: 집 냉장고, 기숙사 냉장고"
                ),
            )

            create = st.form_submit_button(
                "냉장고 만들기",
                use_container_width=True,
            )

        if create:
            name = new_name.strip()

            if not name:
                st.warning(
                    "냉장고 이름을 입력해 주세요."
                )

            else:
                fridge_id = str(uuid4())

                try:
                    (
                        client.table("family_refrigerators")
                        .insert(
                            {
                                "id": fridge_id,
                                "user_id": user_id,
                                "name": name,
                                "ingredients": [],
                            },
                            returning="minimal",
                        )
                        .execute()
                    )

                except Exception as error:
                    if str(
                        getattr(error, "code", "")
                    ) == "23505":
                        st.warning(
                            "이미 사용 중인 냉장고 이름이에요. "
                            "다른 이름을 입력해 주세요."
                        )

                    else:
                        show_error(
                            "냉장고 생성 결과를 확인하지 못했어요. "
                            "목록을 새로 불러와 확인해 주세요.",
                            error,
                        )

                else:
                    st.session_state[
                        f"fridge_pending_{user_id}"
                    ] = fridge_id

                    st.session_state[
                        f"meal_notice_{user_id}"
                    ] = f"‘{name}’을 만들었어요."

                    st.rerun()

    if not fridges:
        st.info(
            "냉장고를 하나 이상 만들어 주세요."
        )
        st.stop()

    fridge_map = {
        item["id"]: item
        for item in fridges
    }

    choice_key = f"active_fridge_{user_id}"

    pending = st.session_state.pop(
        f"fridge_pending_{user_id}",
        None,
    )

    if pending in fridge_map:
        st.session_state[choice_key] = pending

    if st.session_state.get(choice_key) not in fridge_map:
        st.session_state[choice_key] = fridges[0]["id"]

    selected_id = st.selectbox(
        "재료를 확인하거나 사용할 냉장고",
        list(fridge_map),
        format_func=lambda value: (
            fridge_map[value]["name"]
        ),
        key=choice_key,
    )

    fridge = fridge_map[selected_id]

    st.info(
        f"현재 냉장고: {fridge['name']} · "
        f"현재 재료 {len(fridge.get('ingredients') or [])}종류"
    )

    with st.expander(
        "✏️ 선택한 냉장고 이름 변경"
    ):
        with st.form(
            f"fridge_rename_{user_id}_{selected_id}_"
            f"{fingerprint(fridge['name'])}"
        ):
            rename = st.text_input(
                "새 냉장고 이름",
                value=fridge["name"],
                max_chars=50,
            )

            saved = st.form_submit_button(
                "이름 변경 저장",
                use_container_width=True,
            )

        if saved:
            name = rename.strip()

            if not name:
                st.warning(
                    "냉장고 이름을 입력해 주세요."
                )

            elif name == fridge["name"]:
                st.info(
                    "현재와 동일한 이름이에요."
                )

            else:
                try:
                    result = (
                        client.table("family_refrigerators")
                        .update(
                            {"name": name},
                            returning="representation",
                        )
                        .eq("user_id", user_id)
                        .eq("id", selected_id)
                        .execute()
                    )

                    if not result.data:
                        raise ValueError(
                            "변경된 냉장고가 없어요."
                        )

                except Exception as error:
                    if str(
                        getattr(error, "code", "")
                    ) == "23505":
                        st.warning(
                            "이미 사용 중인 냉장고 이름이에요."
                        )

                    else:
                        show_error(
                            "냉장고 이름 변경 결과를 "
                            "확인하지 못했어요.",
                            error,
                        )

                else:
                    st.session_state[
                        f"meal_notice_{user_id}"
                    ] = "냉장고 이름을 변경했어요."

                    st.rerun()

    return fridge


def save_conditions(
    client,
    user_id,
    profile_id,
    values,
    has_settings,
):
    payload = {
        "user_id": user_id,
        "profile_id": profile_id,
        **values,
        "updated_at": get_local_now().isoformat(),
    }

    if not has_settings:
        payload["ingredients"] = []

    (
        client.table("meal_settings")
        .upsert(
            payload,
            on_conflict="profile_id",
            returning="minimal",
        )
        .execute()
    )


st.set_page_config(
    page_title="냉장고 식단 추천 | 당당케어",
    page_icon="🍽️",
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

div[data-testid="stForm"] {
    padding: 22px;
    border-radius: 18px;
    background: white;
    border: 1px solid #EEEEEE;
}
</style>
""",
    unsafe_allow_html=True,
)

profile_menu = show_sidebar_menu(
    "pages/meal.py"
)

client, user = require_login()
timezone_name = get_timezone_name()

try:
    profiles = (
        client.table("care_profiles")
        .select(
            "id,name,profile_type,animal_type"
        )
        .eq("user_id", user.id)
        .order("created_at")
        .execute()
        .data
    ) or []

except Exception as error:
    show_error(
        "관리 대상 목록을 불러오지 못했어요.",
        error,
    )
    st.stop()

st.title("🍽️ 냉장고 식단 추천")

st.caption(
    "냉장고는 이름을 정해 여러 개 만들고 선택할 수 있으며, "
    "식사 조건은 관리 대상별로 저장해요."
)

today = get_local_now().date()

st.caption(
    f"기한 판단 기준: {timezone_name} 날짜 {today:%Y-%m-%d}. "
    "화면을 다시 불러올 때 갱신돼요."
)

if st.button("🔄 날짜·저장 내용 새로 불러오기"):
    st.rerun()

if not profiles:
    st.info(
        "먼저 혈당 기록하기 페이지에서 관리 대상을 등록해 주세요."
    )

    st.page_link(
        "pages/record.py",
        label="관리 대상 등록하러 가기",
        icon="➕",
    )

    st.stop()

profile_map = {
    item["id"]: item
    for item in profiles
}

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
            key=f"meal_profile_{user.id}_{item['id']}",
            type=(
                "primary"
                if active
                else "secondary"
            ),
            use_container_width=True,
        ):
            st.session_state.active_profile = item["id"]
            st.rerun()

profile_id = st.session_state.active_profile
profile = profile_map[profile_id]

scope = f"{user.id}_{profile_id}"
is_person = profile["profile_type"] == "사람"

try:
    fridge = show_fridge_picker(
        client,
        user.id,
    )

    saved_rows = (
        client.table("meal_settings")
        .select(
            "allergies,excluded_foods,dietary_guidance,"
            "servings,max_cooking_minutes,updated_at"
        )
        .eq("user_id", user.id)
        .eq("profile_id", profile_id)
        .limit(1)
        .execute()
        .data
    ) or []

except Exception as error:
    show_error(
        "냉장고 또는 식사 조건을 불러오지 못했어요. "
        "여러 냉장고용 SQL 실행 여부도 확인해 주세요.",
        error,
    )
    st.stop()

settings = (
    saved_rows[0]
    if saved_rows
    else {}
)

notice = st.session_state.pop(
    f"meal_notice_{user.id}",
    None,
)

if notice:
    st.success(notice)

fridge_id = fridge["id"]
fridge_name = fridge["name"]
saved_ingredients = fridge.get("ingredients") or []
fridge_revision = fingerprint(fridge)

revision = fingerprint({
    "settings": settings,
    "fridge": fridge,
})

st.subheader(
    f"🧊 {fridge_name}의 재료"
)

st.caption(
    "재료 저장·삭제·초기화는 위에서 선택한 냉장고에만 적용돼요. "
    "식사 조건의 관리 대상은 왼쪽 사이드바에서 선택해 주세요."
)

st.caption(
    "재료를 추가하려면 ‘새 재료 추가’를, 저장된 재료를 "
    "바꾸거나 삭제하려면 ‘저장된 재료 수정·삭제’를 사용해 주세요. "
    "아래 ‘현재 저장된 내용’ 표는 조회용이에요."
)

with st.expander(
    "➕ 새 재료 추가",
    expanded=not saved_ingredients,
):
    with st.form(
        f"ingredient_add_{user.id}_{fridge_revision}"
    ):
        add_name = st.text_input(
            "추가할 재료명",
            max_chars=80,
            placeholder="예: 달걀, 두부, 양배추",
        )

        add_has_amount = st.checkbox(
            "보유량을 입력할게요."
        )

        add_c1, add_c2 = st.columns(2)

        add_amount = add_c1.number_input(
            "추가할 보유량",
            min_value=0.0,
            value=0.0,
            step=0.5,
        )

        add_unit = add_c2.selectbox(
            "보유량 단위",
            UNITS,
        )

        add_has_expiry = st.checkbox(
            "유통·소비기한을 입력할게요."
        )

        add_expiry = st.date_input(
            "추가할 재료의 유통·소비기한",
            value=today,
        )

        st.caption(
            "보유량이나 유통·소비기한을 모르면 해당 확인란을 "
            "체크하지 마세요. 확인란이 체크된 항목만 저장돼요."
        )

        add_clicked = st.form_submit_button(
            "➕ 선택한 냉장고에 재료 추가",
            use_container_width=True,
        )

    if add_clicked:
        try:
            new_item = make_ingredient(
                add_name,
                add_has_amount,
                add_amount,
                add_unit,
                add_has_expiry,
                add_expiry,
            )

            check_ingredient_name(
                saved_ingredients,
                new_item["name"],
            )

            update_fridge_ingredients(
                client,
                user.id,
                fridge_id,
                fridge_revision,
                saved_ingredients + [new_item],
            )

        except ValueError as error:
            st.warning(str(error))

        except Exception as error:
            show_error(
                "재료 추가 결과를 확인하지 못했어요. "
                "위의 새로 불러오기 버튼으로 저장 내용을 확인해 주세요.",
                error,
            )

        else:
            st.session_state[
                f"meal_notice_{user.id}"
            ] = (
                f"‘{fridge_name}’에 "
                f"‘{new_item['name']}’을 추가했어요."
            )

            st.rerun()

st.markdown(
    "### ✏️ 저장된 재료 수정·삭제"
)

if not saved_ingredients:
    st.info(
        "저장된 재료가 없어요. "
        "위의 ‘새 재료 추가’에서 먼저 재료를 등록해 주세요."
    )

else:
    edit_index = st.selectbox(
        "수정하거나 삭제할 재료를 선택해 주세요.",
        options=list(
            range(len(saved_ingredients))
        ),
        format_func=lambda index: (
            saved_ingredients[index].get("name")
            or f"재료 {index + 1}"
        ),
        key=(
            f"ingredient_edit_choice_"
            f"{user.id}_{fridge_revision}"
        ),
    )

    editing = saved_ingredients[edit_index]
    original_amount = editing.get("amount")
    original_unit = editing.get("unit") or "g"

    edit_units = (
        UNITS
        if original_unit in UNITS
        else UNITS + [original_unit]
    )

    original_expiry = expiry_for_editor(editing)

    _, edit_expiry_status, _ = expiry_info(
        editing,
        today,
    )

    if (
        original_expiry is not None
        and original_expiry < today
    ):
        st.error(
            "유통기한이 지났어요. "
            f"입력한 기한: {original_expiry:%Y-%m-%d}"
        )

    st.caption(
        f"현재 선택한 재료: "
        f"{editing.get('name') or '이름 없음'} · "
        f"{edit_expiry_status}"
    )

    with st.form(
        f"ingredient_edit_{user.id}_"
        f"{fridge_revision}_{edit_index}"
    ):
        edit_name = st.text_input(
            "변경할 재료명",
            value=editing.get("name") or "",
            max_chars=80,
        )

        edit_has_amount = st.checkbox(
            "보유량을 저장할게요.",
            value=original_amount is not None,
        )

        edit_c1, edit_c2 = st.columns(2)

        edit_amount = edit_c1.number_input(
            "변경할 보유량",
            min_value=0.0,
            value=max(
                0.0,
                float(original_amount or 0),
            ),
            step=0.5,
        )

        edit_unit = edit_c2.selectbox(
            "변경할 단위",
            edit_units,
            index=edit_units.index(original_unit),
        )

        # 기한이 없던 재료는 날짜 입력란을 비워 표시합니다.
        # 날짜를 입력하면 별도 체크 없이 저장에 반영합니다.
        edit_expiry = st.date_input(
            "변경할 유통·소비기한",
            value=original_expiry,
            help=(
                "기한을 새로 입력하거나 변경하면 저장 내용에 반영돼요. "
                "기한을 저장하지 않으려면 날짜 입력란을 비워 주세요."
            ),
        )

        edit_has_expiry = edit_expiry is not None

        st.caption(
            "보유량 확인란을 해제하면 기존 보유량·단위를 지워요. "
            "유통·소비기한은 날짜를 입력하면 저장하고, "
            "날짜 입력란을 비우면 기존 기한을 지워요. "
            "변경한 내용은 아래 ‘재료 수정 저장’을 눌러야 반영돼요."
        )

        edit_clicked = st.form_submit_button(
            "💾 재료 수정 저장",
            use_container_width=True,
        )

        st.markdown(
            "**🗑️ 선택한 재료 삭제**"
        )

        confirm_ingredient_delete = st.checkbox(
            "위에서 선택한 재료를 삭제할게요. "
            "삭제한 재료는 앱에서 복구할 수 없어요."
        )

        delete_ingredient_clicked = st.form_submit_button(
            "🗑️ 선택한 재료 삭제",
            use_container_width=True,
        )

    if edit_clicked:
        try:
            updated_item = make_ingredient(
                edit_name,
                edit_has_amount,
                edit_amount,
                edit_unit,
                edit_has_expiry,
                edit_expiry,
            )

            check_ingredient_name(
                saved_ingredients,
                updated_item["name"],
                skip_index=edit_index,
            )

            updated_ingredients = [
                updated_item
                if index == edit_index
                else item
                for index, item in enumerate(
                    saved_ingredients
                )
            ]

            if updated_ingredients == saved_ingredients:
                st.info(
                    "변경된 내용이 없어요."
                )

            else:
                update_fridge_ingredients(
                    client,
                    user.id,
                    fridge_id,
                    fridge_revision,
                    updated_ingredients,
                )

                st.session_state[
                    f"meal_notice_{user.id}"
                ] = (
                    f"‘{fridge_name}’의 "
                    f"‘{updated_item['name']}’ 재료 정보를 수정했어요."
                )

                st.rerun()

        except ValueError as error:
            st.warning(str(error))

        except Exception as error:
            show_error(
                "재료 수정 결과를 확인하지 못했어요. "
                "위의 새로 불러오기 버튼으로 저장 내용을 확인해 주세요.",
                error,
            )

    if delete_ingredient_clicked:
        if not confirm_ingredient_delete:
            st.warning(
                "선택한 재료의 삭제 확인란을 먼저 체크해 주세요."
            )

        else:
            try:
                remaining_items = [
                    item
                    for index, item in enumerate(
                        saved_ingredients
                    )
                    if index != edit_index
                ]

                update_fridge_ingredients(
                    client,
                    user.id,
                    fridge_id,
                    fridge_revision,
                    remaining_items,
                )

            except ValueError as error:
                st.warning(str(error))

            except Exception as error:
                show_error(
                    "재료 삭제 결과를 확인하지 못했어요. "
                    "위의 새로 불러오기 버튼으로 저장 내용을 확인해 주세요.",
                    error,
                )

            else:
                st.session_state[
                    f"meal_notice_{user.id}"
                ] = (
                    f"‘{fridge_name}’에서 "
                    f"‘{editing.get('name')}’ 재료를 삭제했어요."
                )

                st.rerun()

st.subheader(
    f"⚙️ {profile['name']}의 식사 조건"
)

st.caption(
    "아래 조건은 현재 선택한 관리 대상에게만 저장돼요. "
    "다른 대상의 식사 조건을 입력하려면 왼쪽 사이드바의 "
    "‘관리 대상’ 목록에서 해당 이름을 선택해 주세요."
)

if not is_person:
    st.info(
        "반려동물도 선택한 냉장고와 개별 식사 조건을 "
        "저장할 수 있어요. 강아지를 선택하면 아래에서 "
        "토핑·간식 후보를 추천받을 수 있어요."
    )

    st.page_link(
        "pages/lifestyle.py",
        label="반려동물의 사료·간식 섭취 기록하기",
        icon="📝",
    )

with st.form(
    f"meal_conditions_{scope}_"
    f"{fingerprint(settings)}"
):
    allergies = st.text_area(
        "알레르기",
        value=settings.get("allergies") or "",
        placeholder=(
            "확인된 알레르기를 입력해 주세요. "
            "없다면 ‘없음’이라고 입력해 주세요."
        ),
        max_chars=1000,
    )

    st.caption(
        "알레르기는 현재 보관용이며 AI 메뉴 추천에 "
        "전송되거나 자동 반영되지 않아요."
    )

    excluded_foods = st.text_area(
        "제외하고 싶은 음식·재료",
        value=settings.get("excluded_foods") or "",
        placeholder=(
            "제외할 음식·재료 이름을 입력해 주세요."
        ),
        max_chars=1000,
    )

    guidance_label = (
        "의료진에게 받은 식사 지침(선택)"
        if is_person
        else "수의사에게 받은 급여 지침(선택)"
    )

    dietary_guidance = st.text_area(
        guidance_label,
        value=settings.get("dietary_guidance") or "",
        placeholder=(
            "안내받은 내용이 있으면 입력해 주세요."
        ),
        max_chars=3000,
    )

    st.caption(
        "이 지침은 현재 보관용이며 AI 메뉴 추천에 "
        "전송되거나 자동 반영되지 않아요."
    )

    c1, c2 = st.columns(2)

    servings = c1.number_input(
        (
            "한 끼 기준 인분 수"
            if is_person
            else "한 번 준비할 급여 분량 수"
        ),
        min_value=1,
        max_value=20,
        value=int(
            settings.get("servings") or 1
        ),
        step=1,
    )

    if not is_person:
        st.caption(
            "분량 수는 준비 횟수를 뜻하며, "
            "적정 급여량이나 영양 균형을 계산하는 값은 아니에요."
        )

    cooking_minutes = c2.number_input(
        "한 끼 최대 조리 시간(분)",
        min_value=5,
        max_value=240,
        value=int(
            settings.get("max_cooking_minutes") or 30
        ),
        step=5,
    )

    save_conditions_clicked = st.form_submit_button(
        "💾 현재 대상의 식사 조건 저장",
        use_container_width=True,
    )

    conditions_notice = st.session_state.pop(
        f"meal_conditions_notice_{scope}",
        None,
    )

    if conditions_notice:
        st.success(conditions_notice)

if save_conditions_clicked:
    try:
        save_conditions(
            client,
            user.id,
            profile_id,
            {
                "allergies": allergies.strip(),
                "excluded_foods": excluded_foods.strip(),
                "dietary_guidance": dietary_guidance.strip(),
                "servings": int(servings),
                "max_cooking_minutes": int(cooking_minutes),
            },
            bool(settings),
        )

    except Exception as error:
        show_error(
            "식사 조건 저장 결과를 확인하지 못했어요. "
            "페이지를 다시 열어 확인해 주세요.",
            error,
        )

    else:
        st.session_state[
            f"meal_conditions_notice_{scope}"
        ] = (
            f"{profile['name']}의 식사 조건을 저장했어요."
        )

        st.rerun()

st.divider()
st.markdown("### 📋 현재 저장된 내용")

c1, c2, c3 = st.columns(3)

c1.metric(
    "선택한 냉장고 재료",
    f"{len(saved_ingredients)}종류",
)

c2.metric(
    (
        "한 끼 인분 수"
        if is_person
        else "준비할 급여 분량 수"
    ),
    settings.get("servings") or 1,
)

c3.metric(
    "최대 조리 시간",
    f"{settings.get('max_cooking_minutes') or 30}분",
)

if saved_ingredients:
    summary = []
    expired_flags = []

    for item in saved_ingredients:
        expiry, status, eligible = expiry_info(
            item,
            today,
        )

        amount = item.get("amount")

        summary.append({
            "재료명": item["name"],
            "보유량": (
                f"{float(amount):g} {item.get('unit') or ''}"
                if amount is not None
                else "미입력"
            ),
            "유통·소비기한": (
                expiry.isoformat()
                if expiry
                else "미입력 또는 확인 필요"
            ),
            "상태": status,
        })

        expired_flags.append(
            expiry is not None
            and expiry < today
        )

    summary_df = pd.DataFrame(summary)

    styled_summary = summary_df.style.apply(
        lambda row: [
            (
                "color: #C62828; "
                "background-color: #FFF0F0; "
                "font-weight: bold"
            )
            if expired_flags[row.name]
            else ""
        ] * len(row),
        axis=1,
    )

    if any(expired_flags):
        st.error(
            "유통기한이 지났어요. 아래 빨간색으로 표시된 "
            "재료를 확인하고, ‘유통기한 지난 재료 선택 삭제’에서 "
            "삭제할 재료를 골라 주세요."
        )

    st.dataframe(
        styled_summary,
        hide_index=True,
        use_container_width=True,
        column_config={
            "상태": st.column_config.TextColumn(
                "상태",
                width="large",
            ),
        },
    )

    st.caption(
        "이 표는 현재 저장된 내용을 보여주는 조회용 표예요. "
        "재료 수정·삭제는 위의 ‘저장된 재료 수정·삭제’에서 해 주세요."
    )

    st.caption(
        "입력한 유통·소비기한이 오늘보다 이전이면 "
        "지난 재료로 표시해요. 기한이 지난 재료도 "
        "자동 삭제하지 않으며 아래에서 선택해 삭제할 수 있어요."
    )

else:
    st.caption(
        "선택한 냉장고에 저장된 재료가 없어요."
    )

expired_indices = [
    index
    for index, item in enumerate(saved_ingredients)
    if expiry_info(item, today)[0] is not None
    and expiry_info(item, today)[0] < today
]

with st.expander(
    "🗑️ 유통기한 지난 재료 선택 삭제 · "
    f"{len(expired_indices)}종류",
    expanded=bool(expired_indices),
):
    if not expired_indices:
        st.info(
            "입력된 날짜 기준으로 기한이 지난 재료가 없어요."
        )

    else:
        st.warning(
            f"삭제하면 ‘{fridge_name}’에서만 재료가 사라져요. "
            "다른 냉장고의 재료는 유지돼요."
        )

        st.caption(
            "아래 ‘삭제할 재료 선택’ 칸을 눌러 "
            "지울 재료를 골라 주세요. 여러 개를 선택할 수 있어요."
        )

        with st.form(
            f"expired_delete_{user.id}_{fridge_revision}_"
            f"{today}_{timezone_name}"
        ):
            selected_expired = st.multiselect(
                "삭제할 재료 선택",
                options=expired_indices,
                format_func=lambda index: (
                    f"{saved_ingredients[index]['name']} · "
                    "기한 "
                    f"{saved_ingredients[index].get('expiry_date')}"
                ),
            )

            delete_expired_clicked = st.form_submit_button(
                "🗑️ 선택한 기한 지난 재료 삭제",
                use_container_width=True,
            )

        if delete_expired_clicked:
            if not selected_expired:
                st.warning(
                    "삭제할 재료를 먼저 선택해 주세요."
                )

            else:
                try:
                    delete_day = get_local_now().date()
                    selected_set = set(selected_expired)

                    for index in selected_set:
                        expiry = parse_expiry(
                            saved_ingredients[index].get(
                                "expiry_date"
                            )
                        )

                        if (
                            expiry is None
                            or expiry >= delete_day
                        ):
                            raise ValueError(
                                "선택한 재료의 기한을 "
                                "다시 확인해 주세요."
                            )

                    remaining = [
                        item
                        for index, item in enumerate(
                            saved_ingredients
                        )
                        if index not in selected_set
                    ]

                    update_fridge_ingredients(
                        client,
                        user.id,
                        fridge_id,
                        fridge_revision,
                        remaining,
                    )

                except ValueError as error:
                    st.warning(str(error))
                    st.stop()

                except Exception as error:
                    show_error(
                        "삭제 결과를 확인하지 못했어요. "
                        "목록을 다시 불러와 확인해 주세요.",
                        error,
                    )
                    st.stop()

                else:
                    st.session_state[
                        f"meal_notice_{user.id}"
                    ] = (
                        "선택한 기한 지난 재료 "
                        f"{len(selected_set)}종류를 삭제했어요."
                    )

                    st.rerun()

if not settings:
    st.info(
        f"{profile['name']}의 식사 조건은 "
        "아직 저장하지 않았어요."
    )

with st.expander(
    f"{profile['name']}의 저장한 식사 조건 보기"
):
    condition_fields = [
        ("알레르기", "allergies"),
        ("제외할 음식·재료", "excluded_foods"),
        (guidance_label, "dietary_guidance"),
    ]

    for label, field in condition_fields:
        st.markdown(f"**{label}**")
        st.write(
            settings.get(field) or "미입력"
        )

st.caption(
    "입력란을 수정해도 해당 저장 버튼을 누르기 전에는 "
    "저장 내용이 바뀌지 않아요."
)

with st.expander(
    "🗑️ 선택한 냉장고·식사 조건 초기화"
):
    st.write(
        f"냉장고: **{fridge_name}** / "
        f"식사 조건: **{profile['name']}만**"
    )

    reset_label = st.radio(
        "초기화할 항목 옆의 선택 칸을 눌러 주세요.",
        list(RESET_OPTIONS),
        index=None,
        key=(
            f"meal_reset_choice_"
            f"{scope}_{revision}"
        ),
    )

    reset_type = RESET_OPTIONS.get(
        reset_label
    )

    if reset_type in ["ingredients", "all"]:
        st.warning(
            f"선택한 냉장고 재료 {len(saved_ingredients)}종류를 "
            f"‘{fridge_name}’에서 모두 비워요. "
            "다른 냉장고의 재료는 유지돼요."
        )

    if reset_type in ["conditions", "all"]:
        st.warning(
            f"{profile['name']}의 알레르기·제외 음식·식사 지침을 "
            "비우고, 분량 수는 1, 조리 시간은 30분으로 되돌려요."
        )

    if reset_type is None:
        st.info(
            "초기화할 항목을 먼저 선택해 주세요."
        )

    st.caption(
        "다른 대상의 식사 조건과 혈당·식사·활동 기록은 유지돼요. "
        "초기화한 현재 자료는 앱에서 복구할 수 없어요. "
        "다른 냉장고의 재료도 유지돼요."
    )

    reset_has_data = (
        (
            reset_type in ["ingredients", "all"]
            and bool(saved_ingredients)
        )
        or (
            reset_type in ["conditions", "all"]
            and bool(settings)
        )
    )

    with st.form(
        f"meal_reset_form_{scope}_"
        f"{revision}_{reset_type}"
    ):
        confirm_reset = st.checkbox(
            f"선택한 냉장고 ‘{fridge_name}’과 현재 관리 대상에 대해 "
            "선택한 항목이 초기화되는 것을 확인했어요."
        )

        reset_name = st.text_input(
            "확인을 위해 현재 관리 대상 이름을 그대로 입력해 주세요.",
            help=f"입력할 이름: {profile['name']}",
        )

        reset_clicked = st.form_submit_button(
            "🗑️ 선택한 항목 초기화",
            use_container_width=True,
            disabled=(
                reset_type is None
                or not reset_has_data
            ),
        )

    if reset_clicked:
        if not confirm_reset:
            st.warning(
                "초기화 확인란을 먼저 체크해 주세요."
            )

        elif reset_name.strip() != profile["name"]:
            st.warning(
                "현재 관리 대상 이름을 정확히 입력해 주세요."
            )

        else:
            completed = []

            try:
                if reset_type in ["ingredients", "all"]:
                    update_fridge_ingredients(
                        client,
                        user.id,
                        fridge_id,
                        fridge_revision,
                        [],
                    )

                    completed.append(
                        f"‘{fridge_name}’의 재료"
                    )

                if (
                    reset_type in ["conditions", "all"]
                    and settings
                ):
                    save_conditions(
                        client,
                        user.id,
                        profile_id,
                        {
                            "allergies": "",
                            "excluded_foods": "",
                            "dietary_guidance": "",
                            "servings": 1,
                            "max_cooking_minutes": 30,
                        },
                        True,
                    )

                    completed.append(
                        f"{profile['name']}의 식사 조건"
                    )

            except Exception as error:
                if completed:
                    st.warning(
                        "이미 초기화된 항목: "
                        + ", ".join(completed)
                    )

                show_error(
                    "일부 요청의 처리 결과를 확인하지 못했어요. "
                    "페이지를 다시 열어 각 저장 내용을 확인해 주세요.",
                    error,
                )

                st.stop()

            else:
                st.session_state[
                    f"meal_notice_{user.id}"
                ] = (
                    ", ".join(completed)
                    + "을 초기화했어요."
                )

                st.rerun()

st.info(
    f"AI 추천에 사용할 냉장고: {fridge_name} / "
    f"관리 대상: {profile['name']}"
)

ai_today = get_local_now().date()
ai_ingredients = []
excluded_by_date = []

for item in saved_ingredients:
    expiry, status, eligible = expiry_info(
        item,
        ai_today,
    )

    if eligible:
        ai_ingredients.append(item)

    else:
        excluded_by_date.append(
            item["name"]
        )

if excluded_by_date:
    st.warning(
        "기한이 지났거나 날짜 확인이 필요해 "
        "AI 추천에서 제외한 재료: "
        + ", ".join(excluded_by_date)
    )

st.caption(
    "기한 미입력 재료도 추천에 포함될 수 있어요. "
    "입력한 날짜와 별개로 보관 상태는 직접 확인해 주세요."
)

recommendation_settings = {
    **settings,
    "ingredients": ai_ingredients,
}

show_meal_recommendations(
    user_id=user.id,
    profile_id=profile_id,
    settings=recommendation_settings,
    profile=profile,
)
