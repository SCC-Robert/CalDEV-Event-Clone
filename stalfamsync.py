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
TARGET_NAME = "Maddie’s Appointments"

def run_sync():
    client = caldav.DAVClient(
        url="https://caldav.icloud.com",
        username=os.environ.get('ICLOUD_EMAIL'),
        password=os.environ.get('ICLOUD_PWD')
    )
    
    principal = client.principal()
    all_calendars = principal.calendars()

    source_cal = next((c for c in all_calendars if c.get_display_name() == SOURCE_NAME), None)
    target_cal = next((c for c in all_calendars if c.get_display_name() == TARGET_NAME), None)

    if not source_cal or not target_cal:
        print("--- ERROR: Calendar Not Found ---")
        return

    # Broaden window: Start from 2 days ago to catch any timezone-drifting events
    start_time = datetime.now(pytz.utc) - timedelta(days=2)
    end_time = start_time + timedelta(days=SEARCH_DAYS)

    print(f"Scanning '{TARGET_NAME}' for existing clones...")
    target_events = target_cal.search(start=start_time, end=end_time, event=True)
    target_map = {}
    for te in target_events:
        try:
            v_target = vobject.readOne(te.data).vevent
            target_map[v_target.uid.value] = te
        except: continue

    print(f"Checking '{SOURCE_NAME}' for events...")
    source_events = source_cal.search(start=start_time, end=end_time, event=True)
    processed_cloned_uids = set()

    if not source_events:
        print("No events found in 'Home' calendar at all for the next 30 days.")

    for se in source_events:
        # Force a full load to ensure Notes are visible
        se.load()
        v_source = vobject.readOne(se.data).vevent
        
        summary = getattr(v_source, 'summary', None)
        summary_text = summary.value if summary else "No Title"
        
        description = getattr(v_source, 'description', None)
        desc_text = str(description.value) if description else ""
        
        # LOGGING: See exactly what the script is checking
        print(f"Examining: '{summary_text}' | Notes contain keyword: {KEYWORD.lower() in desc_text.lower()}")

        if KEYWORD.lower() in desc_text.lower():
            cloned_uid = f"{v_source.uid.value}-cloned"
            processed_cloned_uids.add(cloned_uid)
            
            v_source.uid.value = cloned_uid
            
            invitee_val = NEW_INVITEE
            if invitee_val and not invitee_val.startswith("mailto:"):
                invitee_val = f"mailto:{invitee_val}"

            if not hasattr(v_source, 'attendee'):
                attendee = v_source.add('attendee')
                attendee.value = invitee_val
                attendee.params['RSVP'] = ['TRUE']
                attendee.params['PARTSTAT'] = ['NEEDS-ACTION']

            if cloned_uid in target_map:
                v_target = vobject.readOne(target_map[cloned_uid].data).vevent
                src_mod = getattr(v_source, 'last_modified', None)
                tgt_mod = getattr(v_target, 'last_modified', None)
                
                if not tgt_mod or (src_mod and src_mod.value > tgt_mod.value):
                    print(f"Updating: {summary_text}")
                    target_map[cloned_uid].save_component(v_source.parent)
            else:
                print(f"Found and Cloning: {summary_text}")
                target_cal.add_event(v_source.parent.serialize())

    for t_uid, t_event in target_map.items():
        if t_uid.endswith("-cloned") and t_uid not in processed_cloned_uids:
            print(f"Removing deleted/unflagged event: {t_uid}")
            t_event.delete()

if __name__ == "__main__":
    run_sync()
