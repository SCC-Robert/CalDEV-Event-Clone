import os
import caldav
import vobject
from datetime import datetime, timedelta

# Configuration - Change these as needed
KEYWORD = "CAL-SYNC"  # The specific phrase to look for in notes
SEARCH_DAYS = 30

def run_sync():
    # 1. Initialize Client
    client = caldav.DAVClient(
        url="https://caldav.icloud.com",
        username=os.environ.get('ICLOUD_EMAIL'),
        password=os.environ.get('ICLOUD_PWD')
    )
    
    principal = client.principal()
    
    # Use the URLs found during your discovery step
    source_cal = client.calendar(url="https://...source_url")
    target_cal = client.calendar(url="https://...target_url")

    # Capture invitee email address
    invitee_email_address = os.environ.get('NEW_INVITEE')

    # Time window: Now to +30 days
    start_time = datetime.now()
    end_time = start_time + timedelta(days=SEARCH_DAYS)

    # 2. Pre-fetch Target UIDs to prevent duplicates
    print("Scanning Target calendar for existing clones...")
    target_events = target_cal.date_search(start=start_time, end=end_time)
    
    # Create a set of existing UIDs for O(1) lookup speed
    existing_target_uids = set()
    for te in target_events:
        try:
            # We use vobject to parse the UID specifically
            tmp_ical = vobject.readOne(te.data)
            existing_target_uids.add(tmp_ical.vevent.uid.value)
        except Exception:
            continue

    # 3. Fetch Source Events
    print(f"Checking Source calendar for keyword: '{KEYWORD}'...")
    source_events = source_cal.date_search(start=start_time, end=end_time)

    for event in source_events:
        ical_data = vobject.readOne(event.data)
        vevent = ical_data.vevent
        
        # Filter by Keyword
        description = getattr(vevent, 'description', None)
        if description and KEYWORD in description.value:
            
            # Construct the "Cloned UID"
            original_uid = vevent.uid.value
            cloned_uid = f("{original_uid}-cloned")

            # 4. DUPLICATE CHECK: Only proceed if this UID isn't in our target set
            if cloned_uid in existing_target_uids:
                print(f"Skipping: '{vevent.summary.value}' (Already cloned)")
                continue

            # 5. Prepare the Clone
            vevent.uid.value = cloned_uid
            
            # Add Invitee
            attendee = vevent.add('attendee')
            attendee.value = invitee_email_address
            attendee.params['RSVP'] = ['TRUE']
            attendee.params['PARTSTAT'] = ['NEEDS-ACTION']

            # 6. Upload
            try:
                target_cal.add_event(ical_data.serialize())
                print(f"Cloned & Invited: {vevent.summary.value}")
            except Exception as e:
                print(f"Error uploading {vevent.summary.value}: {e}")

if __name__ == "__main__":
    run_sync()
