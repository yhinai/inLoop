"""Calendar read-only authorization, date boundaries, and privacy boundaries."""
import asyncio
from datetime import datetime
import json
from pathlib import Path
import stat
import tempfile
import time
import unittest
from unittest import mock
from urllib.parse import parse_qs,urlparse

from aiohttp.test_utils import TestClient,TestServer
from inloop_calendar import CalendarAgenda,normalize_event,zone,SCOPES
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

class FakeCalendarResponse:
    def __init__(self,status=200,payload=None,on_enter=None):
        self.status=status;self.payload=payload;self.on_enter=on_enter
    async def __aenter__(self):
        if self.on_enter:self.on_enter()
        return self
    async def __aexit__(self,*args):pass
    async def json(self):return self.payload

class FakeCalendarHTTP:
    def __init__(self,response):self.response=response;self.calls=[]
    def request(self,*args,**kwargs):
        self.calls.append((args,kwargs));return self.response

class CalendarEditTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        from inloop_calendar import EVENTS_WRITE_SCOPE,CALENDAR_LIST_SCOPE
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        self.agenda=CalendarAgenda(self.root);self.agenda.configure(CLIENT)
        self.agenda.tokens=dict(refresh_token='test-refresh',access_token='test-access',expires_at=time.time()+3600,scope=' '.join((EVENTS_WRITE_SCOPE,CALENDAR_LIST_SCOPE)))
        self.identity='personal@example.com/secondary'
        self.calendar=dict(id=self.identity,name='Personal',timezone='America/Los_Angeles',access_role='owner',writable=True)
        self.agenda.cache=dict(calendars=[self.calendar],events=[],date=datetime.now(zone('America/Los_Angeles')).date().isoformat())
        self.fields=dict(title='Demo review',start='2026-11-15T10:00',end='2026-11-15T10:30',all_day=False,timezone='America/Los_Angeles',description='Bring the prototype.')
        self.provider=dict(id='event/id?x',summary='Demo review',start={'dateTime':'2026-11-15T10:00:00-08:00','timeZone':'America/Los_Angeles'},end={'dateTime':'2026-11-15T10:30:00-08:00'},description='Bring the prototype.',etag='"version-one"')
    def tearDown(self):self.temp.cleanup()

    async def test_create_uses_exact_fields_encoded_calendar_and_no_invites(self):
        from inloop_calendar import API_URL
        http=FakeCalendarHTTP(FakeCalendarResponse(payload=self.provider))
        with mock.patch.object(self.agenda,'refresh',new=mock.AsyncMock()) as refresh:
            event=await self.agenda.create_event(http,self.identity,self.fields)
        (method,url),options=http.calls[0]
        self.assertEqual(method,'POST')
        self.assertEqual(url,API_URL+'/calendars/personal%40example.com%2Fsecondary/events')
        self.assertEqual(options['params'],{'sendUpdates':'none'})
        self.assertEqual(options['json']['start'],{'dateTime':'2026-11-15T10:00:00-08:00','timeZone':'America/Los_Angeles'})
        self.assertEqual(set(options['json']),{'summary','start','end','description'})
        self.assertNotIn('attendees',options['json'])
        self.assertEqual(event['description'],'Bring the prototype.')
        self.assertEqual(event['timezone'],'America/Los_Angeles')
        self.assertEqual(event['etag'],'"version-one"')
        self.assertTrue(event['writable'])
        refresh.assert_awaited_once_with(http)

    async def test_patch_and_delete_encode_event_and_use_etag_without_overwriting_attendees(self):
        event=normalize_event(self.provider,self.calendar);self.agenda.cache['events']=[event]
        http=FakeCalendarHTTP(FakeCalendarResponse(payload=self.provider))
        fields={key:value for key,value in self.fields.items() if key!='description'}
        with mock.patch.object(self.agenda,'refresh',new=mock.AsyncMock()):
            await self.agenda.update_event(http,self.identity,event['id'],fields)
        (method,url),options=http.calls[0]
        self.assertEqual(method,'PATCH');self.assertTrue(url.endswith('/events/event%2Fid%3Fx'))
        self.assertEqual(options['headers']['If-Match'],'"version-one"')
        self.assertNotIn('attendees',options['json']);self.assertNotIn('description',options['json'])
        http=FakeCalendarHTTP(FakeCalendarResponse(status=204))
        with mock.patch.object(self.agenda,'refresh',new=mock.AsyncMock()):
            result=await self.agenda.delete_event(http,self.identity,event['id'])
        self.assertTrue(result['deleted']);self.assertEqual(self.agenda.cache['events'],[])
        self.assertEqual(http.calls[0][0][0],'DELETE');self.assertNotIn('json',http.calls[0][1])
        self.assertEqual(http.calls[0][1]['params'],{'sendUpdates':'none'})

    async def test_missing_event_id_cannot_target_the_event_collection(self):
        http=FakeCalendarHTTP(FakeCalendarResponse(payload=self.provider))
        for identity in (None,'',True):
            with self.subTest(identity=identity):
                with self.assertRaises(ValueError):await self.agenda.update_event(http,self.identity,identity,self.fields)
                with self.assertRaises(ValueError):await self.agenda.delete_event(http,self.identity,identity)
        self.assertEqual(http.calls,[])

    async def test_switching_to_all_day_clears_prior_datetime_fields_in_patch(self):
        provider={**self.provider,'start':{'date':'2026-11-15'},'end':{'date':'2026-11-16'}}
        http=FakeCalendarHTTP(FakeCalendarResponse(payload=provider))
        fields={**self.fields,'all_day':True,'start':'2026-11-15','end':'2026-11-16'}
        with mock.patch.object(self.agenda,'refresh',new=mock.AsyncMock()):
            await self.agenda.update_event(http,self.identity,'event',fields)
        for key in ('start','end'):
            self.assertIsNone(http.calls[0][1]['json'][key]['dateTime'])
            self.assertIsNone(http.calls[0][1]['json'][key]['timeZone'])

    async def test_readonly_token_preserves_agenda_but_cannot_send_write(self):
        from inloop_calendar import EVENTS_READ_SCOPE,CALENDAR_LIST_SCOPE,CalendarAccessError
        self.agenda.tokens['scope']=' '.join((EVENTS_READ_SCOPE,CALENDAR_LIST_SCOPE))
        self.agenda.cache['events']=[normalize_event(self.provider,self.calendar)]
        value=self.agenda.snapshot()
        self.assertTrue(value['authorized']);self.assertTrue(value['write_authorization_required'])
        self.assertFalse(value['writable']);self.assertFalse(value['events'][0]['writable'])
        http=FakeCalendarHTTP(FakeCalendarResponse(payload=self.provider))
        with self.assertRaises(CalendarAccessError):await self.agenda.create_event(http,self.identity,self.fields)
        with self.assertRaises(CalendarAccessError):await self.agenda.delete_event(http,self.identity,'event')
        self.assertEqual(http.calls,[])

    async def test_reader_role_or_unknown_calendar_cannot_send_write(self):
        from inloop_calendar import CalendarAccessError
        self.calendar['access_role']='reader'
        http=FakeCalendarHTTP(FakeCalendarResponse(payload=self.provider))
        for identity in (self.identity,'unknown'):
            with self.assertRaises(CalendarAccessError):await self.agenda.create_event(http,identity,self.fields)
        self.assertEqual(http.calls,[])

    async def test_write_permissions_rechecked_after_token_refresh(self):
        from inloop_calendar import CalendarAccessError,EVENTS_READ_SCOPE
        async def refresh_token(http):
            self.agenda.tokens['scope']=EVENTS_READ_SCOPE
            return 'refreshed-token'
        http=FakeCalendarHTTP(FakeCalendarResponse(payload=self.provider))
        with mock.patch.object(self.agenda,'_access_token',side_effect=refresh_token):
            with self.assertRaises(CalendarAccessError):await self.agenda.create_event(http,self.identity,self.fields)
        self.assertEqual(http.calls,[])

    async def test_provider_errors_are_safe_and_never_silently_retried(self):
        from inloop_calendar import CalendarAccessError
        for status,error in [(401,CalendarAccessError),(403,CalendarAccessError),(412,ValueError),(404,ValueError),(429,OSError),(500,OSError)]:
            self.agenda.tokens['expires_at']=time.time()+3600
            http=FakeCalendarHTTP(FakeCalendarResponse(status=status,payload={'private_token':'must not appear'}))
            with self.subTest(status=status),self.assertRaises(error) as caught:
                await self.agenda.update_event(http,self.identity,'event',self.fields)
            self.assertNotIn('private_token',str(caught.exception))
            self.assertEqual(len(http.calls),1)
            if status==401:self.assertEqual(self.agenda.tokens['expires_at'],0)

    async def test_disconnect_during_write_does_not_restore_private_cache(self):
        from inloop_calendar import CalendarAccessError
        http=FakeCalendarHTTP(FakeCalendarResponse(payload=self.provider,on_enter=self.agenda.disconnect))
        with self.assertRaises(CalendarAccessError):await self.agenda.create_event(http,self.identity,self.fields)
        self.assertEqual(self.agenda.tokens,{})
        self.assertEqual(self.agenda.cache,{})
        self.assertFalse(self.agenda.cache_path.exists())

    async def test_refresh_exposes_actual_access_role_and_write_permission(self):
        async def get(http,token,path,params):
            if path.endswith('calendarList'):return {'items':[dict(id=self.identity,summary='Personal',primary=True,accessRole='owner')]}
            return {'items':[self.provider]}
        with mock.patch.object(self.agenda,'_get',side_effect=get):
            result=await self.agenda.refresh(None)
        self.assertTrue(result['writable'])
        self.assertEqual(result['calendars'][0]['access_role'],'owner')
        self.assertTrue(result['calendars'][0]['writable'])
        self.assertFalse(result['write_authorization_required'])

