from datetime import date, timedelta
from hashlib import sha256
from uuid import uuid4
import json

import pandas as pd
import streamlit as st

from app_shared import (
    require_login,
    get_timezone_name,
    get_local_now,
)
from sidebar_menu import show_sidebar_menu


NOTE_MODES = (
    "진료 준비",
    "진료 일정 저장",
    "진료 후 기록",
)


def default_note_mode(note):
    if note and (
        note.get("completed")
        or note.get("consultation_notes")
        or note.get("followup_notes")
    ):
        return "진료 후 기록"

    return "진료 준비"


def build_note_values(mode, fields, note=None):
    if mode not in NOTE_MODES:
        raise ValueError("작성 모드를 확인해 주세요.")

    if note is None:
        values = {
            "summary_start": fields["summary_start"].isoformat(),
            "summary_end": fields["summary_end"].isoformat(),
            "questions": "",
            "memo": "",
            "consultation_notes": "",
            "followup_notes": "",
            "completed": False,
        }
    else:
        values = {}

    values.update({
        "title": fields["title"].strip(),
        "visit_date": (
            fields["visit_date"].isoformat()
            if fields["visit_date"] is not None
            else None
        ),
    })

    # 일정 모드에서는 기존 질문·진료 후 내용 등을 수정하지 않아요.
    if mode == "진료 일정 저장":
        return values

    values.update({
        "summary_start": fields["summary_start"].isoformat(),
        "summary_end": fields["summary_end"].isoformat(),
    })

    if mode == "진료 준비":
        values.update({
            "questions": fields["questions"].strip(),
            "memo": fields["memo"].strip(),
        })

    else:
        values.update({
            "consultation_notes": (
                fields["consultation_notes"].strip()
            ),
            "followup_notes": fields["followup_notes"].strip(),
            "completed": fields["completed"],
        })

    return values


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


def fetch_all(make_query):
    rows = []
    offset = 0

    while True:
        batch = (
            make_query()
            .range(offset, offset + 499)
            .execute()
            .data
        ) or []

        if not batch:
            return rows

        rows.extend(batch)

        if len(rows) > 10000:
            raise ValueError(
                "조회 결과가 10,000건을 넘었어요. "
                "기간을 줄여 주세요."
            )

        offset += len(batch)


def update_note(
    client,
    user_id,
    profile_id,
    note_id,
    values,
):
    result = (
        client.table("visit_notes")
        .update(
            {
                **values,
                "updated_at": get_local_now().isoformat(),
            },
            returning="representation",
        )
        .eq("user_id", user_id)
        .eq("profile_id", profile_id)
        .eq("id", note_id)
        .execute()
    )

    if not result.data:
        raise ValueError(
            "변경된 노트가 없어요. "
            "페이지를 다시 열어 확인해 주세요."
        )


def blood_table(rows):
    return pd.DataFrame([
        {
            "날짜": row["measure_date"],
            "시간": str(row["measure_time"])[:5],
            "혈당 (mg/dL)": row["glucose"],
            "측정 시점": row.get("meal") or "미입력",
            "인슐린 (단위)": row.get("insulin"),
            "메모": row.get("memo") or "",
        }
        for row in rows
    ])


st.set_page_config(
    page_title="진료 노트 | 당당케어",
    page_icon="🏥",
    layout="wide",
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


profile_menu = show_sidebar_menu("pages/visit.py")

client, user = require_login()
timezone_name = get_timezone_name()

st.title("🏥 진료 노트")

st.caption(
    "작성 목적을 선택해 진료를 준비하거나 일정을 저장하고, "
    "진료 후 들은 설명과 다음 확인 사항을 기록해요."
)

st.caption(
    f"날짜·저장 시각 기준: {timezone_name}"
)


# 관리 대상 조회
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
        "관리 대상을 불러오지 못했어요.",
        error,
    )
    st.stop()

if not profiles:
    st.info("먼저 관리 대상을 등록해 주세요.")

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
            key=f"visit_profile_{user.id}_{item['id']}",
            type="primary" if active else "secondary",
            use_container_width=True,
        ):
            st.session_state.active_profile = item["id"]
            st.rerun()


