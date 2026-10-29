from datetime import date, datetime, time, timedelta
from hashlib import sha256
from zoneinfo import ZoneInfo
import json
import math

import pandas as pd
import streamlit as st

from app_shared import require_login


TYPES = {
    "🍽️ 식사": "meal",
    "🏃 운동·산책": "activity",
    "😴 수면": "sleep",
    "📅 활동 없음 확인": "no_activity"
}

TYPE_LABELS = {
    "meal": "식사",
    "activity": "운동·산책",
    "sleep": "수면",
    "no_activity": "활동 없음"
}

UNITS = ["g", "mL", "개", "공기", "인분", "장", "컵"]
MEAL_SLOTS = ["아침", "점심", "저녁", "간식", "기타"]
INTENSITIES = ["가벼움", "보통", "높음"]


def show_error(message, error):
    st.error(message)
    st.caption(
        f"오류 종류: {type(error).__name__} / "
        f"오류 코드: {getattr(error, 'code', None) or '없음'}"
    )


def fingerprint(value):
    return sha256(
        json.dumps(
            value, sort_keys=True, default=str
        ).encode()
    ).hexdigest()[:16]


def base_query(client, user_id, profile_id):
    return (
        client.table("lifestyle_records")
        .select("*")
        .eq("user_id", user_id)
        .eq("profile_id", profile_id)
    )


def check_activity_conflict(
    client, user_id, profile_id, record_date, record_type
):
    opposite = {
        "activity": "no_activity",
        "no_activity": "activity"
    }.get(record_type)

    if opposite is None:
        return

    existing = (
        base_query(client, user_id, profile_id)
        .eq("record_date", record_date)
        .eq("record_type", opposite)
        .limit(1)
        .execute()
        .data
    )

    if existing:
        if record_type == "activity":
            raise ValueError(
                "이 날짜에 ‘활동 없음’이 저장되어 있어요. "
                "아래 기록 목록에서 해당 확인 기록을 삭제한 뒤 "
                "활동을 입력해 주세요."
            )

        raise ValueError(
            "이 날짜에는 이미 활동 기록이 있어요. "
            "잘못 입력한 활동이라면 아래 목록에서 먼저 삭제해 주세요."
        )


def display_records(rows):
    result = []

    for row in rows:
        kind = row["record_type"]
        amount = row.get("amount")
        duration = row.get("duration_minutes")
        end_text = ""

        if kind == "sleep" and duration:
            started = datetime.fromisoformat(
                row["record_date"]
                + "T"
                + row["record_time"]
            )
            ended = started + timedelta(
                minutes=int(duration)
            )
            end_text = ended.strftime("%Y-%m-%d %H:%M")

        result.append({
            "날짜": row["record_date"],
            "시간": str(row.get("record_time") or "")[:5],
            "종류": TYPE_LABELS.get(kind, kind),
            "음식·활동": row.get("item_name") or "",
            "식사 구분": row.get("meal_slot") or "",
            "섭취량": (
                f"{float(amount):g} {row.get('amount_unit') or ''}"
                if amount is not None
                else ""
            ),
            "지속 시간(분)": (
                int(duration)
                if duration is not None
                else None
            ),
            "강도": row.get("intensity") or "",
            "수면 종료": end_text,
            "메모": row.get("memo") or ""
        })

    return pd.DataFrame(result)


