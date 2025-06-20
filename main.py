import logging
import random
import asyncio

from telegram import Update, ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardButton, InlineKeyboardMarkup, \
    ReplyKeyboardRemove
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    filters,
    ContextTypes,
    ConversationHandler,
    CallbackQueryHandler,
)

import database as db
from config import TELEGRAM_BOT_TOKEN

# Включаем логирование
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

# Состояния для ConversationHandler
ASK_CONTACT, MENU, QUIZ, STATS_VIEW = range(4)
QUIZ_QUESTIONS_COUNT = 10


# --- Новая функция для генерации "псевдо-правильных" форм ---

def generate_plausible_incorrect_forms(infinitive: str) -> tuple[str, str]:
    """
    Генерирует правдоподобные, но неверные формы для неправильных глаголов,
    применяя к ним правила для правильных глаголов.
    Например: singen -> singte, gesingt
    """
    non_separable_prefixes = ('be', 'ge', 'er', 'ver', 'zer', 'ent', 'emp', 'miss')

    # Определяем основу
    if infinitive.endswith('en'):
        stem = infinitive[:-2]
    elif infinitive.endswith('n'):
        stem = infinitive[:-1]
    else:
        stem = infinitive

    # Генерация Präteritum
    if stem.endswith(('t', 'd', 'm', 'n')):  # Упрощенное правило для -ete
        praeteritum = stem + 'ete'
    else:
        praeteritum = stem + 'te'

    # Генерация Partizip II
    partizip_ii = stem
    if stem.endswith(('t', 'd', 'm', 'n')):
        partizip_ii += 'et'
    else:
        partizip_ii += 't'

    if not infinitive.endswith('ieren') and not infinitive.startswith(non_separable_prefixes):
        partizip_ii = 'ge' + partizip_ii

    return praeteritum, partizip_ii


# --- Обновленная функция генерации ответов ---

def generate_answers(question_verb, all_verbs):
    """
    Генерирует 2 правильных и 2 неправильных ответа.
    Логика зависит от типа глагола (правильный/неправильный).
    """
    verb_id, infinitive, correct_praeteritum, correct_partizip, is_irregular = question_verb

    # 2 правильных ответа всегда одинаковы
    correct_answers = [
        (f"{correct_praeteritum}, {correct_partizip}", True),
        (f"{correct_partizip}, {correct_praeteritum}", True)
    ]

    incorrect_answers = []
    if is_irregular:
        # --- НОВАЯ ЛОГИКА ДЛЯ НЕПРАВИЛЬНЫХ ГЛАГОЛОВ ---
        # Генерируем "псевдо-правильные" формы
        inc_praet, inc_part = generate_plausible_incorrect_forms(infinitive)
        incorrect_answers.append((f"{inc_praet}, {inc_part}", False))
        incorrect_answers.append((f"{inc_part}, {inc_praet}", False))
    else:
        # --- СТАРАЯ ЛОГИКА ДЛЯ ПРАВИЛЬНЫХ ГЛАГОЛОВ ---
        # Берем формы от других случайных глаголов
        other_verbs = [v for v in all_verbs if v[0] != verb_id]
        if len(other_verbs) >= 2:
            # Неправильный вариант 1: формы от другого глагола
            other_verb_1 = random.choice(other_verbs)
            incorrect_answers.append((f"{other_verb_1[2]}, {other_verb_1[3]}", False))

            # Неправильный вариант 2: смесь форм
            other_verb_2 = random.choice(other_verbs)
            incorrect_answers.append((f"{correct_praeteritum}, {other_verb_2[3]}", False))
        else:  # На случай, если в базе мало глаголов
            incorrect_answers.append(("falsch, gefalscht", False))
            incorrect_answers.append(("gefalscht, falsch", False))

    # Собираем и перемешиваем
    final_answers = correct_answers + incorrect_answers
    random.shuffle(final_answers)
    return final_answers


# --- Остальные функции бота (остаются без изменений, но включены для полноты) ---

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user = update.effective_user
    user_data = db.get_user(user.id)

    if user_data:
        await show_main_menu(update, context, text=f"С возвращением, {user.first_name}!")
        return MENU
    else:
        keyboard = [[KeyboardButton("Поделиться контактом для регистрации", request_contact=True)]]
        reply_markup = ReplyKeyboardMarkup(keyboard, one_time_keyboard=True, resize_keyboard=True)
        await update.message.reply_text(
            "👋 Добро пожаловать в бот-квиз по немецким глаголам!\n\n"
            "Для начала, пожалуйста, зарегистрируйтесь, нажав на кнопку ниже. "
            "Нам нужен ваш номер телефона для ведения статистики.",
            reply_markup=reply_markup,
        )
        return ASK_CONTACT


