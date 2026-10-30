from datetime import datetime
from uuid import uuid4
from zoneinfo import ZoneInfo

import streamlit as st

from app_shared import require_login
from record_links import show_record_links
from sidebar_menu import show_sidebar_menu


MEALS = [
    "선택해 주세요", "공복", "식전",
    "식후 1시간", "식후 2시간", "취침 전", "기타"
]


def show_error(message, error):
    st.error(message)
    st.caption(
        f"오류 종류: {type(error).__name__} / "
        f"오류 코드: {getattr(error, 'code', None) or '없음'}"
    )


st.set_page_config(
    page_title="혈당 기록하기 | 당당케어",
    page_icon="🩸",
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
profile_menu = show_sidebar_menu("pages/record.py")


# 로그인 확인
client, user = require_login()

st.title("🩸 혈당 기록하기")
st.caption(
    "왼쪽에서 관리 대상을 선택해 혈당을 기록해요. "
    "이전 기록은 ‘기록 확인·수정’에서 확인할 수 있어요."
)


# 로그인한 계정의 관리 대상 불러오기
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


# 관리 대상 등록
with st.expander(
    "➕ 관리 대상 추가",
    expanded=not profiles
):
    profile_type = st.radio(
        "대상 구분",
        ["사람", "반려동물"],
        horizontal=True
    )

    animal_choice = None

    if profile_type == "반려동물":
        animal_choice = st.selectbox(
            "동물 종류",
            ["강아지", "고양이", "기타"]
        )

    with st.form(
        "add_profile",
        clear_on_submit=True
    ):
        name = st.text_input(
            "이름 또는 별명",
            max_chars=50
        )

        custom_animal = ""

        if animal_choice == "기타":
            custom_animal = st.text_input(
                "동물 종류 직접 입력",
                placeholder="예: 토끼, 햄스터, 기니피그",
                max_chars=50
            )

        added = st.form_submit_button(
            "관리 대상 등록",
            use_container_width=True
        )

    if added:
        if not name.strip():
            st.warning("이름 또는 별명을 입력해 주세요.")

        elif animal_choice == "기타" and not custom_animal.strip():
            st.warning("동물 종류를 직접 입력해 주세요.")

        else:
            animal_type = None

            if profile_type == "반려동물":
                animal_type = (
                    custom_animal.strip()
                    if animal_choice == "기타"
                    else animal_choice
                )

            new_profile_id = str(uuid4())

            try:
                client.table("care_profiles").insert(
                    {
                        "id": new_profile_id,
                        "user_id": user.id,
                        "name": name.strip(),
                        "profile_type": profile_type,
                        "animal_type": animal_type
                    },
                    returning="minimal"
                ).execute()

            except Exception as error:
                show_error(
                    "관리 대상을 등록하지 못했어요. "
                    "잠시 후 다시 시도해 주세요.",
                    error
                )

            else:
                st.session_state.active_profile = new_profile_id
                st.rerun()


if not profiles:
    profile_menu.caption("등록된 관리 대상이 없어요.")
    st.info(
        "먼저 위에서 관리 대상을 등록해 주세요. "
        "사람과 반려동물을 함께 등록할 수 있어요."
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
        kind = (
            item.get("animal_type")
            or item["profile_type"]
        )

        icon = (
            "👤"
            if item["profile_type"] == "사람"
            else "🐾"
        )

        label = f"{icon} {item['name']} · {kind}"

        if sum(
            p["name"] == item["name"]
            for p in profiles
        ) > 1:
            label += f" · {item['id'][:8]}"

        is_selected = (
            item["id"]
            == st.session_state.active_profile
        )

        if st.button(
            label,
            key=f"choose_profile_{item['id']}",
            type="primary" if is_selected else "secondary",
            use_container_width=True
        ):
            st.session_state.active_profile = item["id"]
            st.rerun()


selected_id = st.session_state.active_profile
profile = profile_map[selected_id]

st.subheader(f"{profile['name']}의 혈당 관리")

now = datetime.now(ZoneInfo("Asia/Seoul"))


# 저장 완료 안내와 입력 양식 초기화 번호
scope = f"{user.id}_{selected_id}"
notice_key = f"glucose_notice_{scope}"
revision_key = f"glucose_revision_{scope}"
revision = st.session_state.get(revision_key, 0)

notice = st.session_state.pop(notice_key, None)

if notice:
    st.success(notice)

profile_notice_key = f"profile_edit_notice_{scope}"
profile_notice = st.session_state.pop(profile_notice_key, None)

if profile_notice:
    st.success(profile_notice)


# 관리 대상 이름 수정
current_name = profile["name"]
name_form_key = f"profile_name_form_{scope}_{current_name}"

with st.expander("✏️ 관리 대상 이름 수정"):
    st.caption(
        f"수정할 대상: {current_name} · "
        "다른 대상을 수정하려면 왼쪽 메뉴에서 먼저 선택해 주세요."
    )

    st.caption(
        "이름을 변경해도 기존 혈당·식사·활동 기록과 "
        "진료 노트는 같은 관리 대상에 연결돼요."
    )

    with st.form(name_form_key):
        edited_name = st.text_input(
            "변경할 이름 또는 별명",
            value=current_name,
            max_chars=50
        )

        save_name = st.form_submit_button(
            "💾 이름 수정 저장",
            use_container_width=True
        )

    if save_name:
        new_name = edited_name.strip()

        if not new_name:
            st.warning("변경할 이름 또는 별명을 입력해 주세요.")

        elif len(new_name) > 50:
            st.warning("이름 또는 별명은 50자 이내로 입력해 주세요.")

        elif new_name == current_name:
            st.info("현재 등록된 이름과 같아요.")

        else:
            try:
                result = (
                    client.table("care_profiles")
                    .update(
                        {"name": new_name},
                        returning="representation"
                    )
                    .eq("user_id", user.id)
                    .eq("id", selected_id)
                    .execute()
                )

                if not result.data:
                    raise ValueError(
                        "변경된 관리 대상이 없어요. "
                        "목록을 다시 확인해 주세요."
                    )

            except Exception as error:
                show_error(
                    "이름 수정 결과를 확인하지 못했어요. "
                    "페이지를 다시 열어 확인해 주세요.",
                    error
                )

            else:
                st.session_state[profile_notice_key] = (
                    f"관리 대상 이름을 ‘{current_name}’에서 "
                    f"‘{new_name}’(으)로 수정했어요."
                )
                st.rerun()


# 등록된 반려동물 종류 수정
if profile["profile_type"] == "반려동물":
    current_animal = profile.get("animal_type") or ""
    animal_options = ["강아지", "고양이", "기타"]

    edit_version = f"{scope}_{current_animal}"

    with st.expander("🐾 동물 종류 수정"):
        st.caption(
            f"수정할 대상: {profile['name']} · "
            f"현재 종류: {current_animal or '미입력'}"
        )

        edit_animal_choice = st.selectbox(
            "변경할 동물 종류",
            animal_options,
            index=(
                animal_options.index(current_animal)
                if current_animal in ["강아지", "고양이"]
                else 2
            ),
            key=f"edit_animal_choice_{edit_version}"
        )

        with st.form(f"edit_animal_form_{edit_version}"):
            edit_custom_animal = ""

            if edit_animal_choice == "기타":
                edit_custom_animal = st.text_input(
                    "변경할 동물 종류 직접 입력",
                    value=(
                        current_animal
                        if current_animal not in animal_options
                        else ""
                    ),
                    placeholder="예: 토끼, 햄스터, 기니피그",
                    max_chars=50
                )

            update_animal = st.form_submit_button(
                "💾 동물 종류 수정 저장",
                use_container_width=True
            )

        if update_animal:
            new_animal = (
                edit_custom_animal.strip()
                if edit_animal_choice == "기타"
                else edit_animal_choice
            )

            if not new_animal:
                st.warning("변경할 동물 종류를 입력해 주세요.")

            elif new_animal == current_animal:
                st.info("현재 등록된 동물 종류와 같아요.")

            else:
                try:
                    result = (
                        client.table("care_profiles")
                        .update(
                            {"animal_type": new_animal},
                            returning="representation"
                        )
                        .eq("user_id", user.id)
                        .eq("id", selected_id)
                        .eq("profile_type", "반려동물")
                        .execute()
                    )

                    if not result.data:
                        raise ValueError(
                            "변경된 관리 대상이 없어요. "
                            "목록을 다시 확인해 주세요."
                        )

                except Exception as error:
                    show_error(
                        "동물 종류 수정 결과를 확인하지 못했어요. "
                        "페이지를 다시 열어 확인해 주세요.",
                        error
                    )

                else:
                    st.session_state[profile_notice_key] = (
                        f"{profile['name']}의 동물 종류를 "
                        f"‘{new_animal}’(으)로 수정했어요."
                    )
                    st.rerun()


# 혈당 입력
form_key = f"glucose_{scope}_{revision}"

with st.form(form_key):
    c1, c2 = st.columns(2)

    measure_date = c1.date_input(
        "📅 측정 날짜",
        value=now.date(),
        max_value=now.date(),
        key=f"{form_key}_date"
    )

    measure_time = c2.time_input(
        "🕐 측정 시간",
        value=now.time().replace(second=0, microsecond=0),
        step=60,
        key=f"{form_key}_time"
    )

    st.caption(
        "시간은 대한민국 기준이며, "
        "오후 1시는 13:00으로 저장돼요. "
        "현재보다 미래인 측정 시각은 저장할 수 없어요."
    )

    glucose = st.number_input(
        "🩸 혈당 수치 (mg/dL)",
        min_value=0,
        max_value=1000,
        value=0,
        step=1,
        key=f"{form_key}_glucose"
    )

    meal = st.selectbox(
        "🍽️ 측정 시점",
        MEALS,
        key=f"{form_key}_meal"
    )

    insulin = st.number_input(
        "💉 인슐린 투여량 (단위)",
        min_value=0.0,
        value=0.0,
        step=0.5,
        key=f"{form_key}_insulin"
    )

    memo = st.text_area(
        "📝 메모",
        placeholder="식사, 활동량, 컨디션 등을 기록해 주세요.",
        key=f"{form_key}_memo"
    )

    saved = st.form_submit_button(
        "💾 혈당 기록 저장",
        use_container_width=True
    )


# 혈당 저장
if saved:
    measured_at = datetime.combine(
        measure_date,
        measure_time
    ).replace(tzinfo=ZoneInfo("Asia/Seoul"))

    current_time = datetime.now(ZoneInfo("Asia/Seoul"))

    if measured_at > current_time:
        st.warning(
            "측정 시각이 현재보다 미래예요. "
            "실제로 측정한 날짜와 시간으로 바꿔 주세요."
        )

    elif glucose <= 0:
        st.warning("혈당 수치를 입력해 주세요.")

    elif meal == "선택해 주세요":
        st.warning("측정 시점을 선택해 주세요.")

    else:
        try:
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

        except Exception as error:
            show_error("기록을 저장하지 못했어요.", error)

        else:
            st.session_state[notice_key] = (
                f"{profile['name']}의 혈당 "
                f"{glucose} mg/dL 기록을 저장했어요!"
            )
            st.session_state[revision_key] = revision + 1
            st.rerun()


# 선택한 대상의 최근 혈당 기록
st.divider()
st.subheader(f"📋 {profile['name']}의 최근 혈당 기록")
st.caption(
    "측정 날짜·시간이 최신인 순서로 최대 3건을 표시해요."
)

try:
    recent_rows = (
        client.table("blood_glucose")
        .select(
            "record_id,measure_date,measure_time,"
            "glucose,meal,insulin,memo"
        )
        .eq("user_id", user.id)
        .eq("profile_id", selected_id)
        .order("measure_date", desc=True)
        .order("measure_time", desc=True)
        .order("record_id")
        .limit(3)
        .execute()
        .data
    ) or []

except Exception as error:
    show_error(
        "최근 혈당 기록을 불러오지 못했어요.",
        error
    )

else:
    if recent_rows:
        recent_table = [
            {
                "측정 날짜": row["measure_date"],
                "측정 시간": str(row["measure_time"])[:5],
                "혈당 (mg/dL)": row["glucose"],
                "측정 시점": row.get("meal") or "미입력",
                "인슐린 (단위)": row.get("insulin"),
                "메모": row.get("memo") or ""
            }
            for row in recent_rows
        ]

        st.dataframe(
            recent_table,
            hide_index=True,
            use_container_width=True
        )

    else:
        st.info(
            "아직 저장된 혈당 기록이 없어요. "
            "위에서 첫 기록을 입력해 주세요."
        )


# 혈당과 식사·활동 연결
show_record_links(
    client=client,
    user_id=user.id,
    profile_id=selected_id
)


# 혈당 기록 전체 초기화
st.divider()

with st.expander("🗑️ 선택한 대상의 혈당 기록 전체 초기화"):
    reset_count = None

    try:
        count_result = (
            client.table("blood_glucose")
            .select(
                "record_id",
                count="exact",
                head=True
            )
            .eq("user_id", user.id)
            .eq("profile_id", selected_id)
            .execute()
        )

        if count_result.count is None:
            raise ValueError("혈당 기록 수를 확인하지 못했어요.")

        reset_count = count_result.count

    except Exception as error:
        show_error(
            "초기화할 혈당 기록 수를 확인하지 못했어요.",
            error
        )

    if reset_count is not None:
        st.warning(
            f"‘{profile['name']}’의 혈당 기록 "
            f"{reset_count}건을 날짜와 관계없이 모두 삭제해요. "
            "삭제한 기록은 앱에서 복구할 수 없어요."
        )

        st.caption(
            "관리 대상과 식사·활동 기록, 냉장고 재료, "
            "진료 노트의 질문·메모는 유지돼요. "
            "다른 관리 대상의 혈당 기록도 유지돼요."
        )

        st.caption(
            "삭제할 혈당에 연결된 식사·활동의 연결 정보도 사라져요. "
            "진료 노트에 골라둔 혈당은 삭제 후 조회할 수 없고, "
            "혈당 통계와 그래프에서도 제외돼요."
        )

        st.page_link(
            "pages/history.py",
            label="삭제 전에 기록 확인·수정에서 CSV 다운로드하기",
            icon="📥"
        )

        reset_form_key = (
            f"reset_glucose_{scope}_{reset_count}_{revision}"
        )

        with st.form(reset_form_key):
            confirm_reset = st.checkbox(
                "선택한 대상의 혈당 기록 전체가 삭제되는 것을 확인했어요."
            )

            reset_name = st.text_input(
                "확인을 위해 현재 관리 대상 이름을 그대로 입력해 주세요.",
                help=f"입력할 이름: {profile['name']}"
            )

            reset_clicked = st.form_submit_button(
                "🗑️ 이 대상의 혈당 기록 전체 삭제",
                use_container_width=True,
                disabled=reset_count == 0
            )

        if reset_count == 0:
            st.caption("초기화할 혈당 기록이 없어요.")

        if reset_clicked:
            if not confirm_reset:
                st.warning("전체 삭제 확인란을 먼저 체크해 주세요.")

            elif reset_name.strip() != profile["name"]:
                st.warning(
                    "현재 관리 대상 이름을 정확히 입력해 주세요."
                )

            else:
                try:
                    (
                        client.table("blood_glucose")
                        .delete(returning="minimal")
                        .eq("user_id", user.id)
                        .eq("profile_id", selected_id)
                        .execute()
                    )

                    # 응답 행 수 제한과 관계없이 남은 기록을 확인한다.
                    remaining_result = (
                        client.table("blood_glucose")
                        .select(
                            "record_id",
                            count="exact",
                            head=True
                        )
                        .eq("user_id", user.id)
                        .eq("profile_id", selected_id)
                        .execute()
                    )

                    if remaining_result.count is None:
                        raise ValueError(
                            "삭제 후 남은 기록 수를 확인하지 못했어요."
                        )

                    if remaining_result.count != 0:
                        raise ValueError(
                            "혈당 기록이 남아 있어요. "
                            "기록 목록과 삭제 권한을 확인해 주세요."
                        )

                except Exception as error:
                    # 삭제가 실행된 뒤 결과 확인만 실패했을 수도 있다.
                    st.session_state.pop(
                        f"care_record_context_{scope}",
                        None
                    )
                    st.session_state.pop(
                        f"record_ai_result_{scope}",
                        None
                    )

                    show_error(
                        "전체 삭제 결과를 확인하지 못했어요. "
                        "기록 확인·수정 페이지에서 "
                        "남은 기록을 확인해 주세요.",
                        error
                    )

                else:
                    st.session_state.pop(
                        f"care_record_context_{scope}",
                        None
                    )
                    st.session_state.pop(
                        f"record_ai_result_{scope}",
                        None
                    )

                    st.session_state[revision_key] = revision + 1

                    st.session_state[notice_key] = (
                        f"{profile['name']}의 혈당 기록을 "
                        "모두 삭제했어요."
                    )
                    st.rerun()


# 관련 페이지 이동
st.divider()

c1, c2, c3 = st.columns(3)

with c1:
    st.page_link(
        "pages/history.py",
        label="저장한 혈당 확인·수정하기",
        icon="📈"
    )

with c2:
    st.page_link(
        "pages/lifestyle.py",
        label="식사·활동 기록하기",
        icon="📝"
    )

with c3:
    st.page_link(
        "pages/meal.py",
        label="냉장고 재료·식사 조건 입력하기",
        icon="🍽️"
    )
