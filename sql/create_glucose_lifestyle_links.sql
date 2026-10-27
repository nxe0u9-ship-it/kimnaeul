begin;

-- 기존 기록의 ID 자료형을 그대로 가져와 연결 테이블 생성
create table public.glucose_lifestyle_links as
select
    blood.record_id as glucose_record_id,
    lifestyle.id as lifestyle_record_id,
    blood.user_id,
    blood.profile_id
from public.blood_glucose as blood
cross join public.lifestyle_records as lifestyle
with no data;


-- 연결에 필요한 값은 모두 필수
alter table public.glucose_lifestyle_links
    alter column glucose_record_id set not null,
    alter column lifestyle_record_id set not null,
    alter column user_id set not null,
    alter column profile_id set not null;


-- 같은 혈당·생활 기록의 중복 연결 방지
alter table public.glucose_lifestyle_links
    add constraint glucose_lifestyle_links_pkey
    primary key (glucose_record_id, lifestyle_record_id);


-- 원래 기록이 삭제되면 해당 연결 정보도 삭제
alter table public.glucose_lifestyle_links
    add constraint glucose_lifestyle_links_glucose_fkey
    foreign key (glucose_record_id)
    references public.blood_glucose (record_id)
    on delete cascade;

alter table public.glucose_lifestyle_links
    add constraint glucose_lifestyle_links_lifestyle_fkey
    foreign key (lifestyle_record_id)
    references public.lifestyle_records (id)
    on delete cascade;


-- 사용자·관리 대상별 조회용 인덱스
create index glucose_lifestyle_links_owner_idx
    on public.glucose_lifestyle_links (user_id, profile_id);

create index glucose_lifestyle_links_lifestyle_idx
    on public.glucose_lifestyle_links (lifestyle_record_id);


-- 본인의 같은 관리 대상에 속한 기록끼리만 연결 허용
alter table public.glucose_lifestyle_links
    enable row level security;

create policy "Manage own matching record links"
on public.glucose_lifestyle_links
for all
to authenticated
using (
    user_id = (select auth.uid())

    and exists (
        select 1
        from public.blood_glucose as blood
        where blood.record_id =
            glucose_lifestyle_links.glucose_record_id
          and blood.user_id = (select auth.uid())
          and blood.profile_id =
            glucose_lifestyle_links.profile_id
    )

    and exists (
        select 1
        from public.lifestyle_records as lifestyle
        where lifestyle.id =
            glucose_lifestyle_links.lifestyle_record_id
          and lifestyle.user_id = (select auth.uid())
          and lifestyle.profile_id =
            glucose_lifestyle_links.profile_id
    )
)
with check (
    user_id = (select auth.uid())

    and exists (
        select 1
        from public.blood_glucose as blood
        where blood.record_id =
            glucose_lifestyle_links.glucose_record_id
          and blood.user_id = (select auth.uid())
          and blood.profile_id =
            glucose_lifestyle_links.profile_id
    )

    and exists (
        select 1
        from public.lifestyle_records as lifestyle
        where lifestyle.id =
            glucose_lifestyle_links.lifestyle_record_id
          and lifestyle.user_id = (select auth.uid())
          and lifestyle.profile_id =
            glucose_lifestyle_links.profile_id
    )
);


-- 로그인 사용자에게 조회·연결·연결 해제 권한 부여
revoke all on public.glucose_lifestyle_links
    from public, anon, authenticated;

grant select, insert, delete
    on public.glucose_lifestyle_links
    to authenticated;

commit;
