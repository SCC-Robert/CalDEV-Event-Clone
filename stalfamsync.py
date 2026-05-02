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

    start_time = datetime.now(pytz.utc)
    end_time = start_time + timedelta(days=SEARCH_DAYS)

    # Fetch Target Events
    print(f"Scanning '{TARGET_NAME}'...")
    target_events = target_cal.search(start=start_time, end=end_time, event=True)
    target_map = {vobject.readOne(te.data).vevent.uid.value: te for te in target_events if hasattr(vobject.readOne(te.data), 'vevent')}

    # Fetch Source Events
    print(f"Checking '{SOURCE_NAME}' for keyword '{KEYWORD}'...")
    source_events = source_cal.search(start=start_time, end=end_time, event=True)
    processed_cloned_uids = set()

    for se in source_events:
        # DEEP FETCH: Ensure we have the notes/description
        # If se.data is minimal, se.load() pulls the full ICS from iCloud
        if not se.data or 'DESCRIPTION' not in se.data.upper():
            se.load()
            
        v_source = vobject.readOne(se.data).vevent
        description = getattr(v_source, 'description', None)
        desc_text = str(description.value) if description else ""
        
        if KEYWORD.lower() in desc_text.lower():
            cloned_uid = f"{v_source.uid.value}-cloned"
            processed_cloned_uids.add(cloned_uid)
            
            # Prepare Cloned Event
            v_source.uid.value = cloned_uid
            
            # Ensure invitee is present
            if not hasattr(v_source, 'attendee'):
                attendee = v_source.add('attendee')
                attendee.value = NEW_INVITEE
                attendee.params['RSVP'] = ['TRUE']
                attendee.params['PARTSTAT'] = ['NEEDS-ACTION']

            if cloned_uid in target_map:
                # Update if newer
                v_target = vobject.readOne(target_map[cloned_uid].data).vevent
                src_mod = getattr(v_source, 'last_modified', None)
                tgt_mod = getattr(v_target, 'last_modified', None)
                
                if not tgt_mod or (src_mod and src_mod.value > tgt_mod.value):
                    print(f"Updating: {v_source.summary.value}")
                    target_map[cloned_uid].save_component(v_source.parent)
            else:
                print(f"Found and Cloning: {v_source.summary.value}")
                target_cal.add_event(v_source.parent.serialize())

    # Cleanup (Deletions)
    for t_uid, t_event in target_map.items():
        if t_uid.endswith("-cloned") and t_uid not in processed_cloned_uids:
            print(f"Removing deleted/unflagged event: {t_uid}")
            t_event.delete()

if __name__ == "__main__":
    run_sync()
