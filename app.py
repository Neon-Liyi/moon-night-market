"""月亮夜市 Moon Night Market — 地摊美食地图原型 (FastAPI + SQLite)

消费者端：地图看摊位 / AI 营养卡 / 下单取餐码
商家端：出摊开关 / 接单 / 发布菜品
AI 能力：小吃原料·工艺·热量·过敏原 + 拍图识别(演示版) + 营养师问答
"""
import os
import io
import json
import math
import random
import sqlite3
import urllib.request
from datetime import datetime

from fastapi import FastAPI, Body, File, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, FileResponse
from fastapi.staticfiles import StaticFiles

HERE = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(HERE, "moon.db")
STATIC = os.path.join(HERE, "static")

app = FastAPI(title="月亮夜市 Moon Night Market", version="0.1.0")


# ---------------------------------------------------------------- data layer
def db():
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    return conn


SCHEMA = """
CREATE TABLE IF NOT EXISTS stalls(
  id INTEGER PRIMARY KEY, code TEXT, name TEXT, owner TEXT, emoji TEXT,
  x REAL, y REAL, status TEXT, signature TEXT, tags TEXT,
  rating REAL, clean REAL, queue INTEGER, story TEXT, health_cert INTEGER,
  opens_at TEXT, closes_at TEXT, intro TEXT, intro_who TEXT, short TEXT, loc TEXT
);
CREATE TABLE IF NOT EXISTS items(
  id INTEGER PRIMARY KEY, stall_id INTEGER, name TEXT, price REAL, unit TEXT,
  cal REAL, ingredients TEXT, method TEXT, allergens TEXT, tip TEXT
);
CREATE TABLE IF NOT EXISTS orders(
  id INTEGER PRIMARY KEY, stall_id INTEGER, code TEXT, lines TEXT,
  total REAL, status TEXT, created_at TEXT
);
CREATE TABLE IF NOT EXISTS reviews(
  id INTEGER PRIMARY KEY, stall_id INTEGER, order_code TEXT, stars INTEGER,
  text TEXT, who TEXT, created_at TEXT, day TEXT, reply TEXT, reply_at TEXT
);
CREATE TABLE IF NOT EXISTS events(
  id INTEGER PRIMARY KEY, ts TEXT, kind TEXT, payload TEXT
);
"""

