from flask import Flask, render_template, jsonify, request, send_from_directory
from urllib.parse import unquote, quote
import pandas as pd
import pymysql
from pymysql import Error
import os

app = Flask(__name__)

# ===================== 数据库配置 =====================
DB_CONFIG = {
    "host": "localhost",
    "port": 3306,
    "user": "root",
    "password": "3034465941Z",
    "database": "bilibili_spider",
    "charset": "utf8mb4"
}

PAGE_SIZE = 20  # 原首页分页配置不变

# ===================== 工具函数 =====================
def get_db_conn():
    """获取数据库连接"""
    try:
        conn = pymysql.connect(**DB_CONFIG)
        return conn
    except Error as e:
        print(f"数据库连接失败：{e}")
        return None

# ===================== 原首页路由：功能完全保留，无任何修改 =====================
@app.route("/")
def index():
    # 获取请求参数
    page = request.args.get("page", 1, type=int)
    kw = request.args.get("kw", "", type=str).strip()
    sort = request.args.get("sort", "default", type=str)
    offset = (page - 1) * PAGE_SIZE

    conn = get_db_conn()
    if not conn:
        return "<h1>数据库连接异常，请检查配置</h1>"

    try:
        # 数据库已修复，字段顺序正确
        base_sql = """
            SELECT cover_path, video_title, up_name, play_count, danmu_count,
                   like_count, coin_count, favorite_count, publish_time, crawl_time
            FROM video_info
        """
        where_sql = ""
        params = []

        # 搜索条件 - 使用 pymysql 的字符串拼接方式（转义特殊字符），避开 % 格式化
        if kw:
            # 防止 SQL 注入，转义 LIKE 通配符
            safe_kw = kw.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            where_sql = " WHERE video_title LIKE %s OR up_name LIKE %s "
            search_pattern = f"%{safe_kw}%"
            params = [search_pattern, search_pattern]

        # 排序逻辑 - 修复播放量排序问题
        order_sql = " ORDER BY id DESC "
        if sort == "play_desc":
            # 正确处理带"万"单位的播放量排序
            # 包含"万"的转换为数值后乘以10000，不包含"万"的直接转换
            # 使用 LOCATE 函数代替 LIKE，避免 % 格式化冲突
            order_sql = """
                ORDER BY 
                    CASE 
                        WHEN LOCATE('万', play_count) > 0 THEN CAST(REPLACE(play_count, '万', '') AS DECIMAL(10,2)) * 10000 
                        ELSE CAST(play_count AS UNSIGNED) 
                    END DESC 
            """
        elif sort == "danmu_desc":
            # 弹幕数也做同样处理
            order_sql = """
                ORDER BY 
                    CASE 
                        WHEN LOCATE('万', danmu_count) > 0 THEN CAST(REPLACE(danmu_count, '万', '') AS DECIMAL(10,2)) * 10000 
                        ELSE CAST(danmu_count AS UNSIGNED) 
                    END DESC 
            """

        # 查询当前页数据 - 使用 pymysql 游标执行，避开 pandas 格式化问题
        page_sql = f"{base_sql} {where_sql} {order_sql} LIMIT {PAGE_SIZE} OFFSET {offset}"
        cursor = conn.cursor()
        if params:
            cursor.execute(page_sql, params)
        else:
            cursor.execute(page_sql)
        columns = [desc[0] for desc in cursor.description]
        rows = cursor.fetchall()
        df = pd.DataFrame(rows, columns=columns)

        # 查询总条数，计算总页数
        count_sql = f"SELECT COUNT(*) AS total FROM video_info {where_sql}"
        if params:
            cursor.execute(count_sql, params)
        else:
            cursor.execute(count_sql)
        total_count = cursor.fetchone()[0]
        total_page = (total_count + PAGE_SIZE - 1) // PAGE_SIZE

        conn.close()

        return render_template("index.html",
                               data=df.to_dict(orient="records"),
                               page=page,
                               total_page=total_page,
                               kw=kw,
                               sort=sort)
    except Exception as e:
        conn.close()
        return f"<h1>数据查询异常：{str(e)}</h1>"

# ===================== 【新增】Top10专属路由：专门展示你爬取的10个视频 =====================
@app.route("/top10")
def top10():
    conn = get_db_conn()
    if not conn:
        return "<h1>数据库连接异常，请检查配置</h1>"

    try:
        # 严格按列顺序查询，只取前10条视频，按榜单顺序排序
        base_sql = """
            SELECT cover_path, video_title, up_name, play_count, danmu_count,
                   like_count, coin_count, favorite_count, publish_time, crawl_time
            FROM video_info
            ORDER BY id ASC
            LIMIT 10
        """
        df = pd.read_sql(base_sql, conn)
        conn.close()

        # 渲染专属Top10页面
        return render_template("top10.html",
                               data=df.to_dict(orient="records"))
    except Exception as e:
        conn.close()
        return f"<h1>Top10数据加载异常：{str(e)}</h1>"

# ===================== 【新增】视频列表路由：展示bilibili_videos_mp4文件夹中的MP4视频 =====================
@app.route("/videos")
def videos():
    videos_dir = os.path.join(os.path.dirname(__file__), "bilibili_videos_mp4")
    video_files = []
    
    if os.path.exists(videos_dir):
        for filename in os.listdir(videos_dir):
            if filename.endswith(".mp4"):
                # 对文件名进行URL编码，处理中文文件名
                encoded_filename = quote(filename, encoding='utf-8')
                video_files.append({
                    "name": filename.replace(".mp4", "").replace("_", " "),
                    "filename": filename,
                    "path": f"/bilibili_videos_mp4/{encoded_filename}"
                })
        # 按文件名排序
        video_files.sort(key=lambda x: x["filename"])
    
    return render_template("videos.html", videos=video_files)

# ===================== MP4视频文件服务路由（支持流式播放） =====================
@app.route("/bilibili_videos_mp4/<path:filename>")
def video_stream_mp4(filename):
    videos_dir = os.path.join(os.path.dirname(__file__), "bilibili_videos_mp4")
    
    # 解码URL编码的文件名（处理中文文件名）
    try:
        filename = unquote(filename, encoding='utf-8')
    except:
        pass
    
    # 设置正确的响应头以支持流式播放
    response = send_from_directory(videos_dir, filename)
    response.headers.add('Accept-Ranges', 'bytes')
    response.headers.add('Content-Type', 'video/mp4')
    
    return response

# ===================== JSON 数据接口：功能完全保留，无任何修改 =====================
@app.route("/api/data")
def get_data():
    conn = get_db_conn()
    if not conn:
        return jsonify({"code": 500, "msg": "数据库连接失败", "data": []})
    try:
        df = pd.read_sql("SELECT * FROM video_info", conn)
        conn.close()
        return jsonify({
            "code": 200,
            "msg": "请求成功",
            "total": len(df),
            "data": df.to_dict(orient="records")
        })
    except Exception as e:
        conn.close()
        return jsonify({"code": 500, "msg": str(e), "data": []})

# ===================== 运行入口 =====================
if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=True)