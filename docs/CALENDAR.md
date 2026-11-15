# Today agenda

Today replaces the large Devices panel. Device connection indicators and **Devices ↗** remain in the header. The agenda shows current and upcoming events for the connected calendar's day and timezone, in chronological order. The transcript remains newest-first.

## Use

- **Calendars ↗** opens calendar selection and connection settings.
- Select up to five calendars; the primary calendar is selected initially.
- Click an event to open it in Google Calendar; use **Edit** to change its title, dates, time zone or notes, or delete that event.
- **+ Event** opens a new event form.
- **Add to calendar** on a task opens the same form with its spoken title. Supported date/time phrases are prefilled relative to the source speech; missing or ambiguous dates need your input. Check the details before saving.
- **Open calendar ↗** opens the displayed day.
- Empty days, missing access, and stale cached data have distinct labels.

Gemini Decision can apply clear spoken calendar requests automatically after Google event-edit authorization. The event editor remains available for manual changes. Deleting an event asks for confirmation. Only calendars where your account is an owner or writer can be edited. A new spoken obligation needs a concrete date. If no time is spoken, it becomes an all-day event; a timed event uses the spoken time. An edit or cancellation needs one exact existing event. Ambiguous requests remain pending with a reason on the task. Replayed requests and uncertain network outcomes never trigger automatic repeated writes. The editor does not add attendees.

## Speech actions

- “Schedule dentist tomorrow at 2 PM” creates a timed event; “I need to pick up grandma from the airport on Saturday” creates an all-day event. Without an explicit duration, a timed event uses 30 minutes.
- “Move dentist to Wednesday at 3 PM” updates one exact matching future event.
- “Cancel dentist tomorrow at 2 PM” removes one exact matching event.
- “I finished testing the Bluetooth connection” completes the matching open to-do.

Dates are interpreted relative to the source speech time in America/Los_Angeles. Unsupported or ambiguous phrases such as “next week” need more detail. Calendar operations use Gemini Decision 1 closed choices; event IDs come from the actual calendar, never model-generated IDs. The durable local action ledger records the result. Pending authorization requests resume after you grant event-edit access.

## Google sign-in

The app uses a Google OAuth **Desktop app** client, a loopback callback, PKCE, and a single-use authorization state. Google authenticates the user in the browser; inLoop never asks for a Google password.

For another installation:

1. Enable the Google Calendar API in your Google Cloud project.
2. Configure the OAuth consent screen. For a personal testing project, add your Google account as a test user.
3. Create a Desktop app OAuth client and download its JSON file.
4. In Today, choose **Connect ↗**, select the JSON file, and **Continue with Google**.
5. Allow these permissions:
   - `calendar.events` (read, create, edit and delete events)
   - `calendar.calendarlist.readonly`

If you previously connected with read-only access, open **Calendars ↗ → Allow calendar changes** and reconnect once. The existing agenda remains available until then.

The Google consent screen displays the project's branding, which may differ from the Desktop client's name. Creating a separate Desktop client does not rename other apps in that project.

You can also set `INLOOP_GOOGLE_OAUTH_CLIENT_FILE` in the private local environment to use an existing Desktop app JSON file. An API key for Gemini or Maps cannot authorize calendar access.

## Storage and sync

Credentials, refresh tokens, preferences and the last agenda are kept in ignored files under `logs/inloop-calendar-*.json`, with owner-only permissions. No token or client secret is returned to the browser. The callback route is local; authorization codes are not written to access logs.

The app refreshes approximately every minute, independently of caption streaming. It expands recurring instances, respects cancellations and declined invitations, handles all-day dates in the calendar timezone, and keeps cached data when a refresh fails. Last-sync labels distinguish cached data from a fresh sync. Cached events from a previous date are not shown as today's agenda.

**Disconnect from inLoop** deletes its locally stored tokens and cached calendar data. It leaves the OAuth client configuration available for reconnecting. You can separately remove the app's grant in your Google Account settings.
