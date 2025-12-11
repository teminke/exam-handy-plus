# -*- coding: utf-8 -*-
# 考古題 Handy Plus v2.0 — 修正版
# 內容：
# 1) 逐題模式恢復「筆記 / 圖片上傳」區塊（可新增、更新筆記，並上傳/刪除圖片）
# 2) 選項換行修正（支援 \r\n / \r / \n）
# 3) 清單（分頁）支援勾選刪除（單筆/多筆）
# 其餘維持 v2.0 功能。

import os, math, shutil, sqlite3
from datetime import datetime
from typing import List, Dict

import pandas as pd
import streamlit as st

def _safe_add_column(conn, table:str, col:str, decl:str):
    try:
        info = pd.read_sql_query(f"PRAGMA table_info({table})", conn)
        if col not in info["name"].tolist():
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} {decl};")
            conn.commit()
    except Exception:
        pass


DB_PATH = "exam_handy.db"
MEDIA_DIR = "media"

st.set_page_config(page_title="考古題 Handy Plus v2.0", layout="wide")
st.title("**考題整理**")

st.markdown("""
<style>
span[style*="background"]{ padding:0 2px; border-radius:2px; }
</style>
""", unsafe_allow_html=True)

# ---------- DB ----------
@st.cache_resource
def get_conn():
    os.makedirs(MEDIA_DIR, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA synchronous=NORMAL;")
    conn.execute("PRAGMA temp_store=MEMORY;")
    conn.execute("PRAGMA cache_size=100000;")
    return conn

def init_or_upgrade_db():
    conn = get_conn(); cur = conn.cursor()
    cur.execute("""
    CREATE TABLE IF NOT EXISTS questions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        subject TEXT, source TEXT, year TEXT, type TEXT,
        topic TEXT, subtopic TEXT,
        stem TEXT, options TEXT, answer TEXT,
        explanation TEXT, tags TEXT,
        created_at TEXT, updated_at TEXT
    );""")
    cur.execute("""
    CREATE TABLE IF NOT EXISTS notes (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        qid INTEGER UNIQUE,
        note TEXT,
        created_at TEXT, updated_at TEXT
    );""")
    cur.execute("""
    CREATE TABLE IF NOT EXISTS note_assets (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        qid INTEGER, file_path TEXT, caption TEXT, created_at TEXT
    );""")
    cur.execute("""
    CREATE TABLE IF NOT EXISTS annotations (
        qid INTEGER PRIMARY KEY,
        color TEXT DEFAULT '',
        highlight_keywords TEXT DEFAULT '',
        hl_bg TEXT DEFAULT '#ffff66',
        hl_fg TEXT DEFAULT '#000000',
        wrong_count INTEGER DEFAULT 0,
        last_updated TEXT
    );""")
    # 索引
    cur.execute("CREATE INDEX IF NOT EXISTS idx_q_subject ON questions(subject)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_q_year    ON questions(year)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_q_type    ON questions(type)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_q_topic   ON questions(topic)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_img_qid   ON note_assets(qid)")
    # 升級 annotations 欄位（done, star）
    _safe_add_column(conn, "annotations", "done", "INTEGER DEFAULT 0")
    _safe_add_column(conn, "annotations", "star", "INTEGER DEFAULT 0")

    conn.commit()

init_or_upgrade_db()

# ---------- helpers ----------
def ensure_annotation_row(qid:int):
    conn = get_conn(); cur = conn.cursor()
    cur.execute("SELECT qid FROM annotations WHERE qid=?", (qid,))
    if cur.fetchone() is None:
        cur.execute("""INSERT INTO annotations
            (qid, color, highlight_keywords, hl_bg, hl_fg, wrong_count, last_updated)
            VALUES (?, '', '', '#ffff66', '#000000', 0, ?)""",
            (qid, datetime.now().isoformat(timespec='seconds')))
        conn.commit()

def get_annotations(qid:int) -> Dict:
    ensure_annotation_row(qid)
    conn = get_conn()
    df = pd.read_sql_query("SELECT * FROM annotations WHERE qid=?", conn, params=[qid])
    return df.iloc[0].to_dict()

def update_annotations(qid:int, **kwargs):
    ensure_annotation_row(qid)
    if not kwargs: return
    conn = get_conn(); cur = conn.cursor()
    sets, vals = [], []
    for k,v in kwargs.items():
        sets.append(f"{k}=?"); vals.append(v)
    sets.append("last_updated=?"); vals.append(datetime.now().isoformat(timespec='seconds'))
    vals.append(qid)
    cur.execute(f"UPDATE annotations SET {', '.join(sets)} WHERE qid=?", vals)
    conn.commit()


def insert_questions(df: pd.DataFrame):
    # 必要欄位補齊
    req = ["subject","source","year","type","topic","subtopic","stem","options","answer","explanation","tags"]
    for c in req:
        if c not in df.columns:
            df[c] = ""

    # 清理題幹並濾掉空白
    df = df.copy()
    df["stem"] = df["stem"].fillna("").astype(str).str.strip()
    df = df[df["stem"] != ""]

    # 與資料庫比對，避免重複（以「題幹完全相同」視為同題）
    conn = get_conn()
    exist_df = pd.read_sql_query("SELECT stem FROM questions", conn)
    exist_set = set(exist_df["stem"].astype(str).tolist())
    new_df = df[~df["stem"].astype(str).isin(exist_set)].copy()

    if new_df.empty:
        st.warning("⚠️ 本次匯入的題目皆與資料庫重複，未新增任何題目。")
        return

    now = datetime.now().isoformat(timespec="seconds")
    new_df["created_at"] = now
    new_df["updated_at"] = now
    new_df[req+["created_at","updated_at"]].to_sql("questions", conn, if_exists="append", index=False)

    st.session_state["_dirty"] = st.session_state.get("_dirty", 0) + 1
    st.success(f"✅ 已新增 {len(new_df)} 題（已自動跳過重複題）")

def update_question_row(qid:int, data:Dict):
    fields = ["subject","source","year","type","topic","subtopic","stem","options","answer","explanation","tags"]
    sets, vals = [], []
    for f in fields:
        sets.append(f"{f}=?"); vals.append(data.get(f,""))
    sets.append("updated_at=?"); vals.append(datetime.now().isoformat(timespec='seconds'))
    vals.append(qid)
    conn = get_conn(); cur = conn.cursor()
    cur.execute(f"UPDATE questions SET {', '.join(sets)} WHERE id=?", vals)
    conn.commit()
    st.session_state["_dirty"] = st.session_state.get("_dirty", 0) + 1

def get_note_text(qid:int) -> str:
    conn = get_conn()
    df = pd.read_sql_query("SELECT note FROM notes WHERE qid=?", conn, params=[qid])
    if df.empty: return ""
    return df.iloc[0]["note"] or ""

def save_note(qid:int, text:str):
    conn = get_conn(); cur = conn.cursor()
    now = datetime.now().isoformat(timespec='seconds')
    cur.execute("INSERT INTO notes (qid, note, created_at, updated_at) VALUES (?,?,?,?) ON CONFLICT(qid) DO UPDATE SET note=excluded.note, updated_at=excluded.updated_at", (qid, text, now, now))
    conn.commit()

def list_images(qid:int) -> pd.DataFrame:
    conn = get_conn()
    return pd.read_sql_query("SELECT id, file_path, caption, created_at FROM note_assets WHERE qid=? ORDER BY id DESC", conn, params=[qid])

def add_image(qid:int, file_bytes:bytes, filename:str, caption:str=""):
    os.makedirs(MEDIA_DIR, exist_ok=True)
    base, ext = os.path.splitext(filename)
    safe_ext = ext if ext else ".bin"
    save_name = f"{qid}_{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}{safe_ext}"
    save_path = os.path.join(MEDIA_DIR, save_name)
    with open(save_path, "wb") as f:
        f.write(file_bytes)
    conn = get_conn(); cur = conn.cursor()
    cur.execute("INSERT INTO note_assets (qid, file_path, caption, created_at) VALUES (?,?,?,?)",
                (qid, save_path, caption, datetime.now().isoformat(timespec='seconds')))
    conn.commit()

def delete_image(asset_id:int):
    conn = get_conn(); cur = conn.cursor()
    df = pd.read_sql_query("SELECT file_path FROM note_assets WHERE id=?", conn, params=[asset_id])
    if not df.empty:
        path = df.iloc[0]["file_path"]
        try:
            if path and os.path.exists(path):
                os.remove(path)
        except Exception:
            pass
    cur.execute("DELETE FROM note_assets WHERE id=?", (asset_id,))
    conn.commit()



@st.cache_data(show_spinner=False)
def get_meta(_dirty:int):
    conn = get_conn()
    try:
        dfm = pd.read_sql_query("SELECT subject, year, type, topic, subtopic FROM questions", conn)
    except Exception:
        return {"subjects": [], "years": [], "types": [], "topics": []}

    def _uniq(col):
        if col not in dfm.columns:
            return []
        s = dfm[col].dropna().astype(str).map(lambda x: x.strip()).replace({"": None}).dropna()
        return sorted(s.unique().tolist())

    return {
        "subjects": _uniq("subject"),
        "years": _uniq("year"),
        "types": _uniq("type"),
        "topics": _uniq("topic"),
    "subtopics": _uniq("subtopic"),
    }


@st.cache_data(show_spinner=True)
def query_questions_cached(filters: dict, search: str, limit: int, wrong_only: bool, min_wrong: int, _dirty:int):
    conn = get_conn()
    q = "SELECT q.*, COALESCE(a.wrong_count,0) AS wrong_count, COALESCE(a.done,0) AS done, COALESCE(a.star,0) AS star FROM questions q LEFT JOIN annotations a ON a.qid = q.id WHERE 1=1"
    args: List = []
    for key in ["subject","year","type","topic","subtopic"]:
        vals = filters.get(key, [])
        if vals:
            holders = ",".join(["?"]*len(vals))
            q += f" AND q.{key} IN ({holders})"
            args.extend(vals)
    if search:
        q += " AND (q.stem LIKE ? OR q.explanation LIKE ? OR q.tags LIKE ? OR q.source LIKE ? OR q.options LIKE ? OR q.topic LIKE ? OR q.subject LIKE ? OR q.subtopic LIKE ?)"
        s = f"%{search}%"; args.extend([s,s,s,s,s,s,s,s])
    if wrong_only:
        q += " AND COALESCE(a.wrong_count,0) > 0"
    if isinstance(min_wrong, int) and min_wrong > 0:
        q += " AND COALESCE(a.wrong_count,0) >= ?"
        args.append(int(min_wrong))
    q += " ORDER BY COALESCE(a.wrong_count,0) DESC, q.updated_at DESC, q.id DESC LIMIT ?"
    args.append(limit)
    return pd.read_sql_query(q, conn, params=args)

def _delete_ids(qids:List[int]) -> int:
    if not qids: return 0
    conn = get_conn(); cur = conn.cursor()
    holders = ",".join(["?"]*len(qids))
    img_df = pd.read_sql_query(f"SELECT file_path FROM note_assets WHERE qid IN ({holders})", conn, params=qids)
    for _, r in img_df.iterrows():
        try:
            if r["file_path"] and os.path.exists(r["file_path"]):
                os.remove(r["file_path"])
        except Exception:
            pass
    cur.execute(f"DELETE FROM note_assets WHERE qid IN ({holders})", qids)
    cur.execute(f"DELETE FROM notes       WHERE qid IN ({holders})", qids)
    cur.execute(f"DELETE FROM annotations WHERE qid IN ({holders})", qids)
    cur.execute(f"DELETE FROM questions   WHERE id  IN ({holders})", qids)
    conn.commit()
    st.session_state["_dirty"] = st.session_state.get("_dirty", 0) + 1
    return len(qids)

def clear_all(which:str):
    conn = get_conn(); cur = conn.cursor()
    if which == "all":
        try: shutil.rmtree(MEDIA_DIR)
        except Exception: pass
        os.makedirs(MEDIA_DIR, exist_ok=True)
        for tbl in ["note_assets","notes","annotations","questions"]:
            cur.execute(f"DELETE FROM {tbl};")
    elif which == "notes_only":
        try: shutil.rmtree(MEDIA_DIR)
        except Exception: pass
        os.makedirs(MEDIA_DIR, exist_ok=True)
        cur.execute("DELETE FROM note_assets;")
        cur.execute("DELETE FROM notes;")
    elif which == "ann_only":
        cur.execute("DELETE FROM annotations;")
    conn.commit()
    st.session_state["_dirty"] = st.session_state.get("_dirty", 0) + 1


def find_duplicate_ids_to_delete() -> list:
    """回傳應刪除的重複題 id（以相同 stem 為重複，保留每組最小 id）"""
    conn = get_conn()
    # 找出每個 stem 的最小 id
    min_id_df = pd.read_sql_query("SELECT stem, MIN(id) AS keep_id FROM questions GROUP BY stem", conn)
    all_df = pd.read_sql_query("SELECT id, stem FROM questions", conn)
    keep_map = {row["stem"]: int(row["keep_id"]) for _, row in min_id_df.iterrows()}
    ids_to_delete = []
    for _, r in all_df.iterrows():
        sid = int(r["id"]); steme = str(r["stem"])
        if steme in keep_map and sid != keep_map[steme]:
            ids_to_delete.append(sid)
    return ids_to_delete
def apply_highlight(html_txt:str, keywords:str, bg:str, fg:str) -> str:
    if not html_txt: return ""
    if not keywords.strip(): return html_txt
    kws = [k.strip() for k in keywords.split(',') if k.strip()]
    out = html_txt
    for k in sorted(kws, key=len, reverse=True):
        out = out.replace(k, f"<span style='background:{bg};color:{fg};padding:0 2px;border-radius:2px'>{k}</span>")
    return out

# ---------- SIDEBAR ----------
with st.sidebar:
    st.subheader("**資料匯入**")
    up = st.file_uploader("上傳題庫 CSV（UTF-8 / UTF-8-SIG）", type=["csv"])
    if up is not None:
        try:
            try:
                df_in = pd.read_csv(up, encoding="utf-8-sig")
            except Exception:
                up.seek(0); df_in = pd.read_csv(up, encoding="utf-8")
            insert_questions(df_in); st.success(f"已匯入 {len(df_in)} 題"); st.session_state['_dirty'] = st.session_state.get('_dirty', 0) + 1
        except Exception as e:
            st.error(f"匯入失敗：{e}")

    st.divider()
    st.subheader("**查詢設定**")
    max_rows = st.slider("查詢上限（越小越快）", 50, 5000, 800, 50)

    meta = get_meta(st.session_state.get('_dirty', 0))
    subjects = meta["subjects"]
    years    = meta["years"]
    types    = meta["types"]
    topics   = meta["topics"]
    subtopics = meta["subtopics"]
    f_subject = st.multiselect("科目", subjects)
    f_year    = st.multiselect("年度", years)
    f_type    = st.multiselect("題型", types)
    f_topic   = st.multiselect("主題", topics)
    f_subtopic= st.multiselect("次主題 / 子題", subtopics)
    
search_kw = st.text_input("全文搜尋（題幹/詳解/標籤/來源/選項/主題/科目）")

    
st.markdown("—")
cwo1, cwo2 = st.columns([1,1])
with cwo1:
    wrong_only = st.toggle("只顯示做錯過（>0）", value=False)
with cwo2:
    min_wrong = st.number_input("最低錯誤次數（>=）", min_value=0, max_value=999, value=0, step=1)
# 重新載入選單（強制刷新快取）
    if st.button("🔄 重新載入選單"):
        st.session_state["_dirty"] = st.session_state.get("_dirty", 0) + 1
        st.rerun()

    st.divider()
    st.subheader("**資料清除 / 重置**")
    with st.expander("🧨 危險區（請謹慎操作）", expanded=False):
        mode = st.selectbox("選擇清除範圍", ["—", "清除所有題目＋筆記＋圖片＋註記",
                                          "只清除所有題目的筆記與圖片", "只清除所有題目的顏色/螢光筆/錯誤次數"])
        ok = st.checkbox("我了解此動作不可復原")
        token = st.text_input("輸入大寫：DELETE")
        if st.button("執行清除", disabled=(mode=="—")):
            if not ok or token!="DELETE":
                st.error("未勾選確認或驗證碼錯誤，已取消。")
            else:
                if mode.endswith("筆記＋圖片＋註記"): clear_all("all"); st.success("已清除：題目、筆記、圖片、註記。")
                elif mode.startswith("只清除所有題目的筆記"): clear_all("notes_only"); st.success("已清除：筆記與圖片。")
                else: clear_all("ann_only"); st.success("已清除：顏色/螢光筆/錯誤次數。")

        st.markdown("---")
        if st.button("🧹 刪除資料庫中已存在的重複題（以題幹相同，保留每組最小ID）"):
            ids = find_duplicate_ids_to_delete()
            if not ids:
                st.info("未發現重複題。")
            else:
                n = _delete_ids(ids)
                st.success(f"已刪除 {n} 筆重複題。")
# ---------- MAIN ----------
filters = {"subject": f_subject, "year": f_year, "type": f_type, "topic": f_topic, "subtopic": f_subtopic}
df = query_questions_cached(filters, search_kw, max_rows, wrong_only, int(min_wrong), st.session_state.get('_dirty', 0))

tabs = st.tabs(["**逐題模式**", "**清單（分頁）**", "**卡片（分頁）**", "**進度總覽**", "**手動新增 / 修改**", "**匯出**"])

# ===== 逐題模式 =====
with tabs[0]:
    if df.empty:
        st.info("尚無資料或篩選條件無結果。請先匯入或清除篩選。")
    else:
        if "idx" not in st.session_state: st.session_state.idx = 0
        max_idx = len(df)-1
        c1,c2,c3,c4,c5 = st.columns([1,1,1,1,3])
        if c1.button("⏮ 第一題"): st.session_state.idx = 0
        if c2.button("◀ 上一題"): st.session_state.idx = max(0, st.session_state.idx-1)
        if c3.button("下一題 ▶"): st.session_state.idx = min(max_idx, st.session_state.idx+1)
        if c4.button("⏭ 最後一題"): st.session_state.idx = max_idx
        c5.caption(f"共 {len(df)} 題｜目前第 {st.session_state.idx+1} 題")

        r = df.iloc[st.session_state.idx]
        qid = int(r["id"])
        ann = get_annotations(qid)

wrong = int(ann.get("wrong_count") or 0)
done_state = int(ann.get("done") or 0)
star_state = int(ann.get("star") or 0)
# 顏色與錯誤次數（並排）
ca, cb, cc, cd, ce = st.columns([1.6, 1.0, 1.0, 1.2, 1.2])
with ca:
    color = st.color_picker("題卡顏色（可自訂）", value=ann.get("color") or "#FFFFFF")
with cb:
    st.metric("錯誤次數", wrong)
with cc:
    if st.button("➕ 記一次錯誤", key=f"wc_inc_{qid}"):
        update_annotations(qid, wrong_count=wrong+1)
        st.experimental_rerun()
with cd:
    if st.button("🔁 歸零", key=f"wc_reset_{qid}"):
        update_annotations(qid, wrong_count=0)
        st.experimental_rerun()
with ce:
    if st.button(("✅ 已做過 ✓" if done_state else "✅ 已做過"), key=f"done_{qid}"):
        update_annotations(qid, done=0 if done_state else 1)
        st.experimental_rerun()
    if st.button(("★ 取消收藏" if star_state else "☆ 加入收藏"), key=f"star_{qid}"):
        update_annotations(qid, star=0 if star_state else 1)
        st.experimental_rerun()

kw = st.text_input("螢光筆關鍵字（逗號分隔，可多個）", value=ann.get("highlight_keywords") or "")
cc1,cc2 = st.columns(2)
hl_bg = cc1.color_picker("螢光筆底色", value=ann.get("hl_bg") or "#ffff66")
hl_fg = cc2.color_picker("螢光筆文字顏色", value=ann.get("hl_fg") or "#000000")
update_annotations(qid, color=color, highlight_keywords=kw, hl_bg=hl_bg, hl_fg=hl_fg)

st.markdown(f"<div style='padding:14px;border-radius:12px;background:{color};'><b>#{qid}｜{r.get('subject','')}｜{r.get('year','')}｜{r.get('type','')}｜{r.get('topic','')}｜{(r.get('subtopic','') or '')}｜錯誤次數 {wrong}｜{('已做過' if done_state else '未做')}｜{('★' if star_state else '☆')}</b><div style='margin-top:8px;line-height:1.7;'>{apply_highlight(r.get('stem','') or '', kw, hl_bg, hl_fg)}</div></div>", unsafe_allow_html=True)
# 選項換行修正
opts_html = (r.get('options','') or '').replace('\r\n','\n').replace('\r','\n').replace('\n','<br>')
if opts_html:
    st.markdown(opts_html, unsafe_allow_html=True)

with st.expander("答案 / 詳解", expanded=False):
    st.write(f"**答案：** {r.get('answer','')}")
    st.markdown(apply_highlight(r.get('explanation','') or '', kw, hl_bg, hl_fg), unsafe_allow_html=True)
    st.caption(f"標籤：{r.get('tags','')}")

# ✅ 筆記 / 圖片 區塊
st.subheader("📝 筆記 / 圖片")
existing_note = get_note_text(qid)
with st.form(f"note_form_{qid}"):
    note_text = st.text_area("筆記內容（支援一般文字或簡單 Markdown）", value=existing_note, height=180)
    files = st.file_uploader("上傳圖片（可多選；支援 jpg/png/webp）", type=["jpg","jpeg","png","webp"], accept_multiple_files=True, key=f"u_{qid}")
    caption = st.text_input("圖片說明（可留空）", value="")
    save_btn = st.form_submit_button("儲存筆記 / 上傳圖片")
    if save_btn:
        save_note(qid, note_text)
        if files:
            for f in files:
                add_image(qid, f.read(), f.name, caption)
        st.success("已更新筆記 / 上傳圖片。")
        st.session_state["_dirty"] = st.session_state.get("_dirty", 0) + 1

imgs = list_images(qid)
if not imgs.empty:
    st.caption("已上傳圖片")
    for _, row in imgs.iterrows():
        col1, col2 = st.columns([4,1])
        with col1:
            st.image(row["file_path"], use_container_width=True)
            if row.get("caption"):
                st.caption(row["caption"])
        with col2:
            if st.button("刪除", key=f"delimg_{row['id']}"):
                delete_image(int(row["id"]))
                st.success("圖片已刪除")
                st.experimental_rerun()

# ===== 清單（分頁） =====
with tabs[1]:
    if df.empty:
        st.info("尚無資料或篩選條件無結果。")
    else:
        page_size = st.selectbox("每頁顯示筆數", [20,50,100,200], index=1)
        total = len(df); pages = max(1, math.ceil(total/page_size))
        page = st.number_input("頁碼", 1, pages, 1)
        start = (page-1)*page_size; end = start+page_size
        st.caption(f"共 {total} 筆；第 {page}/{pages} 頁")
        df_page = df.iloc[start:end].copy()

        # 勾選刪除
        df_view = df_page[["id","subject","source","year","type","topic","subtopic","wrong_count","done","star","stem","answer"]].copy()
        df_view.insert(0, "選取", False)
        edited = st.data_editor(
            df_view,
            use_container_width=True,
            hide_index=True,
            column_config={
                "選取": st.column_config.CheckboxColumn("選取", help="勾選要刪除的題目", default=False),
                "id": st.column_config.NumberColumn("id", disabled=True),
                "wrong_count": st.column_config.NumberColumn("錯誤次數", disabled=True),
                "done": st.column_config.NumberColumn("已做過", disabled=True),
                "star": st.column_config.NumberColumn("星號", disabled=True)
            }
        )
        selected_ids = edited.loc[edited["選取"]==True, "id"].astype(int).tolist()

        csel1, csel2 = st.columns([2,3])
        with csel1:
            st.caption(f"已勾選：{len(selected_ids)} 題（ID：{selected_ids[:10]}{'…' if len(selected_ids)>10 else ''}）")
            ok_sel = st.checkbox("我了解此動作不可復原（勾選）")
            tk_sel = st.text_input("輸入 DELETE（勾選）")
            if st.button("🗑 刪除已勾選題目", type="secondary", disabled=(len(selected_ids)==0)):
                if ok_sel and tk_sel=="DELETE":
                    n = _delete_ids(selected_ids)
                    st.success(f"已刪除勾選 {n} 題")
                    st.experimental_rerun()
                else:
                    st.error("未勾選確認或驗證碼錯誤")

        st.markdown("### **批次刪除**")
        cL, cR = st.columns(2)
        with cL:
            okp = st.checkbox("我了解此動作不可復原（本頁）")
            tkp = st.text_input("輸入 DELETE（本頁）")
            if st.button("刪除本頁題目"):
                if okp and tkp=="DELETE":
                    n = _delete_ids(list(map(int, df_page["id"].tolist())))
                    st.success(f"已刪除本頁 {n} 題。請重新整理或切換頁碼。")
                else:
                    st.error("未勾選確認或驗證碼錯誤")
        with cR:
            oka = st.checkbox("我了解此動作不可復原（全部）")
            tka = st.text_input("輸入 DELETE（全部）")
            if st.button("刪除目前篩選的全部題目", type="primary"):
                if oka and tka=="DELETE":
                    n = _delete_ids(list(map(int, df["id"].tolist())))
                    st.success(f"已刪除當前篩選的全部 {n} 題。")
                else:
                    st.error("未勾選確認或驗證碼錯誤")

# ===== 卡片（分頁） =====
with tabs[2]:
    if df.empty:
        st.info("尚無資料或篩選條件無結果。")
    else:
        page_size = st.selectbox("每頁顯示張數", [10,20,50], index=0, key="ps_card")
        total = len(df); pages = max(1, math.ceil(total/page_size))
        page = st.number_input("頁碼（卡片）", 1, pages, 1, key="pg_card")
        start = (page-1)*page_size; end = start+page_size
        st.caption(f"共 {total} 題；第 {page}/{pages} 頁")
        for _, r in df.iloc[start:end].iterrows():
            qid = int(r["id"])
            with st.container(border=True):
                st.markdown(f"**#{qid}｜{r.get('subject','')}｜{r.get('year','')}｜{r.get('type','')}｜{r.get('topic','')}｜{r.get('subtopic','')}｜錯誤次數 {int(r.get('wrong_count',0) or 0)}｜{'已做過' if int(r.get('done',0) or 0) else '未做'}｜{'★' if int(r.get('star',0) or 0) else '☆'}**")
                st.markdown(r.get('stem','') or '', unsafe_allow_html=True)
                # 選項換行修正
                opts_html = (r.get('options','') or '').replace('\r\n','\n').replace('\r','\n').replace('\n','<br>')
                if opts_html:
                    st.markdown(opts_html, unsafe_allow_html=True)
                cols = st.columns([1.2, 3.8, 1.4, 1.2])
                cols[0].write(f"**答案：** {r.get('answer','')}")
                cols[1].markdown(r.get("explanation","") or "", unsafe_allow_html=True)
                cols[2].write(f"**標籤：** {r.get('tags','')}")
                note_txt = get_note_text(qid)
                if note_txt:
                    cols[3].markdown(f"**筆記：** {note_txt[:120]}{'…' if len(note_txt)>120 else ''}")
                img_df = list_images(qid)
                if not img_df.empty:
                    st.caption("已上傳圖片（縮圖）")
                    tcols = st.columns(min(3, len(img_df)))
                    for i, (_, rr) in enumerate(img_df.head(3).iterrows()):
                        with tcols[i % len(tcols)]:
                            st.image(rr["file_path"], use_container_width=True)


with tabs[3]:
    if df.empty:
        st.info("目前沒有符合條件的題目。")
    else:
        c1, c2, c3 = st.columns(3)
        with c1:
            st.subheader("✅ 已做過")
            d1 = df[df["done"]>0][["id","subject","year","type","topic","subtopic","wrong_count"]]
            st.write(f"共 {len(d1)} 題")
            st.dataframe(d1, use_container_width=True, hide_index=True)
        with c2:
            st.subheader("❌ 做錯過（>0）")
            d2 = df[df["wrong_count"]>0][["id","subject","year","type","topic","subtopic","wrong_count"]]
            st.write(f"共 {len(d2)} 題")
            st.dataframe(d2, use_container_width=True, hide_index=True)
        with c3:
            st.subheader("★ 已加星")
            d3 = df[df["star"]>0][["id","subject","year","type","topic","subtopic","wrong_count"]]
            st.write(f"共 {len(d3)} 題")
            st.dataframe(d3, use_container_width=True, hide_index=True)

# ===== 手動新增 / 修改 =====
with tabs[3]:
    st.caption("一次新增一題，或編輯現有題目後儲存變更。")
    mode = st.radio("模式", ["新增一題", "修改現有題目"], horizontal=True)
    if mode == "新增一題":
        with st.form("add_one"):
            c1,c2,c3,c4 = st.columns(4)
            subject = c1.text_input("科目", "")
            year    = c2.text_input("年度", "")
            qtype   = c3.text_input("題型", "")
            topic   = c4.text_input("主題", "")
            subtopic= st.text_input("子題 / 次主題", "")
            stem    = st.text_area("題幹（可含 HTML 標籤）")
            options = st.text_area("選項（A) … 請以換行分隔，或直接貼入含 <span> 的 HTML）")
            answer  = st.text_input("答案（A/B/C/D 或自由文字）")
            explanation = st.text_area("詳解 / 參考（可含 HTML）")
            tags    = st.text_input("標籤（逗號分隔）", "")
            ok = st.form_submit_button("新增")
            if ok:
                df_new = pd.DataFrame([{
                    "subject":subject,"source":"manual","year":year,"type":qtype,
                    "topic":topic,"subtopic":subtopic,"stem":stem,"options":options,
                    "answer":answer,"explanation":explanation,"tags":tags
                }])
                insert_questions(df_new)
                st.success("已新增")
    else:
        if df.empty:
            st.info("目前無題目可修改。")
        else:
            id_list = df["id"].astype(int).tolist()
            sel_id = st.selectbox("選擇題目 ID", id_list)
            cur_row = df[df["id"]==sel_id].iloc[0].to_dict()
            with st.form("edit_one"):
                c1,c2,c3,c4 = st.columns(4)
                subject = c1.text_input("科目", cur_row.get("subject",""))
                year    = c2.text_input("年度", cur_row.get("year",""))
                qtype   = c3.text_input("題型", cur_row.get("type",""))
                topic   = c4.text_input("主題", cur_row.get("topic",""))
                subtopic= st.text_input("子題 / 次主題", cur_row.get("subtopic",""))
                stem    = st.text_area("題幹（可含 HTML 標籤）", cur_row.get("stem",""), height=180)
                options = st.text_area("選項（A) … 或含 HTML）", cur_row.get("options",""), height=180)
                answer  = st.text_input("答案（A/B/C/D 或自由文字）", cur_row.get("answer",""))
                explanation = st.text_area("詳解 / 參考（可含 HTML）", cur_row.get("explanation",""), height=160)
                tags    = st.text_input("標籤（逗號分隔）", cur_row.get("tags",""))
                ok = st.form_submit_button("儲存修改")
                if ok:
                    update_question_row(int(sel_id), {
                        "subject":subject,"source":cur_row.get("source","manual"),"year":year,"type":qtype,
                        "topic":topic,"subtopic":subtopic,"stem":stem,"options":options,
                        "answer":answer,"explanation":explanation,"tags":tags
                    })
                    st.success(f"題目 #{sel_id} 已更新")

# ===== 匯出 =====
with tabs[4]:
    st.caption("將當前篩選＋搜尋結果導出為 CSV。")
    if st.button("匯出 CSV"):
        if df.empty:
            st.warning("沒有可匯出的內容。")
        else:
            out = df.to_csv(index=False).encode("utf-8-sig")
            st.download_button("下載 CSV", out, file_name=f"exam_export_{datetime.now().strftime('%Y%m%d_%H%M')}.csv", mime="text/csv")

st.caption("build v2.0 — notes & images restored, options newline fixed, list select-delete")