STALLS = [
    dict(code="A1", name="王阿姨葱油饼", owner="王阿姨", emoji="🥞", x=9, y=41,
         status="open", signature="18年老摊 · 猪油起酥", tags="早餐,上海本帮,面食",
         rating=4.8, clean=4.9, queue=3, health_cert=1,
         story="王阿姨在江湾卖了18年葱油饼，一口平底锅、一把小葱。老客说：她的饼有小时候的味道。",
         items=[
             dict(name="葱油饼", price=5, unit="个", cal=320,
                  ingredients="中筋面粉、小葱、猪油、盐",
                  method="面团三次擀卷起酥，猪油分层，铁板两面煎至金黄",
                  allergens="麸质", tip="猪油版更香；怕腻可要素油版"),
             dict(name="加蛋葱油饼", price=7, unit="个", cal=410,
                  ingredients="中筋面粉、小葱、猪油、鸡蛋",
                  method="起酥后打入鸡蛋，蛋液裹边再煎",
                  allergens="麸质、蛋", tip="加蛋后更顶饱，等的久一点值得"),
             dict(name="现磨豆浆", price=3, unit="杯", cal=110,
                  ingredients="黄豆、水、糖",
                  method="前一晚泡豆，凌晨现磨、煮沸两次",
                  allergens="大豆", tip="可以要求无糖"),
         ]),
    dict(code="A2", name="老李炭火烤串", owner="李叔", emoji="🍢", x=20, y=41,
         status="open", signature="当天现穿 · 炭火慢烤", tags="夜宵,烧烤,重口",
         rating=4.6, clean=4.5, queue=6, health_cert=1,
         story="李叔的炭炉每晚6点准时点着，羊肉串只用当天现穿的内蒙羊腿肉，绝不过夜。",
         items=[
             dict(name="羊肉串", price=4, unit="串", cal=90,
                  ingredients="羊腿肉、孜然、辣椒面、盐",
                  method="现穿现烤，炭火5分钟，翻面两次撒料",
                  allergens="无", tip="让李叔撒两次孜然才够味"),
             dict(name="烤面筋", price=3, unit="串", cal=150,
                  ingredients="面筋、秘制酱、辣椒粉",
                  method="先煮软再刷酱烤制，外焦里韧",
                  allergens="麸质", tip="甜辣酱是李叔自调的"),
             dict(name="烤鸡翅", price=6, unit="个", cal=180,
                  ingredients="鸡中翅、腌料、蜂蜜",
                  method="提前腌4小时，烤制刷蜂蜜上色",
                  allergens="蜂蜜", tip="皮要烤到微焦才好吃"),
         ]),
    dict(code="A3", name="阿婆酒酿小圆子", owner="陈阿婆", emoji="🍡", x=31, y=41,
         status="closed", signature="自家酿米酒", tags="甜汤,暖胃,老味道",
         rating=4.9, clean=5.0, queue=0, health_cert=1,
         story="阿婆七十岁，这一锅酒酿是自家酿的米酒，甜而不腻，冬天最受欢迎。",
         items=[
             dict(name="酒酿小圆子", price=8, unit="碗", cal=260,
                  ingredients="糯米粉、自酿米酒、桂花、白糖",
                  method="小圆子现搓现煮，酒酿后下锅保持米香",
                  allergens="无", tip="冬天喝最暖，可以要求多加酒酿"),
             dict(name="桂花糖芋艿", price=8, unit="碗", cal=240,
                  ingredients="芋艿、红糖、干桂花",
                  method="芋艿蒸透后红糖水慢煨40分钟",
                  allergens="无", tip="甜度可以调，阿婆会问你"),
         ]),
    dict(code="A4", name="小杨生煎", owner="小杨", emoji="🥟", x=42, y=41,
         status="open", signature="底脆汤多 · 现包现煎", tags="上海名点,面食",
         rating=4.7, clean=4.7, queue=9, health_cert=1,
         story="小杨的褶子每天现包800个，底脆汤多，是这条街上排队最长的摊。",
         items=[
             dict(name="生煎包", price=8, unit="4只", cal=400,
                  ingredients="面粉、猪前腿肉、皮冻、芝麻、葱",
                  method="半发面，煎制后加水焖到底脆，出锅撒葱花芝麻",
                  allergens="麸质", tip="先咬小口吸汤，小心烫嘴"),
             dict(name="虾仁生煎", price=12, unit="4只", cal=380,
                  ingredients="面粉、鲜虾仁、猪油、韭黄",
                  method="虾仁现剥现包，旺火快煎",
                  allergens="麸质、甲壳类", tip="虾仁版每天限量60只"),
         ]),
    dict(code="A5", name="张记臭豆腐", owner="张姐", emoji="🧆", x=53, y=41,
         status="open", signature="苋菜梗卤 · 自己点豆腐", tags="夜宵,重口,发酵",
         rating=4.5, clean=4.3, queue=4, health_cert=1,
         story="张姐的豆腐是自己点的老豆腐，在发酵缸里泡足三天，臭得地道。",
         items=[
             dict(name="臭豆腐", price=10, unit="份", cal=280,
                  ingredients="老豆腐、苋菜梗卤水、蒜、辣椒酱、泡菜",
                  method="卤水发酵3天，两次油炸至外酥里嫩，浇蒜蓉辣椒酱",
                  allergens="大豆", tip="趁热吃，配泡菜解腻"),
             dict(name="油墩子", price=5, unit="个", cal=220,
                  ingredients="白萝卜丝、面粉、胡萝卜、葱花",
                  method="萝卜丝裹面糊下油锅定型，炸至金黄",
                  allergens="麸质", tip="萝卜丝脆甜的是当天现刨的"),
         ]),
    dict(code="A6", name="陈叔炸串", owner="陈叔", emoji="🍤", x=64, y=41,
         status="open", signature="现裹现炸 · 秘制椒盐", tags="夜宵,炸物,小吃",
         rating=4.4, clean=4.2, queue=2, health_cert=0,
         story="陈叔炸了十几年，油每天换，串都是现裹粉现下锅，脆得响。",
         items=[
             dict(name="炸里脊", price=8, unit="串", cal=260,
                  ingredients="猪里脊、面包糠、蛋液、椒盐",
                  method="里脊拍松现裹现炸，撒椒盐",
                  allergens="麸质、蛋", tip="刚出锅30秒内最好吃"),
             dict(name="炸串拼盘", price=15, unit="份", cal=520,
                  ingredients="年糕、鱼豆腐、藕片、金针菇、秘制酱",
                  method="串好后入锅油炸，刷秘制甜辣酱",
                  allergens="麸质、鱼", tip="金针菇一定要点，吸酱最香"),
         ]),
    dict(code="A7", name="手搓冰粉西施", owner="小周", emoji="🍧", x=75, y=41,
         status="open", signature="手搓气泡 · 配料管够", tags="甜品,解辣,夏日",
         rating=4.9, clean=4.9, queue=7, health_cert=1,
         story="小周每天手搓6盆冰粉，气泡绵密，配料给得足，是夜市里的降温站。",
         items=[
             dict(name="手搓冰粉", price=10, unit="碗", cal=180,
                  ingredients="冰粉籽、红糖水、山楂碎、葡萄干、花生碎",
                  method="冰粉籽用纱布手搓出浆，静置凝固，浇红糖水",
                  allergens="花生", tip="加一勺醪糟更香"),
             dict(name="芋圆冰粉", price=14, unit="碗", cal=260,
                  ingredients="冰粉、手作芋圆、红豆、椰奶",
                  method="芋圆现煮过冰水，口感更弹",
                  allergens="花生、椰", tip="芋圆是手作的，卖完就没"),
         ]),
    dict(code="A8", name="老张煎饼果子", owner="老张", emoji="🌯", x=86, y=41,
         status="open", signature="绿豆面 · 薄脆现炸", tags="早餐,天津风味,面食",
         rating=4.6, clean=4.6, queue=5, health_cert=1,
         story="老张的绿豆面是每天早上现磨的，薄脆自己炸，脆到你听得见。",
         items=[
             dict(name="煎饼果子", price=7, unit="个", cal=350,
                  ingredients="绿豆面、鸡蛋、薄脆、甜面酱、香菜、葱",
                  method="摊面糊打蛋，撒葱花香菜，刷酱卷薄脆",
                  allergens="麸质、蛋", tip="要辣的可以加一勺辣酱"),
             dict(name="加里脊煎饼", price=10, unit="个", cal=470,
                  ingredients="煎饼果子料 + 猪里脊",
                  method="里脊现煎后卷入",
                  allergens="麸质、蛋", tip="一个顶到中午"),
         ]),
    dict(code="A9", name="阿力木新疆烤肉", owner="阿力木", emoji="🍖", x=14, y=62,
         status="open", signature="红柳枝 · 洋葱汁腌", tags="烧烤,新疆风味,重口",
         rating=4.7, clean=4.6, queue=8, health_cert=1,
         story="阿力木从和田来，烤羊肉只用红柳枝，洋葱汁腌过的肉膻香十足。",
         items=[
             dict(name="红柳烤羊肉串", price=5, unit="串", cal=110,
                  ingredients="羊后腿肉、红柳枝、孜然、洋葱汁",
                  method="洋葱汁腌2小时，红柳枝穿串上炭火烤",
                  allergens="无", tip="红柳枝的香气是签子给的"),
             dict(name="现烤馕", price=6, unit="个", cal=300,
                  ingredients="面粉、芝麻、洋葱油、盐",
                  method="面团擀圆，撒芝麻，烤炉贴壁烤制",
                  allergens="麸质", tip="掰着吃，配羊肉串最搭"),
         ]),
    dict(code="A10", name="刘姐湖南米粉", owner="刘姐", emoji="🍜", x=31, y=62,
         status="open", signature="骨汤熬4小时 · 现烫米粉", tags="主食,湖南风味,辣",
         rating=4.5, clean=4.4, queue=3, health_cert=1,
         story="刘姐的骨汤熬足四小时，酸豆角自己腌，湖南人来了都说地道。",
         items=[
             dict(name="酸辣米粉", price=15, unit="碗", cal=520,
                  ingredients="米粉、酸豆角、剁辣椒、猪骨汤、花生",
                  method="骨汤熬4小时，米粉现烫，浇酸辣浇头",
                  allergens="花生、大豆", tip="微辣/中辣/变态辣，慎选后者"),
             dict(name="卤蛋", price=3, unit="个", cal=80,
                  ingredients="鸡蛋、卤水",
                  method="卤水浸泡过夜",
                  allergens="蛋", tip="加在米粉里更香"),
         ]),
    dict(code="A11", name="无锡小笼", owner="华姐", emoji="🥠", x=48, y=62,
         status="away", signature="18道褶 · 甜汤包", tags="江浙名点,面食,甜口",
         rating=4.8, clean=4.8, queue=0, health_cert=1,
         story="华姐的小笼18道褶，汤汁偏甜，是无锡人从小吃到大的味道。",
         items=[
             dict(name="小笼包", price=10, unit="6只", cal=420,
                  ingredients="面粉、猪前腿肉、皮冻、酱油、糖",
                  method="18道褶现包，旺火蒸8分钟",
                  allergens="麸质、大豆", tip="先开窗后喝汤，别一口闷"),
             dict(name="蟹粉小笼", price=18, unit="6只", cal=400,
                  ingredients="面粉、猪肉、现拆蟹粉、皮冻",
                  method="蟹粉拌入肉馅，旺火蒸制",
                  allergens="麸质、甲壳类", tip="蟹粉季限定，来晚就没"),
         ]),
    dict(code="A12", name="云南包浆豆腐", owner="小杨", emoji="🧈", x=65, y=62,
         status="open", signature="炭火慢烤 · 一口爆浆", tags="夜宵,云南风味,素食",
         rating=4.6, clean=4.7, queue=4, health_cert=1,
         story="云南姑娘小杨守着一炉炭火慢慢烤，豆腐外焦里嫩，咬开一口爆浆。",
         items=[
             dict(name="包浆豆腐", price=10, unit="份", cal=230,
                  ingredients="石屏豆腐、干辣椒面、折耳根、香葱",
                  method="炭火慢烤至鼓包，蘸干辣椒面吃",
                  allergens="大豆", tip="怕折耳根可以不放"),
             dict(name="烤洋芋", price=8, unit="份", cal=210,
                  ingredients="小土豆、辣椒面、花椒粉、葱花",
                  method="土豆先煮后烤，压扁刷料再烤",
                  allergens="无", tip="加一勺辣椒面才是云南吃法"),
         ]),
]


