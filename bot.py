import os
import logging
import json
import csv
import requests
from telegram import (
    Update,
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove,
    InlineKeyboardMarkup,
    InlineKeyboardButton
)
from telegram.ext import (
    ApplicationBuilder,
    ContextTypes,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    filters,
    ConversationHandler
)

# ---------- Конфигурация через переменные окружения ----------
BOT_TOKEN = os.getenv("BOT_TOKEN", "8230348907:AAEyEbrFqn8uhZLVYSL4Qg9w6SIl13QL9wg")
YC_API_KEY = os.getenv("YC_API_KEY", "AQVNzGQyyfsE_0ScOUIqgCbaDjPBQjYEBL7-h_i3")
YC_FOLDER_ID = os.getenv("YC_FOLDER_ID", "b1gvjms07lsr4hfhq8v3")
ADMIN_ID = int(os.getenv("ADMIN_ID", "961018017"))
YC_GPT_URL = "https://llm.api.cloud.yandex.net/foundationModels/v1/completion"
YC_TTS_URL = "https://tts.api.cloud.yandex.net/speech/v1/tts:synthesize"
VACANCIES_FILE = "vacancies.json"
CSV_FILE = "candidates.csv"
INTERVIEW_LINK = "https://example.com/interview"

# ---------- Состояния ----------
SELECT_VACANCY, UPLOAD_RESUME, INTERVIEW = range(3)

# ---------- Данные ----------
user_data = {}
vacancies = {}

