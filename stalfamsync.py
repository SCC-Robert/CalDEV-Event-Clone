import os
import copy
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


def build_clone(ical_data_str, invitee_val):
    """
    Parse a fresh copy of the iCal string, mutate it into a clone,
    and return the modified vobject. Working on a freshly-parsed copy
    avoids stale/None fields left over from the original iCloud response.
    """
    ical_copy = vobject.readOne(ical_data_str)
    v = ical_copy.vevent

    # Stamp a new cloned UID
    original_uid = v.uid.value
    v.uid.value = f"{original_uid}-cloned"

    # Ensure every text field that vobject will backslash-escape is a string
    for attr in ('summary', 'description', 'location'):
        prop = getattr(v, attr, None)
        if prop is not None and prop.value is None:
            prop.value = ""

    # Add invitee only if not already present
    if invitee_val and not hasattr(v, 'attendee'):
        attendee = v.add('attendee')
        attendee.value = invitee_val          # already has mailto: prefix
        attendee.params['RSVP'] = ['TRUE']
        attendee.params['PARTSTAT'] = ['NEEDS-ACTION']

    return ical_copy


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

    principal = client.principal()
    all_calendars = principal.calendars()

    source_cal = next((c for c in all_calendars if c.get_display_name() == SOURCE_NAME), None)
    target_cal = next((c for c in all_calendars if c.get_display_name() == TARGET_NAME), None)

    if not source_cal or not target_cal:
        print("--- ERROR: Calendar Not Found ---")
        if not source_cal:
            print(f"  Missing source: '{SOURCE_NAME}'")
        if not target_cal:
            print(f"  Missing target: '{TARGET_NAME}'")
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
        raw_ical = se.data  # keep the original string for fresh parses

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
            # Update only if source is newer
            try:
                v_target_obj = vobject.readOne(target_map[cloned_uid].data)
                v_target     = v_target_obj.vevent
                src_mod      = getattr(v_source,  'last_modified', None)
                tgt_mod      = getattr(v_target,  'last_modified', None)

                if not tgt_mod or (src_mod and src_mod.value > tgt_mod.value):
                    print(f"Updating: {summary_text}")
                    clone = build_clone(raw_ical, invitee_val)
                    target_map[cloned_uid].save_component(clone)
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