class CalendarFormValidationTests(unittest.TestCase):
    def form(self,**changes):
        return dict(title='Review',start='2026-11-15T10:00',end='2026-11-15T11:00',all_day=False,timezone='America/Los_Angeles',**changes)

    def test_all_day_dates_are_exclusive_and_never_convert_to_utc_midnight(self):
        from inloop_calendar import event_fields
        form=self.form();form.update(all_day=True,start='2026-03-08',end='2026-03-09')
        result=event_fields(form)
        self.assertEqual(result['start'],{'date':'2026-03-08'})
        self.assertEqual(result['end'],{'date':'2026-03-09'})
        form['end']='2026-03-08'
        with self.assertRaises(ValueError):event_fields(form)

    def test_rejects_unknown_fields_invalid_times_and_bad_form_values(self):
        from inloop_calendar import event_fields
        changes=[{'attendees':[{'email':'person@example.com'}]},{'recurrence':['RRULE:FREQ=DAILY']},{'title':''},{'title':True},{'all_day':'false'},{'timezone':'not/a/timezone'},{'start':123},{'start':'bad'},{'end':'2026-11-15T09:00'},{'description':{}},{'description':'x'*10001}]
        for change in changes:
            with self.subTest(change=list(change)),self.assertRaises(ValueError):event_fields({**self.form(),**change})

    def test_clock_change_gaps_and_ambiguous_local_times_require_explicit_choices(self):
        from inloop_calendar import event_fields
        for start,end in [('2026-03-08T02:30','2026-03-08T04:00'),('2026-11-01T01:30','2026-11-01T03:00')]:
            with self.subTest(start=start),self.assertRaises(ValueError):event_fields({**self.form(),'start':start,'end':end})
        result=event_fields({**self.form(),'start':'2026-11-01T01:30:00-07:00','end':'2026-11-01T01:30:00-08:00'})
        self.assertEqual(result['start']['dateTime'],'2026-11-01T01:30:00-07:00')