profile_id = st.session_state.active_profile
profile = profile_map[profile_id]

scope = f"{user.id}_{profile_id}"
ui_scope = f"{scope}_{timezone_name}"

today = get_local_now().date()

st.subheader(f"{profile['name']}의 진료 노트")

notice = st.session_state.pop("visit_notice", None)

if notice and notice[:2] == (user.id, profile_id):
    st.success(notice[2])


# 저장된 노트 목록
try:
    notes = fetch_all(
        lambda: (
            client.table("visit_notes")
            .select("*")
            .eq("user_id", user.id)
            .eq("profile_id", profile_id)
            .order("created_at", desc=True)
            .order("id")
        )
    )

except Exception as error:
    show_error(
        "진료 노트를 불러오지 못했어요.",
        error,
    )
    st.stop()

note_map = {
    item["id"]: item
    for item in notes
}

# 홈에서 특정 노트를 여는 연결 유지
choice_key = f"visit_choice_{scope}"
pending_key = f"visit_pending_{scope}"

pending = st.session_state.pop(pending_key, None)

if pending is not None:
    st.session_state[choice_key] = (
        pending if pending in note_map else "new"
    )

options = ["new"] + list(note_map)

if st.session_state.get(choice_key) not in options:
    st.session_state[choice_key] = "new"


def note_label(note_id):
    if note_id == "new":
        return "➕ 새 진료 노트 만들기"

    item = note_map[note_id]
    status = "완료" if item["completed"] else "준비 중"
    visit_day = item.get("visit_date") or "진료일 미입력"

    return (
        f"{item['title']} · {visit_day} · "
        f"{status} · {note_id[:6]}"
    )


selected_id = st.selectbox(
    "진료 노트 선택",
    options,
    format_func=note_label,
    key=choice_key,
)

note = note_map.get(selected_id)
existing = note is not None

form_version = fingerprint(note or {})


# 작성 모드를 양식 밖에서 먼저 선택
mode_key = f"visit_mode_{scope}_{selected_id}"

mode = st.radio(
    "무엇을 작성할까요?",
    NOTE_MODES,
    index=NOTE_MODES.index(default_note_mode(note)),
    horizontal=True,
    key=mode_key,
)

mode_descriptions = {
    "진료 준비": (
        "진료 때 물어볼 질문과 전달할 내용, "
        "관련 기록 기간을 작성해요."
    ),
    "진료 일정 저장": (
        "제목과 진료 예정일만 입력해 일정을 저장해요."
    ),
    "진료 후 기록": (
        "실제 진료일과 들은 설명, "
        "다음 확인 사항을 기록해요."
    ),
}

st.info(mode_descriptions[mode])

st.caption(
    "다른 모드로 바꾸기 전에 현재 입력을 저장해 주세요. "
    "저장된 같은 노트를 다른 모드로 열어 이어서 작성할 수 있어요."
)

original_summary_start = (
    date.fromisoformat(note["summary_start"])
    if existing
    else today - timedelta(days=29)
)

original_summary_end = (
    date.fromisoformat(note["summary_end"])
    if existing
    else today
)

if (
    mode != "진료 일정 저장"
    and existing
    and (
        original_summary_start > today
        or original_summary_end > today
    )
):
    st.warning(
        "저장된 요약 기간에 현재 시간대의 오늘보다 늦은 날짜가 있어요. "
        "입력란에는 오늘까지로 표시했으니 수정 저장 전에 확인해 주세요. "
        "저장된 기간은 저장 버튼을 누르기 전까지 유지돼요."
    )


# 숨겨진 항목에는 기존 값을 준비해 두고,
# 실제 저장 시 현재 모드에 해당하는 항목만 수정
summary_start = original_summary_start
summary_end = original_summary_end

questions = (
    (note.get("questions") or "")
    if existing
    else ""
)

memo = (
    (note.get("memo") or "")
    if existing
    else ""
)

consultation_notes = (
    (note.get("consultation_notes") or "")
    if existing
    else ""
)

