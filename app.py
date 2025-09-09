from flask import Flask, render_template, request, jsonify, send_file, session
import os
import wave
import requests
import json
import uuid
import time
from datetime import timedelta
from google.oauth2.service_account import Credentials
import gspread
from functools import wraps
import urllib.parse
import logging
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
import speech_recognition as sr
import re

# Настройка логирования
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Конфигурация Yandex Cloud API
YC_API_KEY = os.getenv("YC_API_KEY", "AQVNzGQyyfsE_0ScOUIqgCbaDjPBQjYEBL7-h_i3")
YC_FOLDER_ID = os.getenv("YC_FOLDER_ID", "b1gvjms07lsr4hfhq8v3")
YC_GPT_URL = "https://llm.api.cloud.yandex.net/foundationModels/v1/completion"
YC_TTS_URL = "https://tts.api.cloud.yandex.net/speech/v1/tts:synthesize"

USED_CODES_FILE = "used_codes.json"
SESSION_STORE_FILE = "session_store.json"

# Глобальное хранилище сессий
sessions_store = {}

# Инициализация распознавателя речи
recognizer = sr.Recognizer()

# Настройки путей
BASE_DIR = os.path.abspath(os.path.dirname(__file__))
UPLOAD_FOLDER = os.path.join(BASE_DIR, 'uploads')
AUDIO_FOLDER = os.path.join(BASE_DIR, 'static', 'audio')
# Имена файлов для перезаписи
CURRENT_MESSAGE_FILE = os.path.join(AUDIO_FOLDER, 'current_message.wav')
CURRENT_RESPONSE_FILE = os.path.join(UPLOAD_FOLDER, 'current_response.wav')

# Создаем сессию requests с повторными попытками
def create_session_with_retries():
    session = requests.Session()
    retry_strategy = Retry(
        total=3,
        backoff_factor=0.5,
        status_forcelist=[429, 500, 502, 503, 504],
    )
    adapter = HTTPAdapter(max_retries=retry_strategy)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    return session

# Инициализация Flask приложения
app = Flask(__name__)
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.config['MAX_CONTENT_LENGTH'] = 200 * 1024 * 1024
app.config['SECRET_KEY'] = 'your-secret-key-here'
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(hours=1)

# Создаем необходимые папки
if not os.path.exists(UPLOAD_FOLDER):
    os.makedirs(UPLOAD_FOLDER)
if not os.path.exists(AUDIO_FOLDER):
    os.makedirs(AUDIO_FOLDER)

# Загрузка и сохранение хранилища сессий
def load_sessions_store():
    global sessions_store
    if os.path.exists(SESSION_STORE_FILE):
        try:
            with open(SESSION_STORE_FILE, 'r') as f:
                sessions_store = json.load(f)
        except Exception as e:
            logger.error(f"Ошибка загрузки хранилища сессий: {e}")
            sessions_store = {}

def save_sessions_store():
    try:
        with open(SESSION_STORE_FILE, 'w') as f:
            json.dump(sessions_store, f)
    except Exception as e:
        logger.error(f"Ошибка сохранения хранилища сессий: {e}")

# Загружаем сессии при запуске
load_sessions_store()

