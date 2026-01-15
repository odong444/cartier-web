# app.py - Railway용 웹 버전
from flask import Flask, render_template, request, jsonify
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
import threading
import time
import requests
import json
import os

app = Flask(__name__)

# 전역 변수
monitoring_active = False
monitoring_thread = None
url_list = []
url_titles = {}
url_memos = {}
last_stock_status = {}
check_count = 0
logs = []
config_file = "urls.json"

# 텔레그램 설정
TELEGRAM_TOKEN = "7581538889:AAHqA9oitAEARZj9v8HaTvh9xKRRiJNY67U"
TELEGRAM_CHAT_ID = "-1002901540928"

def add_log(msg):
    """로그 추가"""
    timestamp = time.strftime('%H:%M:%S')
    log_entry = f"[{timestamp}] {msg}"
    logs.append(log_entry)
    if len(logs) > 100:
        logs.pop(0)
    print(log_entry)

def get_chrome_driver():
    """ChromeDriver 생성 (Railway 환경)"""
    options = Options()
    options.add_argument("--headless")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")
    options.add_argument("--disable-javascript")
    
    # Railway/Linux 환경에서 Chromium 경로 설정
    chromium_paths = [
        "/usr/bin/chromium-browser",
        "/usr/bin/chromium",
        "/usr/bin/google-chrome",
        "/usr/bin/chrome"
    ]
    
    for path in chromium_paths:
        if os.path.exists(path):
            options.binary_location = path
            break
    
    # 이미지/CSS 차단
    prefs = {
        "profile.managed_default_content_settings.images": 2,
        "profile.default_content_setting_values.images": 2,
    }
    options.add_experimental_option("prefs", prefs)
    
    try:
        # ChromeDriver 경로 찾기
        driver_paths = [
            "/usr/bin/chromedriver",
            "/usr/local/bin/chromedriver",
            "chromedriver"
        ]
        
        driver_path = None
        for path in driver_paths:
            if os.path.exists(path):
                driver_path = path
                break
        
        if driver_path:
            from selenium.webdriver.chrome.service import Service
            service = Service(driver_path)
            return webdriver.Chrome(service=service, options=options)
        else:
            # 경로 없으면 기본값 시도
            return webdriver.Chrome(options=options)
    except Exception as e:
        add_log(f"ChromeDriver 오류: {str(e)[:100]}")
        raise

def check_stock(url):
    """재고 확인"""
    driver = None
    try:
        driver = get_chrome_driver()
        driver.set_page_load_timeout(20)
        driver.get(url)
        time.sleep(2)
        
        buttons = driver.find_elements(By.CSS_SELECTOR, "button.product-add__button, a.product-add__button")
        for btn in buttons:
            classes = btn.get_attribute("class") or ""
            text = btn.text.strip()
            if "hidden" not in classes:
                if "쇼핑백" in text or "추가" in text:
                    return "재고 있음"
                elif "상담원" in text:
                    return "재고 없음"
        return "확인 실패"
    except Exception as e:
        add_log(f"오류: {str(e)[:50]}")
        return "확인 실패"
    finally:
        if driver:
            try:
                driver.quit()
            except:
                pass

def send_telegram(msg):
    """텔레그램 메시지 전송"""
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        response = requests.post(url, data={'chat_id': TELEGRAM_CHAT_ID, 'text': msg, 'parse_mode': 'HTML'}, timeout=5)
        return response.status_code == 200
    except:
        return False

def monitoring_loop():
    """모니터링 루프"""
    global monitoring_active, check_count
    
    while monitoring_active:
        try:
            check_count += 1
            add_log(f"--- {check_count}번째 확인 ---")
            
            for url in url_list:
                if not monitoring_active:
                    return
                
                title = url_titles.get(url, url.split('/')[-1].split('.')[0])
                status = check_stock(url)
                
                if status == "재고 있음":
                    add_log(f"🟢 [{title}] 재고 있음")
                elif status == "재고 없음":
                    add_log(f"🔴 [{title}] 재고 없음")
                
                # 재고 상태 변경 감지
                if url in last_stock_status and status != last_stock_status[url] and status == "재고 있음":
                    add_log(f"🚨 [{title}] 재고 입고!")
                    msg = f"🎉 <b>재고 알림</b> 🎉\n\n📦 재고 입고!\n📝 {title}\n🕐 {time.strftime('%H:%M:%S')}\n🔗 {url}"
                    send_telegram(msg)
                
                last_stock_status[url] = status
            
            # 10초 대기
            for _ in range(10):
                if not monitoring_active:
                    return
                time.sleep(1)
        except Exception as e:
            add_log(f"모니터링 오류: {str(e)[:50]}")
            break

