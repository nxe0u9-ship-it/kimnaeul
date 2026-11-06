st.subheader("📋 저장한 식사·활동 기록")

c1, c2 = st.columns(2)

start = c1.date_input(
    "조회 시작일",
    value=today - timedelta(days=6),
    key=f"lifestyle_start_{ui_scope}",
)
end = c2.date_input(
    "조회 종료일",
    value=today,
    key=f"lifestyle_end_{ui_scope}",
)

kind_filter = st.selectbox(
    "요약·그래프 기록 종류",
    ["전체"] + list(TYPE_LABELS.values()),
    key=f"lifestyle_filter_{ui_scope}",
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
        query = query.eq("record_type", filter_code)

    rows = (
        query.order("record_date", desc=True)
        .order("record_time", desc=True)
        .order("id")
        .limit(1000)
        .execute()
        .data
    ) or []

except Exception as error:
    show_error("기록을 불러오지 못했어요.", error)
    st.stop()

if not rows:
    st.info(
        "선택한 조회 기간·종류에 해당하는 "
        "요약·그래프 기록이 없어요. "
        "아래 상세 기록 검색은 별도로 사용할 수 있어요."
    )

else:
    show_record_summary(rows, start, end, kind_filter)

    if kind_filter in ["전체", "식사"]:
        show_meal_calendar(
            rows, start, end, ui_scope
        )

    if kind_filter in ["전체", "운동·산책", "활동 없음"]:
        show_activity_chart(
            rows, start, end, ui_scope
        )

    if kind_filter in ["전체", "수면"]:
        show_sleep_chart(
            rows, start, end, ui_scope
        )

st.markdown("### 📋 상세 기록 확인·수정")

st.caption(
    "위에서 정한 조회 기간 안에서 상세 기록을 찾아요. "
    "아래 종류 선택은 상세 표에만 적용돼요. "
    "‘운동’에는 걷기·달리기·산책 등 "
    "모든 운동·산책 기록이 포함돼요."
)

detail_types = {
    "전체": None,
    "식사": "meal",
    "수면": "sleep",
    "운동": "activity",
}

detail_kind = st.radio(
    "상세 기록 종류",
    list(detail_types),
    horizontal=True,
    key=f"lifestyle_detail_kind_{ui_scope}",
)

use_detail_date = st.checkbox(
    "특정 날짜로 검색",
    key=f"lifestyle_detail_use_date_{ui_scope}",
)

picked_detail_date = st.date_input(
    "찾을 날짜",
    value=end,
    min_value=start,
    max_value=end,
    disabled=not use_detail_date,
    key=(
        f"lifestyle_detail_date_"
        f"{ui_scope}_{start}_{end}"
    ),
)

detail_date = (
    picked_detail_date
    if use_detail_date
    else None
)

if detail_kind == "수면":
    st.caption(
        "수면 기록은 잠든 날짜를 기준으로 검색해요."
    )

detail_scope = (
    f"{ui_scope}_{start}_{end}_"
    f"{detail_kind}_{detail_date or 'all'}"
)

detail_table_kind = (
    "운동·산책"
    if detail_kind == "운동"
    else detail_kind
)

try:
    detail_query = (
        base_query(client, user.id, profile_id)
        .gte("record_date", start.isoformat())
        .lte("record_date", end.isoformat())
    )

    if detail_types[detail_kind] is not None:
        detail_query = detail_query.eq(
            "record_type",
            detail_types[detail_kind],
        )

    if detail_date is not None:
        detail_query = detail_query.eq(
            "record_date",
            detail_date.isoformat(),
        )

    detail_rows = (
        detail_query.order("record_date", desc=True)
        .order("record_time", desc=True)
        .order("id")
        .limit(1000)
        .execute()
        .data
    ) or []

except Exception as error:
    show_error(
        "상세 기록 검색 결과를 불러오지 못했어요.",
        error,
    )
    st.stop()

if not detail_rows:
    st.info(
        "선택한 종류와 날짜에 맞는 상세 기록이 없어요. "
        "종류·날짜 또는 위쪽 조회 기간을 바꿔 주세요."
    )
    st.stop()

if detail_date is not None:
    st.caption(
        f"검색 조건: {detail_kind} · "
        f"{detail_date:%Y-%m-%d}"
    )

else:
    st.caption(
        f"검색 조건: {detail_kind} · "
        f"{start:%Y-%m-%d} ~ {end:%Y-%m-%d}"
    )

st.caption(
    f"최신 기록 {len(detail_rows)}건 표시 · 최대 1,000건. "
    "식사는 음식 한 종류당 한 행으로 표시해요. "
    "수정하거나 삭제할 기록은 표 맨 왼쪽, 날짜 앞에 있는 "
    "네모 선택 칸을 눌러 체크해 주세요. "
    "체크하면 표 아래에 해당 기록의 전체 메모와 "
    "수정·삭제 화면이 나타나요."
)

table = display_records(
    detail_rows,
    detail_table_kind,
)

st.caption(
    "행 색상: 🍽️ 식사 — 연한 주황 · "
    "🏃 운동·산책 — 연한 초록 · "
    "😴 수면 — 연한 보라 · "
    "📅 활동 없음 — 연한 회색"
)

event = st.dataframe(
    style_record_table(table, detail_rows),
    hide_index=True,
    use_container_width=True,
    column_config={
        "메모": st.column_config.TextColumn(
            "메모", width="medium"
        ),
        "상세": st.column_config.TextColumn(
            "상세", width="large"
        ),
    },
    on_select="rerun",
    selection_mode="single-row",
    key=(
        f"lifestyle_table_{detail_scope}_"
        f"{fingerprint(detail_rows)}"
    ),
)

st.download_button(
    "📥 표시된 기록 CSV 다운로드",
    data=table.to_csv(index=False).encode("utf-8-sig"),
    file_name="lifestyle_records.csv",
    mime="text/csv",
    key=f"lifestyle_csv_{ui_scope}",
)

positions = event["selection"]["rows"]

if positions and 0 <= positions[0] < len(detail_rows):
    row = detail_rows[positions[0]]

    st.markdown("### 선택한 기록")

    st.write(
        f"{row['record_date']} "
        f"{str(row.get('record_time') or '')[:5]} · "
        f"{TYPE_LABELS.get(row['record_type'], row['record_type'])} · "
        f"{row.get('item_name') or ''}"
    )

    with st.container(border=True):
        st.markdown("**📝 선택한 기록의 전체 메모**")

        if row.get("memo"):
            st.text(row["memo"])
        else:
            st.caption("저장한 메모가 없어요.")

    show_lifestyle_editor(
        client=client,
        user_id=user.id,
        profile_id=profile_id,
        row=row,
    )

    with st.form(
        f"lifestyle_delete_{ui_scope}_"
        f"{row['id']}_{fingerprint(row)}"
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
                    error,
                )

            else:
                if result.data:
                    st.session_state.lifestyle_notice = (
                        user.id,
                        profile_id,
                        "선택한 기록을 삭제했어요.",
                    )
                    st.rerun()

                else:
                    st.warning(
                        "삭제된 기록이 없어요. "
                        "목록을 새로 확인해 주세요."
                    )