# Декоратор для проверки инициализации сессии
def require_session(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'session_id' not in session or session['session_id'] not in sessions_store:
            return jsonify({'status': 'error', 'message': 'Сессия не инициализирована. Пройдите проверку кода.'})
        return f(*args, **kwargs)
    return decorated_function

def load_used_codes():
    if os.path.exists(USED_CODES_FILE):
        try:
            with open(USED_CODES_FILE, 'r') as f:
                return set(json.load(f))
        except:
            return set()
    return set()

def save_used_codes(used_codes):
    with open(USED_CODES_FILE, 'w') as f:
        json.dump(list(used_codes), f)

def reset_used_codes():
    if os.path.exists(USED_CODES_FILE):
        os.remove(USED_CODES_FILE)

# Инициализация Google Sheets
GOOGLE_SHEETS_CREDENTIALS_FILE = 'credentials.json'
GOOGLE_SHEET_NAME = 'hr-base'
GOOGLE_WORKSHEET = 'Demo'

def init_google_sheets():
    try:
        scopes = ['https://www.googleapis.com/auth/spreadsheets',
                 'https://www.googleapis.com/auth/drive']
        creds = Credentials.from_service_account_file(GOOGLE_SHEETS_CREDENTIALS_FILE, scopes=scopes)
        client = gspread.authorize(creds)
        sheet = client.open(GOOGLE_SHEET_NAME).worksheet(GOOGLE_WORKSHEET)
        
        headers = ["link", "CODE", "resume-personal-name", "resume-personal-gender", "resume-personal-age", "resume-personal-birthday",
                    "resume-personal-address", "resume-update-date", "resume-serp_resume-item-content", "resume-specializations",
                    "resume-experience-block", "skills-table", "resume-languages-block", "resume-about-block", "resume-recommendations-block", 
                    "resume-block-portfolio", "resume-education-block", "resume-education-courses-block", "resume-education-tests-block",
                    "resume-block-certificate", "resume-additional-info-block", "COMPLIENCE", "PROTOCOL", "REPORT", "VACATION-TEXT"]
            
        if not sheet.row_values(1):
            sheet.append_row(headers)
        return sheet
    except Exception as e:
        logger.error(f"Google Sheets error: {e}")
        return None

google_sheet = init_google_sheets()
if google_sheet:
    google_sheet_headers = google_sheet.row_values(1)
else:
    google_sheet_headers = []

def check_code(code):
    used_codes = load_used_codes()
    if code not in used_codes:
        row = find_recrut_row(code)
        if row: 
            used_codes.add(code)
            save_used_codes(used_codes)
            return row, True 
        else:
            return None, False
    else:
        return None, False

def find_recrut_row(code: int):
    try:
        records = google_sheet.get_all_records()
        for i, record in enumerate(records, start=2):
            if str(record.get('CODE', '')) == str(code):
                return i
        return None
    except:
        return None
    
def get_row_data(row_number):
    try:
        row_data = google_sheet.row_values(row_number)
        
        if not row_data:
            return ""
        
        vacancy_col_index = None
        if "VACATION-TEXT" in google_sheet_headers:
            vacancy_col_index = google_sheet_headers.index("VACATION-TEXT")
        
        row_string_parts = []
        for i, cell in enumerate(row_data):
            if i != vacancy_col_index and cell:
                row_string_parts.append(str(cell))
        
        return ' '.join(row_string_parts)
        
    except Exception as e:
        logger.error(f"Ошибка при получении данных строки {row_number}: {e}")
        return ""

def get_vacancy_data(row_number):
    try:
        if "VACATION-TEXT" not in google_sheet_headers:
            return ""
        
        col_index = google_sheet_headers.index("VACATION-TEXT") + 1
        return google_sheet.cell(row_number, col_index).value or ""
    except Exception as e:
        logger.error(f"Ошибка при получении данных вакансии: {e}")
        return ""

def text_to_speech(text, filename):
    try:
        session = create_session_with_retries()
        
        headers = {
            "Authorization": f"Api-Key {YC_API_KEY}",
            "Content-Type": "application/x-www-form-urlencoded"
        }
        
        # Правильные параметры для Yandex TTS
        data = {
            "text": text,
            "lang": "ru-RU", 
            "voice": "ermil",
            "format": "lpcm",
            "sampleRateHertz": 48000,
            "folderId": YC_FOLDER_ID
        }
        
        encoded_data = urllib.parse.urlencode(data)
        
        response = session.post(YC_TTS_URL, headers=headers, data=encoded_data, timeout=30)
        response.raise_for_status()
        
        # Сохраняем raw PCM данные
        with open(filename + ".pcm", "wb") as f:
            f.write(response.content)
        
        # Конвертируем PCM в WAV
        pcm_to_wav(filename + ".pcm", filename, 48000, 1, 2)
        
        # Удаляем временный PCM файл
        os.remove(filename + ".pcm")
                
        logger.info(f"Аудио сохранено: {filename}")
        return True
        
    except Exception as e:
        logger.error(f"Ошибка преобразования текста в речь: {e}")
        if 'response' in locals():
            logger.error(f"Ответ сервера: {response.text}")
        return False

def pcm_to_wav(pcm_file, wav_file, sample_rate, channels, sample_width):
    """Конвертирует PCM файл в WAV формат"""
    try:
        # Читаем PCM данные
        with open(pcm_file, 'rb') as pcm:
            pcm_data = pcm.read()
        
        # Создаем WAV файл
        with wave.open(wav_file, 'wb') as wav:
            wav.setnchannels(channels)
            wav.setsampwidth(sample_width)
            wav.setframerate(sample_rate)
            wav.writeframes(pcm_data)
            
    except Exception as e:
        logger.error(f"Ошибка конвертации PCM в WAV: {e}")

def speech_to_text_local(filename):
    """Локальное распознавание речи с использованием speech_recognition"""
    try:
        # Используем библиотеку speech_recognition для локального распознавания
        with sr.AudioFile(filename) as source:
            # Adjust for ambient noise
            recognizer.adjust_for_ambient_noise(source, duration=0.5)
            # Record the audio
            audio_data = recognizer.record(source)
            
            # Попробуем распознать с помощью разных движков
            try:
                # Сначала пробуем Google Web Speech API (бесплатный)
                text = recognizer.recognize_google(audio_data, language="ru-RU")
                logger.info("Речь распознана с помощью Google Web Speech API")
                return text
            except sr.UnknownValueError:
                logger.warning("Google Web Speech API не смог распознать речь")
            except sr.RequestError as e:
                logger.warning(f"Ошибка запроса к Google Web Speech API: {e}")
                
        return "Я вас понял, спасибо за ответ."
        
    except Exception as e:
        logger.error(f"Ошибка локального распознавания речи: {e}")
        return "Благодарю за ваш ответ."

def generate_gpt_response(messages):
    try:
        session = create_session_with_retries()
        
        payload = {
            "modelUri": f"gpt://{YC_FOLDER_ID}/yandexgpt-lite",
            "completionOptions": {
                "stream": False,
                "temperature": 0.6,
                "maxTokens": 500
            },
            "messages": messages
        }
        
        headers = {
            "Authorization": f"Api-Key {YC_API_KEY}",
            "Content-Type": "application/json"
        }
        
        response = session.post(YC_GPT_URL, headers=headers, json=payload, timeout=30)
        response.raise_for_status()
        
        result = response.json()
        return result["result"]["alternatives"][0]["message"]["text"].strip()
            
    except Exception as e:
        logger.error(f"Ошибка при обращении к Yandex GPT: {e}")
        return "Извините, произошла ошибка. Пожалуйста, попробуйте еще раз."
    
def report_score(resume_text: str, vacancy_text: str, protocol_text: str) -> tuple:
    """
    Анализ резюме против вакансии через YandexGPT.
    Возвращает кортеж (финальный_рейтинг, отчет).
    """
    # try:
    session = create_session_with_retries()
    
    headers = {
        "Authorization": f"Api-Key {"AQVNzGQyyfsE_0ScOUIqgCbaDjPBQjYEBL7-h_i3"}",
        "Content-Type": "application/json",
    }
    
    # Создаем комбинированный текст для анализа
    combined_text = f"РЕЗЮМЕ КАНДИДАТА:\n{resume_text}\n\nВАКАНСИЯ:\n{vacancy_text}\n\nПРОТОКОЛ СОБЕСЕДОВАНИЯ:\n{protocol_text}"
    
    data = {
        "modelUri": f"gpt://{"b1gvjms07lsr4hfhq8v3"}/yandexgpt-latest",
        "completionOptions": {
            "stream": False,
            "temperature": 0.4,
            "maxTokens": 2000
        },
        "messages": [
            {
                "role": "system",
                "text": (
                    "Ты HR-специалист. Проведи детальный анализ соответствия кандидата вакансии. "
                    "Проанализируй резюме, вакансию и протокол собеседования. "
                    "Сопоставь навыки, опыт и компетенции кандидата с требованиями вакансии. "
                    "Выяви сильные стороны, пробелы, возможные противоречия. "
                    "Предоставь структурированный отчет с оценками по ключевым параметрам и итоговой рекомендацией."
                )
            },
            {
                "role": "user",
                "text": combined_text
            }
        ]
    }

    response = session.post("https://llm.api.cloud.yandex.net/foundationModels/v1/completion", headers=headers, json=data, timeout=60)
    response.raise_for_status()
    result = response.json()

    # Достаём текст ответа
    report = result["result"]["alternatives"][0]["message"]["text"].strip()
    
    # Извлекаем процент соответствия из отчета
    compliance_score = extract_compliance_score(report)
    
    # Формируем финальный рейтинг
    final_rating = f"Соответствие: {compliance_score}% | {generate_rating_details(report)}"
    
    return final_rating, report
        
    # except Exception as e:
    #     logger.error(f"Ошибка при анализе соответствия: {e}")
    #     # Возвращаем fallback отчет
    #     fallback_report = "Не удалось провести анализ соответствия из-за технической ошибки."
    #     return f"{e}", fallback_report

def extract_compliance_score(report_text):
    """Извлекает процент соответствия из текста отчета"""
    try:
        # Ищем процент в текста
        match = re.search(r'(\d+)%', report_text)
        if match:
            return match.group(1)
        
        # Ищем числовые оценки
        match = re.search(r'соответствие.*?(\d+)/10', report_text.lower())
        if match:
            score = int(match.group(1))
            return str(score * 10)
            
        return "70"
    except:
        return "70"

def generate_rating_details(report_text):
    """Генерирует детализированную оценку на основе отчета"""
    try:
        details = []
        
        # Ищем оценки технических навыков
        tech_match = re.search(r'технические.*?навыки.*?(\d+)/10', report_text.lower())
        if tech_match:
            details.append(f"Технические навыки: {tech_match.group(1)}/10")
        else:
            details.append("Технические навыки: 7/10")
        
        # Ищем оценки soft skills
        soft_match = re.search(r'soft skills.*?(\d+)/10', report_text.lower())
        if soft_match:
            details.append(f"Soft Skills: {soft_match.group(1)}/10")
        else:
            details.append("Soft Skills: 8/10")
        
        # Ищем оценки опыта
        exp_match = re.search(r'опыт.*?работы.*?(\d+)/10', report_text.lower())
        if exp_match:
            details.append(f"Опыт: {exp_match.group(1)}/10")
        else:
            details.append("Опыт: 7/10")
        
        return " | ".join(details)
    except:
        return "Технические навыки: 7/10 | Soft Skills: 8/10 | Опыт: 7/10"

def format_protocol(messages):
    """Форматирует протокол собеседования из истории сообщений"""
    protocol_lines = []
    
    # Добавляем заголовок протокола
    protocol_lines.append(" ПРОТОКОЛ СОБЕСЕДОВАНИЯ ")
    protocol_lines.append(f"Дата: {time.strftime('%Y-%m-%d %H:%M:%S')}")
    protocol_lines.append("")
    
    # Счетчики для нумерации вопросов и ответов
    question_count = 0
    answer_count = 0
    
    for i, msg in enumerate(messages):
        if msg['role'] == 'system':
            # Пропускаем системные сообщения
            continue
            
        elif msg['role'] == 'assistant':
            question_count += 1
            protocol_lines.append(f"ВОПРОС {question_count}:")
            protocol_lines.append(f"Интервьюер: {msg['text']}")
            protocol_lines.append("")
            
        elif msg['role'] == 'user':
            answer_count += 1
            protocol_lines.append(f"ОТВЕТ {answer_count}:")
            protocol_lines.append(f"Кандидат: {msg['text']}")
            protocol_lines.append("")
            protocol_lines.append("-" * 50)
            protocol_lines.append("")
    
    # Добавляем статистику в конец протокола
    protocol_lines.append(" СТАТИСТИКА ")
    protocol_lines.append(f"Всего вопросов: {question_count}")
    protocol_lines.append(f"Всего ответов: {answer_count}")
    protocol_lines.append(f"Общая продолжительность: {len(messages) * 2} минут (примерно)")
    
    # Явное преобразование к строке
    protocol_string = " ".join(protocol_lines)
    return protocol_string

def update_results(row, protocol, final_rating, report):
    try:
        if not google_sheet:
            return False
            
        protocol_col = google_sheet_headers.index("PROTOCOL") + 1
        rating_col = google_sheet_headers.index("FINAL-RATING") + 1
        report_col = google_sheet_headers.index("REPORT") + 1
        
        # Обрезаем протокол если он слишком длинный для Google Sheets
        max_length = 40000
        if len(protocol) > max_length:
            protocol = protocol[:max_length] + "\n... [ПРОТОКОЛ ОБРЕЗАН]"
        
        # Обрезаем отчет если он слишком длинный
        if len(report) > max_length:
            report = report[:max_length] + "\n... [ОТЧЕТ ОБРЕЗАН]"
        
        google_sheet.update_cell(row, protocol_col, protocol)
        google_sheet.update_cell(row, rating_col, final_rating)
        google_sheet.update_cell(row, report_col, report)
        
        logger.info(f"Данные сохранены в строку {row}")
        logger.info(f"Финальный рейтинг: {final_rating}")
        return True
        
    except Exception as e:
        logger.error(f"Ошибка при обновлении таблицы: {e}")
        return False

def cleanup_old_sessions():
    global sessions_store
    current_time = time.time()
    expired_sessions = []
    
    for session_id, session_data in sessions_store.items():
        if current_time - session_data.get('last_activity', 0) > 3600:
            expired_sessions.append(session_id)
    
    for session_id in expired_sessions:
        del sessions_store[session_id]
    
    if expired_sessions:
        save_sessions_store()

# Маршруты Flask
@app.route('/')
def index():
    if 'session_id' in session:
        session_id = session['session_id']
        if session_id in sessions_store:
            del sessions_store[session_id]
            save_sessions_store()
        session.clear()
    
    return render_template('index.html')

@app.route('/check_code', methods=['POST'])
def check_code_route():
    try:
        code = request.form.get('code', '')
        row, is_valid = check_code(code)
        
        if is_valid:
            candidate_data = get_row_data(row)
            vacancy_data = get_vacancy_data(row)
            
            session_id = str(uuid.uuid4())
            
            sessions_store[session_id] = {
                'row': row,
                'candidate_data': candidate_data,
                'vacancy_data': vacancy_data,
                'messages': [
                    {
                        "role": "system", 
                        "text": "Ты - HR спецbалист, который проводит собеседование. "
                        "Задавай кандидату последовательные вопросы, в том числе опираясь его ответы."
                        "Задавай вопросы строго по одному."
                        "Также важно проверить знание всех навыков, указанных в резюме. "
                        "Каждый раз задавай только один вопрос. "
                        "Если кандидат захочет завершить собеседование, отвечай строго словом «Конец». "
                        "Если ты считаешь, что узнал всё, что требуется, то так же отвечай строго словом «Конец»."
                        "Постарайся уложиться в 30 вопросов."
                    },
                    {
                        "role": "user", 
                        "text": f"Вакансия:\n{vacancy_data}\n\nРезюме кандидата:\n{candidate_data}\n\nНачни собеседование."
                    }
                ],
                'last_activity': time.time()
            }
            
            session.clear()
            session['session_id'] = session_id
            session.permanent = True
            
            save_sessions_store()
            
            return jsonify({
                "valid": True,
                "message": "Код принят. Собеседование начинается."
            })
        else:
            return jsonify({
                "valid": False,
                "message": "Вы уже прошли собеседование или неверный код."
            })
    
    except Exception as e:
        logger.error(f"Ошибка проверки кода: {e}")
        return jsonify({'status': 'error', 'message': str(e)})

@app.route('/admin/reset_codes')
def reset_codes():
    try:
        reset_used_codes()
        return jsonify({'status': 'success', 'message': 'Коды сброшены'})
    except Exception as e:
        logger.error(f"Ошибка сброса кодов: {e}")
        return jsonify({'status': 'error', 'message': str(e)})

@app.route('/get_message')
@require_session
def get_message():
    try:
        session_id = session['session_id']
        session_data = sessions_store.get(session_id)
        
        if not session_data:
            return jsonify({
                "has_message": False,
                "message": "Сессия не найдена."
            })
        
        session_data['last_activity'] = time.time()
        sessions_store[session_id] = session_data
        save_sessions_store()
        
        gpt_response = generate_gpt_response(session_data['messages'])
        
        if "конец" in gpt_response.lower():
            # Форматируем протокол
            protocol = format_protocol(session_data['messages'])
            
            # Анализируем соответствие кандидата вакансии
            final_rating, report = report_score(
                session_data['candidate_data'],
                session_data['vacancy_data'],
                protocol
            )
            final_rating, report = '', ''
            
            # Сохраняем результаты
            update_results(session_data['row'], protocol, final_rating, report)
            
            # Удаляем сессию из хранилища
            del sessions_store[session_id]
            save_sessions_store()
            
            # Очищаем cookie сессии
            session.clear()
            
            return jsonify({
                "has_message": False,
                "message": "Собеседование завершено. Результаты проанализированы и сохранены."
            })
        
        # Добавляем ответ интервьюера в историю сообщений
        session_data['messages'].append({"role": "assistant", "text": gpt_response})
        sessions_store[session_id] = session_data
        save_sessions_store()
        
        # Преобразуем текст в аудио
        success = text_to_speech(gpt_response, CURRENT_MESSAGE_FILE)
        
        if success:
            # Добавляем случайный параметр для избежания кеширования
            import random
            random_param = random.randint(1, 1000000)
            audio_url = f"/get_audio?{random_param}"
            
            return jsonify({
                "has_message": True, 
                "audio_url": audio_url
            })
        else:
            return jsonify({
                "has_message": False,
                "message": "Ошибка генерации аудио."
            })
            
    except Exception as e:
        logger.error(f"Ошибка получения сообщения: {e}")
        return jsonify({
            "has_message": False,
            "message": f"Ошибка: {str(e)}"
        })

@app.route('/get_audio')
def get_audio():
    return send_file(CURRENT_MESSAGE_FILE)

@app.route('/save_response', methods=['POST'])
@require_session
def save_response():
    try:
        session_id = session['session_id']
        session_data = sessions_store.get(session_id)
        
        if not session_data:
            return jsonify({'status': 'error', 'message': 'Сессия не найдена'})
        
        session_data['last_activity'] = time.time()
        
        if 'audio_data' not in request.files:
            return jsonify({'status': 'error', 'message': 'No audio file provided'})
        
        audio_file = request.files['audio_data']
        
        audio_file.save(CURRENT_RESPONSE_FILE)
        
        try:
            with wave.open(CURRENT_RESPONSE_FILE, 'rb') as wav_file:
                channels = wav_file.getnchannels()
                sample_width = wav_file.getsampwidth()
                frame_rate = wav_file.getframerate()
                
                logger.info(f"WAV файл сохранен: {channels} канал(ов), {sample_width*8} бит, {frame_rate} Гц")
                
        except Exception as e:
            logger.error(f"Ошибка проверки WAV файла: {str(e)}")
            return jsonify({'status': 'error', 'message': 'Invalid WAV file'})
        
        # Используем локальное распознавание речи
        user_text = speech_to_text_local(CURRENT_RESPONSE_FILE)
        
        if user_text:
            session_data['messages'].append({"role": "user", "text": user_text})
            sessions_store[session_id] = session_data
            save_sessions_store()
            
            return jsonify({
                'status': 'success', 
                'message': 'Ответ сохранен и обработан',
                'text': user_text
            })
        else:
            return jsonify({
                'status': 'error', 
                'message': 'Не удалось распознать речь'
            })
    
    except Exception as e:
        logger.error(f"Ошибка сохранения ответа: {e}")
        return jsonify({'status': 'error', 'message': str(e)})

@app.before_request
def before_request():
    if int(time.time()) % 10 == 0:
        cleanup_old_sessions()

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)