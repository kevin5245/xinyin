import asyncio
from datetime import datetime
import pytz
import requests
import os
from playwright.async_api import async_playwright
from fastapi import FastAPI, BackgroundTasks, HTTPException, Query
from fastapi.responses import FileResponse, JSONResponse

app = FastAPI()

BASE_URL = "https://ssports.iqiyi.com/json/pc/matchData/match_716402760.json"
GROUP_NAME = "新英直播"
TXT_FILE = "output.txt"
M3U_FILE = "output.m3u"
# 与你 CF Worker 脚本中配置的 token 保持一致
SECRET_TOKEN = "03040404aA@"

def get_today_match_url():
    tz = pytz.timezone('Asia/Shanghai')
    today_str = datetime.now(tz).strftime('%Y-%m-%d')
    try:
        resp = requests.get(BASE_URL).json()
        matches = resp.get('retData', {}).get('match', [])
        for m in matches:
            if m.get('day') == today_str:
                return m.get('matchListUrl')
    except Exception as e:
        print(f"[!] 获取基础赛事列表失败: {e}")
    return None

def get_live_matches(list_url):
    if not list_url: return []
    live_matches = []
    try:
        resp = requests.get(list_url).json()
        matches = resp.get('retData', {}).get('match', [])
        for m in matches:
            base_info = m.get('matchBaseInfo', {})
            if base_info.get('timeDesc') == '直播中':
                title = base_info.get('title', '未知比赛')
                match_id = base_info.get('matchId')
                if match_id:
                    live_matches.append({'id': match_id, 'title': title})
    except Exception as e:
        print(f"[!] 获取当天直播列表失败: {e}")
    return live_matches

async def extract_m3u8(match_id):
    target_url = f"https://shinaisports.com/live.html?matchId={match_id}"
    m3u8_url = None
    print(f"[*] 启动浏览器访问: {target_url}")
    
    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True, 
            args=['--no-sandbox', '--disable-setuid-sandbox', '--disable-dev-shm-usage']
        )
        context = await browser.new_context()
        page = await context.new_page()

        def check_request(request):
            nonlocal m3u8_url
            if ".m3u8" in request.url and not m3u8_url:
                m3u8_url = request.url
                print(f"[+] 拦截到 m3u8: {m3u8_url}")

        page.on("request", check_request)

        try:
            await page.goto(target_url, timeout=45000, wait_until="networkidle")
            # 强行停留 15 秒，确保异步加载的 m3u8 能被监听到
            await page.wait_for_timeout(15000)
        except Exception as e:
            print(f"[!] 页面加载出错: {e}")
        finally:
            await context.close()
            await browser.close()
            
    return m3u8_url

async def run_scraper_task():
    """后台运行的实际抓取逻辑"""
    print(f"[{datetime.now().strftime('%H:%M:%S')}] 后台抓取任务开始执行...")
    list_url = get_today_match_url()
    live_matches = get_live_matches(list_url)
    
    # 【新增逻辑】：如果没有直播中的比赛，清空旧数据并返回空订阅
    if not live_matches:
        print("[-] 当前无直播中比赛，正在清空旧数据并返回空订阅...")
        
        # 写入 txt (仅保留分类名)
        with open(TXT_FILE, 'w', encoding='utf-8') as f:
            f.write(f"{GROUP_NAME},#genre#\n")
            
        # 写入 m3u (仅保留协议头)
        with open(M3U_FILE, 'w', encoding='utf-8') as f:
            f.write('#EXTM3U\n')
            
        return

    # === 正常抓取逻辑 ===
    results = []
    for match in live_matches:
        m3u8 = await extract_m3u8(match['id'])
        if m3u8:
            results.append({'title': match['title'], 'url': m3u8})

    if results:
        with open(TXT_FILE, 'w', encoding='utf-8') as f:
            f.write(f"{GROUP_NAME},#genre#\n")
            for r in results:
                f.write(f"{r['title']},{r['url']}\n")
                
        with open(M3U_FILE, 'w', encoding='utf-8') as f:
            f.write('#EXTM3U\n')
            for r in results:
                f.write(f'#EXTINF:-1 group-title="{GROUP_NAME}",{r["title"]}\n')
                f.write(f"{r['url']}\n")
        print("[+] 文件更新完毕")

# ================= FastAPI 接口路由 =================

@app.get("/")
def read_root():
    return {"status": "ok", "msg": "API is running."}

@app.get("/trigger")
async def trigger_scrape(background_tasks: BackgroundTasks, token: str = Query("")):
    """CF Worker 请求的触发接口"""
    if token != SECRET_TOKEN:
        raise HTTPException(status_code=403, detail="Invalid or missing token")
    
    # 将耗时的抓取任务放入后台，立即给 CF Worker 返回 HTTP 200 以防超时
    background_tasks.add_task(run_scraper_task)
    return JSONResponse(content={"status": "accepted", "message": "鉴权成功，抓取任务已在后台启动"})

@app.get("/live.txt")
def get_txt():
    """获取 txt 格式直播源"""
    if os.path.exists(TXT_FILE):
        return FileResponse(TXT_FILE, media_type='text/plain')
    return JSONResponse(status_code=404, content={"message": "源文件未生成"})

@app.get("/live.m3u")
def get_m3u():
    """获取 m3u 格式直播源"""
    if os.path.exists(M3U_FILE):
        return FileResponse(M3U_FILE, media_type='application/vnd.apple.mpegurl')
    return JSONResponse(status_code=404, content={"message": "源文件未生成"})
