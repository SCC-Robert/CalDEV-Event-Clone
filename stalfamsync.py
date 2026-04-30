import os
import caldav
import vobject
from datetime import datetime, timedelta

# Configuration - Change these as needed
KEYWORD = "PROJECT-SYNC"  # The specific phrase to look for in notes
NEW_INVITEE = "mailto:kristina.evanoff@gmail.com"

def run_sync():
    client = caldav.DAVClient(
        url="https://caldav.icloud.com",
        username=os.environ.get('ICLOUD_EMAIL'),
        password=os.environ.get('ICLOUD_PWD')
    )
    
    principal = client.principal()
    
    # Use the URLs found during your discovery step
    source_cal = client.calendar(url="https://...source_url")
    target_cal = client.calendar(url="https://...target_url")

    # Search window: today through the next 30 days
    events = source_cal.date_search(
        start=datetime.now(),
        end=datetime.now() + timedelta(days=30)
    )

    for event in events:
        ical_data = vobject.readOne(event.data)
        vevent = ical_data.vevent
        
        # 1. Check for Keyword in the Description (Notes)
        description = getattr(vevent, 'description', None)
        if description and KEYWORD in description.value:
            
            # 2. Prevent Duplicate UIDs in the same account
            # We append a suffix so iCloud treats it as a new event
            original_uid = vevent.uid.value
            vevent.uid.value = f"{original_uid}-cloned"

            # 3. Add the new Invitee
            # Using 'attendee' property; 'mailto:' prefix is required
            attendee = vevent.add('attendee')
            attendee.value = NEW_INVITEE
            attendee.params['CN'] = ['New Invitee Name']
            attendee.params['RSVP'] = ['TRUE']

            # 4. Upload to Target Calendar
            try:
                target_cal.add_event(ical_data.serialize())
                print(f"Successfully cloned: {vevent.summary.value}")
            except Exception as e:
                # This usually triggers if the cloned UID already exists in target
                print(f"Skipped {vevent.summary.value}: {e}")

if __name__ == "__main__":
    run_sync()