# 수정 내용 검증
def build_edit_values(kind, form, now):
    now = now.replace(tzinfo=None)
    day = form["date"]

    if kind not in TYPE_LABELS:
        raise ValueError("수정할 수 없는 기록 종류예요.")

    values = {
        "record_date": day.isoformat(),
        "record_time": None,
        "item_name": None,
        "meal_slot": None,
        "amount": None,
        "amount_unit": None,
        "duration_minutes": None,
        "intensity": None,
        "memo": form.get("memo", "").strip()
    }

    if kind == "no_activity":
        if day >= now.date():
            raise ValueError(
                "활동 없음은 하루가 끝난 날짜에만 기록해 주세요."
            )

        if not form.get("confirmed"):
            raise ValueError("활동 없음 확인란을 체크해 주세요.")

        values["item_name"] = "활동 없음 확인"
        return values

    clock = form["time"].replace(
        second=0,
        microsecond=0,
        tzinfo=None
    )

    started = datetime.combine(day, clock)

    if started > now:
        raise ValueError(
            "아직 지나지 않은 시각으로 수정할 수 없어요."
        )

    values["record_time"] = clock.strftime("%H:%M")

    if kind == "meal":
        name = form.get("name", "").strip()
        amount = float(form.get("amount", 0))
        unit = form.get("unit", "").strip()
        slot = form.get("meal_slot")

        if not name:
            raise ValueError("음식명·사료명을 입력해 주세요.")

        if not math.isfinite(amount) or amount <= 0:
            raise ValueError(
                "섭취량은 0보다 큰 숫자로 입력해 주세요."
            )

        if not unit or slot not in MEAL_SLOTS:
            raise ValueError(
                "섭취량 단위와 식사 구분을 확인해 주세요."
            )

        values.update(
            item_name=name,
            amount=amount,
            amount_unit=unit,
            meal_slot=slot
        )

    elif kind == "activity":
        name = form.get("name", "").strip()
        duration = int(form.get("duration", 0))
        intensity = form.get("intensity")

        if not name:
            raise ValueError("활동명을 입력해 주세요.")

        if (
            not 1 <= duration <= 1440
            or intensity not in INTENSITIES
        ):
            raise ValueError("활동 시간과 강도를 확인해 주세요.")

        ended = started + timedelta(minutes=duration)

        if ended > now:
            raise ValueError(
                "활동이 끝난 뒤 실제 활동 시간을 기록해 주세요."
            )

        next_midnight = datetime.combine(
            day + timedelta(days=1),
            time(0, 0)
        )

        if ended > next_midnight:
            raise ValueError(
                "자정을 넘긴 활동은 날짜별로 나눠 기록해 주세요."
            )

        values.update(
            item_name=name,
            duration_minutes=duration,
            intensity=intensity
        )

    elif kind == "sleep":
        wake_clock = form["wake_time"].replace(
            second=0,
            microsecond=0,
            tzinfo=None
        )

        ended = datetime.combine(
            form["wake_date"],
            wake_clock
        )

        duration = int(
            (ended - started).total_seconds() // 60
        )

        if duration <= 0:
            raise ValueError(
                "일어난 시각은 잠든 시각보다 늦어야 해요."
            )

        if ended > now:
            raise ValueError(
                "일어난 시각은 현재보다 늦을 수 없어요."
            )

        values.update(
            item_name="수면",
            duration_minutes=duration
        )

    return values


