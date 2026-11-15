"""Google Calendar agenda and explicit event edits with private local OAuth."""
import asyncio
import base64
from datetime import date, datetime, time as day_time, timedelta
import hashlib
import json
import math
import os
import re
from pathlib import Path
import secrets
import time
from urllib.parse import urlencode, urlparse, quote
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import aiohttp

AUTH_URL = 'https://accounts.google.com/o/oauth2/v2/auth'
TOKEN_URL = 'https://oauth2.googleapis.com/token'
API_URL = 'https://www.googleapis.com/calendar/v3'
EVENTS_READ_SCOPE = 'https://www.googleapis.com/auth/calendar.events.readonly'
EVENTS_WRITE_SCOPE = 'https://www.googleapis.com/auth/calendar.events'
CALENDAR_LIST_SCOPE = 'https://www.googleapis.com/auth/calendar.calendarlist.readonly'
FULL_CALENDAR_SCOPE = 'https://www.googleapis.com/auth/calendar'
SCOPES = (EVENTS_WRITE_SCOPE, CALENDAR_LIST_SCOPE)


class CalendarAccessError(Exception):
    pass


def private_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + '.' + secrets.token_hex(6) + '.tmp')
    try:
        fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, 'w') as stream:
            json.dump(value, stream, allow_nan=False)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def read_json(path, default):
    try:
        value = json.loads(Path(path).read_text())
        return value if isinstance(value, type(default)) else default
    except (OSError, ValueError):
        return default


def zone(value):
    try:
        return ZoneInfo(value)
    except (ValueError, TypeError, ZoneInfoNotFoundError):
        return ZoneInfo('America/Los_Angeles')


def event_fields(fields):
    """Validate the small edit form; never accept guests, invitations or arbitrary API fields."""
    allowed={'title','start','end','all_day','timezone','description'}
    if not isinstance(fields,dict) or set(fields)-allowed:
        raise ValueError('Use only title, start, end, all_day, timezone and description.')
    if not {'title','start','end','all_day','timezone'}.issubset(fields):
        raise ValueError('Enter a title, start, end, timezone and all-day setting.')
    title=fields['title']
    if not isinstance(title,str) or not title.strip() or len(title)>300:
        raise ValueError('Enter an event title of at most 300 characters.')
    if not isinstance(fields['all_day'],bool):raise ValueError('Invalid all-day setting.')
    tz_name=fields['timezone']
    if not isinstance(tz_name,str):raise ValueError('Choose a valid timezone.')
    try:tz=ZoneInfo(tz_name)
    except (ValueError,ZoneInfoNotFoundError):raise ValueError('Choose a valid timezone.') from None
    description=fields.get('description')
    if 'description' in fields and (not isinstance(description,str) or len(description)>10000):
        raise ValueError('Description must be text of at most 10000 characters.')
    dates=[]
    for key in ('start','end'):
        value=fields[key]
        if not isinstance(value,str) or len(value)>100:raise ValueError('Enter valid event dates.')
        try:
            if fields['all_day']:
                if not re.fullmatch(r'\d{4}-\d{2}-\d{2}',value):raise ValueError()
                parsed=date.fromisoformat(value)
                dates.append((parsed,{'date':parsed.isoformat()}))
            else:
                if 'T' not in value:raise ValueError()
                parsed=datetime.fromisoformat(value.replace('Z','+00:00'))
                if parsed.tzinfo is None:
                    local=parsed;parsed=local.replace(tzinfo=tz)
                    if datetime.fromtimestamp(parsed.timestamp(),tz).replace(tzinfo=None)!=local:
                        raise ValueError('This local time does not exist because the clock changes. Choose another time.')
                    other=local.replace(tzinfo=tz,fold=1)
                    if other.utcoffset()!=parsed.utcoffset():
                        raise ValueError('This local time occurs twice. Include its UTC offset to choose an occurrence.')
                dates.append((parsed.timestamp(),{'dateTime':parsed.isoformat(),'timeZone':tz_name}))
        except (ValueError,OverflowError) as error:
            if str(error).startswith('This local time'):raise
            raise ValueError('Enter valid event dates and times.') from None
    if dates[1][0]<=dates[0][0]:raise ValueError('The event end must be after its start. All-day end dates are exclusive.')
    result=dict(summary=title.strip(),start=dates[0][1],end=dates[1][1])
    if description is not None:result['description']=description
    return result