followup_notes = (
    (note.get("followup_notes") or "")
    if existing
    else ""
)

completed = (
    bool(note.get("completed"))
    if existing
    else False
)


# 선택한 모드에 맞는 작성 화면
with st.form(
    f"visit_form_{ui_scope}_{selected_id}_{form_version}_{mode}"
):
    title = st.text_input(
        "일정 제목"
        if mode == "진료 일정 저장"
        else "노트 제목",
        value=(
            note["title"]
            if existing
            else (
                "진료 일정"
                if mode == "진료 일정 저장"
                else "진료 노트"
            )
        ),
        max_chars=100,
    )

    date_labels = {
        "진료 준비": "진료 예정일(선택)",
        "진료 일정 저장": "진료 예정일(필수)",
        "진료 후 기록": "실제 진료일(필수)",
    }

    visit_date = st.date_input(
        date_labels[mode],
        value=(
            date.fromisoformat(note["visit_date"])
            if existing and note.get("visit_date")
            else (
                today
                if mode == "진료 후 기록"
                else None
            )
        ),
        help=(
            "진료 후 기록에는 실제 진료받은 날짜를 입력해 주세요."
            if mode == "진료 후 기록"
            else "예약한 진료 날짜를 입력해 주세요."
        ),
    )

    if mode != "진료 일정 저장":
        st.markdown(
            "**이 진료와 관련된 기록의 기간**"
        )

        c1, c2 = st.columns(2)

        summary_start = c1.date_input(
            "기록 시작일",
            value=min(original_summary_start, today),
            max_value=today,
        )

        summary_end = c2.date_input(
            "기록 종료일",
            value=min(original_summary_end, today),
            max_value=today,
        )

    if mode == "진료 준비":
        st.markdown("### 📋 진료 전 준비")

        questions = st.text_area(
            "진료 때 물어볼 질문",
            value=questions,
            placeholder=(
                "질문을 한 줄에 하나씩 입력해 주세요.\n"
                "예: 집에서 측정할 때 주의할 점은 무엇인가요?"
            ),
            height=150,
            max_chars=10000,
        )

        memo = st.text_area(
            "의료진·수의사에게 전달할 내용",
            value=memo,
            placeholder=(
                "관찰한 변화나 전달할 내용을 입력해 주세요."
            ),
            height=120,
            max_chars=10000,
        )

        if existing and (
            note.get("consultation_notes")
            or note.get("followup_notes")
        ):
            st.caption(
                "기존 진료 후 기록은 그대로 보관돼요."
            )

    elif mode == "진료 일정 저장":
        st.caption(
            "질문이나 진료 후 내용을 입력하지 않아도 저장할 수 있어요. "
            "기존 노트의 질문·기록 기간·진료 후 내용·완료 상태는 유지돼요."
        )

    else:
        st.markdown("### 📝 진료 후 기록")

        if existing and (
            note.get("questions")
            or note.get("memo")
        ):
            with st.expander(
                "📋 저장된 진료 준비 내용 보기"
            ):
                st.markdown("**진료 때 물어볼 질문**")
                st.write(
                    note.get("questions") or "미입력"
                )

                st.markdown("**전달할 내용**")
                st.write(
                    note.get("memo") or "미입력"
                )

        consultation_notes = st.text_area(
            "진료에서 들은 설명·안내",
            value=consultation_notes,
            placeholder=(
                "의료진·수의사에게 들은 설명, 검사 결과 안내, "
                "질문에 대한 답변 등을 기록해 주세요."
            ),
            height=180,
            max_chars=10000,
        )

        followup_notes = st.text_area(
            "다음 진료까지 확인할 내용",
            value=followup_notes,
            placeholder=(
                "안내받은 관리 방법, 관찰할 변화, "
                "다음 진료 때 확인할 질문 등을 기록해 주세요."
            ),
            height=140,
            max_chars=10000,
        )

        completed = st.checkbox(
            "이 진료를 마쳤어요.",
            value=completed if existing else True,
        )

    save_labels = {
        "진료 준비": "💾 진료 준비 내용 저장",
        "진료 일정 저장": "📅 진료 일정 저장",
        "진료 후 기록": "💾 진료 후 기록 저장",
    }

    save = st.form_submit_button(
        save_labels[mode],
        use_container_width=True,
    )


