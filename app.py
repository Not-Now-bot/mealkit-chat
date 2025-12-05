import streamlit as st
import google.generativeai as genai
from google.generativeai.types import GenerationConfig, HarmCategory, HarmBlockThreshold
import json
import os
import time
import gspread
from oauth2client.service_account import ServiceAccountCredentials

# ==========================================
# 0. 설정 및 보안 (Password)
# ==========================================
st.set_page_config(page_title="Eternal Memory Chat", layout="wide")

def check_password():
    if "PASSWORD" not in st.secrets["general"]:
        st.error("Secrets에 PASSWORD가 없습니다.")
        return False
    def password_entered():
        if st.session_state["password"] == st.secrets["general"]["PASSWORD"]:
            st.session_state["password_correct"] = True
            del st.session_state["password"]
        else:
            st.session_state["password_correct"] = False
    if "password_correct" not in st.session_state:
        st.text_input("🔒 비밀번호", type="password", on_change=password_entered, key="password")
        return False
    elif not st.session_state["password_correct"]:
        st.text_input("🔒 비밀번호", type="password", on_change=password_entered, key="password")
        st.error("비밀번호 불일치")
        return False
    return True

if not check_password(): st.stop()

# ==========================================
# [중요] 넷플릭스 스타일 프로필 선택 (Landing Page)
# ==========================================
if "current_profile_key" not in st.session_state:
    st.title("👋 누가 접속하셨나요?")
    st.markdown("사용자를 선택하면 **각자의 마지막 상태**를 불러옵니다.")
    st.divider()

    col1, col2, col3 = st.columns(3)
    
    with col1:
        if st.button("👑 지수", type="primary", use_container_width=True):
            st.session_state["current_profile_key"] = "config_master.json"
            st.rerun()
            
    with col2:
        if st.button("🔥 혜령", type="primary", use_container_width=True):
            st.session_state["current_profile_key"] = "config_friend.json"
            st.rerun()
            
    with col3:
        if st.button("🎈 게스트", use_container_width=True):
            st.session_state["current_profile_key"] = "config_guest.json"
            st.rerun()
            
    st.stop() # 프로필 선택 전에는 아래 코드 실행 안 함

# ==========================================
# API 및 DB 연결
# ==========================================
try:
    genai.configure(api_key=st.secrets["general"]["GOOGLE_API_KEY"])
except:
    st.error("Secrets 키 오류"); st.stop()

@st.cache_resource
def init_sheet_connection():
    scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
    creds_dict = json.loads(st.secrets["gcp"]["info"], strict=False)
    creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
    client = gspread.authorize(creds)
    sheet_id = st.secrets["general"]["SHEET_ID"]
    return client.open_by_key(sheet_id).sheet1

try:
    SHEET = init_sheet_connection()
except Exception as e:
    st.error(f"구글 시트 연결 실패!\n{e}"); st.stop()

# ==========================================
# Data Handler (Chunk saving)
# ==========================================
CHUNK_SIZE = 40000 

def load_json(folder, filename):
    full_key = f"{folder}/{filename}"
    try:
        cell = SHEET.find(full_key, in_column=1)
        if cell:
            row_values = SHEET.row_values(cell.row)
            if len(row_values) > 1:
                return json.loads("".join(row_values[1:]))
    except: pass
    return {}

def save_json(folder, filename, data):
    full_key = f"{folder}/{filename}"
    try:
        data_str = json.dumps(data, ensure_ascii=False)
        chunks = [data_str[i:i+CHUNK_SIZE] for i in range(0, len(data_str), CHUNK_SIZE)]
        row_data = [full_key] + chunks
        cell = SHEET.find(full_key, in_column=1)
        if cell:
            if len(row_data) > SHEET.col_count: SHEET.resize(cols=len(row_data) + 5)
            SHEET.update(range_name=f"A{cell.row}", values=[row_data])
        else:
            SHEET.append_row(row_data)
    except Exception as e:
        print(f"Save Error: {e}")

def delete_json(folder, filename):
    full_key = f"{folder}/{filename}"
    try:
        cell = SHEET.find(full_key, in_column=1)
        if cell: SHEET.delete_rows(cell.row); return True
    except: pass
    return False