def normalize_event(event, calendar):
    if not isinstance(event, dict) or event.get('status') == 'cancelled':
        return None
    if any(a.get('self') and a.get('responseStatus') == 'declined' for a in event.get('attendees', [])):
        return None
    start, end = event.get('start', {}), event.get('end', {})
    all_day = 'date' in start
    try:
        tz = zone(calendar.get('timezone'))
        def instant(value):
            if 'dateTime' in value:
                result = datetime.fromisoformat(value['dateTime'].replace('Z', '+00:00'))
                if result.tzinfo is None:
                    result = result.replace(tzinfo=zone(value.get('timeZone', calendar.get('timezone'))))
                return result.timestamp()
            return datetime.combine(date.fromisoformat(value['date']), day_time(), tz).timestamp()
        begin, finish = instant(start), instant(end)
        if not all(math.isfinite(v) for v in (begin, finish)) or finish <= begin:
            return None
    except (ValueError, TypeError, KeyError):
        return None
    link = event.get('htmlLink', '')
    parsed = urlparse(link)
    if parsed.scheme != 'https' or parsed.hostname not in ('calendar.google.com', 'www.google.com'):
        link = 'https://calendar.google.com/'
    return dict(id=str(event.get('id', ''))[:500], calendar_id=calendar['id'],
                calendar_name=calendar['name'], title=str(event.get('summary') or 'Untitled event')[:300],
                start=begin, end=finish, all_day=all_day, html_url=link,
                start_iso=start.get('date') if all_day else start.get('dateTime'),
                end_iso=end.get('date') if all_day else end.get('dateTime'),
                description=str(event.get('description') or '')[:10000],
                timezone=str(start.get('timeZone') or calendar.get('timezone') or 'America/Los_Angeles'),
                etag=event.get('etag') if isinstance(event.get('etag'),str) else None,
                writable=bool(calendar.get('writable')))



