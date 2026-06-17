# !/usr/bin/env python
# -*- coding: utf-8 -*-
"""
B站全站排行榜数据爬虫程序 - 纯API版本
特点：
1. 完全不依赖浏览器，稳定性更高
2. 直接调用B站官方API获取数据
3. 包含完整的错误处理和重试机制
4. 自动处理API返回的数据结构
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

# API配置
API_RANK_URL = "https://api.bilibili.com/x/web-interface/ranking/v2?rid=0&type=all"

# 请求头配置（模拟真实浏览器）
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Referer": "https://www.bilibili.com/v/popular/rank/all",
    "Origin": "https://www.bilibili.com",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive"
}

DOWNLOAD_VIDEO_NUM = 10
MAX_RETRY = 3  # API请求最大重试次数
REQUEST_DELAY = 1  # 请求间隔（秒）

# ==================== 数据库相关函数 ====================
def init_db():
    """初始化数据库表"""
    try:
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
        print("✓ 数据库初始化完成")
    except Exception as e:
        print(f"✗ 数据库初始化失败: {e}")

def clear_table():
    """清空数据表"""
    try:
        conn = pymysql.connect(**DB_CONFIG)
        cur = conn.cursor()
        cur.execute("TRUNCATE TABLE video_info;")
        conn.commit()
        cur.close()
        conn.close()
        print("✓ 已清空旧数据表")
    except Exception as e:
        print(f"✗ 清空数据表失败: {e}")

def save_to_mysql(data_list):
    """保存数据到MySQL"""
    if not data_list:
        print("✗ 无数据存入数据库")
        return
    try:
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
        print(f"✓ 共{len(data_list)}条数据存入MySQL")
    except Exception as e:
        print(f"✗ 保存数据到MySQL失败: {e}")

# ==================== 工具函数 ====================
def safe_filename(name, max_len=80):
    """安全文件名处理"""
    name = re.sub(r'[\\/:*?"<>|]', "_", name)
    return name[:max_len].strip() or "video"

def download_cover(img_url, save_path, max_retry=3):
    """下载封面图片"""
    for i in range(max_retry):
        try:
            resp = requests.get(img_url, headers=HEADERS, timeout=20)
            if resp.status_code == 200 and len(resp.content) > 1024:
                with open(save_path, "wb") as f:
                    f.write(resp.content)
                return True
        except Exception as e:
            time.sleep(1)
    return False

def clear_old_files():
    """清理旧文件"""
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
                except OSError:
                    pass
        print(f"✓ 已清理{label}目录（删除 {removed} 个文件）")

# ==================== 核心爬取函数 ====================
def fetch_rank_data_from_api():
    """
    从API获取排行榜数据（纯API方式）
    返回：(数据列表, 视频URL列表)
    """
    print("正在从API获取排行榜数据...")
    all_data = []
    video_url_list = []
    
    # 创建会话，保持连接
    session = requests.Session()
    session.headers.update(HEADERS)
    
    for retry in range(MAX_RETRY):
        try:
            resp = session.get(API_RANK_URL, timeout=30)
            
            if resp.status_code != 200:
                print(f"  第{retry+1}次尝试失败，状态码: {resp.status_code}")
                time.sleep(REQUEST_DELAY * (retry + 1))
                continue
            
            try:
                data = resp.json()
            except Exception as e:
                print(f"  第{retry+1}次尝试失败，JSON解析错误: {e}")
                time.sleep(REQUEST_DELAY * (retry + 1))
                continue
            
            if data.get("code") != 0:
                print(f"  第{retry+1}次尝试失败，API错误码: {data.get('code')}")
                time.sleep(REQUEST_DELAY * (retry + 1))
                continue
            
            # 成功获取数据
            list_data = data.get("data", {}).get("list", [])
            print(f"✓ API获取到{len(list_data)}条数据")
            
            # 解析数据
            for idx, video in enumerate(list_data, 1):
                try:
                    # 基础信息
                    title = video.get("title", "无标题")
                    bvid = video.get("bvid", "")
                    video_link = f"https://www.bilibili.com/video/{bvid}" if bvid else ""
                    
                    # UP主信息
                    owner = video.get("owner", {})
                    up_name = owner.get("name", "未知UP主")
                    
                    # 统计数据（直接从API获取，准确可靠）
                    stat = video.get("stat", {})
                    play_count = str(stat.get("view", 0))
                    danmu_count = str(stat.get("danmaku", 0))
                    like_count = str(stat.get("like", 0))
                    coin_count = str(stat.get("coin", 0))
                    favorite_count = str(stat.get("favorite", 0))
                    
                    # 发布时间
                    pubdate = video.get("pubdate", time.time())
                    publish_time = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(pubdate))
                    
                    # 封面图片
                    pic = video.get("pic", "")
                    
                    print(f"  第{idx}条: {title[:25]}... | UP主: {up_name[:10]} | 播放量: {play_count}")
                    
                    # 下载封面
                    img_path = "无封面"
                    if pic and len(pic) > 10:
                        fname = f"{idx}_{safe_filename(title)}.jpg"
                        img_full_path = os.path.join(IMG_DIR, fname)
                        if download_cover(pic, img_full_path):
                            img_path = os.path.join("static", "bilibili_video_covers", fname)
                    
                    # 组装数据
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
                    
                    # 记录前10个视频URL
                    if idx <= DOWNLOAD_VIDEO_NUM and video_link:
                        video_url_list.append((video_link, title))
                    
                    # 请求间隔，避免被封
                    time.sleep(REQUEST_DELAY)
                    
                except Exception as e:
                    print(f"  ✗ 解析第{idx}条数据失败: {e}")
                    continue
            
            print(f"✓ 总共从API获取{len(all_data)}条数据")
            return all_data, video_url_list
            
        except Exception as e:
            print(f"  第{retry+1}次尝试失败: {e}")
            time.sleep(REQUEST_DELAY * (retry + 1))
    
    # 所有重试都失败
    print("✗ API请求失败，已达到最大重试次数")
    return all_data, video_url_list

# ==================== 视频下载函数 ====================
def download_single_video(url, title, idx):
    """使用yt-dlp下载单个视频"""
    safe_title = safe_filename(title)
    save_path = os.path.join(VIDEO_DIR, f"{idx:02d}_{safe_title}.mp4")

    if os.path.exists(save_path):
        print(f"  已存在，跳过：{safe_title[:20]}...")
        return

    print(f"  正在下载：{safe_title[:20]}...")

    # ffmpeg路径（相对路径）
    script_dir = os.path.dirname(os.path.abspath(__file__))
    FFMPEG_PATH = os.path.join(script_dir, "ffmpeg-master-latest-win64-gpl", "bin")

    cmd = [
        "yt-dlp",
        "-f", "bestvideo[ext=mp4][height<=720]+bestaudio[ext=m4a]/best[height<=720]",
        "--merge-output-format", "mp4",
        "--ffmpeg-location", FFMPEG_PATH,
        "-o", save_path,
        "--no-playlist",
        "--quiet",
        "--add-header", "Referer:https://www.bilibili.com/",
        "--add-header", "User-Agent:Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "--add-header", "Origin:https://www.bilibili.com",
        url
    ]

    try:
        import subprocess
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        if os.path.exists(save_path):
            print(f"  ✓ 下载完成")
        else:
            print(f"  ✗ 下载失败: {result.stderr[:200]}")
    except subprocess.TimeoutExpired:
        print(f"  ✗ 下载超时")
    except Exception as e:
        print(f"  ✗ 下载异常: {e}")

# ==================== 主程序入口 ====================
if __name__ == "__main__":
    print("=" * 50)
    print("B站全站排行榜爬虫 - 纯API版本")
    print("=" * 50)
    
    # 步骤1：清理旧文件
    print("\n[步骤1/4] 清理旧文件")
    clear_old_files()
    
    # 步骤2：初始化数据库
    print("\n[步骤2/4] 初始化数据库")
    clear_table()
    init_db()
    
    # 步骤3：爬取数据
    print("\n[步骤3/4] 爬取榜单数据")
    total_data, top10_video_list = fetch_rank_data_from_api()
    
    # 步骤4：保存数据
    print("\n[步骤4/4] 保存数据")
    if total_data:
        # 保存CSV
        csv_path = os.path.join(BASE_DIR, "bilibili_video_data.csv")
        df = pd.DataFrame(total_data)
        df.to_csv(csv_path, index=False, encoding="utf-8-sig")
        print(f"✓ CSV文件已保存：{csv_path}")
        
        # 保存MySQL
        save_to_mysql(total_data)
        
        # 下载视频（可选）
        print("\n[可选] 下载前10个视频")
        for i, (v_url, v_title) in enumerate(top10_video_list, 1):
            download_single_video(v_url, v_title, i)
            time.sleep(3)
    else:
        print("✗ 未爬取到任何数据！")
        print("可能原因：")
        print("  1. B站API暂时不可用")
        print("  2. 网络连接问题")
        print("  3. IP被临时封禁（请稍后重试）")
    
    print("\n" + "=" * 50)
    print("任务完成")
    print("=" * 50)