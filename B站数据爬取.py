# !/usr/bin/env python
# -*- coding: utf-8 -*-
"""
B站全站排行榜数据爬虫程序
修复版本：添加详细错误日志和健壮的反反爬机制
"""

import sys
import io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

import re
import time
import os
import pandas as pd
import pymysql
import requests
from selenium import webdriver
from selenium.webdriver.edge.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

# 全局路径配置
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
IMG_DIR = os.path.join(BASE_DIR, "static", "bilibili_video_covers")
VIDEO_DIR = os.path.join(BASE_DIR, "bilibili_videos_mp4")
os.makedirs(IMG_DIR, exist_ok=True)
os.makedirs(VIDEO_DIR, exist_ok=True)

# MySQL数据库配置
DB_CONFIG = {
    "host": "localhost",
    "port": 3306,
    "user": "root",
    "password": "3034465941Z",
    "database": "bilibili_spider",
    "charset": "utf8mb4"
}

# 网站与请求头配置
URL_RANK = "https://www.bilibili.com/v/popular/rank/all"
API_RANK_URL = "https://api.bilibili.com/x/web-interface/ranking/v2?rid=0&type=all"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Referer": "https://www.bilibili.com/",
    "Origin": "https://www.bilibili.com",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive"
}

DOWNLOAD_VIDEO_NUM = 10

# 数据库相关函数
def init_db():
    conn = pymysql.connect(**DB_CONFIG)
    cur = conn.cursor()
    sql = """
    CREATE TABLE IF NOT EXISTS video_info (
        id INT AUTO_INCREMENT PRIMARY KEY,
        video_title VARCHAR(255) NOT NULL COMMENT '视频标题',
        up_name VARCHAR(100) NOT NULL COMMENT 'UP主昵称',
        play_count VARCHAR(50) COMMENT '播放量',
        danmu_count VARCHAR(50) COMMENT '弹幕数',
        like_count VARCHAR(50) COMMENT '点赞数',
        coin_count VARCHAR(50) COMMENT '投币数',
        favorite_count VARCHAR(50) COMMENT '收藏数',
        publish_time VARCHAR(50) COMMENT '发布时间',
        cover_path VARCHAR(255) COMMENT '封面图片本地路径',
        crawl_time DATETIME DEFAULT CURRENT_TIMESTAMP COMMENT '爬取时间'
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
    """
    cur.execute(sql)
    conn.commit()
    cur.close()
    conn.close()
    print("数据库初始化完成")

def clear_table():
    conn = pymysql.connect(**DB_CONFIG)
    cur = conn.cursor()
    cur.execute("TRUNCATE TABLE video_info;")
    conn.commit()
    cur.close()
    conn.close()
    print("已清空旧数据表")

def save_to_mysql(data_list):
    if not data_list:
        print("无数据存入数据库")
        return
    conn = pymysql.connect(**DB_CONFIG)
    cur = conn.cursor()
    insert_sql = """
    INSERT INTO video_info
    (video_title, up_name, play_count, danmu_count, like_count, coin_count, favorite_count, publish_time, cover_path)
    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
    """
    for d in data_list:
        cur.execute(insert_sql, (
            d["video_title"], d["up_name"], d["play_count"], d["danmu_count"],
            d["like_count"], d["coin_count"], d["favorite_count"], d["publish_time"], d["cover_path"]
        ))
    conn.commit()
    cur.close()
    conn.close()
    print(f"共{len(data_list)}条数据存入MySQL")

# 工具函数
def safe_filename(name, max_len=80):
    name = re.sub(r'[\\/:*?"<>|]', "_", name)
    return name[:max_len].strip() or "video"

def download_cover(img_url, save_path, max_retry=5):
    for i in range(max_retry):
        try:
            resp = requests.get(img_url, headers=HEADERS, timeout=20)
            if resp.status_code == 200 and len(resp.content) > 1024:
                with open(save_path, "wb") as f:
                    f.write(resp.content)
                return True
            else:
                print(f"封面下载失败，状态码: {resp.status_code}")
        except Exception as e:
            print(f"封面下载异常({i+1}/{max_retry}): {e}")
            time.sleep(1)
    return False

def clear_old_files():
    for directory, label in ((IMG_DIR, "封面"), (VIDEO_DIR, "视频")):
        if not os.path.exists(directory):
            os.makedirs(directory, exist_ok=True)
            continue
        removed = 0
        for filename in os.listdir(directory):
            filepath = os.path.join(directory, filename)
            if os.path.isfile(filepath):
                try:
                    os.remove(filepath)
                    removed += 1
                except OSError as e:
                    print(f"删除{label}文件失败 {filename}：{e}")
        print(f"已清理{label}目录：{directory}（删除 {removed} 个文件）")

