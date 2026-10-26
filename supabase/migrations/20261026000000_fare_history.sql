-- Price history for the weekend fare scanner.
-- One row per trip per scan; alerts are logged so the same fare isn't emailed twice.
-- RLS is on with no policies, and the public API roles have no grants: only the
-- secret (service role) key used by the scheduled job can read or write.

create table if not exists public.fare_observations (
    id                bigint generated always as identity primary key,
    scanned_at        timestamptz not null default now(),
    run_id            text,
    provider          text not null,
    trip_key          text not null,
    origin            text not null,
    route             text not null,
    pattern           text not null,
    weekend           date not null,
    depart            date not null,
    return_date       date not null,
    airport           text not null,
    lowest_price      integer,
    main_cabin_price  integer,
    gap               integer,
    gap_estimated     boolean not null default false,
    lp_estimate       integer,
    ground_cost       integer,
    door_to_door      integer,
    outbound_depart   text,
    outbound_arrive   text,
    error             text
);

create index if not exists fare_observations_trip_time_idx
    on public.fare_observations (trip_key, scanned_at desc);
create index if not exists fare_observations_route_depart_idx
    on public.fare_observations (route, depart);

create table if not exists public.fare_alerts (
    id        bigint generated always as identity primary key,
    sent_at   timestamptz not null default now(),
    trip_key  text not null,
    reason    text not null check (reason in ('deal', 'drop')),
    price     integer not null
);

create index if not exists fare_alerts_trip_time_idx on public.fare_alerts (trip_key, sent_at desc);

alter table public.fare_observations enable row level security;
alter table public.fare_alerts enable row level security;

revoke all on public.fare_observations, public.fare_alerts from anon, authenticated;
grant select, insert on public.fare_observations, public.fare_alerts to service_role;
