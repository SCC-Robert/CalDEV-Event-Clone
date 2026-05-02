import os
import caldav
import vobject
from datetime import datetime, timedelta
import pytz

# Configuration
KEYWORD = "CAL-SYNC"
NEW_INVITEE = os.environ.get('NEW_INVITEE')
SEARCH_DAYS = 30
SOURCE_NAME = "Home"
TARGET_NAME = "Maddie's Appointments"


def copy_dt_prop(ev, name, source_prop):
    """Copy a date/time property from source, preserving params (e.g. VALUE=DATE for all-day)."""
    new_prop       = ev.add(name)
    new_prop.value = source_prop.value
    if hasattr(source_prop, 'params'):
        new_prop.params.update(source_prop.params)


def build_clone(ical_data_str, invitee_val):
    """
    Build a minimal clone containing only title and date/time from the source.
    Attendees, location, URL, description, alerts, and all other fields are
    intentionally omitted so nothing leaks onto the target calendar.
    """
    source       = vobject.readOne(ical_data_str).vevent
    orig_uid     = source.uid.value
    summary      = getattr(source, 'summary', None)
    summary_text = str(summary.value) if (summary and summary.value) else "Untitled Event"
    dtstart      = source.dtstart
    dtend        = getattr(source, 'dtend', None)
    duration     = getattr(source, 'duration', None)

    now = datetime.now(pytz.utc)

    # Build a brand-new minimal iCal object from scratch
    cal = vobject.iCalendar()
    ev  = vobject.newFromBehavior('vevent')
    cal.add(ev)

    ev.add('uid').value           = f"{orig_uid}-cloned"
    ev.add('summary').value       = summary_text
    ev.add('dtstamp').value       = now
    ev.add('last-modified').value = now

    # Copy date/time values cleanly, preserving all-day (VALUE=DATE) params
    copy_dt_prop(ev, 'dtstart', dtstart)
    if dtend:
        copy_dt_prop(ev, 'dtend', dtend)
    elif duration:
        ev.add('duration').value = duration.value

    if invitee_val:
        att                    = ev.add('attendee')
        att.value              = invitee_val
        att.params['RSVP']     = ['TRUE']
        att.params['PARTSTAT'] = ['NEEDS-ACTION']

    return cal


def run_sync():
    if not NEW_INVITEE:
        print("--- ERROR: NEW_INVITEE environment variable is not set ---")
        return

    # Normalise the invitee address once
    invitee_val = NEW_INVITEE if NEW_INVITEE.startswith("mailto:") else f"mailto:{NEW_INVITEE}"

    client = caldav.DAVClient(
        url="https://caldav.icloud.com",
        username=os.environ.get('ICLOUD_EMAIL'),
        password=os.environ.get('ICLOUD_PWD'),
    )

    principal     = client.principal()
    all_calendars = principal.calendars()

    def find_calendar(calendars, name):
        """Try straight apostrophe, then curly apostrophe, then return None."""
        curly = name.replace("'", "\u2019")
        return next(
            (c for c in calendars if c.get_display_name() in (name, curly)),
            None
        )

    source_cal = find_calendar(all_calendars, SOURCE_NAME)
    target_cal = find_calendar(all_calendars, TARGET_NAME)

    if not source_cal or not target_cal:
        print("--- ERROR: Calendar Not Found ---")
        print("  Calendars visible on this iCloud account:")
        for c in all_calendars:
            print(f"    repr={repr(c.get_display_name())}")
        if not source_cal:
            print(f"  Could not match source: {repr(SOURCE_NAME)}")
        if not target_cal:
            print(f"  Could not match target: {repr(TARGET_NAME)}")
        return

    # Sync window: 2 days ago to SEARCH_DAYS ahead
    start_time = datetime.now(pytz.utc) - timedelta(days=2)
    end_time   = start_time + timedelta(days=SEARCH_DAYS)

    # 1. Map existing clones in Target by UID
    target_events = target_cal.search(start=start_time, end=end_time, event=True)
    target_map = {}
    for te in target_events:
        try:
            v_obj = vobject.readOne(te.data)
            if hasattr(v_obj, 'vevent'):
                target_map[v_obj.vevent.uid.value] = te
        except Exception:
            continue

    # 2. Process Source events
    source_events = source_cal.search(start=start_time, end=end_time, event=True)
    processed_cloned_uids = set()

    for se in source_events:
        se.load()
        raw_ical = se.data

        try:
            ical_data = vobject.readOne(raw_ical)
            v_source  = ical_data.vevent
        except Exception as exc:
            print(f"Skipping unreadable event: {exc}")
            continue

        description = getattr(v_source, 'description', None)
        desc_text   = str(description.value) if (description and description.value) else ""

        if KEYWORD.lower() not in desc_text.lower():
            continue

        original_uid = v_source.uid.value
        cloned_uid   = f"{original_uid}-cloned"
        processed_cloned_uids.add(cloned_uid)

        summary      = getattr(v_source, 'summary', None)
        summary_text = str(summary.value) if (summary and summary.value) else "Untitled Event"

        if cloned_uid in target_map:
            # Update only if source is newer than the existing clone
            try:
                v_target_obj = vobject.readOne(target_map[cloned_uid].data)
                v_target     = v_target_obj.vevent
                src_mod      = getattr(v_source, 'last_modified', None)
                tgt_mod      = getattr(v_target, 'last_modified', None)

                if not tgt_mod or (src_mod and src_mod.value > tgt_mod.value):
                    print(f"Updating: {summary_text}")
                    clone = build_clone(raw_ical, invitee_val)
                    target_map[cloned_uid].save_component(clone.vevent)
            except Exception as exc:
                print(f"Error updating '{summary_text}': {exc}")
        else:
            # Create a new clone
            try:
                print(f"Cloning: {summary_text}")
                clone = build_clone(raw_ical, invitee_val)
                target_cal.add_event(clone.serialize())
            except Exception as exc:
                print(f"Error cloning '{summary_text}': {exc}")

    # 3. Cleanup: remove clones whose source event is gone or lost the keyword
    for t_uid, t_event in target_map.items():
        if t_uid.endswith("-cloned") and t_uid not in processed_cloned_uids:
            print(f"Removing deleted/unflagged event: {t_uid}")
            try:
                t_event.delete()
            except Exception as exc:
                print(f"Error deleting {t_uid}: {exc}")


if __name__ == "__main__":
    run_sync()
