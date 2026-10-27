from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import streamlit as st


LIFESTYLE_FIELDS = (
    "id,record_date,record_time,record_type,"
    "item_name,meal_slot,amount,amount_unit,"
    "duration_minutes,intensity,memo"
)


def show_error(message, error):
    st.error(message)
    st.caption(
        f"오류 종류: {type(error).__name__} / "
        f"오류 코드: {getattr(error, 'code', None) or '없음'}"
    )


def lifestyle_label(row):
    clock = str(row.get("record_time") or "")[:5]
    name = row.get("item_name") or "이름 미입력"

    kind = {
        "meal": "식사",
        "activity": "운동·산책",
        "sleep": "수면",
        "no_activity": "활동 없음"
    }.get(row["record_type"], row["record_type"])

    return (
        f"{row['record_date']} {clock} · "
        f"{kind} · {name} · {str(row['id'])[:8]}"
    )


def lifestyle_table(rows):
    result = []

    for row in rows:
        amount = row.get("amount")
        duration = row.get("duration_minutes")

        if row["record_type"] == "meal":
            details = row.get("meal_slot") or "기타"

            if amount is not None:
                details += (
                    f" · {float(amount):g} "
                    f"{row.get('amount_unit') or ''}"
                )

        else:
            details = (
                f"{duration}분"
                if duration is not None
                else ""
            )

            if row.get("intensity"):
                details += f" · 강도 {row['intensity']}"

        result.append({
            "날짜": row["record_date"],
            "시간": str(row.get("record_time") or "")[:5],
            "종류": {
                "meal": "식사",
                "activity": "운동·산책",
                "sleep": "수면",
                "no_activity": "활동 없음"
            }.get(row["record_type"], row["record_type"]),
            "음식·활동": row.get("item_name") or "",
            "상세": details,
            "메모": row.get("memo") or ""
        })

    return result


def load_link_ids(client, user_id, profile_id, glucose_id):
    result = []
    offset = 0

    while True:
        batch = (
            client.table("glucose_lifestyle_links")
            .select("lifestyle_record_id")
            .eq("user_id", user_id)
            .eq("profile_id", profile_id)
            .eq("glucose_record_id", glucose_id)
            .order("lifestyle_record_id")
            .range(offset, offset + 499)
            .execute()
            .data
        ) or []

        if not batch:
            return result

        result.extend(
            str(row["lifestyle_record_id"])
            for row in batch
        )

        if len(result) > 10000:
            raise ValueError("연결된 기록이 너무 많아 조회를 중단했어요.")

        offset += len(batch)


def load_linked_records(client, user_id, profile_id, linked_ids):
    rows = []

    for offset in range(0, len(linked_ids), 100):
        batch_ids = linked_ids[offset:offset + 100]

        batch = (
            client.table("lifestyle_records")
            .select(LIFESTYLE_FIELDS)
            .eq("user_id", user_id)
            .eq("profile_id", profile_id)
            .in_("id", batch_ids)
            .execute()
            .data
        ) or []

        rows.extend(batch)

    return sorted(
        rows,
        key=lambda row: (
            row["record_date"],
            str(row.get("record_time") or ""),
            str(row["id"])
        )
    )