# ==========================================
# [NEW] Config Manager (프로필별 분리)
# ==========================================
CONFIG_FILE = st.session_state["current_profile_key"] # 선택한 프로필 파일명

DEFAULT_CONFIG = {  
    "chat_model": "models/gemini-1.5-pro",  
    "last_user_id": "default",  
    "last_char_id": ""  
}

def load_config():
    # 이제 main.json이 아니라 master.json / friend.json 등을 부름
    data = load_json("config", CONFIG_FILE)
    return data if data else DEFAULT_CONFIG

def update_config(key, value):
    curr = load_config()
    curr[key] = value
    save_json("config", CONFIG_FILE, curr)

# ==========================================
# Session & Data Loaders
# ==========================================
def get_session_meta(char_id):
    # 세션 목록은 캐릭터에 종속되므로 공유함 (session_meta/{char_id}.json)
    # 하지만 '마지막 사용 세션'은 사람마다 다를 수 있으므로 config에 저장해야 더 완벽하지만
    # 구조상 복잡해지므로 일단 세션 목록은 공유, '선택'은 각자 함.
    meta = load_json("session_meta", f"{char_id}.json")
    if not meta: return {"sessions": ["Default"], "last_used": "Default"}
    return meta

def save_session_meta(char_id, meta):
    save_json("session_meta", f"{char_id}.json", meta)

def create_new_session(char_id, simple_name):
    meta = get_session_meta(char_id)
    if simple_name in meta["sessions"]: return False
    meta["sessions"].append(simple_name)
    save_session_meta(char_id, meta)
    return True

def delete_session(char_id, simple_name):
    meta = get_session_meta(char_id)
    if simple_name in meta["sessions"]:
        meta["sessions"].remove(simple_name)
        real_filename = f"{char_id}__{simple_name}.json"
        delete_json("history", real_filename)
        if not meta["sessions"]: meta["sessions"] = ["Default"]
        save_session_meta(char_id, meta)
        return True
    return False

def get_all_data_optimized():
    try: return SHEET.get_all_values() 
    except: return []

def load_characters():
    rows = get_all_data_optimized()
    db = {}
    for r in rows:
        if not r: continue
        fname = r[0]
        if fname.startswith('characters/') and fname.endswith('.json'):
            cid = fname.split('/')[-1].replace('.json', '')
            try:
                full = "".join(r[1:]) 
                if not full: continue
                data = json.loads(full)
                for k in ["name","description","system_prompt","first_message"]: data.setdefault(k,"")
                data.setdefault("lorebooks", [])
                db[cid] = data
            except: pass
    return db

def load_users():
    rows = get_all_data_optimized()
    db = {}
    for r in rows:
        if not r: continue
        fname = r[0]
        if fname.startswith('users/') and fname.endswith('.json'):
            uid = fname.split('/')[-1].replace('.json', '')
            try: 
                full = "".join(r[1:])
                db[uid] = json.loads(full)
            except: pass
    if not db:
        def_u = {"name": "User", "gender": "?", "age": "?", "profile": "Traveler"}
        db["default"] = def_u
    return db

def load_memory(char_id):
    mem = load_json("memory", f"{char_id}.json")
    return mem if mem else {"summary": "기록 없음", "recent_event": "", "location": "알 수 없음"}

def load_user_note(char_id): return load_json("usernotes", f"{char_id}.json").get("content", "")
def save_user_note(char_id, content): save_json("usernotes", f"{char_id}.json", {"content": content})

# LLM Functions
def trigger_lorebooks(text, lorebooks):
    act = []
    text = text.lower()
    for b in lorebooks:
        tags = [t.strip().lower() for t in b.get("tags", "").split(",") if t.strip()]
        for tag in tags:
            if tag in text: act.append(b.get("content", "")); break
    return "\n[Active Lorebook]\n" + "\n".join(act[:5]) + "\n" if act else ""

