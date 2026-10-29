from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import streamlit as st


TYPE_LABELS = {
    "meal": "식사",
    "activity": "운동·산책",
    "sleep": "수면",
    "no_activity": "활동 없음 확인"
}


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
                "기록이 10,000건을 넘었어. "
                "일부만 불러오지 않도록 조회를 중단했어. "
                "기간을 줄여 줘."
            )

        offset += len(batch)


def load_record_context(
    client,
    user_id,
    profile_id,
    start,
    end
):
    # 로그인 사용자의 관리 대상인지 확인
    profiles = (
        client.table("care_profiles")
        .select("id,profile_type,animal_type")
        .eq("user_id", user_id)
        .eq("id", profile_id)
        .limit(1)
        .execute()
        .data
    ) or []

    if not profiles:
        raise ValueError(
            "선택한 관리 대상을 확인할 수 없어. "
            "관리 대상 목록을 다시 불러와 줘."
        )

    profile = profiles[0]

    blood_rows = fetch_all(
        lambda: (
            client.table("blood_glucose")
            .select(
                "record_id,measure_date,measure_time,"
                "glucose,meal,insulin"
            )
            .eq("user_id", user_id)
            .eq("profile_id", profile_id)
            .gte("measure_date", start.isoformat())
            .lte("measure_date", end.isoformat())
            .order("measure_date")
            .order("measure_time")
            .order("record_id")
        )
    )

    lifestyle_rows = fetch_all(
        lambda: (
            client.table("lifestyle_records")
            .select(
                "id,record_type,record_date,record_time,"
                "item_name,meal_slot,amount,amount_unit,"
                "duration_minutes,intensity"
            )
            .eq("user_id", user_id)
            .eq("profile_id", profile_id)
            .gte("record_date", start.isoformat())
            .lte("record_date", end.isoformat())
            .order("record_date")
            .order("record_time")
            .order("id")
        )
    )

    # 정렬·조회에 사용한 ID는 미리보기 데이터에서 제외
    blood = [
        {
            "date": row["measure_date"],
            "time": str(row["measure_time"]),
            "glucose_mg_dl": row["glucose"],
            "measurement_context": row.get("meal"),
            "insulin_units": row.get("insulin")
        }
        for row in blood_rows
    ]

    lifestyle = [
        {
            "date": row["record_date"],
            "time": (
                str(row["record_time"])
                if row.get("record_time") is not None
                else None
            ),
            "kind": row["record_type"],
            "item_name": row.get("item_name"),
            "meal_slot": row.get("meal_slot"),
            "amount": row.get("amount"),
            "amount_unit": row.get("amount_unit"),
            "duration_minutes": row.get("duration_minutes"),
            "intensity": row.get("intensity")
        }
        for row in lifestyle_rows
    ]

    subject = {
        "profile_type": profile["profile_type"]
    }

    if profile["profile_type"] == "반려동물":
        subject["animal_type"] = profile.get("animal_type")

    return {
        "subject": subject,
        "period": {
            "start": start.isoformat(),
            "end": end.isoformat()
        },
        "blood_glucose": blood,
        "lifestyle": lifestyle
    }


def blood_table(rows):
    return [
        {
            "측정 날짜": row["date"],
            "측정 시간": row["time"][:5],
            "혈당 (mg/dL)": row["glucose_mg_dl"],
            "측정 시점": (
                row.get("measurement_context") or "미입력"
            ),
            "인슐린 (단위)": row.get("insulin_units")
        }
        for row in rows
    ]


def lifestyle_table(rows):
    result = []

    for row in rows:
        amount = row.get("amount")

        result.append({
            "날짜": row["date"],
            "시간": (
                str(row["time"])[:5]
                if row.get("time")
                else "하루 확인"
            ),
            "종류": TYPE_LABELS.get(
                row["kind"],
                row["kind"]
            ),
            "음식·활동": row.get("item_name") or "",
            "식사 구분": row.get("meal_slot") or "",
            "섭취량": (
                f"{amount} {row.get('amount_unit') or ''}"
                if amount is not None
                else ""
            ),
            "지속 시간(분)": row.get("duration_minutes"),
            "강도": row.get("intensity") or ""
        })

    return result