if save:
    if not title.strip():
        st.warning("제목을 입력해 주세요.")

    elif mode != "진료 준비" and visit_date is None:
        st.warning("진료 날짜를 입력해 주세요.")

    elif (
        mode == "진료 후 기록"
        and visit_date > get_local_now().date()
    ):
        st.warning(
            "진료 후 기록의 실제 진료일은 오늘보다 늦을 수 없어요. "
            "앞으로의 일정은 ‘진료 일정 저장’ 모드에서 작성해 주세요."
        )

    elif (
        mode != "진료 일정 저장"
        and summary_start > summary_end
    ):
        st.warning(
            "기록 시작일은 종료일보다 늦을 수 없어요."
        )

    elif (
        mode != "진료 일정 저장"
        and summary_end > get_local_now().date()
    ):
        st.warning(
            "기록 종료일은 현재 시간대의 오늘보다 늦을 수 없어요."
        )

    elif (
        mode != "진료 일정 저장"
        and (summary_end - summary_start).days > 365
    ):
        st.warning(
            "기록 요약 기간은 최대 366일로 설정해 주세요."
        )

    else:
        values = build_note_values(
            mode,
            {
                "title": title,
                "visit_date": visit_date,
                "summary_start": summary_start,
                "summary_end": summary_end,
                "questions": questions,
                "memo": memo,
                "consultation_notes": consultation_notes,
                "followup_notes": followup_notes,
                "completed": completed,
            },
            note=note,
        )

        target_id = (
            selected_id
            if existing
            else str(uuid4())
        )

        try:
            if existing:
                update_note(
                    client,
                    user.id,
                    profile_id,
                    target_id,
                    values,
                )

            else:
                client.table("visit_notes").insert(
                    {
                        **values,
                        "id": target_id,
                        "user_id": user.id,
                        "profile_id": profile_id,
                    },
                    returning="minimal",
                ).execute()

        except Exception as error:
            show_error(
                "저장 결과를 확인하지 못했어요. "
                "페이지를 다시 열어 노트 목록을 확인해 주세요.",
                error,
            )

        else:
            if not existing:
                st.session_state[
                    f"visit_mode_{scope}_{target_id}"
                ] = mode

            st.session_state[pending_key] = target_id

            st.session_state.visit_notice = (
                user.id,
                profile_id,
                f"{mode} 내용을 저장했어요.",
            )

            st.rerun()


if not existing:
    st.info(
        "노트를 먼저 저장하면 아래에 기록 요약과 "
        "혈당 기록 선택 화면이 나타나요."
    )
    st.stop()


# 노트 삭제
with st.expander("🗑️ 이 진료 노트 삭제"):
    with st.form(
        f"visit_delete_{scope}_{selected_id}_{form_version}"
    ):
        st.warning(
            "이 노트의 질문·메모·진료 후 기록·선택 목록을 삭제해요. "
            "원래 혈당과 식사·활동 기록은 유지돼요."
        )

        confirm_delete = st.checkbox(
            "이 진료 노트를 삭제하는 것을 확인했어요."
        )

        delete = st.form_submit_button(
            "진료 노트 삭제"
        )

    if delete:
        if not confirm_delete:
            st.warning(
                "삭제 확인란을 먼저 체크해 주세요."
            )

        else:
            try:
                result = (
                    client.table("visit_notes")
                    .delete(returning="representation")
                    .eq("user_id", user.id)
                    .eq("profile_id", profile_id)
                    .eq("id", selected_id)
                    .execute()
                )

                if not result.data:
                    raise ValueError(
                        "삭제된 노트가 없어요. "
                        "목록을 다시 확인해 주세요."
                    )

            except Exception as error:
                show_error(
                    "삭제 결과를 확인하지 못했어요.",
                    error,
                )

            else:
                st.session_state[pending_key] = "new"

                st.session_state.visit_notice = (
                    user.id,
                    profile_id,
                    "진료 노트를 삭제했어요.",
                )

                st.rerun()