# 선택한 기록 수정 화면
def show_lifestyle_editor(client, user_id, profile_id, row):
    kind = row["record_type"]

    if kind not in TYPE_LABELS:
        st.info("이 종류의 기록은 수정 화면을 지원하지 않아요.")
        return

    scope = f"{user_id}_{profile_id}"
    prefix = (
        f"lifestyle_edit_{scope}_{row['id']}_"
        f"{fingerprint(row)}"
    )

    now = datetime.now(ZoneInfo("Asia/Seoul"))
    original_day = date.fromisoformat(row["record_date"])

    original_clock = time.fromisoformat(
        row.get("record_time") or "00:00"
    )

    latest_day = (
        now.date() - timedelta(days=1)
        if kind == "no_activity"
        else now.date()
    )

    st.markdown("### ✏️ 선택한 기록 수정")
    st.caption(
        f"기록 종류: {TYPE_LABELS[kind]} · "
        "종류는 유지하고 내용을 수정해요. "
        "기존 혈당 기록과의 연결도 유지돼요."
    )

    form = {}

    with st.form(prefix):
        form["date"] = st.date_input(
            "잠든 날짜 수정"
            if kind == "sleep"
            else "기록 날짜 수정",
            value=original_day,
            max_value=max(original_day, latest_day)
        )

        if kind != "no_activity":
            form["time"] = st.time_input(
                "잠든 시간 수정"
                if kind == "sleep"
                else "시작·섭취 시간 수정",
                value=original_clock,
                step=60
            )

        if kind == "meal":
            form["name"] = st.text_input(
                "음식명·사료명 수정",
                value=row.get("item_name") or ""
            )

            slot = row.get("meal_slot") or "기타"

            form["meal_slot"] = st.selectbox(
                "식사 구분 수정",
                MEAL_SLOTS,
                index=(
                    MEAL_SLOTS.index(slot)
                    if slot in MEAL_SLOTS
                    else 4
                )
            )

            form["amount"] = st.number_input(
                "먹은 양 수정",
                min_value=0.0,
                value=float(row.get("amount") or 0),
                step=0.5
            )

            original_unit = row.get("amount_unit") or "g"

            units = (
                UNITS
                if original_unit in UNITS
                else UNITS + [original_unit]
            )

            form["unit"] = st.selectbox(
                "단위 수정",
                units,
                index=units.index(original_unit)
            )

        elif kind == "activity":
            form["name"] = st.text_input(
                "활동명 수정",
                value=row.get("item_name") or ""
            )

            original_duration = max(
                1,
                int(row.get("duration_minutes") or 1)
            )

            form["duration"] = st.number_input(
                "활동 시간 수정(분)",
                min_value=1,
                max_value=max(1440, original_duration),
                value=original_duration,
                step=1
            )

            intensity = row.get("intensity") or "보통"

            form["intensity"] = st.selectbox(
                "활동 강도 수정",
                INTENSITIES,
                index=(
                    INTENSITIES.index(intensity)
                    if intensity in INTENSITIES
                    else 1
                )
            )

        elif kind == "sleep":
            original_end = (
                datetime.combine(original_day, original_clock)
                + timedelta(
                    minutes=int(row.get("duration_minutes") or 1)
                )
            )

            form["wake_date"] = st.date_input(
                "일어난 날짜 수정",
                value=original_end.date(),
                max_value=max(
                    original_end.date(),
                    now.date()
                )
            )

            form["wake_time"] = st.time_input(
                "일어난 시간 수정",
                value=original_end.time(),
                step=60
            )

        else:
            form["confirmed"] = st.checkbox(
                "수정한 날짜에 따로 기록할 운동·산책 활동이 "
                "없었음을 확인했어요."
            )

        form["memo"] = st.text_area(
            "보충 메모 수정",
            value=row.get("memo") or ""
        )

        save = st.form_submit_button(
            "💾 수정 내용 저장",
            use_container_width=True
        )

    if not save:
        return

    try:
        values = build_edit_values(
            kind,
            form,
            datetime.now(ZoneInfo("Asia/Seoul"))
        )

        check_activity_conflict(
            client,
            user_id,
            profile_id,
            values["record_date"],
            kind
        )

        result = (
            client.table("lifestyle_records")
            .update(
                values,
                returning="representation"
            )
            .eq("user_id", user_id)
            .eq("profile_id", profile_id)
            .eq("id", row["id"])
            .eq("record_type", kind)
            .execute()
        )

        if not result.data:
            raise ValueError(
                "변경된 기록이 없어요. "
                "목록을 다시 불러와 주세요."
            )

    except ValueError as error:
        st.warning(str(error))

    except Exception as error:
        if getattr(error, "code", None) == "23505":
            st.warning(
                "이 날짜에는 이미 활동 없음 확인이 있어요. "
                "날짜를 확인해 주세요."
            )

        else:
            show_error(
                "수정 결과를 확인하지 못했어요. "
                "목록을 다시 불러와 주세요.",
                error
            )

    else:
        # 수정 전 기록을 담은 미리보기·분석 결과 초기화
        st.session_state.pop(
            f"care_record_context_{scope}",
            None
        )
        st.session_state.pop(
            f"record_ai_result_{scope}",
            None
        )

        st.session_state.lifestyle_notice = (
            user_id,
            profile_id,
            "선택한 기록을 수정했어요."
        )

        st.rerun()


