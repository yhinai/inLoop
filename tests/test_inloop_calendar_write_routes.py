"""Event write routes enforce local CSRF and expose useful, secret-free failures."""
from pathlib import Path
import tempfile
import unittest
from unittest.mock import AsyncMock, patch

from aiohttp.test_utils import TestClient, TestServer
from inloop_app import InLoop, application
from inloop_calendar import CalendarAccessError


class CalendarWriteRouteTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.workspace=InLoop(Path(self.temp.name)/'app.sqlite3')
        self.client=TestClient(TestServer(application(self.workspace,workers=False)))
        await self.client.start_server()
        self.headers={'X-inLoop-CSRF':self.workspace.nonce}
        self.fields=dict(title='Submit paper',start='2026-11-18T17:00',end='2026-11-18T17:30',all_day=False,timezone='America/Los_Angeles')

    async def asyncTearDown(self):
        await self.client.close();self.workspace.store.db.close();self.temp.cleanup()

    async def test_create_edit_delete_are_explicit_and_use_exact_selected_ids(self):
        event=dict(id='event-one',title='Submit paper')
        for method,path,name in [('post','/api/calendar/events','create_event'),
                                 ('patch','/api/calendar/events/event-one','update_event'),
                                 ('delete','/api/calendar/events/event-one','delete_event')]:
            payload=dict(calendar_id='primary@example.com',event=self.fields)
            with patch.object(self.workspace.calendar,name,AsyncMock(return_value=event)) as operation:
                r=await getattr(self.client,method)(path,json=payload)
                self.assertEqual(r.status,403);operation.assert_not_awaited()
                r=await getattr(self.client,method)(path,json=payload,headers=self.headers)
                self.assertEqual(r.status,200);self.assertIn('calendar',await r.json())
                args=operation.await_args.args
                self.assertEqual(args[1],'primary@example.com')
                if method=='post':self.assertEqual(args[2],self.fields)
                else:self.assertEqual(args[2],'event-one')
                if method=='patch':self.assertEqual(args[3],self.fields)

    async def test_authorization_required_is_explicit_and_does_not_fall_back(self):
        with patch.object(self.workspace.calendar,'create_event',AsyncMock(side_effect=CalendarAccessError('Reconnect Google Calendar to allow editing.'))) as operation:
            r=await self.client.post('/api/calendar/events',json=dict(calendar_id='primary',event=self.fields),headers=self.headers)
            self.assertEqual(r.status,403)
            self.assertIn('Reconnect',(await r.json())['error'])
            self.assertEqual(operation.await_count,1)

    async def test_provider_failure_has_no_response_body_or_token(self):
        with patch.object(self.workspace.calendar,'create_event',AsyncMock(side_effect=OSError('private provider response'))):
            r=await self.client.post('/api/calendar/events',json=dict(calendar_id='primary',event=self.fields),headers=self.headers)
            self.assertEqual(r.status,502);self.assertNotIn('private',await r.text())

    async def test_select_date_is_local_and_csrf_protected(self):
        r=await self.client.post('/api/calendar/date',json={'date':'2026-11-18'})
        self.assertEqual(r.status,403)
        r=await self.client.post('/api/calendar/date',json={'date':'2026-11-18'},headers=self.headers)
        self.assertEqual(r.status,200)
        self.assertEqual(self.workspace.calendar.snapshot()['date'],'2026-11-18')

    async def test_invalid_request_does_not_call_provider(self):
        with patch.object(self.workspace.calendar,'create_event',AsyncMock()) as operation:
            for data in [[],{},dict(calendar_id='primary',event=[]),dict(calendar_id=2,event=self.fields)]:
                r=await self.client.post('/api/calendar/events',json=data,headers=self.headers)
                self.assertEqual(r.status,400)
            operation.assert_not_awaited()


if __name__=='__main__':unittest.main()
