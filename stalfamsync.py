import os
import caldav
import vobject
from datetime import datetime, timedelta
import pytz

# Configuration
# Tip: Ensure this matches exactly what's in your Note/Description
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

    # 1. Use get_display_name() to fix Deprecation Warnings
    source_cal = next((c for c in all_calendars if c.get_display_name() == SOURCE_NAME), None)
    target_cal = next((c for c in all_calendars if c.get_display_name() == TARGET_NAME), None)

    if not source_cal or not target_cal:
        print("--- ERROR: Calendar Not Found ---")
        for c in all_calendars:
            print(f"Available: '{c.get_display_name()}'")
        return

    # UTC Timezone-aware dates
    start_time = datetime.now(pytz.utc)
    end_time = start_time + timedelta(days=SEARCH_DAYS)

    # 2. Use .search() with comp_class to fix Deprecation Warnings
    print(f"Scanning '{TARGET_NAME}' for existing clones...")
    target_events = target_cal.search(start=start_time, end=end_time, event=True)
    
    target_map = {}
    for te in target_events:
        try:
            v_target = vobject.readOne(te.data).vevent
            target_map[v_target.uid.value] = te
        except: continue

    print(f"Checking '{SOURCE_NAME}' for events containing '{KEYWORD}'...")
    source_events = source_cal.search(start=start_time, end=end_time, event=True)
    processed_cloned_uids = set()

    found_any_source = False
    for se in source_events:
        found_any_source = True
        v_source = vobject.readOne(se.data).vevent
        
        # Robust description check
        description = getattr(v_source, 'description', None)
        desc_text = description.value if description else ""
        
        # Case-insensitive keyword check
        if KEYWORD.lower() in desc_text.lower():
            cloned_uid = f"{v_source.uid.value}-cloned"
            processed_cloned_uids.add(cloned_uid)
            
            # Prepare clone
            v_source.uid.value = cloned_uid
            
            # Handle Attendee injection
            if not hasattr(v_source, 'attendee'):
                attendee = v_source.add('attendee')
                attendee.value = NEW_INVITEE
                attendee.params['RSVP'] = ['TRUE']
                attendee.params['PARTSTAT'] = ['NEEDS-ACTION']

            if cloned_uid in target_map:
                # Update logic
                v_target = vobject.readOne(target_map[cloned_uid].data).vevent
                src_mod = getattr(v_source, 'last_modified', None)
                tgt_mod = getattr(v_target, 'last_modified', None)
                
                if not tgt_mod or (src_mod and src_mod.value > tgt_mod.value):
                    print(f"Updating changed event: {v_source.summary.value}")
                    target_map[cloned_uid].save_component(v_source.parent)
            else:
                print(f"Cloning new event: {v_source.summary.value}")
                target_cal.add_event(v_source.parent.serialize())

    if not found_any_source:
        print("No events found in Source calendar within the time window.")

    # 3. Cleanup Logic
    for t_uid, t_event in target_map.items():
        if t_uid.endswith("-cloned") and t_uid not in processed_cloned_uids:
            print(f"Removing deleted/unflagged event: {t_uid}")
            t_event.delete()

if __name__ == "__main__":
    run_sync()