def generate_response(chat_model_id, c_char, c_user, mem, history, user_note):
    chat_model = genai.GenerativeModel(chat_model_id)
    gen_config = GenerationConfig(temperature=1.0, top_p=0.95, max_output_tokens=8192)
    safety = {HarmCategory.HARM_CATEGORY_HARASSMENT: HarmBlockThreshold.BLOCK_NONE, HarmCategory.HARM_CATEGORY_HATE_SPEECH: HarmBlockThreshold.BLOCK_NONE, HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT: HarmBlockThreshold.BLOCK_NONE, HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT: HarmBlockThreshold.BLOCK_NONE}
    
    recent = history[-1]['content'] if history and history[-1]['role'] == 'user' else ""
    ctx = "\n".join([m['content'] for m in history[-5:]])
    active_lore = trigger_lorebooks(ctx + recent, c_char.get("lorebooks", []))
    
    sys = f"""
    [Roleplay]
    Target: {c_char['name']} ({c_char['description']})
    System: {c_char['system_prompt']}
    User: {c_user['name']} ({c_user.get('gender')}, {c_user.get('age')}) - {c_user.get('profile')}
    User Note: {user_note}
    Memory: {mem.get('summary')}
    Recent: {mem.get('recent_event')}
    {active_lore}
    """
    full = f"System: {sys}\n" + "\n".join([f"{m['role']}: {m['content']}" for m in history])
    return chat_model.generate_content(full, generation_config=gen_config, safety_settings=safety).text

# ==========================================
# Main App UI
# ==========================================
try:
    CHARACTER_DB = load_characters()
    USER_DB = load_users()
    current_config = load_config()
except Exception as e:
    st.error(f"데이터 로드 실패: {e}"); st.stop()

with st.sidebar:
    # 프로필 변경 버튼 (로그아웃 개념)
    col_home, col_txt = st.columns([1, 4])
    if col_home.button("🏠", help="프로필 변경"):
        del st.session_state["current_profile_key"]
        st.rerun()
        
    p_name = "나 (Master)" if "master" in CONFIG_FILE else ("친구" if "friend" in CONFIG_FILE else "게스트")
    col_txt.markdown(f"**{p_name}** 접속 중")
    st.divider()
    
    # 모델 선택
    try: av_models = [m.name for m in genai.list_models() if 'generateContent' in m.supported_generation_methods]; av_models.sort()
    except: av_models = ["models/gemini-1.5-flash"]
    try: ic = av_models.index(current_config.get("chat_model"))
    except: ic = 0
    chat_model_id = st.selectbox("모델", av_models, index=ic)
    if chat_model_id != current_config.get("chat_model"):
        update_config("chat_model", chat_model_id); st.rerun()
        
    st.divider()

    # 1. 캐릭터 선택
    if CHARACTER_DB:
        char_options = list(CHARACTER_DB.keys())
        saved_cid = current_config.get("last_char_id", "")
        if saved_cid not in char_options: saved_cid = char_options[0]
        try: default_cid_idx = char_options.index(saved_cid)
        except: default_cid_idx = 0
        sel_cid = st.selectbox("🤖 캐릭터", char_options, index=default_cid_idx, format_func=lambda x: CHARACTER_DB[x]["name"])
        if sel_cid != current_config.get("last_char_id", ""): update_config("last_char_id", sel_cid); st.rerun()  
        curr_char = CHARACTER_DB[sel_cid]
    else:
        curr_char = None; sel_cid = None

    # 2. 세션(대화방) 로직 - 프로필별로 마지막 방 기억
    current_session = "Default"
    if curr_char:
        s_meta = get_session_meta(sel_cid)
        s_list = s_meta["sessions"]
        # 프로필별로 '이 캐릭터의 마지막 세션'을 config에 저장하면 좋겠지만, 
        # 복잡도 줄이기 위해: config에 {cid}_last_session 키로 저장 시도
        last_s_key = f"{sel_cid}_last_session"
        last_s = current_config.get(last_s_key, "Default")
        if last_s not in s_list: last_s = s_list[0]
        
        with st.expander(f"📂 대화방: {last_s}", expanded=False):
            try: s_idx = s_list.index(last_s)
            except: s_idx = 0
            sel_session = st.selectbox("목록", s_list, index=s_idx, key="sess_sel")
            
            if sel_session != last_s:
                update_config(last_s_key, sel_session) # 프로필 config에 저장
                st.rerun()
            current_session = sel_session
            
            new_s = st.text_input("새 대화방 이름", key="n_s")
            if st.button("추가"):
                if new_s and create_new_session(sel_cid, new_s): 
                    update_config(last_s_key, new_s); st.rerun()
            
            if len(s_list)>1 and st.button("삭제", type="primary"):
                delete_session(sel_cid, current_session)
                # 삭제 후 첫번째로 이동
                update_config(last_s_key, s_list[0] if s_list[0]!=current_session else s_list[1])
                st.rerun()

    # 3. 유저 페르소나
    user_options = list(USER_DB.keys())
    saved_uid = current_config.get("last_user_id", "")
    if saved_uid not in user_options and user_options: saved_uid = user_options[0]
    if user_options:
        try: ui = user_options.index(saved_uid)
        except: ui = 0
        sel_uid = st.selectbox("👤 페르소나", user_options, index=ui, format_func=lambda x: USER_DB[x]["name"])
        if sel_uid != current_config.get("last_user_id", ""): update_config("last_user_id", sel_uid); st.rerun()
        curr_user = USER_DB[sel_uid]
    else:
        curr_user = {"name": "User", "gender": "?", "age": "?", "profile": "New Traveler"}
        sel_uid = "default"
        
    st.divider()
    if st.button("🔄 새로고침"): st.rerun()

