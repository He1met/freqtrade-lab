from datetime import date,timedelta
from lab.spot139_gap_proposal import classify_times,complete_dependency_day,recovery_action,KNOWN_START,KNOWN_END,HOUR


def test_retained_short_and_missing_slot_are_visible_not_filled():
    rows=[(KNOWN_START-HOUR,KNOWN_START-1),(KNOWN_START,1613014854773),(KNOWN_END,KNOWN_END+HOUR-1)]
    assert classify_times(rows)=={'status':'EXPLORATORY_TIMES_ONLY','anomalies':[('SHORT',KNOWN_START),('MISSING',KNOWN_START+HOUR)]}
    assert len(rows)==3


def test_unknown_gap_and_duplicate_stop():
    assert classify_times([(0,HOUR-1),(2*HOUR,3*HOUR-1)])['status']=='QUARANTINE_UNKNOWN_GAP_STOP'
    assert classify_times([(0,HOUR-1),(0,HOUR-1)])['status']=='STOP_DUPLICATE_OR_UNORDERED'
    assert classify_times([(0,HOUR)])['status']=='STOP_INVALID_STRUCTURE'


def test_no_calendar_compression_and_each_dependency_recovers_separately():
    missing=date(2021,2,11);complete={missing+timedelta(days=i) for i in range(-300,400)}-{missing}
    assert not complete_dependency_day(missing+timedelta(days=84),complete)
    assert complete_dependency_day(missing+timedelta(days=85),complete)
    assert not complete_dependency_day(missing+timedelta(days=85),complete,272)


def test_recovery_exit_precedes_halt_and_no_catchup_entry():
    assert recovery_action(True,True,False).startswith('EXIT_FIRST')
    assert recovery_action(False,True,True)=='NO_NEW_RISK'
    assert recovery_action(False,False,True)=='WAIT_FRESH_DAILY_DECISION'
