"""Automatic spoken calendar requests use closed decisions, exact targets and replay protection."""
from datetime import datetime,timedelta
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest import mock

from inloop_calendar_decisions import CalendarAutomation,TZ,parsed_request,choice_answer,OPERATIONS

class CalendarParserTests(unittest.TestCase):
    def setUp(self):self.anchor=datetime(2030,5,6,10,tzinfo=TZ).timestamp() # Monday
    def test_date_time_is_anchored_to_speech_and_default_duration_is_30_minutes(self):
        result=parsed_request('Schedule design review tomorrow at 5 PM.',self.anchor)
        self.assertEqual(result['fields'],dict(title='design review',start='2030-05-07T17:00',end='2030-05-07T17:30',all_day=False,timezone='America/Los_Angeles'))
    def test_weekday_iso_date_explicit_duration_and_range(self):
        for text,day,end in [('Create paper deadline this Wednesday at 17:00 for 45 minutes.','2030-05-08','17:45'),('Schedule review 2030-05-09 from 5pm to 6pm.','2030-05-09','18:00')]:
            with self.subTest(text=text):
                value=parsed_request(text,self.anchor)
                self.assertTrue(value['fields']['start'].startswith(day))
                self.assertTrue(value['fields']['end'].endswith(end))
    def test_missing_and_ambiguous_dates_are_not_guessed(self):
        for text in ['Schedule design review next week at 5pm.','Schedule design review at 5pm.','Schedule design review tomorrow.','Schedule design review tomorrow at 5.','Schedule review next Monday at 5pm.','Schedule review today and tomorrow at 5pm.']:
            with self.subTest(text=text),self.assertRaises(ValueError):parsed_request(text,self.anchor)
    def test_this_weekday_from_saturday_is_the_upcoming_wednesday(self):
        saturday=datetime(2026,11,14,17,tzinfo=TZ).timestamp()
        result=parsed_request('I need to submit a paper this Wednesday at 5 PM.',saturday)
        self.assertEqual(result['fields']['start'],'2026-11-18T17:00')
        self.assertEqual(result['fields']['title'],'I need to submit a paper')

    def test_all_day_and_delete_title(self):
        value=parsed_request('Add "Paper deadline" tomorrow all day.',self.anchor)
        self.assertTrue(value['fields']['all_day'])
        self.assertEqual(value['fields']['end'],'2030-05-08')
        self.assertEqual(parsed_request('Cancel my dentist appointment tomorrow',self.anchor,required=False)['fields']['title'],'dentist appointment')
    def test_date_only_obligation_becomes_all_day_only_when_allowed_for_creation(self):
        text='I need to pick up grandma from the airport on Saturday.'
        value=parsed_request(text,self.anchor,allow_date_only=True)
        self.assertEqual(value['fields']['start'],'2030-05-11')
        self.assertEqual(value['fields']['end'],'2030-05-12')
        self.assertTrue(value['fields']['all_day'])
        self.assertNotIn('T',value['fields']['start'])
        with self.assertRaises(ValueError):parsed_request(text,self.anchor)
        with self.assertRaises(ValueError):parsed_request('Pick up grandma next week.',self.anchor,allow_date_only=True)

    def test_bad_decision_distribution_is_rejected(self):
        with self.assertRaises(ValueError):choice_answer(dict(type='choice',choice='create',confidence=.99,probabilities={'create':.99}),OPERATIONS)

class CalendarAutomationTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.db=sqlite3.connect(Path(self.temp.name)/'test.db')
        self.automation=CalendarAutomation(self.db,None)
        self.calendar=mock.Mock()
        self.calendar.snapshot.return_value=dict(authorized=True,write_authorization_required=False,calendars=[dict(id='primary-id',primary=True,writable=True)])
        self.calendar.query_events=mock.AsyncMock(return_value=[])
        self.calendar.create_event=mock.AsyncMock(return_value={'id':'created-id'})
        self.calendar.update_event=mock.AsyncMock(return_value={'id':'existing-id'})
        self.calendar.delete_event=mock.AsyncMock(return_value={'id':'existing-id'})
        self.anchor=datetime(2030,5,6,10,tzinfo=TZ).timestamp()
    def tearDown(self):self.db.close();self.temp.cleanup()
    def task(self,text):
        return dict(id='task',kind='calendar',title=text,source_id='source',quote='I need to submit')
    def source(self,text):return dict(id='source',text=text,said_at=self.anchor)
    async def process(self,text,decisions):
        with mock.patch.object(self.automation,'decide',new=mock.AsyncMock(side_effect=decisions)):
            return await self.automation.process(None,self.calendar,self.task(text),self.source(text))
    async def test_explicit_create_is_real_call_and_replay_cannot_repeat_it(self):
        text='Schedule design review tomorrow at 5pm.'
        result=await self.process(text,[('create',.99)])
        self.assertEqual(result['status'],'created')
        self.calendar.create_event.assert_awaited_once()
        fields=self.calendar.create_event.call_args.args[2]
        self.assertEqual(fields['title'],'design review')
        self.assertEqual(fields['start'],'2030-05-07T17:00')
        # Title uses the joined source, not an incomplete legacy supporting quote.
        await self.automation.process(None,self.calendar,self.task(text),self.source(text))
        self.assertEqual(self.calendar.create_event.await_count,1)
        self.assertEqual(CalendarAutomation(self.db,None).statuses()['task']['status'],'created')
    async def test_date_only_pickup_creates_all_day_without_inventing_an_hour(self):
        result=await self.process('I need to pick up grandma from the airport on Saturday.',[('create',.99)])
        self.assertEqual(result['status'],'created')
        fields=self.calendar.create_event.call_args.args[2]
        self.assertEqual(fields['start'],'2030-05-11')
        self.assertEqual(fields['end'],'2030-05-12')
        self.assertTrue(fields['all_day'])

    async def test_rescheduling_without_a_time_does_not_convert_to_all_day(self):
        result=await self.process('Move design review to Saturday.',[('update',.99)])
        self.assertEqual(result['status'],'needs_details')
        self.calendar.update_event.assert_not_awaited()

    async def test_feature_discussion_and_hypothetical_do_not_write(self):
        for text in ['We need to implement automatic calendar event creation.','If we had time we could schedule a meeting tomorrow at 5pm.']:
            self.db.execute('DELETE FROM calendar_actions');self.db.commit()
            result=await self.process(text,[('none',.99)])
            self.assertEqual(result['status'],'ignored')
        self.calendar.create_event.assert_not_awaited()
    async def test_low_confidence_or_missing_details_do_not_write(self):
        result=await self.process('Schedule review tomorrow at 5pm.',[('create',.6)])
        self.assertEqual(result['status'],'needs_details')
        self.db.execute('DELETE FROM calendar_actions');self.db.commit()
        result=await self.process('Schedule review next week.',[('create',.99)])
        self.assertEqual(result['status'],'needs_details')
        self.calendar.create_event.assert_not_awaited()
    async def test_authorization_queue_only_retries_authorization_pending_actions(self):
        text='Schedule design review tomorrow at 5pm.'
        self.calendar.snapshot.return_value={'authorized':True,'write_authorization_required':True}
        result=await self.process(text,[('create',.99)])
        self.assertEqual(result['status'],'awaiting_authorization')
        self.assertEqual(self.automation.pending_task_ids(),['task'])
        self.calendar.snapshot.return_value=dict(authorized=True,calendars=[dict(id='primary-id',primary=True,writable=True)])
        result=await self.process(text,[('create',.99)])
        self.assertEqual(result['status'],'created')
        self.assertEqual(self.automation.pending_task_ids(),[])
    async def test_timeout_after_dispatch_is_uncertain_and_never_retried(self):
        text='Schedule review tomorrow at 5pm.'
        self.calendar.create_event.side_effect=TimeoutError()
        result=await self.process(text,[('create',.99)])
        self.assertEqual(result['status'],'uncertain')
        again=await self.automation.process(None,self.calendar,self.task(text),self.source(text))
        self.assertEqual(again['status'],'uncertain')
        self.assertEqual(self.calendar.create_event.await_count,1)
        self.assertEqual(self.automation.pending_task_ids(),[])
    async def test_edit_exact_existing_target_requires_second_confident_decision(self):
        text='Move design review to tomorrow at 5pm.'
        self.calendar.query_events.return_value=[dict(id='existing-id',title='design review',start=self.anchor+86400,end=self.anchor+86400+3600,description='Original notes',start_iso='2030-05-07T10:00:00-07:00')]
        result=await self.process(text,[('update',.99),('event_0',.99)])
        self.assertEqual(result['status'],'updated')
        self.assertEqual(self.calendar.update_event.call_args.args[2],'existing-id')
        self.assertEqual(self.calendar.update_event.call_args.args[3]['start'],'2030-05-07T17:00')
        self.assertTrue(self.calendar.update_event.call_args.args[3]['end'].startswith('2030-05-07T18:00'))
        self.assertEqual(self.calendar.update_event.call_args.args[3]['description'],'Original notes')
    async def test_cancel_exact_target_and_ambiguous_target_fail_closed(self):
        text='Cancel my dentist appointment tomorrow'
        event=dict(id='existing-id',title='dentist appointment',start=self.anchor+86400)
        self.calendar.query_events.return_value=[event]
        result=await self.process(text,[('delete',.99),('event_0',.99)])
        self.assertEqual(result['status'],'deleted')
        self.calendar.delete_event.assert_awaited_once()
        self.db.execute('DELETE FROM calendar_actions');self.db.commit()
        self.calendar.query_events.return_value=[event,{**event,'id':'another-id'}]
        result=await self.process(text,[('delete',.99)])
        self.assertEqual(result['status'],'needs_details')
        self.assertEqual(self.calendar.delete_event.await_count,1)
    async def test_equivalent_utc_start_is_not_created_twice(self):
        text='Schedule design review tomorrow at 5pm.'
        self.calendar.query_events.return_value=[dict(id='existing-id',title='design review',all_day=False,
            start=datetime(2030,5,7,17,tzinfo=TZ).timestamp(),end=datetime(2030,5,7,17,30,tzinfo=TZ).timestamp(),
            start_iso='2030-05-08T00:00:00Z')]
        result=await self.process(text,[('create',.99)])
        self.assertEqual(result['status'],'already_present')
        self.calendar.create_event.assert_not_awaited()

    async def test_delete_with_clock_but_no_date_never_targets_a_different_time(self):
        text='Cancel design review at 5pm.'
        self.calendar.query_events.return_value=[dict(id='existing-id',title='design review',start=self.anchor)]
        result=await self.process(text,[('delete',.99)])
        self.assertEqual(result['status'],'needs_details')
        self.calendar.delete_event.assert_not_awaited()

    async def test_crash_dispatch_marker_cannot_be_replayed(self):
        text='Schedule review tomorrow at 5pm.'
        self.automation.save(self.task(text),self.source(text),'dispatching',operation='create')
        self.assertEqual(self.automation.statuses()['task']['status'],'uncertain')
        result=await self.automation.process(None,self.calendar,self.task(text),self.source(text))
        self.assertEqual(result['status'],'uncertain')
        self.calendar.create_event.assert_not_awaited()
