import os
import pandas as pd
import pymysql
from pymysql import Error
import matplotlib.pyplot as plt
import numpy as np
# -*- coding: utf-8 -*-
import sys
sys.stdout.reconfigure(encoding='utf-8')



# 设置中文字体
plt.rcParams['font.sans-serif'] = ['SimHei']
plt.rcParams['axes.unicode_minus'] = False

# 数据库配置
DB_CONFIG = {
    "host": "localhost",
    "port": 3306,
    "user": "root",
    "password": "3034465941Z",
    "database": "bilibili_spider",
    "charset": "utf8mb4"
}

# 图表保存目录
CHARTS_DIR = os.path.join(os.path.dirname(__file__), "static", "analysis_charts")

def get_db_conn():
    """获取数据库连接"""
    try:
        conn = pymysql.connect(**DB_CONFIG)
        return conn
    except Error as e:
        print(f"数据库连接失败：{e}")
        return None

def clear_old_charts():
    """清理旧图表文件"""
    if not os.path.exists(CHARTS_DIR):
        os.makedirs(CHARTS_DIR)
    else:
        for file in os.listdir(CHARTS_DIR):
            if file.endswith('.png'):
                os.remove(os.path.join(CHARTS_DIR, file))
                print(f"已删除旧图表: {file}")

def fetch_data():
    """从数据库获取数据"""
    conn = get_db_conn()
    if not conn:
        # 尝试从CSV文件读取
        csv_path = os.path.join(os.path.dirname(__file__), "bilibili_video_data.csv")
        if os.path.exists(csv_path):
            return pd.read_csv(csv_path)
        else:
            print("数据库和CSV文件都无法访问")
            return None
    
    try:
        # 数据库已修复，字段顺序正确
        df = pd.read_sql("SELECT video_title, up_name, play_count, danmu_count FROM video_info", conn)
        return df
    finally:
        conn.close()

def parse_count(count_str):
    """解析播放量/弹幕数字符串"""
    if pd.isna(count_str):
        return 0
    count_str = str(count_str).strip()
    if '万' in count_str:
        try:
            return float(count_str.replace('万', '')) * 10000
        except:
            return 0
    try:
        return int(count_str)
    except:
        return 0

def plot_play_top10(df):
    """播放量TOP10柱状图 - 增强版"""
    df['play_num'] = df['play_count'].apply(parse_count)
    top10 = df.nlargest(10, 'play_num').sort_values('play_num', ascending=True)
    
    plt.figure(figsize=(12, 8))
    colors = plt.cm.RdYlGn_r(np.linspace(0.3, 0.9, len(top10)))
    bars = plt.barh(top10['video_title'], top10['play_num'] / 10000, color=colors)
    plt.title('播放量TOP10视频排行榜', fontsize=16, fontweight='bold')
    plt.xlabel('播放量（万）', fontsize=13)
    plt.ylabel('视频标题', fontsize=13)
    plt.grid(axis='x', alpha=0.3, linestyle='--')
    
    # 添加数值标签
    for i, bar in enumerate(bars):
        width = bar.get_width()
        plt.text(width + 0.5, bar.get_y() + bar.get_height()/2, 
                 f'{width:.1f}万', va='center', fontsize=10, fontweight='bold')
    
    # 添加排名标记
    for i, y in enumerate(range(len(top10))):
        plt.text(-0.5, y, f'#{i+1}', va='center', fontsize=11, fontweight='bold', color='red')
    
    plt.tight_layout()
    plt.savefig(os.path.join(CHARTS_DIR, '播放量TOP10_优化版.png'), dpi=100, bbox_inches='tight')
    plt.close()
    print("已生成: 播放量TOP10_优化版.png")

