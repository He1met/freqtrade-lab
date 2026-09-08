"""Pure v2 proposal checks, not connected to collector or trading engine."""
from datetime import date, timedelta

HOUR = 3600000
KNOWN_START = 1613012400000  # 2021-02-11 03:00 UTC
KNOWN_END = 1613019600000    # 2021-02-11 05:00 UTC


def classify_times(rows):
    """Rows are (open_ms, close_ms); retain anomalies, never fill a candle.

    The sole candidate exception is the predeclared 03/04 UTC slot envelope.
    This is an exploratory model boundary, not proof of an exchange outage.
    """
    previous=None; anomalies=[]
    for opened,closed in rows:
        if type(opened) is not int or type(closed) is not int or opened % HOUR or not opened<=closed<opened+HOUR:
            return {'status':'STOP_INVALID_STRUCTURE','anomalies':anomalies}
        if previous is not None:
            if opened<=previous:return {'status':'STOP_DUPLICATE_OR_UNORDERED','anomalies':anomalies}
            for missing in range(previous+HOUR,opened,HOUR):
                anomalies.append(('MISSING',missing))
                if not KNOWN_START<=missing<KNOWN_END:return {'status':'QUARANTINE_UNKNOWN_GAP_STOP','anomalies':anomalies}
        if closed!=opened+HOUR-1:
            anomalies.append(('SHORT',opened))
            if not KNOWN_START<=opened<KNOWN_END:return {'status':'QUARANTINE_UNKNOWN_GAP_STOP','anomalies':anomalies}
        previous=opened
    if len({t for _,t in anomalies})>2:return {'status':'STOP_EXCEPTION_CAP','anomalies':anomalies}
    return {'status':'EXPLORATORY_TIMES_ONLY','anomalies':anomalies}


def complete_dependency_day(day, complete_days, lag=84):
    """All calendar days t-lag..t required; never compress away a missing day."""
    if not isinstance(day,date):raise ValueError('calendar day required')
    return all(day-timedelta(days=i) in complete_days for i in range(lag+1))


def recovery_action(pending_exit, halted, new_signal_valid):
    if pending_exit:return 'EXIT_FIRST_AT_ACTUAL_RECOVERY_OPEN_IF_LEGAL'
    if halted:return 'NO_NEW_RISK'
    return 'WAIT_FRESH_DAILY_DECISION'  # no delayed entry catch-up at recovery