# ---------------------------------------- 2026-09-26 追加：定时出摊 + 摊主原声
# 来自同学反馈：① 出摊状态直接标在摊位旁，并支持筛选「出摊中 / 定时出摊」 ② 文案去 AI 味，改采访口吻
EXTRA = {
    "A1": dict(short="王阿姨", loc="第二食堂门口", opens_at="16:30", closes_at="21:30",
               intro="面要醒够四十分钟，急不得。有人从小学吃到结婚。",
               intro_who="王阿姨 · 安徽人 · 在上应大第 18 年"),
    "A2": dict(short="老李烤串", loc="学生活动中心前", opens_at="18:00", closes_at="24:00",
               intro="炉子六点点着，羊肉当天现穿，卖完就收。过夜的肉我不卖。",
               intro_who="李叔 · 内蒙古人 · 第 7 年"),
    "A3": dict(short="阿婆酒酿", loc="宿舍区 15 号楼", opens_at="", closes_at="",
               intro="米酒是我自己发的，甜不甜看天气。七十岁了，做惯了停不下来。",
               intro_who="陈阿婆 · 本地人 · 做了 30 年"),
    "A4": dict(short="小杨生煎", loc="东操场南侧", opens_at="16:00", closes_at="21:00",
               intro="一天包八百个，褶子十八道。汤多不多，咬第一口就知道。",
               intro_who="小杨 · 江苏人 · 第 4 年"),
    "A5": dict(short="张记臭豆腐", loc="第一食堂门口", opens_at="17:30", closes_at="23:00",
               intro="豆腐我自己点，卤水泡足三天。闻着冲，吃着香。",
               intro_who="张姐 · 湖南人 · 第 6 年"),
    "A6": dict(short="陈叔炸串", loc="天车东广场", opens_at="18:00", closes_at="23:30",
               intro="油每天换，串现裹现炸。炸老了我不会给你端出去。",
               intro_who="陈叔 · 本地人 · 第 12 年"),
    "A7": dict(short="冰粉西施", loc="图书馆前广场", opens_at="", closes_at="",
               intro="冰粉要手搓才有气泡，六盆，卖完就没了。",
               intro_who="小周 · 四川人 · 第 3 年"),
    "A8": dict(short="老张煎饼", loc="南门内主路", opens_at="17:00", closes_at="22:30",
               intro="绿豆面早上现磨，薄脆自己炸。脆不脆，你听得见。",
               intro_who="老张 · 天津人 · 第 9 年"),
    "A9": dict(short="阿力木烤肉", loc="教师公寓门口", opens_at="", closes_at="",
               intro="肉用洋葱汁腌一夜，红柳枝烤。和田的味儿，不能糊弄。",
               intro_who="阿力木 · 新疆和田 · 第 2 年"),
    "A10": dict(short="刘姐米粉", loc="第三食堂旁", opens_at="17:00", closes_at="23:00",
                intro="骨汤熬四个钟头，酸豆角我自己腌。湖南老乡来了都说像家里做的。",
                intro_who="刘姐 · 湖南人 · 第 5 年"),
    "A11": dict(short="无锡小笼", loc="室内体育馆前", opens_at="", closes_at="",
                intro="十八道褶，汤汁偏甜。无锡人从小吃这个味道。",
                intro_who="华姐 · 江苏无锡 · 第 8 年"),
    "A12": dict(short="包浆豆腐", loc="第一教学楼东侧", opens_at="18:00", closes_at="23:00",
                intro="炭火要慢，急火就焦了。咬开的时候小心烫。",
                intro_who="小杨 · 云南人 · 第 1 年"),
}
# 地图坐标：2026-09-26 重排。原来 12 家 y 全是 41（一条线），标签互相遮挡没法读。
# 改成沿街两侧两排（上排 6 家、下排 6 家），间距按 390px 手机宽度实测不重叠。
POS = {
    "A1": (35.0, 31.0),   # 第二食堂门口
    "A2": (30.0, 39.5),   # 学生活动中心前
    "A3": (38.5, 23.8),   # 宿舍区 15 号楼
    "A4": (78.6, 29.1),   # 东操场南侧
    "A5": (61.5, 35.8),   # 第一食堂门口
    "A6": (80.5, 63.5),   # 天车东广场
    "A7": (53.3, 60.9),   # 图书馆前广场
    "A8": (47.8, 74.8),   # 南门内主路
    "A9": (24.5, 49.8),   # 教师公寓门口
    "A10": (61.5, 66.5),  # 第三食堂旁
    "A11": (14.5, 58.5),  # 室内体育馆前
    "A12": (39.5, 54.5),  # 第一教学楼东侧
}
for _s in STALLS:
    if _s["code"] in POS:
        _s["x"], _s["y"] = POS[_s["code"]]
    _e = EXTRA.get(_s["code"], {})
    _s["short"] = _e.get("short", _s["name"][:4])
    _s["opens_at"] = _e.get("opens_at", "")
    _s["closes_at"] = _e.get("closes_at", "")
    _s["intro"] = _e.get("intro", _s.get("story", ""))
    _s["intro_who"] = _e.get("intro_who", _s.get("owner", ""))
    _s["loc"] = _e.get("loc", "")