def load_urls():
    """URL 목록 불러오기"""
    global url_list, url_titles, url_memos
    if os.path.exists(config_file):
        try:
            with open(config_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
            url_list = data.get('urls', [])
            url_titles = data.get('titles', {})
            url_memos = data.get('memos', {})
        except:
            pass

def save_urls():
    """URL 목록 저장"""
    try:
        with open(config_file, 'w', encoding='utf-8') as f:
            json.dump({'urls': url_list, 'titles': url_titles, 'memos': url_memos}, f, ensure_ascii=False, indent=2)
    except:
        pass

# 웹 라우트
@app.route('/')
def index():
    """메인 페이지"""
    return render_template('index.html')

@app.route('/api/urls', methods=['GET'])
def get_urls():
    """URL 목록 조회"""
    result = []
    for url in url_list:
        result.append({
            'url': url,
            'title': url_titles.get(url, ''),
            'memo': url_memos.get(url, ''),
            'status': last_stock_status.get(url, '확인 전')
        })
    return jsonify(result)

@app.route('/api/urls', methods=['POST'])
def add_url():
    """URL 추가"""
    data = request.json
    url = data.get('url', '').strip()
    
    if not url or not url.startswith('https://www.cartier.com'):
        return jsonify({'error': '유효하지 않은 URL'}), 400
    
    if url in url_list:
        return jsonify({'error': '이미 추가된 URL'}), 400
    
    url_list.append(url)
    url_titles[url] = data.get('title', url.split('/')[-1].split('.')[0])
    url_memos[url] = data.get('memo', '')
    save_urls()
    
    return jsonify({'success': True})

@app.route('/api/urls/<int:index>', methods=['DELETE'])
def delete_url(index):
    """URL 삭제"""
    if 0 <= index < len(url_list):
        url = url_list.pop(index)
        url_titles.pop(url, None)
        url_memos.pop(url, None)
        save_urls()
        return jsonify({'success': True})
    return jsonify({'error': '잘못된 인덱스'}), 400

@app.route('/api/monitoring', methods=['POST'])
def toggle_monitoring():
    """모니터링 시작/중지"""
    global monitoring_active, monitoring_thread
    
    action = request.json.get('action')
    
    if action == 'start':
        if not url_list:
            return jsonify({'error': 'URL을 먼저 추가하세요'}), 400
        
        monitoring_active = True
        monitoring_thread = threading.Thread(target=monitoring_loop, daemon=True)
        monitoring_thread.start()
        add_log("📡 모니터링 시작")
        return jsonify({'success': True, 'status': 'running'})
    
    elif action == 'stop':
        monitoring_active = False
        add_log("⏹️ 모니터링 중지")
        return jsonify({'success': True, 'status': 'stopped'})
    
    return jsonify({'error': '잘못된 액션'}), 400

@app.route('/api/status', methods=['GET'])
def get_status():
    """상태 조회"""
    return jsonify({
        'monitoring': monitoring_active,
        'check_count': check_count,
        'url_count': len(url_list)
    })

@app.route('/api/logs', methods=['GET'])
def get_logs():
    """로그 조회"""
    return jsonify(logs[-50:])  # 최근 50개만

@app.route('/api/test-telegram', methods=['POST'])
def test_telegram():
    """텔레그램 테스트"""
    if send_telegram("🤖 테스트 메시지"):
        return jsonify({'success': True})
    return jsonify({'error': '전송 실패'}), 500

# 시작 시 URL 불러오기
load_urls()

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
