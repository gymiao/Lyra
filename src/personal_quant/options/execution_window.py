"""Calendar-bound daily execution authority; frozen selection is never replaced."""
from datetime import date,timedelta
from zoneinfo import ZoneInfo
from ..common import QuantError,utc
from ..data.calendar import Calendar


def assess(monthly,request,environment):
    first=date.fromisoformat(monthly['applicable_session'])
    policy=request.get('execution_window')
    maximum=1;session=first;checks=[]
    if policy is not None:
        if (not isinstance(policy,dict) or set(policy)!={'session','maximum_sessions'}
                or type(policy['maximum_sessions']) is not int or policy['maximum_sessions']<1):
            raise QuantError('INVALID_OPTION_EXECUTION_WINDOW','延期执行需明确交易日和正整数窗口长度')
        try:
            session=date.fromisoformat(policy['session'])
            if session.isoformat()!=policy['session']:raise ValueError()
        except (TypeError,ValueError):
            raise QuantError('INVALID_OPTION_EXECUTION_WINDOW','执行日须为YYYY-MM-DD')
        maximum=policy['maximum_sessions']
        if environment!='demo':checks.append('DEFERRED_EXECUTION_DEMO_ONLY')
    calendar=Calendar.market(first.isoformat(),(first+timedelta(days=40)).isoformat())
    days=[day.date() for day in calendar.sessions if day.year==first.year and day.month==first.month]
    # A monthly intent cannot spill into the following monthly decision cycle.
    if maximum>len(days) or session not in days[:maximum]:checks.append('INVALID_EXECUTION_WINDOW')
    if session not in {day.date() for day in calendar.sessions}:
        return {'checks':sorted(set(checks+['INVALID_EXECUTION_WINDOW'])),'session':session.isoformat(),
                'maximum_sessions':maximum,'close':None}
    close=calendar.close(session).to_pydatetime();clock=utc(request['as_of'])
    if (clock.astimezone(ZoneInfo('America/New_York')).date()!=session or utc(request['valid_until'])!=close
            or not utc(monthly['decision_at'])<clock<=close-timedelta(minutes=20)):
        checks.append('INVALID_EXECUTION_WINDOW')
    return {'checks':sorted(set(checks)),'session':session.isoformat(),'maximum_sessions':maximum,'close':close.isoformat()}
