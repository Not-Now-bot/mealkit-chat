import streamlit as st
import google.generativeai as genai
from google.generativeai.types import GenerationConfig, HarmCategory, HarmBlockThreshold
import json
import os
import time
import gspread
from oauth2client.service_account import ServiceAccountCredentials

# ==========================================
# 0. 초기 설정 및 보안 검사
# ==========================================
st.set_page_config(page_title="Eternal Memory Chat", layout="wide")

# [보안 1] 비밀번호 확인
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

# [보안 2] API 키 설정
try:
    genai.configure(api_key=st.secrets["general"]["GOOGLE_API_KEY"])
except:
    st.error("Secrets에 GOOGLE_API_KEY가 없습니다."); st.stop()

# ==========================================
# [핵심] 구글 시트 데이터베이스 연결 (DB)
# ==========================================
@st.cache_resource
def init_sheet_connection():
    scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
    # Secrets에 저장된 JSON 문자열을 파싱
    creds_dict = json.loads(st.secrets["gcp"]["info"], strict=False)
    creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
    client = gspread.authorize(creds)
    # 시트 열기
    sheet_id = st.secrets["general"]["SHEET_ID"]
    return client.open_by_key(sheet_id).sheet1

try:
    SHEET = init_sheet_connection()
except Exception as e:
    st.error(f"구글 시트 연결 실패! Secrets 설정을 확인하세요.\n에러: {e}")
    st.stop()

# ==========================================
# [개조됨] Save/Load 함수 (파일 -> 구글시트)
# ==========================================
# 시트 구조: A열(Filename), B열(JSON Content)
# 로컬 파일 시스템을 흉내내지만 실제로는 시트를 읽고 씁니다.

def get_all_data():
    """시트의 모든 데이터를 가져옵니다 (캐싱 고려 안함, 실시간성 중요)"""
    try:
        return SHEET.get_all_records() # [{'filename':..., 'content':...}, ...]
    except:
        # 헤더가 없을 경우 초기화
        SHEET.update_cell(1, 1, "filename")
        SHEET.update_cell(1, 2, "content")
        return []

def load_json(folder, filename):
    # folder는 구분용 접두어로 사용 (예: "characters/amy.json")
    full_key = f"{folder}/{filename}"
    try:
        cell = SHEET.find(full_key, in_column=1)
        if cell:
            content_str = SHEET.cell(cell.row, 2).value
            return json.loads(content_str)
    except: pass
    return {}

def save_json(folder, filename, data):
    full_key = f"{folder}/{filename}"
    data_str = json.dumps(data, ensure_ascii=False)
    
    try:
        try:
            cell = SHEET.find(full_key, in_column=1)
            # 이미 있으면 업데이트
            SHEET.update_cell(cell.row, 2, data_str)
        except gspread.exceptions.CellNotFound:
            # 없으면 새로 추가
            SHEET.append_row([full_key, data_str])
    except Exception as e:
        st.toast(f"저장 실패(네트워크 오류?): {e}")

# (주의) delete, listdir 등은 시트 방식에 맞게 흉내내야 합니다.
# 이번 버전에서는 복잡성을 줄이기 위해 일부 기능(삭제, 이미지 업로드)은 제한하거나 단순화합니다.
# 이미지는 웹호스팅이 아니므로 업로드 기능이 동작하지 않습니다 (외부 URL 사용 권장).

# ==========================================
# 1. 설정 및 상수
# ==========================================
DEFAULT_CONFIG = {  
    "chat_model": "models/gemini-1.5-pro",  
    "memory_model": "models/gemini-1.5-flash",  
    "memory_level": "Standard (10,000자)",  
    "temperature": 1.0,    
    "top_p": 0.95,         
    "max_tokens": 8192,  
    "last_user_id": "default",  
    "last_char_id": ""  
}
MEMORY_LEVELS = {"Lite (5k)": 5000, "Standard (10k)": 10000, "Heavy (50k)": 50000}

def load_config():
    data = load_json("config", "main.json")
    if not data: return DEFAULT_CONFIG
    return data

def update_config(key, value):
    curr = load_config()
    curr[key] = value
    save_json("config", "main.json", curr)

def save_advanced_config(chat, mem, lev, temp, top, tok):
    curr = load_config()
    curr.update({"chat_model":chat, "memory_model":mem, "memory_level":lev, 
                 "temperature":temp, "top_p":top, "max_tokens":tok})
    save_json("config", "main.json", curr)

