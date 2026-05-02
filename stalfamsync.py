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

    # Sync window: 2 days ago to 30 days ahead
    start_time = datetime.now(pytz.utc) - timedelta(days=2)
    end_time = start_time + timedelta(days=SEARCH_DAYS)

    # 1. Map existing clones in Target
    target_events = target_cal.search(start=start_time, end=end_time, event=True)
    target_map = {}
    for te in target_events:
        try:
            v_obj = vobject.readOne(te.data)
            if hasattr(v_obj, 'vevent'):
                target_map[v_obj.vevent.uid.value] = te
        except: continue

    # 2. Process Source events
    source_events = source_cal.search(start=start_time, end=end_time, event=True)
    processed_cloned_uids = set()

    for se in source_events:
        se.load()
        ical_data = vobject.readOne(se.data)
        v_source = ical_data.vevent
        
        description = getattr(v_source, 'description', None)
        desc_text = str(description.value) if description else ""
        
        if KEYWORD.lower() in desc_text.lower():
            cloned_uid = f"{v_source.uid.value}-cloned"
            processed_cloned_uids.add(cloned_uid)
            v_source.uid.value = cloned_uid
            
            # Setup Invitee
            invitee_val = NEW_INVITEE
            if invitee_val and not invitee_val.startswith("mailto:"):
                invitee_val = f"mailto:{invitee_val}"

            if not hasattr(v_source, 'attendee'):
                attendee = v_source.add('attendee')
                attendee.value = invitee_val
                attendee.params['RSVP'] = ['TRUE']
                attendee.params['PARTSTAT'] = ['NEEDS-ACTION']

            summary = getattr(v_source, 'summary', None)
            summary_text = summary.value if summary else "Untitled Event"

            if cloned_uid in target_map:
                # Update if changed
                v_target_obj = vobject.readOne(target_map[cloned_uid].data)
                v_target = v_target_obj.vevent
                src_mod = getattr(v_source, 'last_modified', None)
                tgt_mod = getattr(v_target, 'last_modified', None)
                
                if not tgt_mod or (src_mod and src_mod.value > tgt_mod.value):
                    print(f"Updating: {summary_text}")
                    target_map[cloned_uid].save_component(ical_data)
            else:
                # Create new clone
                print(f"Cloning: {summary_text}")
                target_cal.add_event(ical_data.serialize())

    # 3. Cleanup: Remove clones if the source or keyword is gone
    for t_uid, t_event in target_map.items():
        if t_uid.endswith("-cloned") and t_uid not in processed_cloned_uids:
            print(f"Removing deleted/unflagged event: {t_uid}")
            t_event.delete()

if __name__ == "__main__":
    run_sync()