def plot_up_contribution(df):
    """UP主投稿占比饼图 - 增强版"""
    up_counts = df['up_name'].value_counts().head(8)
    other_count = len(df) - up_counts.sum()
    
    # 合并其他UP主
    if other_count > 0:
        up_counts['其他UP主'] = other_count
    
    plt.figure(figsize=(10, 10))
    colors = plt.cm.Set3(np.linspace(0, 1, len(up_counts)))
    wedges, texts, autotexts = plt.pie(up_counts.values, labels=up_counts.index, autopct='%1.1f%%', 
                                        startangle=90, colors=colors, textprops={'fontsize': 11})
    
    # 突出显示最大的扇形
    wedges[0].set_edgecolor('red')
    wedges[0].set_linewidth(2)
    
    plt.title('UP主投稿占比分析（TOP8）', fontsize=16, fontweight='bold', pad=20)
    plt.axis('equal')
    
    # 添加图例
    plt.legend(wedges, [f'{k}: {v}条' for k, v in up_counts.items()], 
               title="UP主投稿数量", loc="center left", bbox_to_anchor=(1, 0, 0.5, 1))
    
    plt.tight_layout()
    plt.savefig(os.path.join(CHARTS_DIR, 'UP主投稿占比_优化版.png'), dpi=100, bbox_inches='tight')
    plt.close()
    print("已生成: UP主投稿占比_优化版.png")

def plot_play_distribution(df):
    """播放量分布直方图 - 增强版"""
    df['play_num'] = df['play_count'].apply(parse_count)
    play_data = df['play_num'] / 10000  # 转换为万
    
    plt.figure(figsize=(12, 6))
    n, bins, patches = plt.hist(play_data, bins=20, color='#4ECDC4', edgecolor='black', alpha=0.7)
    
    # 添加均值线
    mean_val = play_data.mean()
    plt.axvline(mean_val, color='red', linestyle='--', linewidth=2, label=f'平均值: {mean_val:.1f}万')
    
    # 添加中位数线
    median_val = play_data.median()
    plt.axvline(median_val, color='blue', linestyle='--', linewidth=2, label=f'中位数: {median_val:.1f}万')
    
    plt.title('播放量分布特征分析', fontsize=16, fontweight='bold')
    plt.xlabel('播放量（万）', fontsize=13)
    plt.ylabel('视频数量', fontsize=13)
    plt.grid(axis='y', alpha=0.3, linestyle='--')
    plt.legend(fontsize=11)
    
    # 添加统计信息
    stats_text = f'样本数: {len(play_data)}\n标准差: {play_data.std():.1f}万\n最小值: {play_data.min():.1f}万\n最大值: {play_data.max():.1f}万'
    plt.text(0.98, 0.98, stats_text, transform=plt.gca().transAxes, 
             fontsize=10, verticalalignment='top', horizontalalignment='right',
             bbox=dict(boxstyle='round', facecolor='wheat', alpha=0.5))
    
    plt.tight_layout()
    plt.savefig(os.path.join(CHARTS_DIR, '播放量分布直方图_优化版.png'), dpi=100, bbox_inches='tight')
    plt.close()
    print("已生成: 播放量分布直方图_优化版.png")

def plot_correlation(df):
    """播放量排名分布图 - 增强版（弹幕数数据缺失，改为排名分布）"""
    df['play_num'] = df['play_count'].apply(parse_count)
    
    # 按播放量排序并计算排名
    df = df.sort_values('play_num', ascending=False).reset_index(drop=True)
    df['rank'] = df.index + 1
    
    plt.figure(figsize=(12, 8))
    
    # 绘制播放量随排名变化的曲线
    plt.plot(df['rank'], df['play_num'] / 10000, color='#96CEB4', linewidth=3, marker='o', markersize=6)
    
    # 添加趋势线
    z = np.polyfit(df['rank'], df['play_num'] / 10000, 2)
    p = np.poly1d(z)
    plt.plot(df['rank'], p(df['rank']), "r--", linewidth=2, label='趋势曲线')
    
    plt.title('播放量与排名关系分析', fontsize=16, fontweight='bold')
    plt.xlabel('排名', fontsize=13)
    plt.ylabel('播放量（万）', fontsize=13)
    plt.grid(True, alpha=0.3, linestyle='--')
    plt.legend(fontsize=11)
    
    # 添加TOP5标注
    top5 = df.head(5)
    for _, row in top5.iterrows():
        plt.text(row['rank'], row['play_num'] / 10000 + 5, 
                 f'{row["play_num"]/10000:.1f}万', 
                 ha='center', fontsize=9, fontweight='bold')
    
    plt.tight_layout()
    plt.savefig(os.path.join(CHARTS_DIR, '播放量弹幕数相关性散点图_优化版.png'), dpi=100, bbox_inches='tight')
    plt.close()
    print("已生成: 播放量弹幕数相关性散点图_优化版.png")