REVIEWS = [
    ("A1", 5, "六点四十到的，前面已经排了五个人。饼边脆、中间软，值。", "李同学", "07:12"),
    ("A1", 5, "加两个蛋还多给一勺酱，阿姨记得我不吃葱。", "小陈", "07:30"),
    ("A1", 4, "好吃是好吃，就是要等，赶早八的别来。", "匿名同学", "08:05"),
    ("A2", 5, "晚自习出来撸三串，羊肉是现穿的，不注水。", "张同学", "21:40"),
    ("A2", 4, "味道没得说，人多的时候等得久。", "王同学", "21:55"),
    ("A3", 5, "冷天一碗酒酿圆子，从手暖到脚。", "小林", "19:20"),
    ("A3", 3, "扑空两次了，建议出摊前在群里喊一声。", "匿名同学", "19:05"),
    ("A4", 5, "底子焦香，第一口汤汁喷了我一身，还是值。", "李同学", "18:10"),
    ("A4", 4, "四只五块，比食堂划算。", "周同学", "18:25"),
    ("A5", 5, "臭得正宗，多要一勺辣。", "匿名同学", "20:30"),
    ("A5", 5, "分量肉眼可见的实在，老板不抠。", "小徐", "20:45"),
    ("A6", 5, "炸年糕必点，外面脆里面是软的。", "陈同学", "20:15"),
    ("A6", 4, "油有点大，但香得没话说。", "匿名同学", "20:20"),
    ("A7", 5, "红糖冰粉加糍粑，军训那几天全靠它。", "王同学", "12:40"),
    ("A7", 3, "料比上学期少了一点点。", "匿名同学", "12:50"),
    ("A8", 5, "薄脆是现炸的，咬下去咔嚓一声。", "张同学", "07:50"),
    ("A9", 5, "现切现烤，孜然给得足。", "匿名同学", "21:10"),
    ("A9", 4, "等了二十分钟，赶课的别来。", "李同学", "21:30"),
    ("A10", 5, "加辣加酸笋，一口下去人就醒了。", "周同学", "17:50"),
    ("A11", 4, "皮薄汁多，一笼八只。", "匿名同学", "17:20"),
    ("A11", 3, "比上学期小了一圈，价格没变。", "王同学", "17:35"),
    ("A12", 5, "外焦里嫩，蘸水是灵魂。", "小陈", "19:45"),
    ("A12", 4, "稍微咸了点，配米饭刚好。", "匿名同学", "20:00"),
]


def seed_reviews(conn):
    """预置几条示例评价（只在评价表为空时灌，现场评的真实数据不会被覆盖）"""
    if conn.execute("SELECT COUNT(*) c FROM reviews").fetchone()["c"]:
        return
    ids = {r["code"]: r["id"] for r in conn.execute("SELECT id,code FROM stalls").fetchall()}
    day = datetime.now().strftime("%Y-%m-%d")
    for code, stars, text, who, tm in REVIEWS:
        sid = ids.get(code)
        if sid:
            conn.execute(
                "INSERT INTO reviews(stall_id,order_code,stars,text,who,created_at,day) VALUES(?,?,?,?,?,?,?)",
                (sid, "", stars, text, who, tm, day))
    conn.commit()


SEED_REPLIES = [
    ("A1", "就是要等", "早八前十分钟最挤。头天晚上在群里喊一声，我给你留着。"),
    ("A3", "扑空两次", "对不住，这两天腰不好。以后出摊提前在群里说一声。"),
    ("A4", "比食堂划算", "学生价，一直这个价，不涨。"),
    ("A6", "油有点大", "油每天一换。下回跟我说少油多脆，我给你单独炸。"),
    ("A7", "料比上学期少", "红糖一斤涨了两块。我再给你多舀半勺。"),
    ("A9", "二十分钟", "高峰期就这二十分钟。提前给我发个消息，我先把你的烤上。"),
    ("A11", "比上学期小了一圈", "肉价涨了，我没涨价。这两天给你补回原来的量。"),
]


