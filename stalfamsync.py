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
    # 1. Initialize Client
    client = caldav.DAVClient(
        url="https://caldav.icloud.com",
        username=os.environ.get('ICLOUD_EMAIL'),
        password=os.environ.get('ICLOUD_PWD')
    )
    
    principal = client.principal()
    all_calendars = principal.calendars()

    # 2. Match calendars by Name
    source_cal = next((c for c in all_calendars if c.name == SOURCE_NAME), None)
    target_cal = next((c for c in all_calendars if c.name == TARGET_NAME), None)

    # 3. Validation and Debugging
    if not source_cal or not target_cal:
        print("--- ERROR: Calendar Not Found ---")
        print(f"Looked for: '{SOURCE_NAME}' -> Found: {source_cal is not None}")
        print(f"Looked for: '{TARGET_NAME}' -> Found: {target_cal is not None}")
        print("\nAvailable calendars in your account:")
        for c in all_calendars:
            print(f"- {c.name}")
        return

    # 4. Define Time Window (UTC for consistency)
    start_time = datetime.now(pytz.utc)
    end_time = start_time + timedelta(days=SEARCH_DAYS)

    # 5. Fetch Target Events for Duplicate/Update Checking
    print(f"Scanning '{TARGET_NAME}' for existing clones...")
    target_events = target_cal.date_search(start=start_time, end=end_time)
    target_map = {}
    for te in target_events:
        try:
            v_target = vobject.readOne(te.data).vevent
            target_map[v_target.uid.value] = te
        except: continue

    # 6. Fetch Source Events
    print(f"Checking '{SOURCE_NAME}' for events with '{KEYWORD}'...")
    source_events = source_cal.date_search(start=start_time, end=end_time)
    processed_cloned_uids = set()

    for se in source_events:
        v_source = vobject.readOne(se.data).vevent
        description = getattr(v_source, 'description', None)
        
        if description and KEYWORD in description.value:
            cloned_uid = f"{v_source.uid.value}-cloned"
            processed_cloned_uids.add(cloned_uid)
            
            # Update the UID and add the invitee
            v_source.uid.value = cloned_uid
            if not hasattr(v_source, 'attendee'):
                attendee = v_source.add('attendee')
                attendee.value = NEW_INVITEE
                attendee.params['RSVP'] = ['TRUE']

            if cloned_uid in target_map:
                # Update Logic
                v_target = vobject.readOne(target_map[cloned_uid].data).vevent
                src_mod = getattr(v_source, 'last_modified', None)
                tgt_mod = getattr(v_target, 'last_modified', None)
                
                if not tgt_mod or (src_mod and src_mod.value > tgt_mod.value):
                    print(f"Updating: {v_source.summary.value}")
                    target_map[cloned_uid].save_component(v_source.parent)
            else:
                # Create Logic
                print(f"Cloning: {v_source.summary.value}")
                target_cal.add_event(v_source.parent.serialize())

    # 7. Cleanup Logic (Deletions)
    for t_uid, t_event in target_map.items():
        if t_uid.endswith("-cloned") and t_uid not in processed_cloned_uids:
            print(f"Deleting (Original removed/keyword cleared): {t_uid}")
            t_event.delete()

if __name__ == "__main__":
    run_sync()