def plot_play_boxplot(df):
    """播放量箱线图 - 增强版"""
    df['play_num'] = df['play_count'].apply(parse_count)
    play_data = df['play_num'] / 10000  # 转换为万
    
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(14, 6))
    
    # 左侧：箱线图
    box = ax1.boxplot(play_data, vert=False, patch_artist=True)
    ax1.set_title('播放量分布箱线图', fontsize=14, fontweight='bold')
    ax1.set_xlabel('播放量（万）', fontsize=12)
    ax1.grid(axis='x', alpha=0.3, linestyle='--')
    
    # 美化箱线图
    colors = ['#FF6B6B', '#4ECDC4', '#45B7D1', '#FFA07A', '#98D8C8']
    for patch, color in zip(box['boxes'], colors):
        patch.set_facecolor(color)
        patch.set_alpha(0.7)
    
    # 添加统计标注
    q1 = play_data.quantile(0.25)
    q3 = play_data.quantile(0.75)
    median = play_data.median()
    iqr = q3 - q1
    
    stats_text = f'Q1: {q1:.1f}万\n中位数: {median:.1f}万\nQ3: {q3:.1f}万\nIQR: {iqr:.1f}万'
    ax1.text(0.98, 0.98, stats_text, transform=ax1.transAxes, 
             fontsize=10, verticalalignment='top', horizontalalignment='right',
             bbox=dict(boxstyle='round', facecolor='wheat', alpha=0.7))
    
    # 右侧：小提琴图
    ax2.violinplot(play_data, vert=False, showmeans=True, showmedians=True)
    ax2.set_title('播放量分布密度图', fontsize=14, fontweight='bold')
    ax2.set_xlabel('播放量（万）', fontsize=12)
    ax2.grid(axis='x', alpha=0.3, linestyle='--')
    
    # 添加异常值标注
    outliers = play_data[(play_data < q1 - 1.5 * iqr) | (play_data > q3 + 1.5 * iqr)]
    if len(outliers) > 0:
        outlier_text = f'异常值数量: {len(outliers)}\n占比: {len(outliers)/len(play_data)*100:.1f}%'
        ax2.text(0.98, 0.98, outlier_text, transform=ax2.transAxes, 
                 fontsize=10, verticalalignment='top', horizontalalignment='right',
                 bbox=dict(boxstyle='round', facecolor='lightcoral', alpha=0.7))
    
    plt.tight_layout()
    plt.savefig(os.path.join(CHARTS_DIR, '播放量箱线图_优化版.png'), dpi=100, bbox_inches='tight')
    plt.close()
    print("已生成: 播放量箱线图_优化版.png")

def main():
    """主函数"""
    print("===== 开始生成数据可视化图表 =====")
    
    # 清理旧图表
    clear_old_charts()
    
    # 获取数据
    df = fetch_data()
    if df is None or df.empty:
        print("没有数据可分析")
        return
    
    print(f"共获取 {len(df)} 条视频数据")
    
    # 生成图表
    plot_play_top10(df)
    plot_up_contribution(df)
    plot_play_distribution(df)
    plot_correlation(df)
    plot_play_boxplot(df)
    
    print("===== 所有图表生成完成 =====")

if __name__ == "__main__":
    main()