def seed_replies(conn):
    """给几条预置评价配上摊主回复（只在还没回复过时补，现场回复不会被覆盖）"""
    ids = {r["code"]: r["id"] for r in conn.execute("SELECT id,code FROM stalls").fetchall()}
    for code, snip, reply in SEED_REPLIES:
        sid = ids.get(code)
        if not sid:
            continue
        row = conn.execute(
            "SELECT id FROM reviews WHERE stall_id=? AND text LIKE ? AND IFNULL(reply,'')='' LIMIT 1",
            (sid, "%" + snip + "%")).fetchone()
        if row:
            conn.execute("UPDATE reviews SET reply=?, reply_at=? WHERE id=?",
                         (reply, datetime.now().strftime("%H:%M"), row["id"]))
    conn.commit()


def review_agg(conn):
    """每个摊位的评价数与均分（有真实评价后，前端显示的就是实时均分）"""
    rows = conn.execute("SELECT stall_id, COUNT(*) c, AVG(stars) a FROM reviews GROUP BY stall_id").fetchall()
    return {r["stall_id"]: (r["c"], round(r["a"] or 0, 1)) for r in rows}


def _with_reviews(d, agg):
    d["base_rating"] = d["rating"]
    cnt, avg = agg.get(d["id"], (0, 0.0))
    d["review_count"] = cnt
    d["review_avg"] = avg if cnt else d["rating"]
    if cnt:
        d["rating"] = avg
    return d


def seed(conn):
    for s in STALLS:
        cur = conn.execute(
            "INSERT INTO stalls(code,name,owner,emoji,x,y,status,signature,tags,rating,clean,queue,"
            "story,health_cert,opens_at,closes_at,intro,intro_who,short,loc)"
            " VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (s["code"], s["name"], s["owner"], s["emoji"], s["x"], s["y"], s["status"],
             s["signature"], s["tags"], s["rating"], s["clean"], s["queue"], s["story"], s["health_cert"],
             s.get("opens_at", ""), s.get("closes_at", ""), s.get("intro", ""), s.get("intro_who", ""),
             s.get("short", ""), s.get("loc", "")))
        sid = cur.lastrowid
        for it in s["items"]:
            conn.execute(
                "INSERT INTO items(stall_id,name,price,unit,cal,ingredients,method,allergens,tip)"
                " VALUES(?,?,?,?,?,?,?,?,?)",
                (sid, it["name"], it["price"], it["unit"], it["cal"], it["ingredients"],
                 it["method"], it["allergens"], it["tip"]))
    conn.commit()


@app.on_event("startup")
def startup():
    os.makedirs(STATIC, exist_ok=True)
    conn = db()
    conn.executescript(SCHEMA)

    # 老库自动升级：补齐 2026-09-26 新增的「定时出摊 / 摊主原声」字段，并按 code 回填
    have = {r["name"] for r in conn.execute("PRAGMA table_info(stalls)").fetchall()}
    for col, typ in (("opens_at", "TEXT"), ("closes_at", "TEXT"), ("intro", "TEXT"),
                     ("intro_who", "TEXT"), ("short", "TEXT"), ("loc", "TEXT")):
        if col not in have:
            conn.execute("ALTER TABLE stalls ADD COLUMN {} {}".format(col, typ))
    for s in STALLS:
        conn.execute(
            "UPDATE stalls SET opens_at=COALESCE(NULLIF(opens_at,''),?),"
            " closes_at=COALESCE(NULLIF(closes_at,''),?),"
            " intro=COALESCE(NULLIF(intro,''),?),"
            " intro_who=COALESCE(NULLIF(intro_who,''),?),"
            " short=COALESCE(NULLIF(short,''),?), loc=COALESCE(NULLIF(loc,''),?) WHERE code=?",
            (s.get("opens_at", ""), s.get("closes_at", ""), s.get("intro", ""),
             s.get("intro_who", ""), s.get("short", ""), s.get("loc", ""), s["code"]))
        conn.execute("UPDATE stalls SET x=?, y=? WHERE code=?", (s["x"], s["y"], s["code"]))

    have_rv = {r["name"] for r in conn.execute("PRAGMA table_info(reviews)").fetchall()}
    for col in ("reply", "reply_at"):
        if col not in have_rv:
            conn.execute("ALTER TABLE reviews ADD COLUMN {} TEXT".format(col))

    if conn.execute("SELECT COUNT(*) c FROM stalls").fetchone()["c"] == 0:
        seed(conn)
    seed_reviews(conn)
    seed_replies(conn)
    conn.commit()
    conn.close()


# ---------------------------------------------------------------- helpers
def order_no(n):
    return f"A-{n:03d}"


def log_event(kind, payload):
    conn = db()
    conn.execute("INSERT INTO events(ts,kind,payload) VALUES(?,?,?)",
                 (datetime.now().isoformat(timespec="seconds"), kind, json.dumps(payload, ensure_ascii=False)))
    conn.commit()
    conn.close()


# ---------------------------------------------------------------- API
@app.get("/api/stalls")
def api_stalls():
    conn = db()
    rows = conn.execute("SELECT * FROM stalls ORDER BY code").fetchall()
    agg = review_agg(conn)
    out = []
    for r in rows:
        d = dict(r)
        d["items"] = [dict(x) for x in conn.execute(
            "SELECT id,name,price,unit,cal FROM items WHERE stall_id=? ORDER BY id", (r["id"],)).fetchall()]
        d["tags"] = d["tags"].split(",") if d["tags"] else []
        _with_reviews(d, agg)
        out.append(d)
    open_now = sum(1 for s in out if s["status"] == "open")
    conn.close()
    return {"stalls": out, "open_now": open_now, "total": len(out),
            "server_time": datetime.now().strftime("%H:%M:%S")}


@app.get("/api/stalls/{sid}")
def api_stall(sid: int):
    conn = db()
    r = conn.execute("SELECT * FROM stalls WHERE id=?", (sid,)).fetchone()
    if not r:
        raise HTTPException(404, "摊主不存在")
    d = dict(r)
    d["items"] = [dict(x) for x in conn.execute("SELECT * FROM items WHERE stall_id=?", (sid,)).fetchall()]
    d["tags"] = d["tags"].split(",") if d["tags"] else []
    _with_reviews(d, review_agg(conn))
    d["reviews"] = [dict(x) for x in conn.execute(
        "SELECT id,stars,text,who,created_at,reply,reply_at FROM reviews WHERE stall_id=? ORDER BY id DESC LIMIT 6",
        (sid,)).fetchall()]
    conn.close()
    return d


