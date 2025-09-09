from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from webdriver_manager.chrome import ChromeDriverManager
from google.oauth2.service_account import Credentials
import gspread
import time
import requests
import json
import docx2txt

# Global constants
TARGET_DATA_QA = [
    "resume-personal-name",
    "resume-personal-gender",
    "resume-personal-age",
    "resume-personal-birthday",
    "resume-personal-address",
    "resume-update-date",
    "resume-serp_resume-item-content",
    "resume-specializations",
    "resume-experience-block",
    "skills-table",
    "resume-languages-block",
    "resume-about-block",
    "resume-recommendations-block",
    "resume-block-portfolio",
    "resume-education-block",
    "resume-education-courses-block",
    "resume-education-tests-block",
    "resume-block-certificate",
    "resume-additional-info-block"
]

# Google Sheets settings
GOOGLE_SHEETS_CREDENTIALS_FILE = 'credentials.json'
GOOGLE_SHEET_NAME = 'hr-base'
GOOGLE_WORKSHEET_ALL = 'All'
GOOGLE_WORKSHEET_TEST = 'Test_Vacation'


def extract_docx(file_path):
    """
    Извлекает текст из .docx файла с помощью docx2txt
    """
    try:
        text = docx2txt.process(file_path)
        return text
    except Exception as e:
        print(f"Ошибка при чтении файла: {e}")
        return None

# Конфиг (замени своими значениями)
YC_GPT_URL = "https://llm.api.cloud.yandex.net/foundationModels/v1/completion"
YC_FOLDER_ID = "b1gvjms07lsr4hfhq8v3"
YC_API_KEY = "AQVNzGQyyfsE_0ScOUIqgCbaDjPBQjYEBL7-h_i3"

def determine_score(resume_text: str, vacancy_text: str) -> int:
    """
    Анализ резюме против вакансии через YandexGPT.
    Возвращает процент соответствия.
    """
    headers = {
        "Authorization": f"Api-Key {YC_API_KEY}",
        "Content-Type": "application/json",
    }
    data = {
        "modelUri": f"gpt://{YC_FOLDER_ID}/yandexgpt/latest",
        "completionOptions": {
            "stream": False,
            "temperature": 0.2,
            "maxTokens": 1000
        },
        "messages": [
            {
                "role": "system",
                "text": (
                    "Ты HR-специалист. Сравни резюме и вакансию и оцени, "
                    "насколько кандидат подходит. Верни только число процентов (0–100)."
                )
            },
            {
                "role": "user",
                "text": f"Вакансия:\n{vacancy_text}\n\nРезюме:\n{resume_text}"
            }
        ]
    }

    resp = requests.post(YC_GPT_URL, headers=headers, data=json.dumps(data))
    resp.raise_for_status()
    result = resp.json()

    # Достаём текст ответа
    answer = result["result"]["alternatives"][0]["message"]["text"]

    # Пробуем выделить число
    try:
        percent = int("".join(ch for ch in answer if ch.isdigit()))
        # Преобразуем проценты в дробное число от 0.0 до 1.0
        return max(0.0, min(1.0, percent / 100.0))
    except ValueError:
        return 0.0

def init_google_sheets(sheet_name):
    # Initialize Google Sheets for specific worksheet
    try:
        scopes = ['https://www.googleapis.com/auth/spreadsheets',
                 'https://www.googleapis.com/auth/drive']
        creds = Credentials.from_service_account_file(GOOGLE_SHEETS_CREDENTIALS_FILE, scopes=scopes)
        client = gspread.authorize(creds)
        sheet = client.open(GOOGLE_SHEET_NAME).worksheet(sheet_name)
        
        # Create headers if they don't exist
        if sheet_name == GOOGLE_WORKSHEET_TEST:
            headers = ["CODE", "link"] + TARGET_DATA_QA + ["COMPLIENCE", "PROTOCOL", "REPORT", "FINAL-RATING", "VACATION-TEXT"]
        else:
            headers = ["link"] + TARGET_DATA_QA
            
        if not sheet.row_values(1):
            sheet.append_row(headers)
        return sheet
    except Exception as e:
        print(f"Google Sheets error ({sheet_name}): {e}")
        return None

def setup_driver():
    # Initialize and configure Chrome driver
    options = Options()
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    
    driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=options)
    driver.maximize_window()
    return driver

def login_to_site(driver):
    # Navigate to login page and expand password login
    try:
        driver.get("https://hh.ru/account/login?role=employer")
        WebDriverWait(driver, 20).until(
            EC.presence_of_element_located((By.TAG_NAME, "body"))
        )
        print('Page loaded successfully')
        
        login_button = WebDriverWait(driver, 20).until(
            EC.element_to_be_clickable((By.CSS_SELECTOR, "button[data-qa='expand-login-by_password']"))
        )
        print('Button found')
        
        driver.execute_script("arguments[0].click();", login_button)
        print("Click via JavaScript executed")
        time.sleep(3)
        return True
    except Exception as e:
        print(f"Error occurred: {e}")
        return False

