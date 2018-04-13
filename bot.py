#!/usr/bin/env python

import argparse, configparser, os, pytz, signal, sqlite3, subprocess, sys, time, traceback

import conversation, database, keybase, parse, reminders, util
from conversation import Conversation

# Static response messages
HELP_WHEN = "Sorry, I didn't understand. When should I set the reminder for?" \
        " You can say something like \"tomorrow at 10am\" or \"in 30 minutes\"."
HELP_TZ = "Sorry, I couldn't understand your timezone. It can be something like \"US/Pacific\"" \
        " or \"GMT\". If you're stuck, I can use any of the timezones in this list:" \
        " https://stackoverflow.com/questions/13866926/python-pytz-list-of-timezones."\
        " Be sure to get the capitalization right!"
UNKNOWN = "Sorry, I didn't understand that message."
PROMPT_HELP = "Hey there, I didn't understand that." \
        " Just say \"help\" to see what sort of things I understand."
ASSUME_TZ = "I'm assuming your timezone is US/Eastern." \
        " If it's not, just tell me something like \"my timezone is US/Pacific\"."
WHEN = "When do you want to be reminded?"
ACK = "Got it!"
ACK_WHEN = ACK + " " + WHEN
OK = "ok!"
NO_REMINDERS = "You don't have any upcoming reminders."
LIST_INTRO = "Here are your upcoming reminders:\n\n"
SOURCE = "I'm a bot written in python by @jessk.\n"\
         "Source available here: https://github.com/seveneightn9ne/keybase-reminder-bot"

# Returns True iff I interacted with the user.
def process_message_inner(config, message, conv):
    if not message.is_private_channel() \
            and not config.username in message.text \
            and conv.context == conversation.CTX_NONE:
        print "Ignoring message not for me"
        return False

    # TODO need some sort of onboarding for first-time user

    msg_type, data = parse.parse_message(message, conv)
    print "Received message parsed as " + str(msg_type)
    if msg_type == parse.MSG_REMINDER and message.user().timezone is None:
        keybase.send(conv.id, ASSUME_TZ)
        message.user().set_timezone("US/Eastern")

    if msg_type == parse.MSG_REMINDER:
        reminder = data
        reminder.store()
        if not reminder.reminder_time:
            conv.set_context(conversation.CTX_WHEN, reminder=reminder)
            return keybase.send(conv.id, WHEN)
        else:
            return keybase.send(conv.id, reminder.confirmation())

    elif msg_type == parse.MSG_STFU:
        conv.clear_context()
        return keybase.send(conv.id, OK)

    elif msg_type == parse.MSG_HELP:
        message.user().set_seen_help()
        return keybase.send(conv.id, HELP)

    elif msg_type == parse.MSG_TIMEZONE:
        message.user().set_timezone(data)
        if conv.context == conversation.CTX_WHEN:
            return keybase.send(conv.id, ACK_WHEN)
        return keybase.send(conv.id, ACK)

    elif msg_type == parse.MSG_WHEN:
        reminder = conv.get_reminder()
        reminder.set_time(data)
        confirmation = reminder.confirmation()
        conv.set_context(conversation.CTX_NONE)
        return keybase.send(conv.id, confirmation)

    elif msg_type == parse.MSG_LIST:
        reminders = conv.get_all_reminders()
        if not len(reminders):
            return keybase.send(conv.id, NO_REMINDERS)
        response = LIST_INTRO
        for i, reminder in enumerate(reminders, start=1):
            response += str(i) + ". " + reminder.body + " - " + reminder.human_time(full=True) + "\n"
        return keybase.send(conv.id, response)

    elif msg_type == parse.MSG_SOURCE:
        return keybase.send(conv.id, SOURCE)

    elif msg_type == parse.MSG_UNKNOWN_TZ:
        return keybase.send(conv.id, HELP_TZ)

    elif msg_type == parse.MSG_UNKNOWN:
        if conv.context == conversation.CTX_WHEN:
            return keybase.send(conv.id, HELP_WHEN)
        else: # CTX_NONE
            if conv.last_active_time and \
                (util.now_utc() - conv.last_active_time).total_seconds() < 60 * 30:
                # we're in the middle of a conversation
                return keybase.send(conv.id, UNKNOWN)
            if not message.is_private_channel():
                # assume you weren't talking to me..
                return False
            if not message.user().has_seen_help:
                return keybase.send(conv.id, PROMPT_HELP)
            # TODO not sure what to do here. I'll ignore it for now
            return False

    # Shouldn't be able to get here
    print msg_type, data
    assert False

def process_message(config, message, conv):
    if process_message_inner(config, message, conv):
        conv.set_active()

def process_new_messages(config):
    results = keybase.call("list")
    all_convs = results["conversations"]

    if not all_convs:
        return

    unread_convs = filter(lambda conv: conv["unread"], all_convs)
    print str(len(unread_convs)) + " unread conversations"

    for conv_json in unread_convs:
        id = conv_json["id"]
        conv = Conversation.lookup(id, conv_json, config.db)
        params = {"options": {
                "conversation_id": id,
                "unread_only": True}}
        response = keybase.call("read", params)
        #print "other response", response
        for message in response["messages"]:
            if "error" in message:
                print "message error: {}".format(message["error"])
                continue
            # TODO consider processing all messages together
            if not "text" in message["msg"]["content"]:
                # Ignore messages like edits and people joining the channel
                print "ignoring message of type: {}".format(message["msg"]["content"]["type"])
                continue
            try:
                process_message(config, keybase.Message(id, message, config.db), conv)
            except:
                keybase.send(id,
                        "Ugh! I crashed! You can complain to @" + config.owner + ".")
                conv.set_context(conversation.CTX_NONE)
                raise

def send_reminders(config):
    for reminder in reminders.get_due_reminders(config.db):
        conv = Conversation.lookup(reminder.conv_id, None, config.db)
        keybase.send(conv.id, reminder.reminder_text())
        print "sent a reminder for", reminder.reminder_time
        reminder.delete()

class Config(object):
    def __init__(self, db, username, owner):
        self.db = db
        self.username = username
        self.owner = owner

    @classmethod
    def fromFile(cls, configFile):
        config = configparser.ConfigParser()
        config.read(configFile)
        db = config['database']['file']
        username = config['keybase']['username']
        owner = config['keybase']['owner']
        return Config(db, username, owner)

def setup(config):
    keybase.setup(config.username)
    database.setup(config.db)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='Beep boop.')
    parser.add_argument('--config', default='default.ini',
                        help='config file')
    parser.add_argument('--wipedb', help='wipe the database before running',
                        action='store_true')
    args = parser.parse_args()

    config = Config.fromFile(args.config)

    if args.wipedb:
        try:
            os.remove(config.db)
        except OSError:
            pass # it doesn't exist

    setup(config)

    print "ReminderBot is running..."

    running = True
    def signal_handler(signal, frame):
        global running
        running = False

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    while running:
        try:
            process_new_messages(config)
        except:
            exc_type, value, tb = sys.exc_info()
            traceback.print_tb(tb)
            print >> sys.stderr, str(exc_type) + ": " + str(value)

        if not running:
            break

        try:
            send_reminders(config)
        except:
            exc_type, value, tb = sys.exc_info()
            traceback.print_tb(tb)
            print >> sys.stderr, str(exc_type) + ": " + str(value)

        if not running:
            break

        time.sleep(1)

    print "ReminderBot shut down gracefully."