@app.post("/api/stalls/{sid}/status")
def api_set_status(sid: int, payload: dict = Body(...)):
    status = payload.get("status", "open")
    conn = db()
    conn.execute("UPDATE stalls SET status=? WHERE id=?", (status, sid))
    conn.commit()
    r = dict(conn.execute("SELECT * FROM stalls WHERE id=?", (sid,)).fetchone())
    conn.close()
    log_event("stall_status", {"stall": r["name"], "status": status})
    return {"ok": True, "status": status, "stall": r["name"]}


@app.post("/api/stalls/{sid}/items")
def api_add_item(sid: int, payload: dict = Body(...)):
    """商家端极简发布（原型版为表单；正式版为拍照/语音 → 大模型结构化）"""
    conn = db()
    cur = conn.execute(
        "INSERT INTO items(stall_id,name,price,unit,cal,ingredients,method,allergens,tip)"
        " VALUES(?,?,?,?,?,?,?,?,?)",
        (sid, payload.get("name", "新菜品"), float(payload.get("price", 0)), payload.get("unit", "份"),
         float(payload.get("cal", 0)), payload.get("ingredients", "待补充"), payload.get("method", "待补充"),
         payload.get("allergens", "无"), payload.get("tip", "")))
    conn.commit()
    conn.close()
    log_event("item_publish", {"stall_id": sid, "name": payload.get("name")})
    return {"ok": True, "item_id": cur.lastrowid}


class OrderIn(dict):
    pass


@app.post("/api/orders")
def api_create_order(payload: dict = Body(...)):
    # 坏载荷要回 400，不要 500（评委或队友手抖也不能把接口打崩）
    if not isinstance(payload, dict) or "stall_id" not in payload or "lines" not in payload:
        raise HTTPException(400, "请求缺少 stall_id 或 lines")
    try:
        sid = int(payload["stall_id"])
        lines = list(payload["lines"])
    except (TypeError, ValueError):
        raise HTTPException(400, "stall_id / lines 格式不对")
    if not lines:
        raise HTTPException(400, "购物车是空的")
    conn = db()
    row = conn.execute("SELECT * FROM stalls WHERE id=?", (sid,)).fetchone()
    if not row:
        conn.close()
        raise HTTPException(404, "摊位不存在")
    stalls = dict(row)
    total, detail = 0.0, []
    for ln in lines:
        it = conn.execute("SELECT * FROM items WHERE id=? AND stall_id=?", (ln["item_id"], sid)).fetchone()
        if not it:
            continue
        qty = int(ln.get("qty", 1))
        total += it["price"] * qty
        detail.append({"name": it["name"], "qty": qty, "price": it["price"], "cal": it["cal"]})
    if not detail:
        raise HTTPException(400, "购物车是空的")
    n = conn.execute("SELECT COUNT(*) c FROM orders").fetchone()["c"] + 1
    code = order_no(n)
    cur = conn.execute(
        "INSERT INTO orders(stall_id,code,lines,total,status,created_at) VALUES(?,?,?,?,?,?)",
        (sid, code, json.dumps(detail, ensure_ascii=False), round(total, 2), "new",
         datetime.now().strftime("%H:%M:%S")))
    conn.commit()
    conn.close()
    log_event("order_new", {"code": code, "stall": stalls["name"], "total": total})
    return {"ok": True, "order_id": cur.lastrowid, "code": code, "total": round(total, 2),
            "lines": detail, "stall": stalls["name"], "queue_ahead": random.randint(1, 4)}


@app.get("/api/orders")
def api_orders(stall_id: int = 0):
    conn = db()
    if stall_id:
        rows = conn.execute("SELECT * FROM orders WHERE stall_id=? ORDER BY id DESC LIMIT 20", (stall_id,)).fetchall()
    else:
        rows = conn.execute("SELECT * FROM orders ORDER BY id DESC LIMIT 20").fetchall()
    out = []
    for r in rows:
        d = dict(r)
        d["lines"] = json.loads(d["lines"])
        st = conn.execute("SELECT name,emoji FROM stalls WHERE id=?", (d["stall_id"],)).fetchone()
        d["stall_name"] = st["name"] if st else "?"
        d["stall_emoji"] = st["emoji"] if st else "🍽"
        out.append(d)
    conn.close()
    return {"orders": out}


@app.post("/api/orders/{oid}/status")
def api_order_status(oid: int, payload: dict = Body(...)):
    status = payload.get("status", "accepted")
    conn = db()
    conn.execute("UPDATE orders SET status=? WHERE id=?", (status, oid))
    conn.commit()
    r = dict(conn.execute("SELECT * FROM orders WHERE id=?", (oid,)).fetchone())
    conn.close()
    log_event("order_status", {"code": r["code"], "status": status})
    return {"ok": True, "code": r["code"], "status": status}


@app.get("/api/stats")
def api_stats():
    conn = db()
    orders = conn.execute("SELECT COUNT(*) c, IFNULL(SUM(total),0) s FROM orders").fetchone()
    open_stalls = conn.execute("SELECT COUNT(*) c FROM stalls WHERE status='open'").fetchone()["c"]
    by_stall = conn.execute(
        "SELECT s.name, s.emoji, COUNT(o.id) c FROM stalls s LEFT JOIN orders o ON o.stall_id=s.id"
        " GROUP BY s.id ORDER BY c DESC LIMIT 5").fetchall()
    rv = conn.execute("SELECT COUNT(*) c, IFNULL(AVG(stars),0) a FROM reviews").fetchone()
    conn.close()
    return {"orders": orders["c"], "gmv": round(orders["s"], 1), "open_stalls": open_stalls,
            "reviews": rv["c"], "review_avg": round(rv["a"], 1),
            "top": [dict(x) for x in by_stall]}


# ---------------------------------------------------------------- 评价
_RV_LAST = {}          # (ip, stall_id) -> 上次评价时间戳，防连点刷分
RV_WORDS = {1: "不太行", 2: "一般般", 3: "还不错", 4: "挺好吃", 5: "这个摊我锁死了"}