# 저장된 노트의 기간으로 요약
st.divider()
st.subheader("📋 저장된 노트의 기록 요약")

st.caption(
    f"{note['summary_start']} ~ {note['summary_end']} · "
    "기간을 바꿨다면 위의 저장 버튼을 눌러 주세요."
)

try:
    glucose_rows = fetch_all(
        lambda: (
            client.table("blood_glucose")
            .select(
                "record_id,measure_date,measure_time,"
                "glucose,meal,insulin,memo"
            )
            .eq("user_id", user.id)
            .eq("profile_id", profile_id)
            .gte("measure_date", note["summary_start"])
            .lte("measure_date", note["summary_end"])
            .order("measure_date")
            .order("measure_time")
            .order("record_id")
        )
    )

    lifestyle_rows = fetch_all(
        lambda: (
            client.table("lifestyle_records")
            .select("id,record_type,record_date")
            .eq("user_id", user.id)
            .eq("profile_id", profile_id)
            .gte("record_date", note["summary_start"])
            .lte("record_date", note["summary_end"])
            .order("record_date")
            .order("id")
        )
    )

except Exception as error:
    show_error(
        "기록 요약을 불러오지 못했어요.",
        error,
    )
    st.stop()


c1, c2 = st.columns(2)

c1.metric(
    "혈당 기록",
    f"{len(glucose_rows)}건",
)

c2.metric(
    "식사·활동 기록",
    f"{len(lifestyle_rows)}건",
)

summary = pd.DataFrame()

if glucose_rows:
    frame = pd.DataFrame(glucose_rows)

    frame["glucose"] = pd.to_numeric(
        frame["glucose"],
        errors="coerce",
    )

    frame["meal"] = frame["meal"].fillna("미입력")

    invalid_count = int(
        frame["glucose"].isna().sum()
    )

    frame = frame.dropna(subset=["glucose"])

    if not frame.empty:
        summary = (
            frame.groupby("meal")
            .agg(
                기록수=("glucose", "size"),
                측정일수=("measure_date", "nunique"),
                평균=("glucose", "mean"),
                중앙값=("glucose", "median"),
                최솟값=("glucose", "min"),
                최댓값=("glucose", "max"),
            )
            .round(1)
        )

        summary.index.name = "측정 시점"

        st.markdown(
            "**측정 시점별 혈당 요약 · 단위 mg/dL**"
        )

        st.dataframe(
            summary,
            use_container_width=True,
        )

    if invalid_count:
        st.caption(
            f"숫자로 읽을 수 없는 혈당 {invalid_count}건은 "
            "통계에서 제외했어요."
        )

else:
    st.info(
        "선택한 기간에 혈당 기록이 없어요."
    )

kind_labels = {
    "meal": "식사 — 음식 항목",
    "activity": "운동·산책",
    "sleep": "수면",
    "no_activity": "활동 없음 확인",
}

if lifestyle_rows:
    lifestyle_summary = (
        pd.Series([
            kind_labels.get(
                row["record_type"],
                row["record_type"],
            )
            for row in lifestyle_rows
        ])
        .value_counts()
        .rename_axis("종류")
        .rename("기록 수")
        .to_frame()
    )

    st.markdown("**식사·활동 기록 현황**")

    st.dataframe(
        lifestyle_summary,
        use_container_width=True,
    )

st.caption(
    "식사 건수는 식사 횟수가 아니라 입력한 음식 항목 수예요. "
    "이 요약은 진료 준비용 기록이며 진단이나 치료 판단은 하지 않아요."
)


# 기간 내 혈당 기록을 노트에 추가
st.divider()
st.subheader("⭐ 진료 때 확인할 혈당 기록")

pinned_ids = list(dict.fromkeys(
    str(item)
    for item in (note.get("pinned_record_ids") or [])
))