# ==========================================
# 데이터 로더 (시트 기반)
# ==========================================
def load_characters():
    # 시트 전체를 뒤져서 'characters/'로 시작하는 것들을 찾음
    records = get_all_data() # [{'filename':'characters/abc.json', ...}]
    db = {}
    for r in records:
        fname = r.get('filename', '')
        if fname.startswith('characters/') and fname.endswith('.json'):
            cid = fname.split('/')[-1].replace('.json', '')
            try:
                data = json.loads(r.get('content', '{}'))
                # 기본값 채우기
                for k in ["name","description","system_prompt","first_message","image"]: data.setdefault(k,"")
                data.setdefault("lorebooks", [])
                db[cid] = data
            except: pass
    return db

def load_users():
    records = get_all_data()
    db = {}
    for r in records:
        fname = r.get('filename', '')
        if fname.startswith('users/') and fname.endswith('.json'):
            uid = fname.split('/')[-1].replace('.json', '')
            try: db[uid] = json.loads(r.get('content', '{}'))
            except: pass
            
    if not db:
        def_u = {"name": "User", "gender": "?", "age": "?", "profile": "Traveler"}
        save_json("users", "default.json", def_u)
        db["default"] = def_u
    return db

def load_memory(char_id):
    mem = load_json("memory", f"{char_id}.json")
    if not mem: return {"summary": "기록 없음", "recent_event": "", "location": "알 수 없음", "relations": ""}
    return mem

def load_user_note(char_id): return load_json("usernotes", f"{char_id}.json").get("content", "")
def save_user_note(char_id, content): save_json("usernotes", f"{char_id}.json", {"content": content})

# 로직 함수들
def trigger_lorebooks(text, lorebooks):
    act = []
    text = text.lower()
    for b in lorebooks:
        tags = [t.strip().lower() for t in b.get("tags", "").split(",") if t.strip()]
        for tag in tags:
            if tag in text: act.append(b.get("content", "")); break
    return "\n[Active Lorebook]\n" + "\n".join(act[:5]) + "\n" if act else ""

def get_safety_settings():
    return {HarmCategory.HARM_CATEGORY_HARASSMENT: HarmBlockThreshold.BLOCK_NONE, HarmCategory.HARM_CATEGORY_HATE_SPEECH: HarmBlockThreshold.BLOCK_NONE, HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT: HarmBlockThreshold.BLOCK_NONE, HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT: HarmBlockThreshold.BLOCK_NONE}

def generate_response(chat_model_id, prompt_temp, c_char, c_user, mem, lore, history, user_note, temperature, top_p, max_tokens):
    chat_model = genai.GenerativeModel(chat_model_id)
    gen_config = GenerationConfig(temperature=temperature, top_p=top_p, max_output_tokens=max_tokens)
    safety = get_safety_settings()
    recent = history[-1]['content'] if history and history[-1]['role'] == 'user' else ""
    ctx = "\n".join([m['content'] for m in history[-5:]])
    active_lore = trigger_lorebooks(ctx + recent, c_char.get("lorebooks", []))
    sys = f"""{prompt_temp}
    [Target] {c_char['name']}: {c_char['description']}
    [System] {c_char['system_prompt']}
    [User] {c_user['name']} / {c_user.get('gender')} / {c_user.get('age')} / {c_user.get('profile')}
    [User Note] {user_note}
    [Memory] {mem.get('summary')} / {mem.get('location')} / {mem.get('relations')}
    {mem.get('recent_event')}
    {active_lore}"""
    full = f"System: {sys}\n" + "\n".join([f"{m['role']}: {m['content']}" for m in history])
    return chat_model.generate_content(full, generation_config=gen_config, safety_settings=safety).text

# ==========================================
# 메인 UI
# ==========================================
# 데이터 로드
CHARACTER_DB = load_characters()
USER_DB = load_users()
current_config = load_config()

