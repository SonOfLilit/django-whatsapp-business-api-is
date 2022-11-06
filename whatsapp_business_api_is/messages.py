import copy
import json
import logging
import os
import re

import requests
from django.conf import settings
from whatsapp_business_api_is.models import OutgoingMessage
from whatsapp_business_api_is.utils import get_data

MESSAGES_URL = settings.D360_BASE_URL + 'messages'
MEDIA_URL = settings.D360_BASE_URL + 'media'
AUTH_HEADER = {
    'D360-API-KEY': settings.D360_API_KEY,
}
HEADERS = {
    **AUTH_HEADER,
    'Content-Type': "application/json",
}

COMPONENT_NAME_PATTERN = re.compile('(?P<type>\w+)(%(?P<index>\d))?')


def get_template_message_data(to_number, template_name, components, lang_code=None):
    language_code = lang_code or os.environ.get('TEMPLATE_LANG_CODE', 'he')
    message = {
        "to": to_number,
        "type": "template",
        "template": {
            "language": {
                "policy": "deterministic",
                "code": language_code
            },
            "name": template_name,
        }
    }
    message['template']['components'] = components

    logging.debug(f"get_template_message_data:\n{message=}")
    return message


def get_media_message_data(to, media_data):
    message = {
        "recipient_type": "individual",
        "to": to,
        "type": media_data['media_type'],

        media_data['media_type']: media_data['payload']
    }
    logging.debug(f"get_media_message_data:\n{message=}")
    return message


def get_text_message_data(to_number, text):
    message = {
        "to": to_number,
        "type": "text",
        "text": {
            "body": text
        }
    }
    logging.debug(f"get_text_message_data:\n{message=}")
    return message


def get_interactive_message_data(parts, to_number):
    message = {
        "recipient_type": "individual",
        "to": to_number,
        "type": "interactive",
        "interactive": parts
    }
    logging.debug(f"get_interactive_message_data:\n{message=}")
    return message


def create_button(id_, title):
    button = {
        "type": "reply",
        "reply": {
            "id": id_,
            "title": title
        }
    }
    return button


def send_message(message):
    logging.debug(f"response: {MESSAGES_URL} \nresponse: {message=} {HEADERS=}")
    res = requests.post(url=MESSAGES_URL,
                        data=json.dumps(message),
                        headers=HEADERS)

    logging.debug(f"{res=} {res.text=} {res.json()=}")
    if res.status_code != 201:
        logging.error(f"Something went wrong")
        raise Exception(res.json())


def send_template_message(user, wab_bot_message):
    components = copy.deepcopy(wab_bot_message.message_variables)  # we can do this because this is a parsed JSON field
    if components:
        for component in components:
            for parameter in component['parameters']:
                variable = parameter.pop('variable')
                parameter[parameter['type']] = str(get_data(user, variable))

    logging.debug(f"{components=}")
    message = get_template_message_data(user.number, wab_bot_message.template_name, components)

    if settings.DEMO_MODE:
        logging.info(f"{'*' * 20}\n*   {message=}\n{'*' * 20}")
        text = wab_bot_message.pk
        if wab_bot_message.quick_reply:
            text = f"{text}: [{[r[1] for r in wab_bot_message.quick_reply]}]"
        message = get_text_message_data(user.number, text)

    if message:
        send_message(message)


def send_media_message(user, wab_bot_message, message_text=None):
    message_text = message_text or wab_bot_message.text
    if message_text and wab_bot_message.message_variables['caption']:
        variables = {k: get_data(user, v) for k, v in
                     wab_bot_message.message_variables['caption'].items()}
        message_text = message_text.format(**variables)

    payload = wab_bot_message.message_variables['media']['payload']  # TODO make dynamic
    if message_text:
        payload['caption'] = message_text

    media_data = {
        'media_type': wab_bot_message.message_variables['media']['type'],
        'payload': payload
    }

    message = get_media_message_data(user.number, media_data)

    assert message
    send_message(message)


def send_interactive_message(user, wab_bot_message, message_text=None):
    message_text = message_text or wab_bot_message.text

    # we can do this because this is a parsed JSON field
    parts = copy.deepcopy(wab_bot_message.message_variables) or {}
    if body := parts.get('body'):
        variables = {k: get_data(user, v) for k, v in body.pop('variables').items()}
        body['text'] = message_text.format(**variables)
    else:
        parts['body'] = {'text': message_text}

    match wab_bot_message.type:  # there are other type that not implemented yet
        case 'quick_reply':
            parts['type'] = 'button'
            buttons = wab_bot_message.quick_reply
            parts['action'] = {
                "buttons": [create_button(id, name) for id, name in buttons]
            }

    message = get_interactive_message_data(parts, user.number)

    assert message
    send_message(message)


def send_text_message(user, wab_bot_message, message_text=None):
    message_text = message_text or wab_bot_message.text
    if wab_bot_message.message_variables:
        variables = {k: get_data(user, v) for k, v in
                     wab_bot_message.message_variables.items()}
        message_text = message_text.format(**variables)

    message = get_text_message_data(user.number, message_text)

    assert message
    send_message(message)


def send_unknown_message(user):
    unknown_message = OutgoingMessage.objects.get(key='unknown')
    send_text_message(user, unknown_message)


def send_error_message(user, error):
    if error and hasattr(error, 'params') and error.params and error.params.get('custom_message', False):
        if message := OutgoingMessage.objects.filter(key=error.message).first():
            send_text_message(user, message)
        else:
            message = get_text_message_data(user.number, error.message)
            send_message(message)
    else:
        unknown_message = OutgoingMessage.objects.get(key='wrong_format')
        send_text_message(user, unknown_message)


def get_media(media_id):
    res = requests.get(
        url=MEDIA_URL + '/' + media_id,
        headers=AUTH_HEADER
    )
    logging.info(res.__dict__)
    return res