if glucose_rows:
    st.caption(
        "아래 표에서 기록을 여러 개 고른 뒤 "
        "‘선택한 기록을 노트에 추가’를 눌러 주세요."
    )

    event = st.dataframe(
        blood_table(glucose_rows),
        hide_index=True,
        use_container_width=True,
        on_select="rerun",
        selection_mode="multi-row",
        key=(
            f"visit_blood_{scope}_{selected_id}_"
            f"{fingerprint(glucose_rows)}_{fingerprint(pinned_ids)}"
        ),
    )

    if st.button(
        "⭐ 선택한 기록을 노트에 추가",
        key=f"visit_add_pins_{scope}_{selected_id}",
    ):
        positions = event["selection"]["rows"]

        selected_ids = [
            str(glucose_rows[position]["record_id"])
            for position in positions
            if 0 <= position < len(glucose_rows)
        ]

        combined = list(dict.fromkeys(
            pinned_ids + selected_ids
        ))

        if not selected_ids:
            st.warning(
                "표에서 기록을 먼저 선택해 주세요."
            )

        elif len(combined) > 100:
            st.warning(
                "한 노트에는 최대 100건까지 골라둘 수 있어요."
            )

        else:
            try:
                update_note(
                    client,
                    user.id,
                    profile_id,
                    selected_id,
                    {"pinned_record_ids": combined},
                )

            except Exception as error:
                show_error(
                    "선택 목록을 저장하지 못했어요.",
                    error,
                )

            else:
                st.session_state.visit_notice = (
                    user.id,
                    profile_id,
                    "선택한 혈당 기록을 노트에 추가했어요.",
                )

                st.rerun()


# 골라둔 기록은 요약 기간 밖이어도 별도로 조회
pinned_rows = []

try:
    for offset in range(0, len(pinned_ids), 100):
        batch_ids = pinned_ids[offset:offset + 100]

        batch = (
            client.table("blood_glucose")
            .select(
                "record_id,measure_date,measure_time,"
                "glucose,meal,insulin,memo"
            )
            .eq("user_id", user.id)
            .eq("profile_id", profile_id)
            .in_("record_id", batch_ids)
            .execute()
            .data
        ) or []

        pinned_rows.extend(batch)

except Exception as error:
    show_error(
        "골라둔 혈당 기록을 불러오지 못했어요.",
        error,
    )
    st.stop()

pinned_rows.sort(
    key=lambda row: (
        row["measure_date"],
        row["measure_time"],
        str(row["record_id"]),
    )
)

st.markdown("**현재 골라둔 기록**")

if pinned_rows:
    st.dataframe(
        blood_table(pinned_rows),
        hide_index=True,
        use_container_width=True,
    )

else:
    st.caption(
        "현재 확인 가능한 선택 기록이 없어요."
    )

if len(pinned_rows) < len(pinned_ids):
    st.caption(
        "선택 목록 중 현재 참조할 수 없는 기록이 있어요. "
        "원래 기록의 삭제 여부 등을 확인해 주세요."
    )

if pinned_ids:
    pinned_map = {
        str(row["record_id"]): row
        for row in pinned_rows
    }

    def pin_label(record_id):
        row = pinned_map.get(record_id)

        if row is None:
            return (
                "현재 참조할 수 없는 기록 · "
                f"{record_id[:8]}"
            )

        return (
            f"{row['measure_date']} "
            f"{str(row['measure_time'])[:5]} · "
            f"{row['glucose']} mg/dL · "
            f"{row.get('meal') or '미입력'} · "
            f"{record_id[:6]}"
        )

    to_remove = st.multiselect(
        "노트에서 뺄 기록",
        pinned_ids,
        format_func=pin_label,
        key=(
            f"visit_remove_pins_{scope}_{selected_id}_"
            f"{fingerprint(pinned_ids)}"
        ),
    )

    if st.button(
        "선택 목록에서 빼기",
        key=f"visit_remove_button_{scope}_{selected_id}",
    ):
        if not to_remove:
            st.warning(
                "목록에서 뺄 기록을 선택해 주세요."
            )

        else:
            try:
                update_note(
                    client,
                    user.id,
                    profile_id,
                    selected_id,
                    {
                        "pinned_record_ids": [
                            item
                            for item in pinned_ids
                            if item not in to_remove
                        ],
                    },
                )

            except Exception as error:
                show_error(
                    "선택 목록을 변경하지 못했어요.",
                    error,
                )

            else:
                st.session_state.visit_notice = (
                    user.id,
                    profile_id,
                    "노트의 선택 목록에서 뺐어요. "
                    "원래 혈당 기록은 유지돼요.",
                )

                st.rerun()