class CalendarAgenda:
    def __init__(self, directory, client_file=None):
        root = Path(directory)
        self.client_path = Path(client_file) if client_file else root / 'inloop-calendar-client.json'
        self.token_path = root / 'inloop-calendar-tokens.json'
        self.cache_path = root / 'inloop-calendar-cache.json'
        self.preferences_path = root / 'inloop-calendar-preferences.json'
        self.client = None
        self.tokens = read_json(self.token_path, {})
        self.cache = read_json(self.cache_path, {})
        self.preferences = read_json(self.preferences_path, {})
        self.pending = {}
        self.lock = asyncio.Lock()
        self.generation = 0
        try:
            self.client = self.validate_client(read_json(self.client_path, {}))
        except ValueError:
            pass
        self.status = 'connecting' if self.client and self.tokens else 'disconnected' if self.client else 'not_configured'

    @staticmethod
    def validate_client(data):
        installed = data.get('installed') if isinstance(data, dict) else None
        if not isinstance(installed, dict):
            raise ValueError('Choose a Google OAuth Desktop app credentials JSON file.')
        identity, secret = installed.get('client_id'), installed.get('client_secret')
        if (not isinstance(identity, str) or not identity.endswith('.apps.googleusercontent.com')
                or not isinstance(secret, str) or not 1 <= len(secret) <= 1000):
            raise ValueError('The file is missing Desktop app OAuth credentials.')
        return dict(client_id=identity, client_secret=secret)

    def configure(self, data):
        client = self.validate_client(data)
        if self.client and self.client != client:
            self.disconnect()
        private_json(self.client_path, {'installed': client})
        self.client = client
        self.status = 'connecting' if self.tokens else 'disconnected'

    def has_write_scope(self):
        scopes=self.tokens.get('scope','')
        granted=set(scopes.split()) if isinstance(scopes,str) else set()
        return bool(granted & {EVENTS_WRITE_SCOPE,FULL_CALENDAR_SCOPE})

    def selected_date(self, tz_name=None):
        value=self.preferences.get('date')
        if isinstance(value,str) and re.fullmatch(r'\d{4}-\d{2}-\d{2}',value):
            try:return date.fromisoformat(value)
            except ValueError:pass
        return datetime.now(zone(tz_name or self.cache.get('timezone'))).date()

    def select_date(self, value):
        if not isinstance(value,str) or not re.fullmatch(r'\d{4}-\d{2}-\d{2}',value):
            raise ValueError('Choose a calendar date in YYYY-MM-DD format.')
        try:day=date.fromisoformat(value)
        except ValueError:raise ValueError('Choose a valid calendar date.') from None
        self.preferences['date']=day.isoformat()
        private_json(self.preferences_path,self.preferences)

    def snapshot(self):
        tz_name = self.cache.get('timezone', 'America/Los_Angeles')
        today = datetime.now(zone(tz_name)).date().isoformat()
        selected_day = self.selected_date(tz_name).isoformat()
        valid_day = self.cache.get('date') == selected_day
        selected = self.preferences.get('selected')
        calendars=[{**c,'writable':self.has_write_scope() and c.get('access_role') in ('owner','writer')}
                   for c in self.cache.get('calendars',[])]
        writable={c['id'] for c in calendars if c['writable']}
        events = [{**e,'writable':e.get('calendar_id') in writable} for e in self.cache.get('events', [])
                  if selected is None or e.get('calendar_id') in selected]
        return dict(status=self.status, configured=bool(self.client), authorized=bool(self.tokens),
                    events=events if valid_day else [],
                    calendars=calendars, writable=bool(writable),
                    write_authorization_required=bool(self.tokens) and not self.has_write_scope(),
                    selected=self.preferences.get('selected', []), timezone=tz_name, date=selected_day, today=today,
                    checked_at=self.cache.get('checked_at'),
                    open_url='https://calendar.google.com/calendar/u/0/r/day/' + selected_day.replace('-', '/'))

    def begin(self, redirect_uri):
        if not self.client:
            raise ValueError('Set up the Google OAuth Desktop app first.')
        uri = urlparse(redirect_uri)
        if uri.scheme != 'http' or uri.hostname not in ('127.0.0.1', 'localhost') or uri.path != '/api/calendar/callback':
            raise ValueError('Invalid calendar callback.')
        verifier, state = secrets.token_urlsafe(48), secrets.token_urlsafe(32)
        challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip('=')
        now = time.time()
        self.pending = {s: p for s, p in self.pending.items() if p['expires'] > now}
        if len(self.pending) >= 4:
            self.pending.clear()
        self.pending[state] = dict(verifier=verifier, redirect_uri=redirect_uri, expires=now+600)
        self.status = 'connecting'
        return AUTH_URL + '?' + urlencode(dict(client_id=self.client['client_id'], redirect_uri=redirect_uri,
            response_type='code', scope=' '.join(SCOPES), access_type='offline', prompt='consent',
            code_challenge=challenge, code_challenge_method='S256', state=state))

    async def complete(self, http, state, code):
        flow = self.pending.pop(state, None)
        if not flow or flow['expires'] < time.time() or not isinstance(code, str) or not code or not self.client:
            raise ValueError('Calendar sign-in expired. Please try connecting again.')
        async with self.lock:
            generation = self.generation
            data = await self._token(http, dict(code=code, redirect_uri=flow['redirect_uri'],
                code_verifier=flow['verifier'], grant_type='authorization_code', **self.client))
            if generation != self.generation:
                raise ValueError('Calendar connection was cancelled.')
            granted = set(data.get('scope', '').split())
            if granted and (not granted.intersection({EVENTS_READ_SCOPE,EVENTS_WRITE_SCOPE,FULL_CALENDAR_SCOPE})
                    or not granted.intersection({CALENDAR_LIST_SCOPE,FULL_CALENDAR_SCOPE})):
                raise ValueError('Allow calendar event access and read access to the calendar list to connect.')
            if not granted:data['scope']=' '.join(SCOPES)

            if not data.get('refresh_token'):
                raise ValueError('Google did not provide offline access. Please connect again.')
            self.tokens = data
            self.tokens['expires_at'] = time.time() + max(0, float(data.get('expires_in', 3600)))
            private_json(self.token_path, self.tokens)
        await self.refresh(http)

    async def _token(self, http, data):
        async with http.post(TOKEN_URL, data=data, timeout=aiohttp.ClientTimeout(total=15)) as response:
            if response.status != 200:
                if response.status in (400, 401):
                    raise CalendarAccessError('Calendar authorization is required.')
                raise OSError('Google sign-in is temporarily unavailable.')
            result = await response.json()
            if not isinstance(result, dict) or not isinstance(result.get('access_token'), str):
                raise ValueError('Google sign-in returned an invalid response.')
            return {k: result[k] for k in ('access_token', 'refresh_token', 'expires_in', 'scope', 'token_type') if k in result}

    async def _access_token(self, http):
        generation = self.generation
        if not self.client or not self.tokens.get('refresh_token'):
            raise CalendarAccessError('Connect Google Calendar first.')
        if self.tokens.get('access_token') and self.tokens.get('expires_at', 0) > time.time()+60:
            return self.tokens['access_token']
        result = await self._token(http, dict(grant_type='refresh_token', refresh_token=self.tokens['refresh_token'], **self.client))
        if generation != self.generation:
            raise CalendarAccessError('Calendar connection was cancelled.')
        self.tokens.update(result)
        self.tokens['expires_at'] = time.time() + max(0, float(result.get('expires_in', 3600)))
        private_json(self.token_path, self.tokens)
        return self.tokens['access_token']

    async def _get(self, http, token, path, params):
        async with http.get(API_URL+path, params=params, headers={'Authorization':'Bearer '+token},
                            timeout=aiohttp.ClientTimeout(total=12)) as response:
            if response.status == 401:
                self.tokens['expires_at'] = 0
                raise CalendarAccessError('Calendar sign-in needs to be renewed.')
            if response.status != 200:
                raise OSError('Calendar sync is temporarily unavailable.')
            result = await response.json()
            if not isinstance(result, dict):
                raise ValueError('Invalid calendar response.')
            return result

    async def refresh(self, http):
        if not self.client or not self.tokens:
            self.status = 'disconnected' if self.client else 'not_configured'
            return self.snapshot()
        async with self.lock:
            generation = self.generation
            try:
                token = await self._access_token(http)
                calendars = []
                page = None
                for _ in range(4):
                    params = {'maxResults':'100', 'minAccessRole':'reader'}
                    if page: params['pageToken'] = page
                    result = await self._get(http, token, '/users/me/calendarList', params)
                    for c in result.get('items', []):
                        if c.get('deleted') or c.get('hidden') or not isinstance(c.get('id'), str): continue
                        calendars.append(dict(id=c['id'], name=str(c.get('summary') or 'Calendar')[:200],
                                              timezone=str(c.get('timeZone') or 'America/Los_Angeles'), primary=bool(c.get('primary')),
                                              access_role=str(c.get('accessRole') or 'reader'),
                                              writable=self.has_write_scope() and c.get('accessRole') in ('owner','writer')))
                    page = result.get('nextPageToken')
                    if not page: break
                selected = self.preferences.get('selected')
                if selected is None:
                    selected = [c['id'] for c in calendars if c['primary']] or [c['id'] for c in calendars[:1]]
                    self.preferences['selected'] = selected
                    private_json(self.preferences_path, self.preferences)
                active = [c for c in calendars if c['id'] in selected][:5]
                tz_name = next((c['timezone'] for c in calendars if c['primary']), 'America/Los_Angeles')
                tz = zone(tz_name)
                selected_day = self.selected_date(str(tz))
                start = datetime.combine(selected_day, day_time(), tz)
                finish = datetime.combine(selected_day+timedelta(days=1), day_time(), tz)
                async def events_for(calendar):
                    events, page = [], None
                    for _ in range(5):
                        params = dict(timeMin=start.isoformat(), timeMax=finish.isoformat(), singleEvents='true',
                                      orderBy='startTime', showDeleted='false', maxResults='100')
                        if page: params['pageToken'] = page
                        result = await self._get(http, token, '/calendars/'+quote(calendar['id'], safe='')+'/events', params)
                        for event in result.get('items', []):
                            normalized = normalize_event(event, calendar)
                            if normalized: events.append(normalized)
                        page = result.get('nextPageToken')
                        if not page: break
                    return events
                groups = await asyncio.gather(*(events_for(c) for c in active))
                events = [e for group in groups for e in group]
                events.sort(key=lambda e: (not e['all_day'], e['start'], e['calendar_id'], e['id']))
                if generation != self.generation:
                    return self.snapshot()
                self.cache = dict(events=events, calendars=calendars, timezone=str(tz), date=selected_day.isoformat(), checked_at=time.time())
                private_json(self.cache_path, self.cache)
                self.status = 'connected'
            except CalendarAccessError:
                if generation == self.generation:self.status = 'authorization_required'
            except (aiohttp.ClientError, OSError, TimeoutError, ValueError, TypeError, KeyError):
                if generation == self.generation:self.status = 'unavailable'
        return self.snapshot()

    async def query_events(self, http, calendar_id, start, end):
        """Read a bounded interval for explicit transcript action target matching."""
        def instant(value):
            result=value if isinstance(value,datetime) else datetime.fromisoformat(str(value).replace('Z','+00:00'))
            if result.tzinfo is None:raise ValueError('Event lookup needs timezone-aware dates.')
            return result
        begin,finish=instant(start),instant(end)
        if not 0<finish.timestamp()-begin.timestamp()<=32*86400:raise ValueError('Choose an event lookup window of at most 32 days.')
        async with self.lock:
            generation=self.generation
            calendar=next((c for c in self.cache.get('calendars',[]) if c.get('id')==calendar_id),None)
            if not calendar:raise ValueError('Choose a connected calendar.')
            calendar={**calendar,'writable':self.has_write_scope() and calendar.get('access_role') in ('owner','writer')}
            token=await self._access_token(http)
            events=[];page=None
            for _ in range(5):
                params=dict(timeMin=begin.isoformat(),timeMax=finish.isoformat(),singleEvents='true',orderBy='startTime',showDeleted='false',maxResults='100')
                if page:params['pageToken']=page
                result=await self._get(http,token,'/calendars/'+quote(calendar_id,safe='')+'/events',params)
                for event in result.get('items',[]):
                    normalized=normalize_event(event,calendar)
                    if normalized:events.append(normalized)
                page=result.get('nextPageToken')
                if not page:break
            if page:raise ValueError('Too many calendar events to choose a target safely.')
            if generation!=self.generation:raise CalendarAccessError('Calendar connection changed.')
            return events

    def _writable_calendar(self, identity):
        if not self.has_write_scope():
            raise CalendarAccessError('Reconnect Google Calendar and allow event editing to make changes.')
        if not isinstance(identity,str) or not identity or len(identity)>1000:
            raise ValueError('Choose a connected calendar.')
        calendar=next((c for c in self.cache.get('calendars',[]) if c.get('id')==identity),None)
        if not calendar or calendar.get('access_role') not in ('owner','writer'):
            raise CalendarAccessError('Choose a calendar you have permission to edit.')
        return {**calendar,'writable':True}

    async def _write_event(self, http, method, calendar_id, fields=None, event_id=None):
        body=event_fields(fields) if method!='DELETE' else None
        if method in ('PATCH','DELETE') and (not isinstance(event_id,str) or not event_id or len(event_id)>500):
            raise ValueError('Choose a valid calendar event.')
        if method=='PATCH':
            for key in ('start','end'):
                body[key]['dateTime' if fields['all_day'] else 'date']=None
                if fields['all_day']:body[key]['timeZone']=None
        async with self.lock:
            generation=self.generation
            calendar=self._writable_calendar(calendar_id)
            token=await self._access_token(http)
            # A refresh can change the granted scopes; check again before sending a write.
            self._writable_calendar(calendar_id)
            path='/calendars/'+quote(calendar_id,safe='')+'/events'
            if event_id is not None:path+='/'+quote(event_id,safe='')
            headers={'Authorization':'Bearer '+token}
            cached=next((e for e in self.cache.get('events',[]) if e.get('calendar_id')==calendar_id and e.get('id')==event_id),None)
            etag=(cached or {}).get('etag')
            if isinstance(etag,str) and len(etag)<2000 and not any(c in etag for c in ('\r','\n')):headers['If-Match']=etag
            options=dict(headers=headers,params={'sendUpdates':'none'},timeout=aiohttp.ClientTimeout(total=15))
            if body is not None:options['json']=body
            try:
                async with http.request(method,API_URL+path,**options) as response:
                    if response.status==401:
                        self.tokens['expires_at']=0
                        raise CalendarAccessError('Calendar sign-in needs to be renewed before editing.')
                    if response.status==403:raise CalendarAccessError('Google Calendar did not allow this edit. Reconnect or check calendar permissions.')
                    if response.status==412:raise ValueError('This event changed elsewhere. Refresh the agenda before editing it again.')
                    if response.status in (404,410):raise ValueError('This event or calendar no longer exists. Refresh the agenda.')
                    if response.status not in ((204,) if method=='DELETE' else (200,201)):
                        raise OSError('Calendar could not confirm this change. Check Google Calendar before retrying.')
                    result=None if method=='DELETE' else await response.json()
            except (aiohttp.ClientError,TimeoutError):
                raise OSError('Calendar could not confirm this change. Check Google Calendar before retrying.') from None
            if generation!=self.generation:
                raise CalendarAccessError('The calendar connection changed. Check Google Calendar before retrying the edit.')
            normalized=None if method=='DELETE' else normalize_event(result,calendar)
            if method!='DELETE' and normalized is None:
                raise ValueError('Calendar changed, but its response could not be read. Refresh before retrying.')
            # Apply the confirmed result locally before refreshing, so stale cache cannot undo it.
            self.cache['events']=[e for e in self.cache.get('events',[]) if not (e.get('calendar_id')==calendar_id and e.get('id')==event_id)]
            if normalized:
                tz=zone(self.cache.get('timezone',calendar.get('timezone')))
                selected_day=self.selected_date(str(tz))
                begin=datetime.combine(selected_day,day_time(),tz).timestamp()
                finish=datetime.combine(selected_day+timedelta(days=1),day_time(),tz).timestamp()
                if normalized['start']<finish and normalized['end']>begin:self.cache['events'].append(normalized)
            private_json(self.cache_path,self.cache)
        await self.refresh(http)
        return normalized

    async def create_event(self, http, calendar_id, fields):
        return await self._write_event(http,'POST',calendar_id,fields=fields)

    async def update_event(self, http, calendar_id, event_id, fields):
        return await self._write_event(http,'PATCH',calendar_id,fields=fields,event_id=event_id)

    async def delete_event(self, http, calendar_id, event_id):
        await self._write_event(http,'DELETE',calendar_id,event_id=event_id)
        return {'deleted':True,'id':event_id,'calendar_id':calendar_id}

    def select(self, identities):
        available = {c['id'] for c in self.cache.get('calendars', [])}
        if (not isinstance(identities, list) or not all(isinstance(i,str) and i in available for i in identities)
                or len(identities)>5):
            raise ValueError('Choose up to five calendars from the connected account.')
        self.preferences['selected'] = list(dict.fromkeys(identities))
        private_json(self.preferences_path, self.preferences)

    def disconnect(self):
        self.generation += 1
        self.tokens = {};self.cache = {};self.preferences = {};self.pending.clear()
        for path in (self.token_path, self.cache_path, self.preferences_path):
            path.unlink(missing_ok=True)
        self.status = 'disconnected' if self.client else 'not_configured'
