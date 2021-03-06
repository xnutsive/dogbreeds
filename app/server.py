import aiohttp, asyncio
import os, glob

import rollbar

from io import BytesIO
from urllib.request import urlretrieve

from fastai import *
from fastai.vision import *

from telegram import ChatAction, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Updater, MessageHandler, CommandHandler, CallbackQueryHandler
from telegram.ext.filters import Filters

from dotenv import load_dotenv
load_dotenv()


# Configuration
#

path = Path(__file__).parent
data_path = Path(os.path.normpath(path/'../data/live'))
arch = models.resnet101
classes = pickle.load(open(path/'models/classes.pkl', 'rb'))

model_file_name = os.getenv('model', 'stage2-50-ep8-ep16')
size = int(os.getenv('size', 299))
bot_token = os.getenv('bot_token')
rollbar_token = os.getenv('rollbar_token')
rollbar_env = os.getenv('rollbar_env', 'development')

# Helper functions
#

def setup_learner():
    data_bunch = ImageDataBunch.single_from_classes(path, classes,
        tfms=get_transforms(), size=size).normalize(imagenet_stats)
    learn = create_cnn(data_bunch, arch, pretrained=False)
    learn.load(model_file_name)
    return learn

def class_to_human(pred_class):
    return ' '.join(pred_class.split('-')[-1].split('_')).capitalize()

def record_incorrect_label(label_row):
    with open(data_path/'labels.csv','a') as fd:
        fd.write(label_row)

# Telegram Bot handler functions
#

def start(bot, update):
    update.message.reply_text(f"Howdy {update.message.from_user.first_name}! " +
    "Send me your doggie pic.")

def stats(bot, update):
    if update.message.from_user.username == 'xnutsive':
        files_uploaded = len(glob.glob1(data_path, '*')) - 1
        update.message.reply_text(f"Processed {files_uploaded} pictures")

def text(bot, update):
    update.message.reply_text("Please only send dog pics thx 🐕")

def button(bot, update):
    query = update.callback_query

    if query.data == 'correct':
        reply_text = "💙"
    else:
        reply_text = "Thanks!"
        record_incorrect_label(query.data + "\n")
        rollbar.report_message('Made an incorrect prediction', level='info')

    bot.edit_message_text(text=reply_text,
                          chat_id=query.message.chat_id,
                          message_id=query.message.message_id)

def photo(bot, update):
    try:
        print("      Received a photo.")

        pic = update.message.photo[-1]
        file_id = pic['file_id']
        print("      File id: " + file_id)

        print(update.message.chat)
        print(update.message.chat.id)
        bot.sendChatAction(update.message.chat.id, ChatAction.TYPING)
        print("      Sent typing notification")

        print("      Getting the image URL: ")
        # Request a link to a file that'll be valid for an hour.
        pic_url = bot.getFile(file_id)['file_path']
        print("      Done, img url: " + pic_url)

        print("      Downloading the pic to tmp...")
        pic_file_name = pic_url.split("/")[-1]
        urlretrieve(pic_url, data_path/pic_file_name)

        print("      Evaluating the image...")
        img = open_image(data_path/pic_file_name)
        pred_class, confidence, preds = learn.predict(img)
        print(f"      Breed class: {pred_class}")

        best_idx = np.argpartition(preds, -4)[-4:-1]

        keyboard = [[InlineKeyboardButton("Yep!", callback_data='correct')]] + \
            [[InlineKeyboardButton(class_to_human(classes[i]), \
            callback_data=f"{pic_file_name},{classes[i]}")] for i in best_idx]

        reply_markup = InlineKeyboardMarkup(keyboard)

        update.message.reply_text(f"It looks like a {class_to_human(pred_class)}!",
            reply_markup=reply_markup)

        # Report to analytics and rollbar
        rollbar.report_message('Processed a picture', level='info')

    except:
        update.message.reply_text("That was a bit too hard for me ;-(")
        rollbar.report_exc_info()


if __name__ == '__main__':
    rollbar.init(rollbar_token, rollbar_env)
    rollbar.report_message('Starting up', level='info')

    try:
        if bot_token is None:
            raise Exception("Provide bot_token env variable")

        if not os.path.exists(data_path):
            raise Exception("Data path is not available")

        learn = setup_learner()
        updater = Updater(bot_token)

        updater.dispatcher.add_handler(CommandHandler('start', start))
        updater.dispatcher.add_handler(CommandHandler('stats', stats))
        updater.dispatcher.add_handler(MessageHandler(Filters.text, text))
        updater.dispatcher.add_handler(MessageHandler(Filters.photo, photo))
        updater.dispatcher.add_handler(CallbackQueryHandler(button))

        print("Starting up...")
        updater.start_polling()
        updater.idle()

    except:
        rollbar.report_exc_info()
