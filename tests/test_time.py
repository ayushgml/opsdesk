from opsdesk.facts import age_minutes

def test_offsets_represent_the_same_instant():
    assert age_minutes("2026-10-01T12:00:00+00:00", "2026-10-01T13:00:00+01:00") == 0

def test_half_minute_age():
    assert age_minutes("2026-10-01T12:00:00+00:00", "2026-10-01T11:59:30+00:00") == 0.5