def enter_credentials(driver):
    # Enter email and password credentials
    try:
        email_field = WebDriverWait(driver, 10).until(
            EC.element_to_be_clickable((By.CSS_SELECTOR, "input[data-qa='login-input-username']"))
        )
        email_field.clear()
        email_field.send_keys("")
        print("Login entered successfully")
        time.sleep(3)
        
        password_field = WebDriverWait(driver, 10).until(
            EC.element_to_be_clickable((By.CSS_SELECTOR, "input[data-qa='login-input-password']"))
        )
        password_field.clear()
        password_field.send_keys("")
        print("Password entered successfully")
        
        login_button = WebDriverWait(driver, 20).until(
            EC.element_to_be_clickable((By.CSS_SELECTOR, "button[data-qa='account-login-submit']"))
        )
        print('Login button found')

        driver.execute_script("arguments[0].click();", login_button)
        print("Login click via JavaScript executed")
        time.sleep(5)
        return True
    except Exception as e:
        print(f"Error occurred: {e}")
        return False

def get_all_resume_links(driver):
    # Get all resume links from the vacancies page
    try:
        print("Redirecting to vacancies page...")
        driver.get("https://hh.ru/search/resume?text=&professional_role=156&professional_role=160&professional_role=10&professional_role=150&professional_role=165&professional_role=36&professional_role=96&professional_role=164&professional_role=104&professional_role=157&professional_role=112&professional_role=113&professional_role=148&professional_role=114&professional_role=116&professional_role=124&professional_role=125&professional_role=126&ored_clusters=true&order_by=relevance&items_on_page=50&search_period=0&job_search_status=unknown&job_search_status=active_search&job_search_status=looking_for_offers&logic=normal&pos=full_text&exp_period=all_time&filter_exp_period=last_three_years&exp_company_size=any&filter_exp_industry=7&label=exclude_viewed_by_user_id&experience=between1And3&experience=between3And6&experience=moreThan6&hhtmFrom=resume_search_result&hhtmFromLabel=resume_search_line")
        time.sleep(5)
        
        # Wait for page to fully load
        WebDriverWait(driver, 20).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, "[data-qa='serp-item__title']"))
        )
        
        # Find all resume links
        resume_links = driver.find_elements(By.CSS_SELECTOR, "a[data-qa='serp-item__title']")
        print(f'Found {len(resume_links)} candidate resumes')
        
        # Extract hrefs from all links
        resume_urls = []
        for i, link in enumerate(resume_links):
            href = link.get_attribute('href')
            text = link.text[:50] + "..." if len(link.text) > 50 else link.text
            print(f"{i+1}. {text} -> {href}")
            resume_urls.append(href)
        
        return resume_urls
        
    except Exception as e:
        print(f"Error getting resume links: {e}")
        return []

def extract_resume_data(driver, url):
    # Extract data from a single resume
    try:
        print(f"Processing resume: {url}")
        driver.get(url)
        time.sleep(3)
        
        # Wait for resume page to load completely
        WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, "[data-qa]"))
        )
        
        resume_data = {"link": url}  # Add link to data
        
        for data_qa in TARGET_DATA_QA:
            try:
                elements = driver.find_elements(By.CSS_SELECTOR, f"[data-qa='{data_qa}']")
                if elements:
                    all_text = []
                    for element in elements:
                        element_text = element.text.strip()
                        if element_text:
                            all_text.append(element_text)
                    resume_data[data_qa] = "\n".join(all_text)
                else:
                    resume_data[data_qa] = ""
            except Exception as e:
                print(f"Error extracting {data_qa}: {e}")
                resume_data[data_qa] = ""
        
        return resume_data
        
    except Exception as e:
        print(f"Error processing resume {url}: {e}")
        return None