def show_record_context(client, user_id, profile_id):
    scope = f"{user_id}_{profile_id}"
    snapshot_key = f"care_record_context_{scope}"
    today = datetime.now(ZoneInfo("Asia/Seoul")).date()

    st.subheader("📋 내 기록 미리보기")

    st.caption(
        "선택한 관리 대상의 혈당·식사·활동 기록을 불러와. "
        "이번 단계에서는 앱 안에서만 확인하며 "
        "AI로 전송하지 않아."
    )

    with st.form(f"record_context_form_{scope}"):
        c1, c2 = st.columns(2)

        start = c1.date_input(
            "살펴볼 기록 시작일",
            value=today - timedelta(days=6),
            max_value=today
        )

        end = c2.date_input(
            "살펴볼 기록 종료일",
            value=today,
            max_value=today
        )

        st.caption(
            "최근 7일이 기본이고, 한 번에 최대 90일까지 조회해."
        )

        load_clicked = st.form_submit_button(
            "📋 이 기간의 기록 불러오기",
            use_container_width=True
        )

    if load_clicked:
        if start > end:
            st.warning("시작일은 종료일보다 늦을 수 없어.")

        elif (end - start).days > 89:
            st.warning("조회 기간은 최대 90일로 설정해 줘.")

        else:
            # 새 조회가 실패하면 이전 기록과 혼동하지 않도록 초기화
            st.session_state.pop(snapshot_key, None)

            try:
                with st.spinner("선택한 기간의 기록을 불러오고 있어…"):
                    payload = load_record_context(
                        client=client,
                        user_id=user_id,
                        profile_id=profile_id,
                        start=start,
                        end=end
                    )

            except ValueError as error:
                st.warning(str(error))
                return None

            except Exception as error:
                show_error(
                    "기록을 불러오지 못했어. "
                    "잠시 후 다시 시도해 줘.",
                    error
                )
                return None

            else:
                st.session_state[snapshot_key] = {
                    "loaded_at": datetime.now(
                        ZoneInfo("Asia/Seoul")
                    ).strftime("%Y-%m-%d %H:%M"),
                    "payload": payload
                }

                st.success("기록을 불러왔어.")

    snapshot = st.session_state.get(snapshot_key)

    if not snapshot:
        st.info("기간을 선택하고 기록 불러오기를 눌러 줘.")
        return None

    payload = snapshot["payload"]
    period = payload["period"]
    blood = payload["blood_glucose"]
    lifestyle = payload["lifestyle"]

    st.caption(
        f"불러온 기간: {period['start']} ~ {period['end']} · "
        f"조회 시각: {snapshot['loaded_at']}"
    )

    st.caption(
        "날짜를 바꾸거나 다른 페이지에서 기록을 수정했다면 "
        "‘이 기간의 기록 불러오기’를 다시 눌러 줘."
    )

    c1, c2, c3 = st.columns(3)

    c1.metric("혈당 기록", f"{len(blood)}건")

    c2.metric(
        "식사 기록",
        f"{sum(row['kind'] == 'meal' for row in lifestyle)}건"
    )

    c3.metric(
        "운동·산책 기록",
        f"{sum(row['kind'] == 'activity' for row in lifestyle)}건"
    )

    blood_tab, lifestyle_tab = st.tabs([
        "🩸 혈당 기록",
        "📝 식사·활동·수면 기록"
    ])

    with blood_tab:
        if blood:
            st.dataframe(
                blood_table(blood),
                hide_index=True,
                use_container_width=True
            )

        else:
            st.info("이 기간에 저장된 혈당 기록이 없어.")

    with lifestyle_tab:
        if lifestyle:
            st.dataframe(
                lifestyle_table(lifestyle),
                hide_index=True,
                use_container_width=True
            )

        else:
            st.info("이 기간에 저장된 식사·활동 기록이 없어.")

        st.caption(
            "식사는 음식 한 종류당 한 행이야. "
            "수면은 잠들기 시작한 날짜를 기준으로 불러와. "
            "기록이 없다는 것은 식사나 활동을 하지 않았다는 뜻이 아니야."
        )

    st.caption(
        "이 미리보기에는 이름·이메일·계정 ID·기록 ID·"
        "자유 메모 항목을 포함하지 않아. "
        "혈당 등 건강 관련 내용은 여전히 민감한 정보야."
    )

    if not blood and not lifestyle:
        return None

    return payload