with st.sidebar:
    st.title("☁️ 클라우드 메모리 챗봇")
    st.caption("Google Sheets와 연동되어 기억이 영원히 저장됩니다.")
    
    # 모델 설정
    try: av_models = [m.name for m in genai.list_models() if 'generateContent' in m.supported_generation_methods]; av_models.sort()
    except: av_models = ["models/gemini-1.5-flash"]
    
    try: ic = av_models.index(current_config.get("chat_model"))
    except: ic = 0
    chat_model_id = st.selectbox("모델", av_models, index=ic)
    
    if chat_model_id != current_config.get("chat_model"):
        save_advanced_config(chat_model_id, current_config.get("memory_model", av_models[0]), "Standard", 1.0, 0.95, 8192)
        st.rerun()

    st.divider()
    
    # 캐릭터 선택
    if CHARACTER_DB:
        char_options = list(CHARACTER_DB.keys())
        saved_cid = current_config.get("last_char_id", "")
        try: default_cid_idx = char_options.index(saved_cid)
        except: default_cid_idx = 0
        
        sel_cid = st.selectbox("🤖 캐릭터", char_options, index=default_cid_idx, format_func=lambda x: CHARACTER_DB[x]["name"])
        
        if sel_cid != saved_cid:
            update_config("last_char_id", sel_cid); st.rerun()
            
        curr_char = CHARACTER_DB[sel_cid]
    else:
        st.info("캐릭터가 없습니다. 스튜디오 탭에서 생성하세요.")
        curr_char = None
        sel_cid = None

    # 유저 선택
    user_options = list(USER_DB.keys())
    saved_uid = current_config.get("last_user_id", "")
    try: ui = user_options.index(saved_uid)
    except: ui = 0
    sel_uid = st.selectbox("👤 유저", user_options, index=ui, format_func=lambda x: USER_DB[x]["name"])
    if sel_uid != saved_uid: update_config("last_user_id", sel_uid); st.rerun()
    curr_user = USER_DB[sel_uid]
    
    st.divider()
    if st.button("🔄 새로고침 (데이터 동기화)"): st.rerun()

# 탭 구성
tab1, tab2, tab3 = st.tabs(["💬 대화", "🧠 기억", "✏️ 스튜디오"])

if sel_cid:
    sess_key = f"hist_{sel_cid}"
    # 히스토리는 너무 길 수 있으니 로컬 세션우선 + 필요시 로드
    # 여기서는 매번 로드 (안전성)
    hf = load_json("history", f"{sel_cid}.json")
    if not hf: hf = []
    st.session_state[sess_key] = hf
    
    mem_data = load_memory(sel_cid)
    u_note = load_user_note(sel_cid)

    with tab1:
        # 채팅 UI
        for m in st.session_state[sess_key]:
            with st.chat_message(m["role"]): st.markdown(m["content"])
        
        if p := st.chat_input("메시지 입력..."):
            st.session_state[sess_key].append({"role":"user", "content":p})
            save_json("history", f"{sel_cid}.json", st.session_state[sess_key]) # 시트에 저장
            
            try:
                r = generate_response(chat_model_id, "", curr_char, curr_user, mem_data, curr_char.get("lorebooks",[]), st.session_state[sess_key], u_note, 1.0, 0.95, 8192)
                st.session_state[sess_key].append({"role":"assistant", "content":r})
                save_json("history", f"{sel_cid}.json", st.session_state[sess_key]) # 시트에 저장
                st.rerun()
            except Exception as e: st.error(f"오류: {e}")

    with tab2:
        st.subheader("DB 저장된 기억")
        st.json(mem_data)
        if st.button("기억 강제 업데이트"):
             # (요약 로직 생략 - 필요시 복구 가능)
             st.success("기능 준비중")

    with tab3:
        # 캐릭터 생성/수정 (간소화)
        ncid = st.text_input("새 캐릭터 ID / 편집할 ID", sel_cid)
        ncnm = st.text_input("캐릭터 이름", curr_char['name'] if curr_char else "")
        ncds = st.text_area("설명", curr_char['description'] if curr_char else "")
        nfs = st.text_area("첫 메시지", curr_char['first_message'] if curr_char else "")
        nsys = st.text_area("시스템 프롬프트", curr_char['system_prompt'] if curr_char else "")
        
        if st.button("캐릭터 저장/생성"):
            new_data = {
                "name": ncnm, "description": ncds, "first_message": nfs, 
                "system_prompt": nsys, "image": "", "lorebooks": []
            }
            save_json("characters", f"{ncid}.json", new_data)
            st.success("구글 시트에 저장 완료!"); time.sleep(1); st.rerun()
else:
    with tab3:
        st.warning("캐릭터를 먼저 생성해주세요.")
        ncid = st.text_input("새 캐릭터 ID (영어)")
        ncnm = st.text_input("이름")
        if st.button("생성"):
             save_json("characters", f"{ncid}.json", {"name":ncnm})
             st.rerun()