st.set_page_config(
    page_title="식사·활동 기록 | 당당케어",
    page_icon="📝",
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


# 페이지 메뉴
st.sidebar.title("🩸 당당케어")

st.sidebar.page_link(
    "pages/home.py",
    label="우리집 케어 홈",
    icon="🏠"
)

st.sidebar.page_link(
    "pages/record.py",
    label="혈당 기록하기",
    icon="🩸"
)

st.sidebar.page_link(
    "pages/history.py",
    label="기록 확인·수정",
    icon="📈"
)

st.sidebar.page_link(
    "pages/lifestyle.py",
    label="식사·활동 기록",
    icon="📝"
)

st.sidebar.page_link(
    "pages/meal.py",
    label="냉장고 식단 추천",
    icon="🍽️"
)

st.sidebar.page_link(
    "pages/explore.py",
    label="내 기록 탐구실",
    icon="🔍"
)

st.sidebar.page_link(
    "pages/visit.py",
    label="진료 준비 노트",
    icon="🏥"
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

except Exception as error:
    show_error(
        "관리 대상을 불러오지 못했어요.",
        error
    )
    st.stop()

if not profiles:
    st.info(
        "먼저 혈당 기록하기에서 관리 대상을 등록해 주세요."
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
            key=f"lifestyle_profile_{user.id}_{item['id']}",
            type="primary" if active else "secondary",
            use_container_width=True
        ):
            st.session_state.active_profile = item["id"]
            st.rerun()


profile_id = st.session_state.active_profile
profile = profile_map[profile_id]
scope = f"{user.id}_{profile_id}"

now = datetime.now(ZoneInfo("Asia/Seoul"))
today = now.date()
clock = now.time().replace(second=0, microsecond=0)

st.title("📝 식사·활동 기록")
st.caption(
    "실제로 먹은 음식과 활동을 날짜·시간·양으로 기록해요. "
    "입력하지 않은 항목은 ‘없음’으로 판단하지 않아요."
)

st.subheader(f"{profile['name']}의 식사·활동")

notice = st.session_state.pop("lifestyle_notice", None)

if notice and notice[:2] == (user.id, profile_id):
    st.success(notice[2])


# 입력 종류 선택
selected_type = st.radio(
    "무엇을 기록할까요?",
    list(TYPES),
    horizontal=True,
    key=f"lifestyle_type_{scope}"
)

record_type = TYPES[selected_type]
is_pet = profile["profile_type"] == "반려동물"

food_count = 1
activity_name = None

if record_type == "meal":
    st.caption(
        "같은 식사에서 먹은 음식을 음식별로 입력해요. "
        "섭취량은 실제 먹은 양을 적어 주세요."
    )

    food_count = st.number_input(
        "입력할 음식 개수",
        min_value=1,
        max_value=10,
        value=1,
        step=1,
        key=f"food_count_{scope}"
    )

elif record_type == "activity":
    activities = (
        ["산책", "실내 놀이", "달리기", "기타"]
        if is_pet
        else [
            "걷기", "달리기", "자전거",
            "근력 운동", "수영", "기타"
        ]
    )

    activity_name = st.selectbox(
        "활동 종류",
        activities,
        key=f"activity_kind_{scope}"
    )

    st.caption(
        "시작 시각과 지속 시간을 입력해요. "
        "자정을 넘긴 활동은 날짜별로 나눠 기록해 주세요."
    )

elif record_type == "sleep":
    st.caption(
        "잠든 날짜·시간과 일어난 날짜·시간을 입력해요. "
        "기록 날짜는 잠들기 시작한 날짜로 저장돼요."
    )

else:
    st.info(
        "운동·산책 등 따로 기록할 활동이 없었던 날을 확인해요. "
        "하루가 끝난 어제 이전 날짜만 선택할 수 있어요."
    )


# 저장 성공 후 입력 양식을 새로 만드는 번호
revision_key = f"lifestyle_form_revision_{scope}"
revision = st.session_state.get(revision_key, 0)

form_key = (
    f"lifestyle_form_{scope}_{record_type}_{revision}"
)


# 기록 입력
with st.form(form_key):
    default_date = (
        today - timedelta(days=1)
        if record_type in ["sleep", "no_activity"]
        else today
    )

    latest_date = (
        today - timedelta(days=1)
        if record_type == "no_activity"
        else today
    )

    record_date = st.date_input(
        "잠든 날짜"
        if record_type == "sleep"
        else "기록 날짜",
        value=default_date,
        max_value=latest_date
    )

    record_time = None

    if record_type != "no_activity":
        record_time = st.time_input(
            "잠든 시간"
            if record_type == "sleep"
            else "시작·섭취 시간",
            value=(
                time(23, 0)
                if record_type == "sleep"
                else clock
            ),
            step=60
        )

    foods = []
    meal_slot = None
    duration = None
    intensity = None
    custom_activity = ""
    wake_date = None
    wake_time = None
    confirmed = False

    if record_type == "meal":
        meal_slot = st.selectbox(
            "식사 구분",
            MEAL_SLOTS
        )

        for index in range(int(food_count)):
            st.markdown(f"**음식 {index + 1}**")

            c1, c2, c3 = st.columns([2, 1, 1])

            food_name = c1.text_input(
                "음식명·사료명",
                key=f"{form_key}_food_{index}",
                placeholder="예: 현미밥 또는 사료 제품명"
            )

            amount = c2.number_input(
                "먹은 양",
                min_value=0.0,
                value=0.0,
                step=0.5,
                key=f"{form_key}_amount_{index}"
            )

            unit = c3.selectbox(
                "단위",
                UNITS,
                key=f"{form_key}_unit_{index}"
            )

            foods.append((food_name, amount, unit))

        st.caption(
            "같은 ‘컵·공기·개’라도 실제 양은 다를 수 있어요. "
            "무게를 잴 수 있으면 g으로 기록해 주세요."
        )

    elif record_type == "activity":
        if activity_name == "기타":
            custom_activity = st.text_input("활동명")

        duration = st.number_input(
            "활동 시간(분)",
            min_value=1,
            max_value=1440,
            value=20,
            step=1
        )

        intensity = st.selectbox(
            "느낀 활동 강도",
            INTENSITIES
        )

    elif record_type == "sleep":
        wake_date = st.date_input(
            "일어난 날짜",
            value=today,
            max_value=today
        )

        wake_time = st.time_input(
            "일어난 시간",
            value=time(7, 0),
            step=60
        )

    else:
        confirmed = st.checkbox(
            "이 날짜에 따로 기록할 운동·산책 활동이 "
            "없었음을 확인했어요."
        )

    memo = st.text_area(
        "보충 메모(선택)",
        placeholder="추가로 남길 내용이 있을 때만 입력해 주세요."
    )

    submitted = st.form_submit_button(
        "💾 기록 저장",
        use_container_width=True
    )


# 입력 검증과 저장
if submitted:
    try:
        values = {
            "user_id": user.id,
            "profile_id": profile_id,
            "record_type": record_type,
            "record_date": record_date.isoformat(),
            "record_time": (
                record_time.strftime("%H:%M")
                if record_time is not None
                else None
            ),
            "memo": memo.strip()
        }

        started = None

        if record_time is not None:
            started = datetime.combine(
                record_date,
                record_time
            )

            if started > now.replace(tzinfo=None):
                raise ValueError(
                    "아직 지나지 않은 시각은 기록할 수 없어요."
                )

        if record_type == "meal":
            if any(
                not name.strip() or amount <= 0
                for name, amount, unit in foods
            ):
                raise ValueError(
                    "모든 음식의 이름과 "
                    "0보다 큰 섭취량을 입력해 주세요."
                )

            payload = [
                {
                    **values,
                    "item_name": name.strip(),
                    "meal_slot": meal_slot,
                    "amount": amount,
                    "amount_unit": unit
                }
                for name, amount, unit in foods
            ]

        elif record_type == "activity":
            name = (
                custom_activity.strip()
                if activity_name == "기타"
                else activity_name
            )

            if not name:
                raise ValueError("활동명을 입력해 주세요.")

            ended = started + timedelta(
                minutes=int(duration)
            )

            if ended > now.replace(tzinfo=None):
                raise ValueError(
                    "활동이 끝난 뒤 실제 활동 시간을 기록해 주세요."
                )

            next_midnight = datetime.combine(
                record_date + timedelta(days=1),
                time(0, 0)
            )

            if ended > next_midnight:
                raise ValueError(
                    "자정을 넘긴 활동은 날짜별로 나눠 기록해 주세요."
                )

            payload = [{
                **values,
                "item_name": name,
                "duration_minutes": int(duration),
                "intensity": intensity
            }]

        elif record_type == "sleep":
            ended = datetime.combine(
                wake_date,
                wake_time
            )

            minutes = int(
                (ended - started).total_seconds() // 60
            )

            if minutes <= 0:
                raise ValueError(
                    "일어난 시각은 잠든 시각보다 늦어야 해요."
                )

            if ended > now.replace(tzinfo=None):
                raise ValueError(
                    "일어난 시각이 현재보다 늦게 입력되어 있어요."
                )

            payload = [{
                **values,
                "item_name": "수면",
                "duration_minutes": minutes
            }]

        else:
            if not confirmed:
                raise ValueError(
                    "활동 없음 확인란을 체크해 주세요."
                )

            if record_date >= today:
                raise ValueError(
                    "활동 없음은 하루가 끝난 날짜에만 기록해 주세요."
                )

            payload = [{
                **values,
                "item_name": "활동 없음 확인"
            }]

        check_activity_conflict(
            client,
            user.id,
            profile_id,
            record_date.isoformat(),
            record_type
        )

        client.table("lifestyle_records").insert(
            payload,
            returning="minimal"
        ).execute()

    except ValueError as error:
        st.warning(str(error))

    except Exception as error:
        if getattr(error, "code", None) == "23505":
            st.warning(
                "이미 같은 날짜의 활동 없음 확인이 저장되어 있어요. "
                "아래 목록을 확인해 주세요."
            )

        else:
            show_error(
                "저장 결과를 확인하지 못했어요. "
                "중복 저장 전에 아래 기록 목록을 확인해 주세요.",
                error
            )

    else:
        st.session_state[revision_key] = revision + 1

        st.session_state.lifestyle_notice = (
            user.id,
            profile_id,
            f"{len(payload)}건의 기록을 저장했어요."
        )

        st.rerun()


# 저장 기록 조회
st.divider()
st.subheader("📋 저장한 식사·활동 기록")

c1, c2 = st.columns(2)

start = c1.date_input(
    "조회 시작일",
    value=today - timedelta(days=6),
    key=f"lifestyle_start_{scope}"
)

end = c2.date_input(
    "조회 종료일",
    value=today,
    key=f"lifestyle_end_{scope}"
)

kind_filter = st.selectbox(
    "기록 종류",
    ["전체"] + list(TYPE_LABELS.values()),
    key=f"lifestyle_filter_{scope}"
)

if start > end:
    st.warning("조회 시작일은 종료일보다 늦을 수 없어요.")
    st.stop()

try:
    query = (
        base_query(client, user.id, profile_id)
        .gte("record_date", start.isoformat())
        .lte("record_date", end.isoformat())
    )

    if kind_filter != "전체":
        filter_code = next(
            code
            for code, label in TYPE_LABELS.items()
            if label == kind_filter
        )

        query = query.eq(
            "record_type",
            filter_code
        )

    rows = (
        query.order("record_date", desc=True)
        .order("record_time", desc=True)
        .order("id")
        .limit(1000)
        .execute()
        .data
    ) or []

except Exception as error:
    show_error(
        "기록을 불러오지 못했어요.",
        error
    )
    st.stop()

if not rows:
    st.info(
        "선택한 조건에 해당하는 기록이 없어요. "
        "기록이 없다는 것은 활동이나 식사가 없었다는 뜻은 아니에요."
    )
    st.stop()

st.caption(
    f"최신 기록 {len(rows)}건 표시 · 최대 1,000건. "
    "식사는 음식 한 종류당 한 행으로 표시해요. "
    "표에서 한 행을 선택하면 수정하거나 삭제할 수 있어요."
)

table = display_records(rows)

event = st.dataframe(
    table,
    hide_index=True,
    use_container_width=True,
    on_select="rerun",
    selection_mode="single-row",
    key=f"lifestyle_table_{scope}_{fingerprint(rows)}"
)

st.download_button(
    "📥 표시된 기록 CSV 다운로드",
    data=table.to_csv(index=False).encode("utf-8-sig"),
    file_name="lifestyle_records.csv",
    mime="text/csv",
    key=f"lifestyle_csv_{scope}"
)


# 선택한 기록 수정·삭제
positions = event["selection"]["rows"]

if positions and 0 <= positions[0] < len(rows):
    row = rows[positions[0]]

    st.markdown("### 선택한 기록")

    st.write(
        f"{row['record_date']} "
        f"{str(row.get('record_time') or '')[:5]} · "
        f"{TYPE_LABELS.get(row['record_type'], row['record_type'])} · "
        f"{row.get('item_name') or ''}"
    )

    show_lifestyle_editor(
        client=client,
        user_id=user.id,
        profile_id=profile_id,
        row=row
    )

    with st.form(
        f"lifestyle_delete_{scope}_{row['id']}_{fingerprint(row)}"
    ):
        st.warning(
            "선택한 한 행을 삭제해요. "
            "삭제한 기록은 앱에서 복구할 수 없어요."
        )

        confirm_delete = st.checkbox(
            "선택한 기록의 삭제를 확인했어요."
        )

        delete_clicked = st.form_submit_button(
            "🗑️ 선택한 기록 삭제"
        )

    if delete_clicked:
        if not confirm_delete:
            st.warning(
                "삭제 확인란을 먼저 체크해 주세요."
            )

        else:
            try:
                result = (
                    client.table("lifestyle_records")
                    .delete(returning="representation")
                    .eq("user_id", user.id)
                    .eq("profile_id", profile_id)
                    .eq("id", row["id"])
                    .execute()
                )

            except Exception as error:
                show_error(
                    "삭제 결과를 확인하지 못했어요. "
                    "목록을 새로 확인해 주세요.",
                    error
                )

            else:
                if result.data:
                    st.session_state.lifestyle_notice = (
                        user.id,
                        profile_id,
                        "선택한 기록을 삭제했어요."
                    )
                    st.rerun()

                else:
                    st.warning(
                        "삭제된 기록이 없어요. "
                        "목록을 새로 확인해 주세요."
                    )
