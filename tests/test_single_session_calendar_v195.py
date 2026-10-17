from personal_quant.data.calendar import Calendar


def test_single_session_keeps_actual_close_across_dst_and_early_close():
    for day,close in [('2024-11-01','2024-11-01T20:00:00+00:00'),
                      ('2024-11-04','2024-11-04T21:00:00+00:00'),
                      ('2024-11-29','2024-11-29T18:00:00+00:00')]:
        calendar=Calendar.market(day,day)
        assert [str(d.date()) for d in calendar.sessions]==[day]
        assert calendar.close(day).isoformat()==close


def test_single_holiday_or_weekend_is_not_invented_as_a_session():
    for day in ['2024-11-28','2024-11-02']:
        assert len(Calendar.market(day,day).sessions)==0
