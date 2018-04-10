import datetime, pytz, sqlite3, unittest
from mock import patch

import bot, conversation, keybase, reminders
from conversation import Conversation
from user import User

DB = 'test.db' # Why doesn't :memory: work?
TEST_BOT = '__testbot__'
TEST_USER = '__testuser__'
TEST_OWNER = '__testowner__'
TEST_CHANNEL = TEST_USER + "," + TEST_BOT
NOW_TS = 1523235748.0 # Sunday April 8 2018, 21:02:28 EDT. Monday April 9 2018, 01:02:28 UTC.
NOW_UTC = datetime.datetime.fromtimestamp(NOW_TS, tz=pytz.utc)

@patch('keybase.send', return_value=True)
@patch('random.choice', side_effect=lambda i: i[0])
@patch('util.now_utc', return_value=NOW_UTC)
class TestBot(unittest.TestCase):

    @patch('subprocess.check_call')
    @patch('keybase.status')
    def setUp(self, mockKeybaseStatus, mockCheckCall):
        mockKeybaseStatus.return_value = {"LoggedIn": True, "Username": TEST_BOT}
        self.config = bot.Config(DB, TEST_BOT, TEST_OWNER)
        self.now = datetime.datetime.fromtimestamp(NOW_TS, tz=pytz.utc)
        bot.setup(self.config)

    def tearDown(self):
        conv = Conversation.lookup(TEST_CHANNEL, DB)
        conv.delete()
        user = User.lookup(TEST_USER, DB)
        user.delete()

    def test_recent_message(self, mockNow, mockRandom, mockKeybaseSend):
        # When bot receives two messages in a row, it shouldn't send the full help message twice.

        conv = Conversation.lookup(TEST_CHANNEL, DB)
        message = keybase.Message.inject('not parsable', TEST_USER, TEST_CHANNEL, DB)

        bot.process_message(self.config, message, conv)
        mockKeybaseSend.assert_called_with(TEST_CHANNEL, bot.PROMPT_HELP)

        bot.process_message(self.config, message, conv)
        mockKeybaseSend.assert_called_with(TEST_CHANNEL, bot.UNKNOWN)

    def reminder_test(self, text, reminder, whentext, fullwhen, timedelta, mockNow, mockKeybaseSend):
        conv = Conversation.lookup(TEST_CHANNEL, DB)
        message = keybase.Message.inject(text, TEST_USER, TEST_CHANNEL, DB)
        bot.process_message(self.config, message, conv)
        mockKeybaseSend.assert_any_call(TEST_CHANNEL, bot.ASSUME_TZ)
        mockKeybaseSend.assert_called_with(TEST_CHANNEL,
            "Ok! I'll remind you to " + reminder + " " + whentext)

        message = keybase.Message.inject("list", TEST_USER, TEST_CHANNEL, DB)
        bot.process_message(self.config, message, conv)
        mockKeybaseSend.assert_called_with(TEST_CHANNEL, "Here are your upcoming reminders:\n\n"
                "1. " + reminder + " - " + fullwhen)

        mockNow.return_value = NOW_UTC + timedelta
        bot.send_reminders(self.config)
        mockKeybaseSend.assert_called_with(TEST_CHANNEL, "*Reminder:* " + reminder)

    def test_set_reminder(self, mockNow, mockRandom, mockKeybaseSend):
        self.reminder_test(
                "remind me to foo tomorrow",
                "foo", "on Monday at 09:02 PM",
                "on Monday April 09 2018 at 09:02 PM",
                datetime.timedelta(days=1),
                mockNow, mockKeybaseSend)

    # use separate functions for each reminder_test to reset the mocks and db
    def test_set_reminder_time_day(self, mockNow, mockRandom, mockKeybaseSend):
        self.reminder_test(
                "remind me to paint dan's fence at 10:30pm today",
                "paint dan's fence", "at 10:30 PM",
                "on Sunday April 08 2018 at 10:30 PM",
                datetime.timedelta(hours=2),
                mockNow, mockKeybaseSend)

    def test_set_reminder_day_time(self, mockNow, mockRandom, mockKeybaseSend):
        self.reminder_test(
                "remind me to paint dan's fence today at 10:30pm",
                "paint dan's fence", "at 10:30 PM",
                "on Sunday April 08 2018 at 10:30 PM",
                datetime.timedelta(hours=2),
                mockNow, mockKeybaseSend)

    def test_set_reminder_separate_when(self, mockNow, mockRandom, mockKeybaseSend):
        conv = Conversation.lookup(TEST_CHANNEL, DB)
        message = keybase.Message.inject("Remind me to say hello", TEST_USER, TEST_CHANNEL, DB)
        bot.process_message(self.config, message, conv)
        mockKeybaseSend.assert_any_call(TEST_CHANNEL, bot.ASSUME_TZ)
        mockKeybaseSend.assert_called_with(TEST_CHANNEL, bot.WHEN)


        message = keybase.Message.inject("10pm", TEST_USER, TEST_CHANNEL, DB)
        bot.process_message(self.config, message, conv)
        mockKeybaseSend.assert_called_with(TEST_CHANNEL,
                "Ok! I'll remind you to say hello at 10:00 PM")

        message = keybase.Message.inject("List", TEST_USER, TEST_CHANNEL, DB)
        bot.process_message(self.config, message, conv)
        mockKeybaseSend.assert_called_with(TEST_CHANNEL, "Here are your upcoming reminders:\n\n"
                "1. say hello - on Sunday April 08 2018 at 10:00 PM")

        mockNow.return_value = NOW_UTC + datetime.timedelta(hours=1)
        bot.send_reminders(self.config)
        mockKeybaseSend.assert_called_with(TEST_CHANNEL, "*Reminder:* say hello")

    def test_set_timezone_during_when(self, mockNow, mockRandom, mockKeybaseSend):
        conv = Conversation.lookup(TEST_CHANNEL, DB)
        message = keybase.Message.inject("remind me to foo", TEST_USER, TEST_CHANNEL, DB)
        bot.process_message(self.config, message, conv)
        mockKeybaseSend.assert_any_call(TEST_CHANNEL, bot.ASSUME_TZ)
        mockKeybaseSend.assert_called_with(TEST_CHANNEL, bot.WHEN)

        message = keybase.Message.inject("set my timezone to US/Pacific.",
                TEST_USER, TEST_CHANNEL, DB)
        bot.process_message(self.config, message, conv)
        mockKeybaseSend.assert_called_with(TEST_CHANNEL, bot.ACK_WHEN)

        message = keybase.Message.inject("tomorrow at 9am", TEST_USER, TEST_CHANNEL, DB)
        bot.process_message(self.config, message, conv)
        mockKeybaseSend.assert_called_with(TEST_CHANNEL,
            "Ok! I'll remind you to foo at 09:00 AM")

    def test_set_timezone_after_reminder(self, mockNow, mockRandom, mockKeybaseSend):
        conv = Conversation.lookup(TEST_CHANNEL, DB)
        message = keybase.Message.inject("remind me to foo tomorrow at 9am",
                TEST_USER, TEST_CHANNEL, DB)
        bot.process_message(self.config, message, conv)
        mockKeybaseSend.assert_any_call(TEST_CHANNEL, bot.ASSUME_TZ)
        mockKeybaseSend.assert_called_with(TEST_CHANNEL,
            "Ok! I'll remind you to foo at 09:00 AM")

        message = keybase.Message.inject("set my timezone to US/Pacific.",
                TEST_USER, TEST_CHANNEL, DB)
        bot.process_message(self.config, message, conv)
        mockKeybaseSend.assert_called_with(TEST_CHANNEL, bot.ACK)

        message = keybase.Message.inject("list my reminders", TEST_USER, TEST_CHANNEL, DB)
        bot.process_message(self.config, message, conv)
        mockKeybaseSend.assert_called_with(TEST_CHANNEL, "Here are your upcoming reminders:\n\n"
                "1. foo - on Monday April 09 2018 at 09:00 AM")

if __name__ == '__main__':
    unittest.main()