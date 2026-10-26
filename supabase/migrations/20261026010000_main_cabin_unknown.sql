-- Main Cabin prices are no longer estimated: an empty Main Cabin search is
-- recorded as unknown. Rows written with an estimated gap are corrected so the
-- guessed price doesn't linger in the history.

alter table public.fare_observations
    add column if not exists main_cabin_unknown boolean not null default false;

update public.fare_observations
set main_cabin_unknown = true, main_cabin_price = null, gap = null, lp_estimate = null
where gap_estimated;

comment on column public.fare_observations.gap_estimated is
    'Deprecated (Oct 2026): estimated rows were converted to main_cabin_unknown.';