class CalendarDateNavigationTests(unittest.IsolatedAsyncioTestCase):
    async def test_selected_day_persists_drives_query_and_hides_other_day_cache(self):
        with tempfile.TemporaryDirectory() as directory:
            service=CalendarAgenda(directory);service.configure(CLIENT)
            service.tokens=dict(refresh_token='test-refresh',access_token='test-access',expires_at=time.time()+3600,scope=' '.join(SCOPES))
            actual_today=service.snapshot()['today']
            service.cache=dict(date=actual_today,events=[{'id':'old','calendar_id':'primary'}])
            service.select_date('2026-11-18')
            self.assertEqual(service.snapshot()['date'],'2026-11-18')
            self.assertEqual(service.snapshot()['today'],actual_today)
            if actual_today!='2026-11-18':self.assertEqual(service.snapshot()['events'],[])
            queried=[]
            async def get(http,token,path,params):
                if path.endswith('calendarList'):return {'items':[dict(id='primary',summary='Main',primary=True,accessRole='owner',timeZone='America/Los_Angeles')]}
                queried.append(params)
                return {'items':[dict(id='deadline',summary='Paper deadline',start={'dateTime':'2026-11-18T16:00:00-08:00'},end={'dateTime':'2026-11-18T17:00:00-08:00'})]}
            with mock.patch.object(service,'_get',side_effect=get):await service.refresh(None)
            self.assertTrue(queried[0]['timeMin'].startswith('2026-11-18T00:00:00'))
            self.assertTrue(queried[0]['timeMax'].startswith('2026-11-19T00:00:00'))
            value=service.snapshot()
            self.assertEqual(value['events'][0]['title'],'Paper deadline')
            self.assertTrue(value['events'][0]['writable'])
            self.assertTrue(value['open_url'].endswith('/2026/11/18'))
            reopened=CalendarAgenda(directory)
            self.assertEqual(reopened.snapshot()['date'],'2026-11-18')

    async def test_bad_selected_dates_are_rejected_without_saving(self):
        with tempfile.TemporaryDirectory() as directory:
            service=CalendarAgenda(directory)
            for value in [None,True,'2026-02-30','2026-1-1','2026-11-18T10:00','not-a-date']:
                with self.subTest(value=value),self.assertRaises(ValueError):service.select_date(value)
            self.assertFalse(service.preferences_path.exists())
