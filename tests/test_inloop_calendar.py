"""Calendar read-only authorization, date boundaries, and privacy boundaries."""
import asyncio
from datetime import datetime, timedelta
import json
from pathlib import Path
import stat
import tempfile
import time
import unittest
from unittest import mock
from urllib.parse import parse_qs,urlparse

from aiohttp.test_utils import TestClient,TestServer
from inloop_calendar import CalendarAgenda,normalize_event,zone,SCOPES,PAST_DAYS,FUTURE_DAYS
from inloop_app import InLoop,application

CLIENT={'installed':{'client_id':'test.apps.googleusercontent.com','client_secret':'test-only'}}

class CalendarTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        self.agenda=CalendarAgenda(self.root)
    def tearDown(self):self.temp.cleanup()

    async def test_missing_connection_is_explicit_and_no_secret_enters_snapshot(self):
        self.assertEqual(self.agenda.snapshot()['status'],'not_configured')
        self.agenda.configure(CLIENT)
        self.assertEqual(stat.S_IMODE(self.agenda.client_path.stat().st_mode),0o600)
        self.assertEqual(self.agenda.snapshot()['status'],'disconnected')
        self.assertNotIn('test-only',json.dumps(self.agenda.snapshot()))
        for invalid in ({'web':CLIENT['installed']},{'installed':{'client_id':'bad','client_secret':'x'}}):
            with self.assertRaises(ValueError):self.agenda.configure(invalid)

    async def test_oauth_pkce_scopes_and_state_are_checked_and_single_use(self):
        self.agenda.configure(CLIENT)
        url=self.agenda.begin('http://127.0.0.1:8790/api/calendar/callback')
        query=parse_qs(urlparse(url).query);state=query['state'][0]
        self.assertEqual(urlparse(url).hostname,'accounts.google.com')
        self.assertEqual(set(query['scope'][0].split()),set(SCOPES))
        self.assertEqual(query['code_challenge_method'],['S256'])
        self.assertNotIn('client_secret',query)
        self.assertNotIn(self.agenda.pending[state]['verifier'],url)
        with self.assertRaises(ValueError):await self.agenda.complete(None,'wrong','code')
        with self.assertRaises(ValueError):self.agenda.begin('https://evil.example/api/calendar/callback')
        token=dict(access_token='test-access',refresh_token='test-refresh',scope=' '.join(SCOPES),expires_in=3600)
        with mock.patch.object(self.agenda,'_token',new=mock.AsyncMock(return_value=token)),mock.patch.object(self.agenda,'refresh',new=mock.AsyncMock()):
            await self.agenda.complete(None,state,'sample-code')
        self.assertEqual(stat.S_IMODE(self.agenda.token_path.stat().st_mode),0o600)
        self.assertNotIn('test-refresh',json.dumps(self.agenda.snapshot()))
        with self.assertRaises(ValueError):await self.agenda.complete(None,state,'sample-code')

    async def test_missing_permissions_and_expired_flow_do_not_save_tokens(self):
        self.agenda.configure(CLIENT)
        state=parse_qs(urlparse(self.agenda.begin('http://localhost:8790/api/calendar/callback')).query)['state'][0]
        with mock.patch.object(self.agenda,'_token',new=mock.AsyncMock(return_value={'scope':SCOPES[0],'access_token':'test','refresh_token':'test'})):
            with self.assertRaises(ValueError):await self.agenda.complete(None,state,'code')
        self.assertFalse(self.agenda.token_path.exists())
        state=parse_qs(urlparse(self.agenda.begin('http://localhost:8790/api/calendar/callback')).query)['state'][0]
        self.agenda.pending[state]['expires']=0
        with self.assertRaises(ValueError):await self.agenda.complete(None,state,'code')

    async def test_all_day_dst_and_cancelled_declined_instances(self):
        c=dict(id='primary',name='Personal',timezone='America/Los_Angeles')
        event=dict(id='one',start={'date':'2026-03-08'},end={'date':'2026-03-09'},summary='All day',htmlLink='javascript:alert(1)')
        item=normalize_event(event,c)
        self.assertEqual(item['end']-item['start'],23*3600)
        self.assertTrue(item['all_day']);self.assertEqual(item['html_url'],'https://calendar.google.com/')
        self.assertIsNone(normalize_event({**event,'status':'cancelled'},c))
        self.assertIsNone(normalize_event({**event,'attendees':[{'self':True,'responseStatus':'declined'}]},c))
        self.assertIsNone(normalize_event({**event,'end':{'date':'2026-03-07'}},c))

    async def test_sync_filters_calendar_selection_and_keeps_cache_on_failure(self):
        self.agenda.configure(CLIENT);self.agenda.tokens={'refresh_token':'test'}
        today=datetime.now(zone('America/Los_Angeles')).date().isoformat()
        calls=[]
        async def get(http,token,path,params):
            calls.append((path,params))
            if path.endswith('calendarList'):return {'items':[{'id':'main@example.com','primary':True,'summary':'Main','timeZone':'America/Los_Angeles'}]}
            return {'items':[dict(id='one',summary='Demo',start={'dateTime':today+'T14:00:00-08:00'},end={'dateTime':today+'T15:00:00-08:00'})]}
        with mock.patch.object(self.agenda,'_access_token',new=mock.AsyncMock(return_value='test')),mock.patch.object(self.agenda,'_get',side_effect=get):
            await self.agenda.refresh(None)
        value=self.agenda.snapshot();self.assertEqual(value['status'],'connected');self.assertEqual(len(value['events']),1)
        self.assertIn('main%40example.com',calls[1][0]);self.assertEqual(calls[1][1]['singleEvents'],'true')
        with self.assertRaises(ValueError):self.agenda.select(['unknown'])
        with mock.patch.object(self.agenda,'_access_token',new=mock.AsyncMock(side_effect=OSError())):
            await self.agenda.refresh(None)
        self.assertEqual(self.agenda.status,'unavailable');self.assertEqual(len(self.agenda.snapshot()['events']),1)
        self.agenda.cache['date']='2000-01-01';self.assertEqual(self.agenda.snapshot()['events'],[])
        self.agenda.disconnect();self.assertEqual(self.agenda.snapshot()['events'],[]);self.assertFalse(self.agenda.cache_path.exists())

    async def test_sync_fetches_a_browsable_window_around_today(self):
        self.agenda.configure(CLIENT);self.agenda.tokens={'refresh_token':'test'}
        tz=zone('America/Los_Angeles');today=datetime.now(tz).date()
        calls=[]
        async def get(http,token,path,params):
            calls.append((path,params))
            if path.endswith('calendarList'):return {'items':[{'id':'main@example.com','primary':True,'summary':'Main','timeZone':'America/Los_Angeles'}]}
            later=(today+timedelta(days=3)).isoformat()
            return {'items':[dict(id='later',summary='Later',start={'dateTime':later+'T09:00:00-08:00'},end={'dateTime':later+'T10:00:00-08:00'})]}
        with mock.patch.object(self.agenda,'_access_token',new=mock.AsyncMock(return_value='test')),mock.patch.object(self.agenda,'_get',side_effect=get):
            await self.agenda.refresh(None)
        params=calls[1][1]
        self.assertEqual(datetime.fromisoformat(params['timeMin']).date(),today-timedelta(days=PAST_DAYS))
        self.assertEqual(datetime.fromisoformat(params['timeMax']).date(),today+timedelta(days=FUTURE_DAYS+1))
        value=self.agenda.snapshot()
        self.assertEqual([e['id'] for e in value['events']],['later'])
        self.assertEqual(value['range_start'],(today-timedelta(days=PAST_DAYS)).isoformat())
        self.assertEqual(value['range_end'],(today+timedelta(days=FUTURE_DAYS)).isoformat())

class CalendarApiTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp=tempfile.TemporaryDirectory();self.workspace=InLoop(Path(self.temp.name)/'app.sqlite3')
        self.client=TestClient(TestServer(application(self.workspace,workers=False)));await self.client.start_server()
    async def asyncTearDown(self):
        await self.client.close();self.workspace.store.db.close();self.temp.cleanup()
    async def test_setup_connect_csrf_and_callback_state(self):
        r=await self.client.post('/api/calendar/setup',json=CLIENT);self.assertEqual(r.status,403)
        headers={'X-inLoop-CSRF':self.workspace.nonce}
        r=await self.client.post('/api/calendar/setup',json=CLIENT,headers=headers);self.assertEqual(r.status,200)
        r=await self.client.post('/api/calendar/connect',json={},headers=headers);self.assertEqual(r.status,200)
        self.assertEqual(urlparse((await r.json())['url']).hostname,'accounts.google.com')
        r=await self.client.get('/api/calendar/callback?state=wrong&code=bad');self.assertEqual(r.status,400)
        r=await self.client.get('/api/state');value=await r.json();self.assertEqual(value['calendar']['status'],'connecting')
        self.assertNotIn('test-only',json.dumps(value))
        r=await self.client.get('/assets/calendar.js');self.assertEqual(r.status,200)

class CalendarDisconnectRaceTests(unittest.IsolatedAsyncioTestCase):
    async def test_disconnect_during_token_refresh_cannot_restore_tokens(self):
        with tempfile.TemporaryDirectory() as directory:
            service=CalendarAgenda(directory);service.configure(CLIENT)
            service.tokens={'refresh_token':'test-refresh','expires_at':0}
            began,finish=asyncio.Event(),asyncio.Event()
            async def token(http,data):
                began.set();await finish.wait()
                return {'access_token':'test-access','expires_in':3600}
            with mock.patch.object(service,'_token',side_effect=token):
                job=asyncio.create_task(service._access_token(None));await began.wait()
                service.disconnect();finish.set()
                from inloop_calendar import CalendarAccessError
                with self.assertRaises(CalendarAccessError):await job
            self.assertEqual(service.tokens,{})
            self.assertFalse(service.token_path.exists())