def buy_contacts_and_extract(driver, resume_data):
    # Click buy-contacts button and extract additional contact info
    try:
        # Click the buy-contacts button
        buy_button = WebDriverWait(driver, 10).until(
            EC.element_to_be_clickable((By.CSS_SELECTOR, "[data-qa='buy-contacts']"))
        )
        driver.execute_script("arguments[0].click();", buy_button)
        print("Buy contacts button clicked")
        time.sleep(3)
        
        # Extract all text from resume-serp_resume-item-content, keep only digits
        contact_info = ""
        try:
            # Find the element with contact information
            contact_elements = driver.find_elements(By.CSS_SELECTOR, "[data-qa='resume-serp_resume-item-content']")
            if contact_elements:
                all_digits = []
                for element in contact_elements:
                    element_text = element.text.strip()
                    if element_text:
                        # Extract only digits from the text
                        digits = ''.join(filter(str.isdigit, element_text))
                        if digits:
                            all_digits.append(digits)
                contact_info = ''.join(all_digits)
                print(f"Digits extracted: {contact_info}")
            else:
                print("No resume-serp_resume-item-content element found")
        except Exception as e:
            print(f"Error extracting contact info: {e}")
        
        # Update resume data with digits in code column
        updated_data = resume_data.copy()
        updated_data["CODE"] = contact_info
        
        # Re-extract all data to get updated information after buying contacts
        for data_qa in TARGET_DATA_QA:
            try:
                elements = driver.find_elements(By.CSS_SELECTOR, f"[data-qa='{data_qa}']")
                if elements:
                    all_text = []
                    for element in elements:
                        element_text = element.text.strip()
                        if element_text:
                            all_text.append(element_text)
                    updated_data[data_qa] = "\n".join(all_text)
            except Exception as e:
                print(f"Error re-extracting {data_qa}: {e}")
        
        return updated_data
        
    except Exception as e:
        print(f"Error buying contacts: {e}")
        return resume_data


def save_to_google_sheets(sheet, data, sheet_name, vacation_text, complience):
    # Save data to Google Sheets
    try:
        if sheet_name == GOOGLE_WORKSHEET_TEST:
            # For Test_Vacation sheet: [link, code, ...TARGET_DATA_QA]
            data_row = [data.get("CODE", ""), data.get("link", "")]
            for data_qa in TARGET_DATA_QA:
                data_row.append(data.get(data_qa, ""))
            data_row = data_row + [complience, "", "", "", vacation_text]
        else:
            # For All sheet: [link, ...TARGET_DATA_QA]
            data_row = [data.get("link", "")]
            for data_qa in TARGET_DATA_QA:
                data_row.append(data.get(data_qa, ""))
        
        # Append row to Google Sheets
        sheet.append_row(data_row)
        return True
        
    except Exception as e:
        print(f"Error saving to Google Sheets ({sheet_name}): {e}")
        return False

def main():
    # Main function to run the entire process
    
    # Initialize Google Sheets for both worksheets
    sheet_all = init_google_sheets(GOOGLE_WORKSHEET_ALL)
    sheet_test = init_google_sheets(GOOGLE_WORKSHEET_TEST)
    vacation_text = extract_docx("AI HR\Описание ИТ.docx")
    if not sheet_all or not sheet_test:
        print("Failed to initialize Google Sheets. Exiting.")
        return
    
    driver = setup_driver()
    
    try:
        # Login to site
        if not login_to_site(driver):
            return
        
        if not enter_credentials(driver):
            return
        
        # Get all resume links
        resume_urls = get_all_resume_links(driver)
        if not resume_urls:
            print("No resume links found")
            return
        
        print(f"Found {len(resume_urls)} resumes to process")
        
        # Process each resume
        for i, url in enumerate(resume_urls):
            print(f"Processing resume {i+1}/{len(resume_urls)}")
            
            # Extract basic resume data
            resume_data = extract_resume_data(driver, url)
            if not resume_data:
                print(f"Failed to extract data for resume {i+1}")
                continue
            
            # Save to All sheet
            if save_to_google_sheets(sheet_all, resume_data, GOOGLE_WORKSHEET_ALL, " ", " "):
                print(f"Resume {i+1} saved to All sheet")
            
            # Check score and process contacts if needed
            resume_text = '\n'.join(f"{key}: {value}" for key, value in resume_data.items() if value)
            score = determine_score(resume_text, vacation_text)
            print(f"Resume {i+1} score: {score:.3f}")
            
            if score >= 0.7:
                print(f"Score > 0.7, buying contacts for resume {i+1}")
                
                # Buy contacts and extract updated data
                updated_data = buy_contacts_and_extract(driver, resume_data)
                
                # Save to Test_Vacation sheet
                if save_to_google_sheets(sheet_test, updated_data, GOOGLE_WORKSHEET_TEST, vacation_text, score):
                    print(f"Resume {i+1} with contacts saved to Test_Vacation sheet")
            
            # Add delay between processing resumes
            if i < len(resume_urls) - 1:
                time.sleep(2)
        
        print("All resumes processed. Data saved to Google Sheets")
        print("Waiting 10 seconds for verification...")
        time.sleep(10)
            
    except Exception as e:
        print(f"Error in main process: {e}")
    
    finally:
        driver.quit()
        print("Driver closed")

# Run the main function
if __name__ == "__main__":
    main()