# 탭 구성
tab1, tab2, tab3 = st.tabs([f"💬 대화 ({current_session})", "🧠 기억", "✏️ 스튜디오"])

if sel_cid:
    # 세션별 파일 로드
    real_filename = f"{sel_cid}__{current_session}.json"
    sess_key = f"hist_{sel_cid}_{current_session}"
    
    if sess_key not in st.session_state:
        hf = load_json("history", real_filename)
        if not hf and curr_char.get("first_message"):
            hf = [{"role": "assistant", "content": curr_char["first_message"]}]
            save_json("history", real_filename, hf)
        st.session_state[sess_key] = hf if hf else []
    
    mem_data = load_memory(sel_cid)
    u_note = load_user_note(sel_cid)

    with tab1:
        # 메시지 렌더링
        h_len = len(st.session_state[sess_key])
        for idx, m in enumerate(st.session_state[sess_key]):
            with st.chat_message(m["role"]):
                # 수정 모드
                if st.session_state.get(f"em_{sess_key}") == idx:
                    nw = st.text_area("수정", m["content"], key=f"t_{idx}")
                    c1, c2 = st.columns([1,4])
                    if c1.button("저장", key=f"s_{idx}"):
                        st.session_state[sess_key][idx]["content"] = nw
                        save_json("history", real_filename, st.session_state[sess_key])
                        st.session_state[f"em_{sess_key}"] = -1
                        st.rerun()
                    if c2.button("취소", key=f"c_{idx}"):
                        st.session_state[f"em_{sess_key}"] = -1
                        st.rerun()
                # 일반 모드
                else:
                    st.markdown(m["content"])
                    with st.popover("⋮"):
                        if st.button("✏️ 수정", key=f"e_{idx}", use_container_width=True):
                            st.session_state[f"em_{sess_key}"] = idx; st.rerun()
                        if st.button("🗑️ 삭제", key=f"d_{idx}", use_container_width=True):
                            del st.session_state[sess_key][idx]
                            save_json("history", real_filename, st.session_state[sess_key])
                            st.rerun()
                        # 마지막 봇 재생성
                        if m["role"] == "assistant" and idx == h_len - 1:
                            if st.button("🔄 재생성", key=f"r_{idx}", use_container_width=True):
                                del st.session_state[sess_key][idx]
                                with st.spinner("..."):
                                    r = generate_response(chat_model_id, curr_char, curr_user, mem_data, st.session_state[sess_key], u_note)
                                    st.session_state[sess_key].append({"role":"assistant", "content":r})
                                    save_json("history", real_filename, st.session_state[sess_key])
                                    st.rerun()
        
        # 끊김 방지 (Retry)
        if st.session_state[sess_key] and st.session_state[sess_key][-1]["role"] == "user":
            if st.button("🔄 답변 이어서 받기"):
                with st.spinner("..."):
                    r = generate_response(chat_model_id, curr_char, curr_user, mem_data, st.session_state[sess_key], u_note)
                    st.session_state[sess_key].append({"role":"assistant", "content":r})
                    save_json("history", real_filename, st.session_state[sess_key]); st.rerun()

        # 입력
        if p := st.chat_input("메시지..."):
            st.session_state[sess_key].append({"role":"user", "content":p})
            save_json("history", real_filename, st.session_state[sess_key])
            try:
                r = generate_response(chat_model_id, curr_char, curr_user, mem_data, st.session_state[sess_key], u_note)
                st.session_state[sess_key].append({"role":"assistant", "content":r})
                save_json("history", real_filename, st.session_state[sess_key]); st.rerun()
            except Exception as e: st.error(f"Error: {e}")

    with tab2:
        st.json(mem_data)
        st.text_area("노트", value=u_note, key="un")
        if st.button("노트 저장"): save_user_note(sel_cid, st.session_state["un"]); st.success("OK")
        if st.button("대화만 초기화"):
            st.session_state[sess_key] = []
            save_json("history", real_filename, []); st.rerun()

    with tab3:
        # 스튜디오 (캐릭터/페르소나)
        c1, c2 = st.columns(2)
        with c1:
            st.subheader("🤖 캐릭터")
            m_c = st.radio("모드", ["수정", "생성"], key="mc", horizontal=True)
            if m_c=="수정" and curr_char:
                cid, cnm, cds, cmsg, csys = sel_cid, curr_char['name'], curr_char['description'], curr_char['first_message'], curr_char['system_prompt']
                dis=True
            else:
                cid, cnm, cds, cmsg, csys = "", "", "", "", ""
                dis=False
            
            ncid = st.text_input("ID", cid, disabled=dis)
            ncnm = st.text_input("이름", cnm)
            ncds = st.text_area("설명", cds)
            nmsg = st.text_area("첫대사", cmsg)
            nsys = st.text_area("프롬프트", csys)
            if st.button("캐릭터 저장"):
                if ncid:
                    save_json("characters", f"{ncid}.json", {"name":ncnm, "description":ncds, "first_message":nmsg, "system_prompt":nsys, "lorebooks":[]})
                    st.success("저장됨"); time.sleep(0.5); st.rerun()
            if m_c=="수정" and st.button("삭제", type="primary"):
                 delete_json("characters", f"{sel_cid}.json"); st.rerun()
                 
        with c2:
            st.subheader("👤 페르소나")
            m_u = st.radio("모드", ["수정", "생성"], key="mu", horizontal=True)
            if m_u=="수정" and curr_user:
                uid, unm, ugen, uage, uprof = sel_uid, curr_user.get('name',''), curr_user.get('gender',''), curr_user.get('age',''), curr_user.get('profile','')
                dis_u=True
            else:
                uid, unm, ugen, uage, uprof = "", "", "", "", ""
                dis_u=False
                
            nuid = st.text_input("User ID", uid, disabled=dis_u)
            nunm = st.text_input("Name", unm)
            nugen = st.text_input("Gender", ugen)
            nuage = st.text_input("Age", uage)
            nuprof = st.text_area("Profile", uprof)
            
            if st.button("페르소나 저장"):
                if nuid:
                    save_json("users", f"{nuid}.json", {"name":nunm, "gender":nugen, "age":nuage, "profile":nuprof})
                    st.success("저장됨"); time.sleep(0.5); st.rerun()
            if m_u=="수정" and sel_uid!="default" and st.button("삭제", type="primary"):
                delete_json("users", f"{sel_uid}.json"); st.rerun()

else:
    with tab3:
        st.info("첫 캐릭터를 만드세요.")
        ni = st.text_input("ID"); nn = st.text_input("Name")
        if st.button("Create"): save_json("characters", f"{ni}.json", {"name":nn}); st.rerun()


