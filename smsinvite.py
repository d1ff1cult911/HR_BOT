from twilio.rest import Client
from google.oauth2.service_account import Credentials
import gspread
import time
import logging

# Настройка логирования
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Конфигурация Twilio
SID = ''
AUTH_TOKEN = ''
SYS_NUMBER = ''

# Конфигурация Google Sheets
GOOGLE_SHEETS_CREDENTIALS_FILE = 'credentials.json'
GOOGLE_SHEET_NAME = 'hr-base'
GOOGLE_WORKSHEET = 'Demo'

# Конфигурация сайта
SITE_LINK = ''

def init_google_sheets():
    """Инициализирует подключение к Google Sheets"""
    try:
        scopes = ['https://www.googleapis.com/auth/spreadsheets',
                 'https://www.googleapis.com/auth/drive']
        creds = Credentials.from_service_account_file(GOOGLE_SHEETS_CREDENTIALS_FILE, scopes=scopes)
        client = gspread.authorize(creds)
        sheet = client.open(GOOGLE_SHEET_NAME).worksheet(GOOGLE_WORKSHEET)
        return sheet
    except Exception as e:
        logger.error(f"Ошибка инициализации Google Sheets: {e}")
        return None

def get_candidates_data(sheet):
    """Получает данные кандидатов из таблицы"""
    try:
        # Получаем все записи
        records = sheet.get_all_records()
        
        candidates = []
        for i, record in enumerate(records, start=2):
            # Проверяем, что есть номер телефона и код не использовался
            phone = record.get('resume-personal-phone', '') or record.get('phone', '') or record.get('телефон', '')
            code = record.get('CODE', '')
            vacancy = record.get('VACATION-TEXT', '') or record.get('vacancy', '') or record.get('вакансия', '')
            
            if phone and code:
                # Очищаем номер телефона от лишних символов
                cleaned_phone = clean_phone_number(phone)
                if cleaned_phone:
                    candidates.append({
                        'row': i,
                        'phone': cleaned_phone,
                        'code': code,
                        'vacancy': vacancy,
                        'name': record.get('resume-personal-name', '') or record.get('name', '') or 'Кандидат'
                    })
        
        return candidates
    except Exception as e:
        logger.error(f"Ошибка получения данных кандидатов: {e}")
        return []

def clean_phone_number(phone):
    """Очищает номер телефона от лишних символов и приводит к международному формату"""
    try:
        # Удаляем все нецифровые символы
        cleaned = ''.join(filter(str.isdigit, str(phone)))
        
        # Если номер начинается с 8, заменяем на +7
        if cleaned.startswith('8') and len(cleaned) == 11:
            cleaned = '7' + cleaned[1:]
        
        # Если номер без кода страны, добавляем +7 для России
        if len(cleaned) == 10:
            cleaned = '7' + cleaned
        
        # Добавляем + в начало
        if cleaned and not cleaned.startswith('+'):
            cleaned = '+' + cleaned
            
        return cleaned
    except Exception as e:
        logger.error(f"Ошибка очистки номера {phone}: {e}")
        return None

def send_sms(text, receiver):
    """Отправляет SMS через Twilio"""
    try:
        account_sid = SID
        auth_token = AUTH_TOKEN
        sender_number = SYS_NUMBER

        client = Client(account_sid, auth_token)

        message = client.messages.create(
            body=text,
            from_=sender_number,
            to=receiver
        )

        logger.info(f"SMS отправлено на {receiver}: {message.sid}")
        return f"SMS успешно отправлено на {receiver}"
        
    except Exception as ex:
        error_msg = f"Ошибка отправки SMS на {receiver}: {str(ex)}"
        logger.error(error_msg)
        return error_msg

def generate_sms_text(candidate_name, vacancy, code):
    """Генерирует текст SMS сообщения"""
    if vacancy:
        vacancy_text = f"по вакансии '{vacancy[:50]}{'...' if len(vacancy) > 50 else ''}'"
    else:
        vacancy_text = "в нашу компанию"
    
    message = f"""Добрый день, {candidate_name}! Приглашаем Вас пройти онлайн-собеседование на вакансию {vacancy_text}.

Ваш код доступа: {code}
Сайт для прохождения: {SITE_LINK}

Собеседование займет 15-20 минут. Желаем успехов!"""

    return message

def mark_as_sent(sheet, row):
    """Помечает кандидата как отправленного (добавляет отметку в таблицу)"""
    try:
        # Предположим, что у нас есть колонка "SMS_SENT" или создаем ее
        headers = sheet.row_values(1)
        
        if "SMS_SENT" not in headers:
            # Добавляем новую колонку если ее нет
            sms_sent_col = len(headers) + 1
            sheet.update_cell(1, sms_sent_col, "SMS_SENT")
        else:
            sms_sent_col = headers.index("SMS_SENT") + 1
        
        # Помечаем как отправлено с timestamp
        timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
        sheet.update_cell(row, sms_sent_col, f"Отправлено {timestamp}")
        
        logger.info(f"Кандидат в строке {row} помечен как отправленный")
        return True
        
    except Exception as e:
        logger.error(f"Ошибка пометки кандидата в строке {row}: {e}")
        return False

def main():
    """Основная функция скрипта"""
    logger.info("Запуск скрипта рассылки SMS...")
    
    # Инициализируем Google Sheets
    sheet = init_google_sheets()
    if not sheet:
        logger.error("Не удалось подключиться к Google Sheets")
        return
    
    # Получаем данные кандидатов
    candidates = get_candidates_data(sheet)
    if not candidates:
        logger.warning("Не найдено кандидатов для рассылки")
        return
    
    logger.info(f"Найдено {len(candidates)} кандидатов для рассылки")
    
    # Счетчики для статистики
    success_count = 0
    fail_count = 0
    
    # Проходим по всем кандидатам
    for candidate in candidates:
        try:
            # Генерируем текст сообщения
            sms_text = generate_sms_text(
                candidate['name'],
                candidate['vacancy'],
                candidate['code']
            )
            
            logger.info(f"Отправка SMS на {candidate['phone']}...")
            
            # Отправляем SMS
            result = send_sms(sms_text, candidate['phone'])
            
            if "успешно" in result.lower():
                # Помечаем как отправленного
                mark_as_sent(sheet, candidate['row'])
                success_count += 1
                logger.info(f"✓ Успешно отправлено: {candidate['phone']}")
            else:
                fail_count += 1
                logger.error(f"✗ Ошибка: {candidate['phone']} - {result}")
            
            # Пауза между отправками чтобы не превысить лимиты Twilio
            time.sleep(1)
            
        except Exception as e:
            fail_count += 1
            logger.error(f"Ошибка обработки кандидата {candidate['phone']}: {e}")
            continue
    
    # Выводим итоговую статистику
    logger.info("=" * 50)
    logger.info("РАССЫЛКА ЗАВЕРШЕНА")
    logger.info(f"Успешно отправлено: {success_count}")
    logger.info(f"Не удалось отправить: {fail_count}")
    logger.info(f"Всего обработано: {len(candidates)}")
    logger.info("=" * 50)

if __name__ == "__main__":
    # Проверяем наличие необходимых переменных
    if not all([SID, AUTH_TOKEN, SYS_NUMBER]):
        logger.error("Не заданы переменные Twilio. Проверьте SID, AUTH_TOKEN и SYS_NUMBER.")
    elif not SITE_LINK:
        logger.error("Не задана ссылка на сайт. Проверьте SITE_LINK.")
    else:
        main()