async def ask_contact(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    contact = update.effective_message.contact
    user = update.effective_user

    if contact:
        db.add_user(user.id, contact.phone_number, user.first_name)
        logger.info(f"User {user.id} ({user.first_name}) registered with phone {contact.phone_number}")
        await show_main_menu(update, context, text="🎉 Регистрация прошла успешно!")
        return MENU
    else:
        await update.message.reply_text("Пожалуйста, используйте кнопку, чтобы поделиться контактом.")
        return ASK_CONTACT


async def show_main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str = "Главное меню"):
    keyboard = [
        [InlineKeyboardButton("🚀 Начать квиз", callback_data="start_quiz")],
        [InlineKeyboardButton("📊 Моя статистика", callback_data="show_stats")],
        [InlineKeyboardButton("ℹ️ Справка", callback_data="help")],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    query = update.callback_query
    if query:
        await query.answer()
        await query.edit_message_text(text=text, reply_markup=reply_markup, parse_mode='Markdown')
    else:
        await update.message.reply_text(text=text, reply_markup=reply_markup)


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    text = (
        "🤖 *Этот бот поможет вам выучить 3 формы немецких глаголов.*\n\n"
        "1️⃣ Нажмите *'Начать квиз'*, чтобы запустить игру из 10 вопросов.\n"
        "2️⃣ На каждый вопрос будет 4 варианта ответа: *2 правильных и 2 неправильных*.\n"
        "3️⃣ Выбирайте тот вариант, который считаете верным.\n"
        "4️⃣ В разделе *'Моя статистика'* вы можете отслеживать свой прогресс за день, неделю и месяц, а также сбросить его.\n\n"
        "Удачи!"
    )

    keyboard = [[InlineKeyboardButton("⬅️ Назад в меню", callback_data="back_to_menu")]]
    reply_markup = InlineKeyboardMarkup(keyboard)

    if query:
        await query.answer()
        await query.edit_message_text(text=text, reply_markup=reply_markup, parse_mode='Markdown')
    else:
        await update.message.reply_text(text=text, reply_markup=reply_markup, parse_mode='Markdown')


async def start_quiz(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()

    context.user_data['quiz_score'] = 0
    context.user_data['question_number'] = 1

    await ask_question(update, context)
    return QUIZ

async def ask_question(update: Update, context: ContextTypes.DEFAULT_TYPE):
    question_number = context.user_data['question_number']

    verbs = db.get_random_verbs(4)
    question_verb = verbs[0]

    context.user_data['current_verb'] = question_verb

    # ИСПОЛЬЗУЕМ ОБНОВЛЕННУЮ ФУНКЦИЮ
    answers = generate_answers(question_verb, verbs)
    context.user_data['answers'] = answers

    keyboard = []
    for i, (text, _) in enumerate(answers):
        keyboard.append([InlineKeyboardButton(text, callback_data=f"ans_{i}")])
    reply_markup = InlineKeyboardMarkup(keyboard)

    text = (f"Вопрос {question_number}/{QUIZ_QUESTIONS_COUNT}\n\n"
            f"Выберите правильные формы Präteritum и Partizip II для глагола: *{question_verb[1]}*")

    query = update.callback_query
    await query.edit_message_text(text, reply_markup=reply_markup, parse_mode='Markdown')

async def handle_answer(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()

    answer_index = int(query.data.split('_')[1])
    answers = context.user_data.get('answers', [])
    verb_id, infinitive, praeteritum, partizip_ii, _ = context.user_data.get('current_verb')

    if not answers:
        await show_main_menu(update, context, text="Произошла ошибка, давайте начнем сначала.")
        return MENU

    is_correct = answers[answer_index][1]

    db.log_answer(update.effective_user.id, verb_id, is_correct)

    if is_correct:
        context.user_data['quiz_score'] += 1
        result_text = f"✅ Верно!\n\n_{infinitive} - {praeteritum} - {partizip_ii}_"
    else:
        result_text = f"❌ Неверно.\n\nПравильный ответ: _{infinitive} - {praeteritum} - {partizip_ii}_"

    await query.edit_message_text(text=result_text, parse_mode='Markdown')
    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action='typing')
    await asyncio.sleep(2.5) # Немного увеличим паузу

    context.user_data['question_number'] += 1
    if context.user_data['question_number'] > QUIZ_QUESTIONS_COUNT:
        score = context.user_data['quiz_score']
        end_text = (
            f"🎉 Квиз завершен!\n\n"
            f"Ваш результат: *{score} из {QUIZ_QUESTIONS_COUNT}* правильных ответов."
        )
        await show_main_menu(update, context, text=end_text)
        return MENU
    else:
        await ask_question(update, context)
        return QUIZ

async def show_stats(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()

    user_id = update.effective_user.id
    stats = db.get_user_stats(user_id)

    text = (
        f"📊 *Ваша статистика*\n\n"
        f"Всего сыграно квизов: *{stats['games_played']}*\n\n"
        f"*За последний день:*\n"
        f"  Правильно: {stats['day']['correct']} из {stats['day']['total']} ({stats['day']['percentage']:.1f}%)\n\n"
        f"*За последнюю неделю:*\n"
        f"  Правильно: {stats['week']['correct']} из {stats['week']['total']} ({stats['week']['percentage']:.1f}%)\n\n"
        f"*За последний месяц:*\n"
        f"  Правильно: {stats['month']['correct']} из {stats['month']['total']} ({stats['month']['percentage']:.1f}%)"
    )

    keyboard = [
        [InlineKeyboardButton("🔄 Обнулить статистику", callback_data="reset_stats_confirm")],
        [InlineKeyboardButton("⬅️ Назад в меню", callback_data="back_to_menu")],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await query.edit_message_text(text, reply_markup=reply_markup, parse_mode='Markdown')
    return STATS_VIEW

async def reset_stats_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()

    text = "⚠️ *Вы уверены, что хотите обнулить свою статистику?*\n\n" \
           "Все ваши текущие данные будут заархивированы, и вы начнете с чистого листа. Это действие необратимо."

    keyboard = [
        [InlineKeyboardButton("✅ Да, обнулить", callback_data="reset_stats_do")],
        [InlineKeyboardButton("❌ Нет, вернуться", callback_data="show_stats")],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await query.edit_message_text(text, reply_markup=reply_markup, parse_mode='Markdown')
    return STATS_VIEW

async def do_reset_stats(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()

    user_id = update.effective_user.id
    user_info = db.get_user(user_id)

    if user_info:
        phone_number = user_info[1]
        db.reset_statistics(user_id, phone_number)
        logger.info(f"Stats reset for user {user_id}")

        await query.edit_message_text("Ваша статистика была успешно заархивирована и обнулена. Начинаем заново!")
        return await start(query, context)

    await show_main_menu(update, context, text="Произошла ошибка при сбросе.")
    return MENU

async def back_to_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await show_main_menu(update, context, text="Главное меню")
    return MENU

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.message.reply_text("Действие отменено.", reply_markup=ReplyKeyboardRemove())
    return ConversationHandler.END


def main() -> None:
    db.init_db()
    application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

    conv_handler = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            ASK_CONTACT: [MessageHandler(filters.CONTACT, ask_contact)],
            MENU: [
                CallbackQueryHandler(start_quiz, pattern="^start_quiz$"),
                CallbackQueryHandler(show_stats, pattern="^show_stats$"),
                CallbackQueryHandler(help_command, pattern="^help$"),
            ],
            QUIZ: [CallbackQueryHandler(handle_answer, pattern="^ans_")],
            STATS_VIEW: [
                CallbackQueryHandler(back_to_menu, pattern="^back_to_menu$"),
                CallbackQueryHandler(show_stats, pattern="^show_stats$"),
                CallbackQueryHandler(reset_stats_confirm, pattern="^reset_stats_confirm$"),
                CallbackQueryHandler(do_reset_stats, pattern="^reset_stats_do$"),
            ],
        },
        fallbacks=[
            CommandHandler("start", start),
            CallbackQueryHandler(back_to_menu, pattern="^back_to_menu$"),
            CommandHandler("cancel", cancel)
        ],
        per_message=False
    )
    application.add_handler(conv_handler)
    print("Bot started with improved quiz logic...")
    application.run_polling()

if __name__ == "__main__":
    main()