# ---------- Логирование ----------
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ================== CSV ==================
def save_candidate_to_csv(user_id, full_name, vacancy_title, resume, percentage, analysis, status=""):
    """Сохраняем кандидата в CSV"""
    file_exists = os.path.isfile(CSV_FILE)
    with open(CSV_FILE, "a", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        if not file_exists:
            writer.writerow([
                "ID", "ФИО", "Вакансия", "Резюме",
                "Соответствие", "Анализ", "Статус",
                "Протокол", "Финальный отчёт", "Глубинный анализ"
            ])
        writer.writerow([
            user_id, full_name, vacancy_title, resume,
            percentage, analysis, status, "", "", ""
        ])

def update_csv_with_protocol(user_id, protocol, final_report="", deep_analysis=""):
    """Обновляем CSV протоколом и финальным отчётом"""
    if not os.path.exists(CSV_FILE):
        return
        
    rows = []
    with open(CSV_FILE, "r", encoding="utf-8") as f:
        reader = list(csv.reader(f))
        headers = reader[0]
        rows = reader[1:]

    for row in rows:
        if row and row[0] == str(user_id):
            if len(row) < 10:
                row.extend([""] * (10 - len(row)))
            row[7] = protocol
            row[8] = final_report
            row[9] = deep_analysis

    with open(CSV_FILE, "w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(headers)
        writer.writerows(rows)

# ================== ВАКАНСИИ ==================
def save_vacancies():
    with open(VACANCIES_FILE, "w", encoding="utf-8") as f:
        json.dump(vacancies, f, ensure_ascii=False, indent=2)

def load_vacancies():
    global vacancies
    try:
        with open(VACANCIES_FILE, "r", encoding="utf-8") as f:
            vacancies = json.load(f)
    except FileNotFoundError:
        vacancies = {}
    except json.JSONDecodeError:
        vacancies = {}

async def add_vacancy(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Добавление вакансии (только админ)"""
    if update.message.from_user.id != ADMIN_ID:
        await update.message.reply_text("Нет прав для этой команды.")
        return ConversationHandler.END

    if not context.args:
        await update.message.reply_text("Использование: /add_vacancy <название>")
        return ConversationHandler.END

    vacancy_title = " ".join(context.args)
    context.user_data["new_vacancy_title"] = vacancy_title

    await update.message.reply_text(f"Добавляем вакансию '{vacancy_title}'. Пришлите текст.")
    return 1

async def save_vacancy_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    vacancy_text = update.message.text
    vacancy_title = context.user_data["new_vacancy_title"]
    vacancy_id = str(len(vacancies) + 1)

    vacancies[vacancy_id] = {"title": vacancy_title, "text": vacancy_text}
    save_vacancies()

    await update.message.reply_text(f"Вакансия '{vacancy_title}' сохранена (ID {vacancy_id}).")
    return ConversationHandler.END

async def list_vacancies(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not vacancies:
        await update.message.reply_text("Нет доступных вакансий.")
        return

    msg = "Доступные вакансии:\n\n"
    for vid, vac in vacancies.items():
        msg += f"{vid}. {vac['title']}\n"

    await update.message.reply_text(msg)

async def delete_vacancy(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Удаление вакансии (только админ)"""
    if update.message.from_user.id != ADMIN_ID:
        await update.message.reply_text("Нет прав.")
        return

    if not vacancies:
        await update.message.reply_text("Нет вакансий для удаления.")
        return

    keyboard = [
        [InlineKeyboardButton(f"Удалить {vid}: {vac['title']}", callback_data=f"delete_{vid}")]
        for vid, vac in vacancies.items()
    ]
    await update.message.reply_text("Выберите вакансию:", reply_markup=InlineKeyboardMarkup(keyboard))

async def confirm_delete_vacancy(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if query.from_user.id != ADMIN_ID:
        await query.edit_message_text("Нет прав.")
        return

    vid = query.data.replace("delete_", "")
    if vid not in vacancies:
        await query.edit_message_text("Не найдено.")
        return

    deleted = vacancies[vid]["title"]
    del vacancies[vid]
    save_vacancies()
    await query.edit_message_text(f"Вакансия '{deleted}' удалена.")

# ================== TTS ==================
async def send_tts_message(update: Update, text: str):
    """Озвучка текста через Yandex SpeechKit"""
    headers = {"Authorization": f"Api-Key {YC_API_KEY}"}
    data = {"text": text, "lang": "ru-RU", "voice": "ermil", "folderId": YC_FOLDER_ID}

    try:
        r = requests.post(YC_TTS_URL, headers=headers, data=data)
        r.raise_for_status()
        path = "speech.ogg"
        with open(path, "wb") as f:
            f.write(r.content)
        await update.message.reply_voice(voice=open(path, "rb"))
        os.remove(path)
    except Exception as e:
        logger.error(f"TTS error: {e}")
        await update.message.reply_text(text)

# ================== ОСНОВНОЙ ФЛОУ ==================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not vacancies:
        await update.message.reply_text("Нет вакансий.")
        return ConversationHandler.END

    keyboard = [[f"Вакансия {vid}: {v['title']}"] for vid, v in vacancies.items()]
    await update.message.reply_text(
        "Привет! Выберите вакансию:", 
        reply_markup=ReplyKeyboardMarkup(keyboard, one_time_keyboard=True)
    )
    return SELECT_VACANCY

async def select_vacancy(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    try:
        vid = update.message.text.split(":")[0].replace("Вакансия", "").strip()
        vacancy = vacancies[vid]
    except Exception:
        await update.message.reply_text("Выберите вакансию из списка.")
        return SELECT_VACANCY

    user_data[user_id] = {
        "vacancy_id": vid, 
        "vacancy_title": vacancy["title"], 
        "vacancy_text": vacancy["text"]
    }
    await update.message.reply_text(f"Вы выбрали: {vacancy['title']}. Отправьте резюме.")
    return UPLOAD_RESUME

async def handle_resume(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    resume = update.message.text
    
    if update.message.document:
        try:
            file = await update.message.document.get_file()
            resume_bytes = await file.download_as_bytearray()
            resume = resume_bytes.decode("utf-8")
        except Exception as e:
            logger.error(f"Ошибка загрузки файла: {e}")
            await update.message.reply_text("Ошибка обработки файла. Отправьте текст.")
            return UPLOAD_RESUME

    user_data[user_id]["resume"] = resume
    await update.message.reply_text("Резюме получено. Анализирую...")
    return await analyze_compatibility(update, context)

async def analyze_compatibility(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Анализ через Yandex GPT"""
    user_id = update.message.from_user.id
    full_name = update.message.from_user.full_name
    data = user_data[user_id]

    prompt = {
        "modelUri": f"gpt://{YC_FOLDER_ID}/yandexgpt-lite",
        "completionOptions": {"stream": False, "temperature": 0.7, "maxTokens": 1000},
        "messages": [
            {"role": "system", "text": "Проанализируй резюме и вакансию. Ответ: Процент соответствия: X%\n\nАнализ: ..."},
            {"role": "user", "text": f"Вакансия:\n{data['vacancy_text']}\n\nРезюме:\n{data['resume']}"}
        ]
    }
    headers = {"Content-Type": "application/json", "Authorization": f"Api-Key {YC_API_KEY}"}

    try:
        r = requests.post(YC_GPT_URL, json=prompt, headers=headers, timeout=30)
        r.raise_for_status()
        result = r.json()
        analysis = result["result"]["alternatives"][0]["message"]["text"]
        data["analysis"] = analysis
        try:
            perc = int(analysis.split("Процент соответствия: ")[1].split("%")[0])
        except Exception:
            perc = 0
        data["percentage"] = perc

        if perc >= 70:
            save_candidate_to_csv(user_id, full_name, data["vacancy_title"], data["resume"], perc, analysis, "Приглашён")
            await update.message.reply_text(f"Соответствие: {perc}%\nСсылка: {INTERVIEW_LINK}\nВаш ID: {user_id}\nВведите /access {user_id}")
        else:
            save_candidate_to_csv(user_id, full_name, data["vacancy_title"], data["resume"], perc, analysis, "Бездарь")
            await update.message.reply_text(f"Соответствие: {perc}%. Кандидат не подходит.")
        return ConversationHandler.END
    except Exception as e:
        logger.error(f"Анализ ошибка: {e}")
        await update.message.reply_text("Ошибка при анализе.")
        return ConversationHandler.END

# ================== ДОСТУП ==================
async def access_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Проверка ID доступа и запуск собеседования"""
    if not context.args:
        await update.message.reply_text("Использование: /access <ID>")
        return ConversationHandler.END

    uid = context.args[0]
    found = False
    
    try:
        if not os.path.exists(CSV_FILE):
            await update.message.reply_text("База кандидатов не найдена.")
            return ConversationHandler.END
            
        with open(CSV_FILE, "r", encoding="utf-8") as f:
            reader = csv.reader(f)
            next(reader, None)
            for row in reader:
                if row and row[0] == uid:
                    found = True
                    break
    except Exception as e:
        logger.error(f"Ошибка чтения CSV: {e}")
        await update.message.reply_text("Ошибка доступа к базе кандидатов.")
        return ConversationHandler.END

    if found:
        user_id = int(uid)
        if user_id not in user_data:
            # Попытка восстановить данные из CSV
            try:
                with open(CSV_FILE, "r", encoding="utf-8") as f:
                    reader = csv.reader(f)
                    next(reader, None)
                    for row in reader:
                        if row and row[0] == uid:
                            user_data[user_id] = {
                                "resume": row[3],
                                "vacancy_title": row[2]
                            }
                            break
            except Exception as e:
                logger.error(f"Ошибка восстановления данных: {e}")
                await update.message.reply_text("Ошибка восстановления данных кандидата.")
                return ConversationHandler.END
        
        await update.message.reply_text("Доступ подтверждён. Начинаем собеседование.")
        return await start_interview(update, context, user_id=user_id)
    else:
        await update.message.reply_text("Код доступа неверный.")
        return ConversationHandler.END

# ================== ИНТЕРВЬЮ ==================
async def start_interview(update: Update, context: ContextTypes.DEFAULT_TYPE, user_id=None):
    """Запуск собеседования"""
    if user_id is None:
        user_id = update.message.from_user.id

    # Инициализация истории
    if user_id not in user_data:
        user_data[user_id] = {}
    
    data = user_data[user_id]
    data["interview_history"] = []
    resume_short = data.get("resume", "")[:1500]

    prompt = {
        "modelUri": f"gpt://{YC_FOLDER_ID}/yandexgpt-lite",
        "completionOptions": {"stream": False, "temperature": 0.7, "maxTokens": 800},
        "messages": [
            {
                "role": "system",
                "text": "Ты интервьюер. Задавай релевантные вопросы по вакансии кандидату. Начни с простого вопроса о его опыте."
            },
            {"role": "user", "text": f"Резюме кандидата (сокращенное):\n{resume_short}"}
        ]
    }

    headers = {"Content-Type": "application/json", "Authorization": f"Api-Key {YC_API_KEY}"}

    try:
        r = requests.post(YC_GPT_URL, json=prompt, headers=headers, timeout=30)
        r.raise_for_status()
        result = r.json()

        # Проверяем корректность ответа
        alternatives = result.get("result", {}).get("alternatives", [])
        question = alternatives[0]["message"]["text"].strip() if alternatives else "Расскажите подробнее о вашем опыте работы."

        data["interview_history"].append(("Interviewer", question))
        data["current_question"] = question

        await update.message.reply_text(question)
        return INTERVIEW

    except Exception as e:
        logger.error(f"Ошибка запуска собеседования: {e}")
        await update.message.reply_text("Ошибка запуска собеседования.")
        return ConversationHandler.END

async def handle_interview_answer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка ответа кандидата и генерация следующего вопроса"""
    user_id = update.message.from_user.id
    
    if user_id not in user_data:
        await update.message.reply_text("Ошибка: данные сессии не найдены.")
        return ConversationHandler.END
        
    data = user_data[user_id]
    
    if "interview_history" not in data:
        await update.message.reply_text("Ошибка: история собеседования не найдена.")
        return ConversationHandler.END
        
    answer = update.message.text
    data["interview_history"].append(("Candidate", answer))
    
    # Берем последние 5 реплик для контекста
    recent_history = data["interview_history"][-5:] if len(data["interview_history"]) > 5 else data["interview_history"]
    resume_short = data.get("resume", "")[:1500]

    # Формируем промпт для GPT
    prompt = {
        "modelUri": f"gpt://{YC_FOLDER_ID}/yandexgpt-lite",
        "completionOptions": {"stream": False, "temperature": 0.7, "maxTokens": 800},
        "messages": [
            {
                "role": "system",
                "text": "Ты интервьюер. Задавай следующий релевантный вопрос по вакансии кандидату. Учитывай предыдущие ответы, задавай по одному вопросу за раз."
            }
        ]
    }

    # Добавляем историю диалога
    for speaker, text in recent_history:
        role = "assistant" if speaker == "Interviewer" else "user"
        prompt["messages"].append({"role": role, "text": text})

    # Добавляем резюме
    prompt["messages"].append({"role": "user", "text": f"Резюме кандидата (сокращенное):\n{resume_short}"})

    headers = {"Content-Type": "application/json", "Authorization": f"Api-Key {YC_API_KEY}"}

    try:
        r = requests.post(YC_GPT_URL, json=prompt, headers=headers, timeout=30)
        r.raise_for_status()
        result = r.json()

        alternatives = result.get("result", {}).get("alternatives", [])
        question = alternatives[0]["message"]["text"].strip() if alternatives else "Расскажите подробнее о вашем опыте работы."

        data["interview_history"].append(("Interviewer", question))
        data["current_question"] = question

        await update.message.reply_text(question)
        return INTERVIEW

    except Exception as e:
        logger.error(f"Ошибка генерации вопроса: {e}")
        await update.message.reply_text("Ошибка. Завершаем собеседование.")
        return await stop_interview(update, context)

async def stop_interview(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    
    if user_id not in user_data:
        await update.message.reply_text("Нет данных собеседования.")
        return ConversationHandler.END
        
    data = user_data[user_id]
    protocol = "\n".join([f"{s}: {t}" for s, t in data.get("interview_history", [])])

    # Генерация финального отчета
    prompt = {
        "modelUri": f"gpt://{YC_FOLDER_ID}/yandexgpt-lite",
        "completionOptions": {"stream": False, "temperature": 0.7, "maxTokens": 1500},
        "messages": [
            {"role": "system", "text": "Составь подробный отчёт и глубинный анализ по резюме и собеседованию."},
            {"role": "user", "text": f"Резюме:\n{data['resume']}\n\nПротокол собеседования:\n{protocol}"}
        ]
    }
    headers = {"Content-Type": "application/json", "Authorization": f"Api-Key {YC_API_KEY}"}

    try:
        r = requests.post(YC_GPT_URL, json=prompt, headers=headers, timeout=60)
        r.raise_for_status()
        text = r.json()["result"]["alternatives"][0]["message"]["text"]
        final_report, deep_analysis = text, text
    except Exception as e:
        logger.error(f"Ошибка генерации отчёта: {e}")
        final_report, deep_analysis = "", ""

    update_csv_with_protocol(user_id, protocol, final_report, deep_analysis)

    await update.message.reply_text("Собеседование завершено. Результаты сохранены.")
    return ConversationHandler.END

# ================== CANCEL ==================
async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Отмена текущей операции"""
    await update.message.reply_text("Операция отменена.")
    return ConversationHandler.END

# ================== HELP ==================
async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Справка по командам"""
    help_text = """
Доступные команды:
/start - начать процесс подачи заявки
/access <ID> - начать собеседование (для кандидатов)
/list_vacancies - список вакансий
/add_vacancy - добавить вакансию (только для админа)
/delete_vacancy - удалить вакансию (только для админа)
/help - показать эту справку
"""
    await update.message.reply_text(help_text)

# ================== MAIN ==================
def main():
    load_vacancies()
    
    # Создаем Application
    application = ApplicationBuilder().token(BOT_TOKEN).build()

    # Основной обработчик диалога
    conv_handler = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            SELECT_VACANCY: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, select_vacancy)
            ],
            UPLOAD_RESUME: [
                MessageHandler(filters.TEXT | filters.Document.ALL, handle_resume)
            ],
            INTERVIEW: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_interview_answer),
                CommandHandler("stop", stop_interview)
            ],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )
    application.add_handler(conv_handler)

    # Обработчики команд
    application.add_handler(CommandHandler("list_vacancies", list_vacancies))
    application.add_handler(CommandHandler("delete_vacancy", delete_vacancy))
    application.add_handler(CommandHandler("access", access_command))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CallbackQueryHandler(confirm_delete_vacancy, pattern="^delete_"))

    # Обработчик добавления вакансий
    add_vac_handler = ConversationHandler(
        entry_points=[CommandHandler("add_vacancy", add_vacancy)],

states={
            1: [MessageHandler(filters.TEXT & ~filters.COMMAND, save_vacancy_text)]
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )
    application.add_handler(add_vac_handler)

    # Запускаем бота
    logger.info("Бот запущен...")
    application.run_polling()

if __name__ == "__main__":
    main()