def fetch_rank_stats_from_api():
    """从API获取统计数据，添加详细错误日志"""
    print("正在从API获取统计数据...")
    try:
        session = requests.Session()
        session.headers.update(HEADERS)
        resp = session.get(API_RANK_URL, timeout=30)
        
        print(f"API响应状态码: {resp.status_code}")
        if resp.status_code != 200:
            print(f"API请求失败，状态码: {resp.status_code}")
            print(f"响应内容: {resp.text[:500]}")
            return []
        
        try:
            data = resp.json()
        except Exception as e:
            print(f"JSON解析失败: {e}")
            print(f"响应内容: {resp.text[:500]}")
            return []
        
        if data.get("code") != 0:
            print(f"API返回错误码: {data.get('code')}")
            print(f"错误信息: {data.get('message', '未知错误')}")
            return []
        
        stats_list = []
        for video in data.get("data", {}).get("list", []):
            stat = video.get("stat", {})
            pubdate = video.get("pubdate", time.time())
            stats_list.append({
                "play_count": str(stat.get("view", 0)),
                "danmu_count": str(stat.get("danmaku", 0)),
                "like_count": str(stat.get("like", 0)),
                "coin_count": str(stat.get("coin", 0)),
                "favorite_count": str(stat.get("favorite", 0)),
                "publish_time": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(pubdate)),
            })
        print(f"API获取到{len(stats_list)}条统计数据")
        return stats_list
    except Exception as e:
        print(f"API请求异常: {e}")
        return []

# 爬取榜单数据
def crawl_rank_data():
    """爬取全站榜单数据，添加详细调试日志"""
    print("初始化浏览器...")
    options = Options()
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_argument("--start-maximized")
    options.add_argument("--disable-notifications")
    options.add_argument("--disable-images")  # 禁用图片加载加快速度
    options.add_argument("--disdble-ja_asgumen")  # 禁用JSt只获取静l内容avascript")  # 禁用JS，只获取静态内容
    options.add_experimental_option("excludeSwitches", ["enable-automation"])
    options.add_experimental_option("useAutomationExtension", False)

    driver = webdriver.Edge(options=options)
    driver.execute_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
    
    all_data = []
    video_url_list = []
    api_stats_list = fetch_rank_stats_from_api()

    try:
        print(f"正在访问: {URL_RANK}")
        driver.get(URL_RANK)
        
        wait = WebDriverWait(driver, 30)
        
        try:
            print("等待页面加载...")
            wait.until(EC.presence_of_element_located((By.CLASS_NAME, "rank-list")))
            print("页面加载成功")
        except Exception as e:
            print(f"等待rank-list失败: {e}")
            # 尝试获取页面源代码查看实际结构
            print("页面源码预览(前2000字符):")
            print(driver.page_source[:2000])
            driver.quit()
            return all_data, video_url_list
        
        time.sleep(3)

        # 关闭登录弹窗
        try:
            close_btn = driver.find_element(By.XPATH, "//div[@class='close'] | //span[@class='close']")
            close_btn.click()
            time.sleep(1)
        except:
            pass

        # 分屏滚动
        try:
            scroll_height = driver.execute_script("return document.body.scrollHeight")
            print(f"页面高度: {scroll_height}")
            for i in range(0, scroll_height, 500):
                driver.execute_script(f"window.scrollTo(0, {i});")
                time.sleep(0.5)
            driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
            time.sleep(2)
        except Exception as e:
            print(f"滚动页面失败: {e}")

        # 获取所有榜单项
        items = driver.find_elements(By.CLASS_NAME, "rank-item")
        print(f"找到{len(items)}个榜单项")
        
        if len(items) == 0:
            print("未找到任何榜单项，可能页面结构已变化")
            print("尝试查找其他可能的元素...")
            # 尝试其他选择器
            try:
                # 尝试用其他方式查找
                elements = driver.find_elements(By.XPATH, "//div[contains(@class, 'rank')]")
                print(f"找到{len(elements)}个包含rank的元素")
                for elem in elements[:3]:
                    print(f"元素class: {elem.get_attribute('class')}")
            except Exception as e:
                print(f"查找替代元素失败: {e}")
        
        for idx, item in enumerate(items, 1):
            try:
                title = "无标题"
                video_link = ""
                up_name = "未知UP主"
                play_count = "0"
                danmu_count = "0"
                like_count = "0"
                coin_count = "0"
                favorite_count = "0"
                publish_time = time.strftime("%Y-%m-%d %H:%M:%S")

                # 获取标题
                try:
                    title_elem = item.find_element(By.CLASS_NAME, "title")
                    title = title_elem.text.strip()
                    video_link = title_elem.get_attribute("href")
                    print(f"第{idx}条: 标题={title[:30]}...")
                except Exception as e:
                    print(f"第{idx}条获取标题失败: {e}")
                    # 尝试其他选择器
                    try:
                        title_elem = item.find_element(By.TAG_NAME, "a")
                        title = title_elem.text.strip()
                        video_link = title_elem.get_attribute("href")
                        print(f"备用选择器获取标题: {title[:30]}...")
                    except:
                        pass

                # 获取UP主
                try:
                    up_elem = item.find_element(By.CLASS_NAME, "up-name")
                    up_name = up_elem.text.strip()
                    if up_name and (up_name.isdigit() or '万' in up_name):
                        up_name = "未知UP主"
                except Exception as e:
                    print(f"第{idx}条获取UP主失败: {e}")

                # 从API获取统计数据
                if idx <= len(api_stats_list):
                    stats = api_stats_list[idx - 1]
                    play_count = stats["play_count"]
                    danmu_count = stats["danmu_count"]
                    like_count = stats["like_count"]
                    coin_count = stats["coin_count"]
                    favorite_count = stats["favorite_count"]
                    publish_time = stats["publish_time"]
                else:
                    print(f"第{idx}条无API数据")

                # 下载封面
                img_path = "无封面"
                try:
                    img_elem = item.find_element(By.TAG_NAME, "img")
                    img_src = img_elem.get_attribute("src") or img_elem.get_attribute("data-src")
                    if img_src and len(img_src) > 10:
                        if not img_src.startswith("http"):
                            img_src = "https:" + img_src
                        fname = f"{idx}_{safe_filename(title)}.jpg"
                        img_full_path = os.path.join(IMG_DIR, fname)
                        if download_cover(img_src, img_full_path):
                            img_path = os.path.join("static", "bilibili_video_covers", fname)
                except Exception as e:
                    print(f"第{idx}条封面异常：{e}")

                row = {
                    "video_title": title,
                    "up_name": up_name,
                    "play_count": play_count,
                    "danmu_count": danmu_count,
                    "like_count": like_count,
                    "coin_count": coin_count,
                    "favorite_count": favorite_count,
                    "publish_time": publish_time,
                    "cover_path": img_path
                }
                all_data.append(row)

                if idx <= DOWNLOAD_VIDEO_NUM:
                    video_url_list.append((video_link, title))

                print(f"第{idx}条爬取成功: {title[:20]}... 播放量:{play_count}")
                time.sleep(0.3)
            except Exception as e:
                print(f"第{idx}条数据爬取失败：{e}")
                continue
    except Exception as e:
        print(f"页面加载异常：{e}")
        import traceback
        traceback.print_exc()
    finally:
        driver.quit()

    print(f"总共爬取{len(all_data)}条数据")
    return all_data, video_url_list

