"""Read-only Google Calendar agenda with local OAuth, PKCE and private storage."""
import asyncio
import base64
from datetime import date, datetime, time as day_time, timedelta
import hashlib
import json
import math
import os
from pathlib import Path
import secrets
import time
from urllib.parse import urlencode, urlparse, quote
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import aiohttp

AUTH_URL = 'https://accounts.google.com/o/oauth2/v2/auth'
TOKEN_URL = 'https://oauth2.googleapis.com/token'
API_URL = 'https://www.googleapis.com/calendar/v3'
SCOPES = ('https://www.googleapis.com/auth/calendar.events.readonly',
          'https://www.googleapis.com/auth/calendar.calendarlist.readonly')
# Days around today fetched in each sync, so the agenda can step between days.
PAST_DAYS = 7
FUTURE_DAYS = 14


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
                start=begin, end=finish, all_day=all_day, html_url=link)


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

    def snapshot(self):
        tz_name = self.cache.get('timezone', 'America/Los_Angeles')
        current = datetime.now(zone(tz_name)).date()
        today = current.isoformat()
        valid_day = self.cache.get('date') == today
        selected = self.preferences.get('selected')
        events = [e for e in self.cache.get('events', []) if selected is None or e.get('calendar_id') in selected]
        return dict(status=self.status, configured=bool(self.client), authorized=bool(self.tokens),
                    events=events if valid_day else [],
                    calendars=self.cache.get('calendars', []),
                    selected=self.preferences.get('selected', []), timezone=tz_name, date=today,
                    range_start=(current-timedelta(days=PAST_DAYS)).isoformat(),
                    range_end=(current+timedelta(days=FUTURE_DAYS)).isoformat(),
                    checked_at=self.cache.get('checked_at'),
                    open_url='https://calendar.google.com/calendar/u/0/r/day/' + today.replace('-', '/'))

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
            if granted and not set(SCOPES).issubset(granted):
                raise ValueError('Allow read access to calendar events and the calendar list to connect.')
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
                                              timezone=str(c.get('timeZone') or 'America/Los_Angeles'), primary=bool(c.get('primary'))))
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
                today = datetime.now(tz).date()
                start = datetime.combine(today-timedelta(days=PAST_DAYS), day_time(), tz)
                finish = datetime.combine(today+timedelta(days=FUTURE_DAYS+1), day_time(), tz)
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
                self.cache = dict(events=events, calendars=calendars, timezone=str(tz), date=today.isoformat(), checked_at=time.time())
                private_json(self.cache_path, self.cache)
                self.status = 'connected'
            except CalendarAccessError:
                if generation == self.generation:self.status = 'authorization_required'
            except (aiohttp.ClientError, OSError, TimeoutError, ValueError, TypeError, KeyError):
                if generation == self.generation:self.status = 'unavailable'
        return self.snapshot()

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