# 텍스트 다운로드
st.divider()
st.subheader("📥 진료 노트 다운로드")

kind = (
    profile.get("animal_type")
    or profile["profile_type"]
)

export_now = get_local_now()

lines = [
    "당당케어 진료 노트",
    (
        f"자료 생성 시각: {export_now:%Y-%m-%d %H:%M} "
        f"({timezone_name})"
    ),
    "측정 기록의 날짜·시간은 저장된 값을 그대로 표시함",
    "",
    f"대상: {profile['name']} · {kind}",
    f"제목: {note['title']}",
    f"진료일·예정일: {note.get('visit_date') or '미입력'}",
    f"상태: {'완료' if note['completed'] else '준비 중'}",
    f"요약 기간: {note['summary_start']} ~ {note['summary_end']}",
    "",
    "[진료 때 물어볼 질문]",
    note.get("questions") or "미입력",
    "",
    "[전달할 내용]",
    note.get("memo") or "미입력",
    "",
    "[진료에서 들은 설명·안내]",
    note.get("consultation_notes") or "미입력",
    "",
    "[다음 진료까지 확인할 내용]",
    note.get("followup_notes") or "미입력",
    "",
    "[혈당 기록 요약]",
    f"조회한 혈당 기록: {len(glucose_rows)}건",
]

if not summary.empty:
    for meal, row in summary.iterrows():
        lines.append(
            f"- {meal}: {int(row['기록수'])}건, "
            f"{int(row['측정일수'])}일 측정, "
            f"평균 {row['평균']:g}, "
            f"중앙값 {row['중앙값']:g}, "
            f"최솟값 {row['최솟값']:g}, "
            f"최댓값 {row['최댓값']:g} mg/dL"
        )

lines.extend([
    "",
    "[식사·활동 기록 현황]",
])

for code, label in kind_labels.items():
    count = sum(
        row["record_type"] == code
        for row in lifestyle_rows
    )

    lines.append(
        f"- {label}: {count}건"
    )

lines.extend([
    "",
    "[진료 때 확인할 혈당 기록]",
    "선택한 기록은 요약 기간 밖의 기록도 포함할 수 있음",
])

for row in pinned_rows:
    lines.append(
        f"- {row['measure_date']} "
        f"{str(row['measure_time'])[:5]} / "
        f"{row['glucose']} mg/dL / "
        f"{row.get('meal') or '미입력'} / "
        f"인슐린 {row.get('insulin')}단위 / "
        f"메모: {row.get('memo') or '없음'}"
    )

if not pinned_rows:
    lines.append(
        "현재 확인 가능한 선택 기록 없음"
    )

if len(pinned_rows) < len(pinned_ids):
    lines.append(
        "현재 참조할 수 없는 선택 기록: "
        f"{len(pinned_ids) - len(pinned_rows)}건"
    )

lines.extend([
    "",
    "이 파일은 사용자가 입력한 기록을 바탕으로 만든 진료 전·후 기록 자료입니다.",
    "식사 기록 건수는 식사 횟수가 아닌 음식 항목 수입니다.",
    "기록이 없다는 것은 식사나 활동이 없었다는 뜻이 아닙니다.",
])

report = "\n".join(lines)

st.download_button(
    "📄 진료 노트 TXT 다운로드",
    data=report.encode("utf-8-sig"),
    file_name=f"visit_note_{selected_id[:8]}.txt",
    mime="text/plain",
    key=f"visit_download_{scope}_{selected_id}",
)