# 下载视频
def download_single_video(url, title, idx):
    safe_title = safe_filename(title)
    save_path = os.path.join(VIDEO_DIR, f"{idx:02d}_{safe_title}.mp4")

    if os.path.exists(save_path):
        print(f"已存在，跳过：{save_path}")
        return

    print(f"正在下载：{safe_title}")

    script_dir = os.path.dirname(os.path.abspath(__file__))
    FFMPEG_PATH = os.path.join(script_dir, "ffmpeg-master-latest-win64-gpl", "bin")

    cmd = [
        "yt-dlp",
        "-f", "bestvideo[ext=mp4][height<=720]+bestaudio[ext=m4a]/bestvideo[height<=720]+bestaudio/best[height<=720]",
        "--merge-output-format", "mp4",
        "--remux-video", "mp4",
        "--ffmpeg-location", FFMPEG_PATH,
        "-o", save_path,
        "--no-playlist",
        "--quiet", "--no-warnings",
        "--add-header", "Referer:https://www.bilibili.com/",
        "--add-header", "User-Agent:Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "--add-header", "Origin:https://www.bilibili.com",
        url
    ]

    try:
        import subprocess
        result = subprocess.run(cmd, check=True, capture_output=True, text=True)
        if os.path.exists(save_path):
            print(f"下载完成 → {save_path}")
        else:
            print(f"下载可能未完成，输出：{result.stderr}")
    except subprocess.CalledProcessError as e:
        print(f"下载失败：{e.stderr or e}")
    except Exception as e:
        print(f"下载异常：{e}")

# 主程序入口
if __name__ == "__main__":
    print("===== 步骤0：清理旧文件 =====")
    clear_old_files()

    print("\n===== 步骤1：初始化数据库 =====")
    clear_table()
    init_db()

    print("\n===== 步骤2：爬取榜单数据、封面图 =====")
    total_data, top10_video_list = crawl_rank_data()

    print("\n===== 步骤3：数据导出CSV =====")
    if total_data:
        csv_path = os.path.join(BASE_DIR, "bilibili_video_data.csv")
        df = pd.DataFrame(total_data)
        df.to_csv(csv_path, index=False, encoding="utf-8-sig")
        print(f"CSV文件已保存：{csv_path}")
        save_to_mysql(total_data)
    else:
        print("警告：未爬取到任何数据！")
        print("可能的原因：")
        print("1. B站页面结构已变化")
        print("2. API被反爬拦截")
        print("3. 网络连接问题")

    print("\n===== 步骤4：开始下载前10个视频 =====")
    for i, (v_url, v_title) in enumerate(top10_video_list, 1):
        download_single_video(v_url, v_title, i)
        time.sleep(3)

    print("\n===== 所有任务执行完毕 =====")