@app.get("/api/reviews")
def api_reviews(stall_id: int = 0, limit: int = 20):
    limit = max(1, min(int(limit), 100))
    conn = db()
    if stall_id:
        rows = conn.execute(
            "SELECT id,stall_id,stars,text,who,created_at,order_code,reply,reply_at FROM reviews"
            " WHERE stall_id=? ORDER BY id DESC LIMIT ?", (stall_id, limit)).fetchall()
        agg = conn.execute("SELECT COUNT(*) c, AVG(stars) a FROM reviews WHERE stall_id=?",
                           (stall_id,)).fetchone()
    else:
        rows = conn.execute(
            "SELECT r.id,r.stall_id,r.stars,r.text,r.who,r.created_at,r.order_code,r.reply,r.reply_at,"
            " s.name stall_name"
            " FROM reviews r LEFT JOIN stalls s ON s.id=r.stall_id ORDER BY r.id DESC LIMIT ?",
            (limit,)).fetchall()
        agg = conn.execute("SELECT COUNT(*) c, AVG(stars) a FROM reviews").fetchone()
    conn.close()
    return {"reviews": [dict(x) for x in rows], "count": agg["c"], "avg": round(agg["a"] or 0, 1)}


@app.post("/api/reviews")
def api_create_review(payload: dict = Body(...), request: Request = None):
    if not isinstance(payload, dict) or "stall_id" not in payload or "stars" not in payload:
        raise HTTPException(400, "请求缺少 stall_id 或 stars")
    try:
        sid = int(payload["stall_id"])
        stars = int(payload["stars"])
    except (TypeError, ValueError):
        raise HTTPException(400, "stall_id / stars 格式不对")
    if stars < 1 or stars > 5:
        raise HTTPException(400, "分数只能是 1~5")
    text = str(payload.get("text") or "").strip()
    who = str(payload.get("who") or "").strip()
    code = str(payload.get("order_code") or "").strip()
    if len(text) > 60:
        raise HTTPException(400, "一句话短评别超过 60 字")
    if len(who) > 8:
        raise HTTPException(400, "署名别超过 8 个字")
    conn = db()
    row = conn.execute("SELECT id,name FROM stalls WHERE id=?", (sid,)).fetchone()
    if not row:
        conn.close()
        raise HTTPException(404, "摊位不存在")
    if code:
        o = conn.execute("SELECT id FROM orders WHERE code=?", (code,)).fetchone()
        if not o:
            conn.close()
            raise HTTPException(400, "取餐码对不上，评价没提交")
        if conn.execute("SELECT id FROM reviews WHERE order_code=?", (code,)).fetchone():
            conn.close()
            raise HTTPException(400, "这一单已经评过了")
    ip = "?"
    try:
        ip = request.client.host if request and request.client else "?"
    except Exception:
        pass
    import time as _t
    key = (ip, sid)
    now = _t.time()
    if now - _RV_LAST.get(key, 0) < 3:
        conn.close()
        raise HTTPException(429, "同一摊位 3 秒内只能评一次")
    _RV_LAST[key] = now
    conn.execute("INSERT INTO reviews(stall_id,order_code,stars,text,who,created_at,day) VALUES(?,?,?,?,?,?,?)",
                 (sid, code, stars, text, who or "匿名同学", datetime.now().strftime("%H:%M"),
                  datetime.now().strftime("%Y-%m-%d")))
    conn.commit()
    agg = conn.execute("SELECT COUNT(*) c, AVG(stars) a FROM reviews WHERE stall_id=?", (sid,)).fetchone()
    conn.close()
    log_event("review_new", {"stall": row["name"], "stars": stars, "text": text[:20]})
    return {"ok": True, "stall": row["name"], "stars": stars, "word": RV_WORDS.get(stars, ""),
            "count": agg["c"], "avg": round(agg["a"] or 0, 1)}


@app.post("/api/reviews/{rid}/reply")
def api_reply_review(rid: int, payload: dict = Body(...)):
    """摊主回复评价（只能回自己摊位的；回复传空串=撤回回复）"""
    reply = str(payload.get("reply") or "").strip()
    if len(reply) > 60:
        raise HTTPException(400, "回复别超过 60 字")
    conn = db()
    r = conn.execute("SELECT * FROM reviews WHERE id=?", (rid,)).fetchone()
    if not r:
        conn.close()
        raise HTTPException(404, "这条评价不存在")
    if payload.get("stall_id") is not None:
        try:
            if int(payload["stall_id"]) != r["stall_id"]:
                conn.close()
                raise HTTPException(403, "只能回复自己摊位的评价")
        except (TypeError, ValueError):
            conn.close()
            raise HTTPException(400, "stall_id 格式不对")
    at = datetime.now().strftime("%H:%M") if reply else ""
    conn.execute("UPDATE reviews SET reply=?, reply_at=? WHERE id=?", (reply, at, rid))
    conn.commit()
    conn.close()
    log_event("review_reply", {"review_id": rid, "reply": reply[:20]})
    return {"ok": True, "id": rid, "reply": reply, "reply_at": at}


# ---------------------------------------------------------------- AI
COLOR_MAP = [
    ((180, 120, 40), "葱油饼"), ((200, 150, 80), "生煎包"), ((210, 60, 50), "臭豆腐"),
    ((240, 240, 235), "小笼包"), ((235, 200, 120), "煎饼果子"), ((150, 90, 60), "烤羊肉串"),
    ((170, 200, 150), "冰粉"), ((220, 180, 140), "包浆豆腐"),
]