def show_record_links(client, user_id, profile_id):
    scope = f"{user_id}_{profile_id}"
    today = datetime.now(ZoneInfo("Asia/Seoul")).date()
    notice_key = f"record_links_notice_{scope}"

    st.divider()
    st.subheader("🔗 혈당과 식사·활동 연결")
    st.caption(
        "혈당 기록을 선택한 뒤 관련된 식사나 운동 기록을 연결해요. "
        "연결은 사용자가 선택한 관계이며, "
        "혈당 변화의 원인을 자동으로 판단하지 않아요."
    )

    notice = st.session_state.pop(notice_key, None)

    if notice:
        st.success(notice)

    c1, c2 = st.columns(2)

    start = c1.date_input(
        "연결할 혈당 조회 시작일",
        value=today - timedelta(days=29),
        max_value=today,
        key=f"link_blood_start_{scope}"
    )

    end = c2.date_input(
        "연결할 혈당 조회 종료일",
        value=today,
        max_value=today,
        key=f"link_blood_end_{scope}"
    )

    if start > end:
        st.warning("조회 시작일은 종료일보다 늦을 수 없어요.")
        return

    try:
        blood_rows = (
            client.table("blood_glucose")
            .select(
                "record_id,measure_date,measure_time,glucose,meal"
            )
            .eq("user_id", user_id)
            .eq("profile_id", profile_id)
            .gte("measure_date", start.isoformat())
            .lte("measure_date", end.isoformat())
            .order("measure_date", desc=True)
            .order("measure_time", desc=True)
            .order("record_id")
            .limit(200)
            .execute()
            .data
        ) or []

    except Exception as error:
        show_error("연결할 혈당 기록을 불러오지 못했어요.", error)
        return

    if not blood_rows:
        st.info(
            "선택한 기간에 혈당 기록이 없어요. "
            "혈당을 저장하거나 조회 기간을 바꿔 주세요."
        )
        return

    st.caption(
        "선택한 기간의 최신 혈당 기록을 최대 200건 표시해요. "
        "찾는 기록이 없다면 조회 기간을 좁혀 주세요."
    )

    blood_map = {
        str(row["record_id"]): row
        for row in blood_rows
    }

    def blood_label(record_id):
        row = blood_map[record_id]

        return (
            f"{row['measure_date']} "
            f"{str(row['measure_time'])[:5]} · "
            f"{row['glucose']} mg/dL · "
            f"{row.get('meal') or '미입력'} · "
            f"{record_id[:8]}"
        )

    selected_key = st.selectbox(
        "식사·활동을 연결할 혈당 기록",
        list(blood_map),
        format_func=blood_label,
        key=f"link_blood_choice_{scope}"
    )

    blood = blood_map[selected_key]
    glucose_id = blood["record_id"]
    record_scope = f"{scope}_{selected_key}"

    try:
        linked_ids = load_link_ids(
            client, user_id, profile_id, glucose_id
        )

        linked_rows = load_linked_records(
            client, user_id, profile_id, linked_ids
        )

    except Exception as error:
        show_error("현재 연결된 기록을 불러오지 못했어요.", error)
        return

    st.markdown("**현재 연결된 식사·활동**")

    if linked_rows:
        st.dataframe(
            lifestyle_table(linked_rows),
            hide_index=True,
            use_container_width=True
        )

    else:
        st.caption("아직 연결된 식사·활동 기록이 없어요.")

    # 연결할 생활 기록 찾기
    blood_day = min(
        date.fromisoformat(blood["measure_date"]),
        today
    )

    c1, c2 = st.columns(2)

    activity_start = c1.date_input(
        "식사·활동 조회 시작일",
        value=blood_day - timedelta(days=1),
        max_value=today,
        key=f"link_activity_start_{record_scope}"
    )

    activity_end = c2.date_input(
        "식사·활동 조회 종료일",
        value=blood_day,
        max_value=today,
        key=f"link_activity_end_{record_scope}"
    )

    if activity_start > activity_end:
        st.warning("식사·활동 조회 시작일을 확인해 주세요.")
        return

    try:
        candidates = (
            client.table("lifestyle_records")
            .select(LIFESTYLE_FIELDS)
            .eq("user_id", user_id)
            .eq("profile_id", profile_id)
            .in_("record_type", ["meal", "activity"])
            .gte("record_date", activity_start.isoformat())
            .lte("record_date", activity_end.isoformat())
            .order("record_date", desc=True)
            .order("record_time", desc=True)
            .order("id")
            .limit(500)
            .execute()
            .data
        ) or []

    except Exception as error:
        show_error("식사·활동 목록을 불러오지 못했어요.", error)
        return

    linked_set = set(linked_ids)

    available = {
        str(row["id"]): row
        for row in candidates
        if str(row["id"]) not in linked_set
    }

    st.caption(
        "같은 관리 대상의 식사·운동 기록만 선택할 수 있어요. "
        "선택한 기간의 최신 기록을 최대 500건 표시하며, "
        "이미 연결된 기록은 추가 목록에서 제외해요."
    )

    if available:
        with st.form(f"link_add_form_{record_scope}"):
            selected_ids = st.multiselect(
                "추가로 연결할 식사·활동",
                list(available),
                format_func=lambda item: lifestyle_label(
                    available[item]
                )
            )

            add_clicked = st.form_submit_button(
                "🔗 선택한 기록 연결",
                use_container_width=True
            )

        if add_clicked:
            if not selected_ids:
                st.warning("연결할 기록을 선택해 주세요.")

            elif len(linked_set | set(selected_ids)) > 100:
                st.warning(
                    "혈당 기록 한 건에는 식사·활동을 "
                    "최대 100건까지 연결할 수 있어요."
                )

            else:
                payload = [
                    {
                        "glucose_record_id": glucose_id,
                        "lifestyle_record_id": item,
                        "user_id": user_id,
                        "profile_id": profile_id
                    }
                    for item in selected_ids
                    if item in available
                ]

                try:
                    client.table("glucose_lifestyle_links").insert(
                        payload,
                        returning="minimal"
                    ).execute()

                except Exception as error:
                    if getattr(error, "code", None) == "23505":
                        st.warning(
                            "이미 연결된 기록이 포함되어 있어요. "
                            "목록을 다시 불러온 뒤 선택해 주세요."
                        )

                    else:
                        show_error(
                            "연결 결과를 확인하지 못했어요. "
                            "현재 연결 목록을 다시 확인해 주세요.",
                            error
                        )

                else:
                    st.session_state[notice_key] = (
                        f"식사·활동 기록 {len(payload)}건을 연결했어요."
                    )
                    st.rerun()

    else:
        st.info(
            "이 기간에는 새로 연결할 식사·운동 기록이 없어요. "
            "조회 기간을 바꾸거나 식사·활동 기록을 추가해 주세요."
        )

    # 연결 정보만 삭제
    if linked_rows:
        linked_map = {
            str(row["id"]): row
            for row in linked_rows
        }

        with st.form(f"link_remove_form_{record_scope}"):
            remove_ids = st.multiselect(
                "연결을 해제할 식사·활동",
                list(linked_map),
                format_func=lambda item: lifestyle_label(
                    linked_map[item]
                )
            )

            st.caption(
                "연결을 해제해도 원래 혈당과 식사·활동 기록은 유지돼요."
            )

            remove_clicked = st.form_submit_button(
                "연결 해제",
                use_container_width=True
            )

        if remove_clicked:
            if not remove_ids:
                st.warning("연결을 해제할 기록을 선택해 주세요.")

            else:
                try:
                    result = (
                        client.table("glucose_lifestyle_links")
                        .delete(returning="representation")
                        .eq("user_id", user_id)
                        .eq("profile_id", profile_id)
                        .eq("glucose_record_id", glucose_id)
                        .in_("lifestyle_record_id", remove_ids)
                        .execute()
                    )

                except Exception as error:
                    show_error(
                        "연결 해제 결과를 확인하지 못했어요.",
                        error
                    )

                else:
                    count = len(result.data or [])

                    st.session_state[notice_key] = (
                        f"연결 {count}건을 해제했어요. "
                        "원래 기록은 유지돼요."
                    )
                    st.rerun()