@app.post("/api/recognize")
async def api_recognize(file: UploadFile = File(...)):
    """拍图识别（演示版：颜色特征匹配；正式版接多模态大模型）"""
    raw = await file.read()
    try:
        from PIL import Image
        im = Image.open(io.BytesIO(raw)).convert("RGB").resize((48, 48))
        px = list(im.getdata())
        r = sum(p[0] for p in px) / len(px)
        g = sum(p[1] for p in px) / len(px)
        b = sum(p[2] for p in px) / len(px)
    except Exception:
        r, g, b = 200, 150, 80
    best, name = 1e9, "葱油饼"
    for (cr, cg, cb), nm in COLOR_MAP:
        d = (r - cr) ** 2 + (g - cg) ** 2 + (b - cb) ** 2
        if d < best:
            best, name = d, nm
    conn = db()
    it = conn.execute("SELECT * FROM items WHERE name LIKE ?", (f"%{name}%",)).fetchone()
    if not it:
        it = conn.execute("SELECT * FROM items LIMIT 1").fetchone()
    st = conn.execute("SELECT * FROM stalls WHERE id=?", (it["stall_id"],)).fetchone()
    conn.close()
    conf = max(0.62, min(0.96, 1 - best / (255 ** 2 * 3)))
    return {"ok": True, "guess": it["name"], "confidence": round(conf, 2),
            "avg_rgb": [round(r), round(g), round(b)],
            "stall": st["name"], "stall_emoji": st["emoji"],
            "card": {"ingredients": it["ingredients"], "method": it["method"],
                     "cal": it["cal"], "allergens": it["allergens"], "tip": it["tip"]},
            "note": "演示版：颜色特征匹配（正式版接入多模态大模型 → 更高精度 + 多品识别）"}


def _deepseek_key():
    # 1) 环境变量优先：队友/部署环境只需设置 DEEPSEEK_API_KEY 即可
    env_key = os.environ.get("DEEPSEEK_API_KEY")
    if env_key:
        return env_key.strip()
    # 2) 本机 hermes .env 兜底（原开发机）
    paths = [os.path.join(os.environ.get("LOCALAPPDATA", ""), "hermes", ".env"),
             os.path.expanduser("~/AppData/Local/hermes/.env")]
    for p in paths:
        try:
            with open(p, "r", encoding="utf-8") as f:
                for line in f:
                    if line.startswith("DEEPSEEK_API_KEY="):
                        return line.split("=", 1)[1].strip()
        except Exception:
            continue
    return None


def _rule_answer(q):
    q = q.lower()
    if any(k in q for k in ["热量", "卡路里", "胖", "减肥", "多少卡"]):
        return "给你个参考：夜市一份小吃的热量大致在 90~520 大卡之间。羊肉串最低（约90大卡/串），米粉、炸串拼盘偏高（500大卡以上）。想控热量就挑烤串+冰粉，避开油炸和汤面。"
    if any(k in q for k in ["过敏", "花生", "海鲜", "麸质", "虾"]):
        return "夜市常见过敏原有三类要留意：麸质（面制品）、花生（冰粉配料/米粉浇头）、甲壳类（虾仁生煎、蟹粉小笼）。点单前可以看每道菜的「AI 营养卡」，里面标了过敏原。"
    if any(k in q for k in ["高血压", "糖尿病", "血糖", "痛风"]):
        return "有慢性病的话建议：避开重盐重油（臭豆腐、炸串）、少喝糖水（冰粉红糖可要求半糖）；痛风人群注意羊肉串和骨汤米粉（嘌呤偏高）。这只是通用提示，具体请遵医嘱。"
    if any(k in q for k in ["推荐", "吃什么", "好吃", "必吃"]):
        return "第一次来「月亮夜市」建议这样吃：王阿姨葱油饼开场 → 小杨生煎 + 阿力木血柳羊肉串当主菜 → 手搓冰粉收尾解腻。人均 35 元能吃到 4 家。"
    return "我是月亮夜市的 AI 小吃顾问：可以问我某道小吃的原料、做法、热量、过敏原，或者让我按你的口味/预算/健康需求推荐摊位。"


@app.post("/api/ask")
def api_ask(payload: dict = Body(...)):
    q = (payload.get("question") or "").strip()
    if not q:
        raise HTTPException(400, "问点什么吧")
    key = _deepseek_key()
    if key:
        try:
            body = json.dumps({
                "model": "deepseek-chat",
                "messages": [
                    {"role": "system", "content": "你是「月亮夜市」的AI小吃顾问，用简洁温柔的中文回答。"
                     "熟悉上海地摊小吃，会讲原料、做法、热量与过敏原；不给医疗诊断，健康问题提示遵医嘱。回答控制在120字内。"},
                    {"role": "user", "content": q}],
                "temperature": 0.7, "max_tokens": 300,
            }).encode()
            req = urllib.request.Request(
                "https://api.deepseek.com/v1/chat/completions", data=body,
                headers={"Content-Type": "application/json", "Authorization": f"Bearer {key}"})
            with urllib.request.urlopen(req, timeout=12) as resp:
                data = json.loads(resp.read().decode())
            return {"ok": True, "answer": data["choices"][0]["message"]["content"].strip(), "engine": "DeepSeek"}
        except Exception:
            pass
    log_event("ask", {"q": q})
    return {"ok": True, "answer": _rule_answer(q), "engine": "本地知识库"}


# ---------------------------------------------------------------- static
from fastapi.middleware.gzip import GZipMiddleware

# 首页 48KB（内联 JS/CSS）→ gzip 后 ~12KB，手机上少等一截
app.add_middleware(GZipMiddleware, minimum_size=800)


@app.middleware("http")
async def _static_cache_headers(request, call_next):
    """静态资源（底图/图标）加上长缓存：第二次打开不再走网络。"""
    resp = await call_next(request)
    if request.url.path.startswith("/static/"):
        resp.headers.setdefault("Cache-Control", "public, max-age=604800")
    return resp


@app.get("/", response_class=HTMLResponse)
def index():
    # 首屏数据直接内联进页面：公网隧道一次往返约 1 秒，省掉这次往返用户能立刻看到地图和列表
    try:
        boot = json.dumps(api_stalls(), ensure_ascii=False, separators=(",", ":"))
    except Exception:  # noqa: BLE001
        boot = "null"
    with open(os.path.join(STATIC, "index.html"), "r", encoding="utf-8") as f:
        html = f.read().replace("/*__BOOT__*/null", boot)
    # 首页不缓存：以后改完，朋友那边刷新就是新版（手机上最容易看到旧的）
    return HTMLResponse(html, headers={"Cache-Control": "no-store, must-revalidate"})


app.mount("/static", StaticFiles(directory=STATIC), name="static")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8790)
